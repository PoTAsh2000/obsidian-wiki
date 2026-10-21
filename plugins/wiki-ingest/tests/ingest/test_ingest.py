"""Tests for the wiki-ingest:ingest scripts and the vault.py injection.

Scripts run as subprocesses with a temp HOME whose vault-path file points at the
vault under test (use_vault). Tests that write use a temp copy of the fixture
vault; the fixture itself must stay unchanged.

run: python3 -m unittest discover -s plugins/wiki-ingest/tests -t plugins/wiki-ingest
"""

import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[1]
SCRIPTS = PLUGIN / "skills" / "ingest" / "scripts"
VAULT_PY = PLUGIN / "scripts" / "vault.py"
FIXTURE = HERE / "fixture-vault"
MISSING = ("ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use "
           "/wiki-vault:add <vault path> to configure your vault.")


def file_date(path):
    st = Path(path).stat()
    return datetime.date.fromtimestamp(min(getattr(st, "st_birthtime", st.st_mtime), st.st_mtime)).isoformat()


def fixture_hashes():
    return sorted((p.relative_to(FIXTURE).as_posix(), hashlib.md5(p.read_bytes()).hexdigest())
                  for p in FIXTURE.rglob("*") if p.is_file())


_before = None


def setUpModule():
    global _before
    _before = fixture_hashes()


def tearDownModule():
    if fixture_hashes() != _before:
        raise AssertionError("fixture vault changed")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.config = self.home / ".claude" / "obsidian-wiki" / "vault-path"
        self.config.parent.mkdir(parents=True)
        self.v = self.tmp / "v"

    def fresh(self):
        """A writable copy of the fixture vault at self.v, configured as the vault."""
        shutil.rmtree(self.v, ignore_errors=True)
        shutil.copytree(FIXTURE, self.v)
        self.use_vault(self.v)

    def use_vault(self, vault):
        """Point the vault-path file in the temp HOME at vault, as wiki-vault would."""
        self.config.write_text(f"{Path(vault).as_posix()}\n", encoding="utf-8")

    def make_vault(self, name):
        """An empty vault folder with only a CLAUDE.md, configured as the vault."""
        vault = self.tmp / name
        vault.mkdir(exist_ok=True)
        (vault / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")
        self.use_vault(vault)
        return vault

    def run_script(self, script, *args, env=None, input=None):
        path = VAULT_PY if script == "vault" else SCRIPTS / f"{script}.py"
        # the run ledger goes to the temp dir: point it at this test's tmp
        full_env = {**os.environ, "HOME": str(self.home), "TMP": str(self.tmp), "TEMP": str(self.tmp),
                    "TMPDIR": str(self.tmp)}
        full_env.pop("INGEST_INDEX_LIMIT", None)
        full_env.pop("INGEST_ALL_LIMIT", None)
        full_env.update(env or {})
        proc = subprocess.run([sys.executable, str(path), *args], capture_output=True,
                              env=full_env, encoding="utf-8", input=input)
        self.err = proc.stderr
        out = proc.stdout.rstrip("\n")
        if script == "select" and proc.returncode == 0 and not out.startswith(("ERROR:", "usage:")):
            out, _, run = out.rpartition("\n")
            self.assertRegex(run, r"^run: [0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
            self.run_id = run.removeprefix("run: ")
        return proc.returncode, out

    def check(self, want_code, want_out, script, *args, env=None, input=None):
        """Assert exit code and (unless want_out is None) the whole stdout."""
        code, out = self.run_script(script, *args, env=env, input=input)
        self.assertEqual(code, want_code, f"stderr: {self.err[:300]}")
        if want_out is not None:
            self.assertEqual(out, want_out)
        return out

    def assert_err(self, prefix):
        self.assertTrue(self.err.startswith(prefix), f"stderr lacks {prefix!r}: {self.err!r}")

    def assert_bytes(self, path, want):
        self.assertEqual(Path(path).read_bytes(), want)


class HelpTest(Base):
    def test_help(self):
        for script in ("vault", "select", "promote", "relink", "merge", "frontmatter", "ledger", "plan"):
            for flag in ("--help", "-h"):
                with self.subTest(script=script, flag=flag):
                    self.check(0, None, script, flag)


class VaultInjectionTest(Base):
    def test_missing(self):
        self.check(0, MISSING, "vault")

    def test_empty(self):
        self.config.write_bytes(b"\n")
        self.check(0, MISSING, "vault")

    def test_no_claude_md(self):
        self.config.write_bytes(f"{FIXTURE}/01. Inbox\r\n".encode())
        out = self.check(0, None, "vault")
        self.assertTrue(out.startswith("ERROR: The configured vault folder has no CLAUDE.md"))

    def test_ok(self):
        self.config.write_bytes(f"{FIXTURE}\n".encode())
        rules = (FIXTURE / "CLAUDE.md").read_text(encoding="utf-8").rstrip("\n")
        self.check(0, f"vault: {FIXTURE.as_posix()}\n--- vault CLAUDE.md ---\n{rules}", "vault")

    def test_usage(self):
        self.check(2, "", "vault", "extra")
        self.assert_err("SYSTEM ERROR:")


INDEX = """folder: 01. Inbox
note: No Status
note: Reviewed | status: review
folder: 01. Inbox/Sub
note: Deep | status: draft
folder: 30. Knowledge
note: ACE | status: evergreen | aliases: Agentic Context Engineering, ACE framework | title: Agentic Context Engineering
note: Tokens | status: review
folder: 40. Projects
note: Proj | status: review
folder: 99. Archived
note: Old | status: archived"""


class SelectTest(Base):
    def setUp(self):
        super().setUp()
        self.use_vault(FIXTURE)

    def test_all(self):
        ace, idea = file_date(FIXTURE / "01. Inbox" / "ACE notes.md"), file_date(FIXTURE / "01. Inbox" / "Idea.md")
        want = f"""candidate: 01. Inbox/ACE notes.md
frontmatter: 01. Inbox/ACE notes.md | missing: topic, tags, created, related, source | empty: aliases | created: {ace} (file date)
mention: 01. Inbox/ACE notes.md | ACE -> 30. Knowledge/ACE.md
candidate: 01. Inbox/Idea.md
frontmatter: 01. Inbox/Idea.md | missing: type, topic, aliases, tags, created, related, source | created: {idea} (file date)
candidate: 01. Inbox/Tokens.md | same name: 30. Knowledge/Tokens.md
frontmatter: 01. Inbox/Tokens.md | missing: related, source
candidates: 3
{INDEX}
notes: 7"""
        self.check(0, want, "select")
        self.check(0, want, "select", "all")

    def test_name(self):
        idea = file_date(FIXTURE / "01. Inbox" / "Idea.md")
        self.check(0, f"""candidate: 01. Inbox/Idea.md
frontmatter: 01. Inbox/Idea.md | missing: type, topic, aliases, tags, created, related, source | created: {idea} (file date)
candidates: 1
folder: 01. Inbox
note: ACE notes | status: draft
note: No Status
note: Reviewed | status: review
note: Tokens | status: draft | aliases: tok, token count
folder: 01. Inbox/Sub
note: Deep | status: draft
folder: 30. Knowledge
note: ACE | status: evergreen | aliases: Agentic Context Engineering, ACE framework | title: Agentic Context Engineering
note: Tokens | status: review
folder: 40. Projects
note: Proj | status: review
folder: 99. Archived
note: Old | status: archived
notes: 9""", "select", "IDEA")

    def test_user_errors(self):
        cases = [
            ("reviewed", "USER ERROR: select.py: 01. Inbox/Reviewed.md has status review in 01. Inbox"),
            ("No Status", "USER ERROR: select.py: 01. Inbox/No Status.md has no status"),
            ("deep", "USER ERROR: select.py: 01. Inbox/Sub/Deep.md has status draft in 01. Inbox/Sub"),
            ("nope", 'USER ERROR: select.py: no note named "nope"'),
        ]
        for name, err in cases:
            with self.subTest(name=name):
                self.check(3, "", "select", name)
                self.assert_err(err)

    def test_bad_usage(self):
        self.check(2, "", "select", "a", "b")
        self.assert_err("SYSTEM ERROR:")

    def test_vault_problem(self):
        self.config.unlink()
        self.check(0, MISSING, "select")
        self.use_vault(self.tmp / "missing")
        out = self.check(0, None, "select", "tokens")
        self.assertTrue(out.startswith("ERROR: The configured vault folder has no CLAUDE.md"))

    def test_no_vault_rules_printed(self):
        out = self.check(0, None, "select")
        self.assertNotIn("--- vault CLAUDE.md ---", out)
        self.assertNotIn("vault: ", out)

    def test_empty_vault(self):
        self.make_vault("empty")
        self.check(0, "candidates: 0\nnotes: 0", "select")

    def test_bom(self):
        self.fresh()
        (self.v / "01. Inbox" / "Bom.md").write_bytes(b"\xef\xbb\xbf---\nstatus: draft\n---\n# Bom\n")
        out = self.check(0, None, "select", "bom")
        self.assertTrue(out.startswith("candidate: 01. Inbox/Bom.md\n"))

    def test_mentions(self):
        # names of other notes outside frontmatter, code and links, not yet linked, own names skipped
        self.fresh()
        (self.v / "01. Inbox" / "Ctx.md").write_bytes(
            b"---\ntype: concept\ntopic: AI\naliases:\n  - context\ntags: [ai]\ncreated: 2026-01-01\n"
            b"related: x\nsource: y\nstatus: draft\n---\n# Ctx\n\n"
            b"Uses agentic context engineering and the ACE framework, ACE again, Proj.\n"
            b"Not `Tokens` or [[Idea]] or [Old](x) or ACEs; context is own; Old is archived.\n"
            b"```\nTokens\n```\n[[40. Projects/Proj|p]]\n")
        out = self.check(0, None, "select", "ctx", env={"INGEST_INDEX_LIMIT": "0"})
        self.assertEqual(out.split("\ncandidates: 1")[0], """candidate: 01. Inbox/Ctx.md
mention: 01. Inbox/Ctx.md | agentic context engineering -> 30. Knowledge/ACE.md
overlap: 01. Inbox/Ctx.md | 30. Knowledge/ACE.md | 0.38""")

    def test_source_suggestion(self):
        # a Source: or URL: line first, else the first web link, code skipped; only when source is empty
        vault = self.make_vault("src")
        inbox = vault / "01. Inbox"
        inbox.mkdir()
        bodies = {
            "Line": "See [x](https://a.example/first).\n**Source:** <https://b.example/page>.\n",
            "Link": "`https://code.example` then [x](https://a.example/first), and https://c.example\n",
            "None": "No address here, only [[Line]].\n```\nhttps://fenced.example\n```\n",
            "Set": "https://a.example/first\n",
        }
        for name, body in bodies.items():
            source = "source: web\n" if name == "Set" else "source:\n"
            (inbox / f"{name}.md").write_text(f"---\nstatus: draft\ncreated: 2026-01-01\n{source}---\n{body}",
                                               encoding="utf-8")
        out = self.check(0, None, "select", "all")
        lines = [line for line in out.split("\n") if line.startswith("frontmatter:")]
        missing = "missing: type, topic, aliases, tags, related"
        self.assertEqual(lines, [
            f"frontmatter: 01. Inbox/Line.md | {missing} | empty: source | source: https://b.example/page (from draft)",
            f"frontmatter: 01. Inbox/Link.md | {missing} | empty: source | source: https://a.example/first (from draft)",
            f"frontmatter: 01. Inbox/None.md | {missing} | empty: source",
            f"frontmatter: 01. Inbox/Set.md | {missing}"])

    def test_all_batch(self):
        # all takes the oldest drafts by created, then file date; the rest stay in the index
        vault = self.make_vault("batch")
        inbox = vault / "01. Inbox"
        inbox.mkdir()
        for name, created in (("A", "2026-03-01"), ("B", "2026-01-01"), ("C", ""), ("D", "2026-02-01")):
            (inbox / f"{name}.md").write_text(f"---\nstatus: draft\ncreated: {created}\n---\n", encoding="utf-8")
        os.utime(inbox / "C.md", (0, 0))  # file date 1970, the oldest
        out = self.check(0, None, "select", "all", env={"INGEST_ALL_LIMIT": "2"})
        self.assertEqual([line for line in out.split("\n") if line.startswith(("candidate", "folder:", "note:"))], [
            "candidate: 01. Inbox/B.md", "candidate: 01. Inbox/C.md", "candidates: 4, selected: 2",
            "folder: 01. Inbox", "note: A | status: draft", "note: D | status: draft"])
        log = (self.tmp / f"wiki-ingest-{self.run_id}.log").read_text(encoding="utf-8")
        self.assertIn("B.md", log)
        self.assertNotIn("A.md", log)
        self.assertIn("\ncandidates: 4\n", self.check(0, None, "select", "all"))
        self.check(2, "", "select", "all", env={"INGEST_ALL_LIMIT": "x"})

    def test_overlap(self):
        # distinctive shared words, ranked; stopwords, common words, code, links and archived notes skipped
        vault = self.make_vault("overlap")
        for folder in ("01. Inbox", "30. Knowledge", "99. Archived"):
            (vault / folder).mkdir()
        notes = {
            "01. Inbox/Draft.md": "---\nstatus: draft\n---\n# Retrieval caching\n\nPrompt caching saves tokens "
                                  "and latency for retrieval pipelines, about which there would be `embeddings` "
                                  "and [[vectors]].\n",
            "30. Knowledge/Cache.md": "# Prompt caching\n\nCaching saves tokens, retrieval latency.\n",
            "30. Knowledge/Half.md": "Prompt pipelines, retrieval, saves.\n",
            "30. Knowledge/Words.md": "about which there would be embeddings vectors prompt\n",
            "30. Knowledge/Low.md": "prompt pipelines\n",
            "30. Knowledge/F1.md": "filler\n",
            "30. Knowledge/F2.md": "filler\n",
            "99. Archived/Old.md": "---\nstatus: archived\n---\nPrompt caching saves tokens latency retrieval\n",
        }
        for rel, text in notes.items():
            (vault / rel).write_text(text, encoding="utf-8")
        out = self.check(0, None, "select", "draft")
        # draft words: retrieval caching prompt saves tokens latency pipelines; prompt is in 5 of 7 notes
        self.assertEqual([line for line in out.split("\n") if line.startswith("overlap:")], [
            "overlap: 01. Inbox/Draft.md | 30. Knowledge/Cache.md | 0.83",
            "overlap: 01. Inbox/Draft.md | 30. Knowledge/Half.md | 0.50"])

    def test_draft_twins(self):
        # other selected drafts count for overlap too, marked draft; the same text is a duplicate, first
        vault = self.make_vault("twins")
        (vault / "01. Inbox").mkdir()
        (vault / "30. Knowledge").mkdir()
        text = "Prompt caching saves tokens and latency for retrieval pipelines.\n"
        notes = {
            "01. Inbox/A.md": "---\nstatus: draft\ncreated: 2026-01-01\n---\n" + text,
            "01. Inbox/B.md": "---\nstatus: draft\ncreated: 2026-02-02\n---\n\n" + text.replace(" and ", "\n  and "),
            "01. Inbox/C.md": "---\nstatus: draft\n---\nPrompt caching saves tokens, cheaper.\n",
            "01. Inbox/E.md": "---\nstatus: draft\n---\n",
            "01. Inbox/F.md": "---\nstatus: draft\n---\n",
            "30. Knowledge/K.md": "Retrieval latency pipelines matter.\n",
        }
        for rel, body in notes.items():
            (vault / rel).write_text(body, encoding="utf-8")
        out = self.check(0, None, "select", "all")
        self.assertEqual([line for line in out.split("\n") if line.startswith("overlap: 01. Inbox/A.md")], [
            "overlap: 01. Inbox/A.md | 01. Inbox/B.md | 1.00 | draft, duplicate",
            "overlap: 01. Inbox/A.md | 01. Inbox/C.md | 0.57 | draft",
            "overlap: 01. Inbox/A.md | 30. Knowledge/K.md | 0.43"])
        self.assertNotIn("overlap: 01. Inbox/E.md", out)  # empty drafts are no duplicates
        out = self.check(0, None, "select", "a")
        self.assertEqual([line for line in out.split("\n") if line.startswith("overlap:")],
                         ["overlap: 01. Inbox/A.md | 30. Knowledge/K.md | 0.43"])  # only selected drafts

    def test_mentioned_in(self):
        # notes naming the draft outside code and links, not linking it, not archived, own names masked; cap 3
        vault = self.make_vault("incoming")
        for folder in ("01. Inbox", "30. Knowledge", "99. Archived"):
            (vault / folder).mkdir()
        notes = {
            "01. Inbox/Prompt Caching.md": "---\nstatus: draft\naliases: [KV cache]\n---\n# Prompt Caching\n",
            "30. Knowledge/A.md": "We use prompt caching here.\n",
            "30. Knowledge/B.md": "Prompt caching, see [[01. Inbox/Prompt Caching|it]].\n",
            "30. Knowledge/C.md": "Only `prompt caching` and [x](Prompt Caching) here.\n",
            "30. Knowledge/D.md": "# Prompt Caching Guide\n\nThe prompt caching guide.\n",
            "30. Knowledge/E.md": "The KV cache.\n",
            "30. Knowledge/F.md": "prompt caching\n",
            "30. Knowledge/G.md": "prompt caching\n",
            "99. Archived/Old.md": "---\nstatus: archived\n---\nprompt caching\n",
        }
        for rel, body in notes.items():
            (vault / rel).write_text(body, encoding="utf-8")
        out = self.check(0, None, "select", "prompt caching")
        self.assertEqual([line for line in out.split("\n") if line.startswith("mentioned-in:")], [
            "mentioned-in: 01. Inbox/Prompt Caching.md | prompt caching <- 30. Knowledge/A.md",
            "mentioned-in: 01. Inbox/Prompt Caching.md | KV cache <- 30. Knowledge/E.md",
            "mentioned-in: 01. Inbox/Prompt Caching.md | prompt caching <- 30. Knowledge/F.md"])
        log = (self.tmp / f"wiki-ingest-{self.run_id}.log").read_text(encoding="utf-8")
        self.assertIn("mentioned\t30. Knowledge/E.md\n", log)
        self.assertNotIn("G.md", log)

    def test_cap(self):
        # 15 + 22 for the folder line, 9 per note: limit 60 passes at the third note
        vault = self.make_vault("big")
        big = vault / "30. Knowledge"
        big.mkdir()
        for i in range(1, 7):
            (big / f"N{i}.md").write_bytes(b"")
        self.check(0, """candidates: 0
folder: 30. Knowledge
note: N1
note: N2
note: N3
notes: 6
index: first 3 of 6 notes listed (output limit), search the vault for the rest""",
                   "select", env={"INGEST_INDEX_LIMIT": "60"})
        (vault / "Root.md").write_bytes(b"")
        self.assertIn("\nfolder: (vault root)\nnote: Root\n", self.check(0, None, "select"))
        self.check(2, "", "select", env={"INGEST_INDEX_LIMIT": "x"})


class PromoteTest(Base):
    def setUp(self):
        super().setUp()
        self.fresh()

    def promote(self, want_code, want_out, note, folder, status="review"):
        return self.check(want_code, want_out, "promote", note, folder, status)

    def fixture_bytes(self, rel):
        return (FIXTURE / rel).read_bytes()

    def test_move_and_again(self):
        self.promote(0, "path: 40. Projects/Tokens.md\nstatus: review", "01. Inbox/Tokens.md", "40. Projects")
        want = self.fixture_bytes("01. Inbox/Tokens.md").replace(b"\nstatus: draft\n", b"\nstatus: review\n")
        self.assert_bytes(self.v / "40. Projects" / "Tokens.md", want)
        self.assertFalse((self.v / "01. Inbox" / "Tokens.md").exists())
        self.promote(0, "path: 40. Projects/Tokens.md\nstatus: review\nunchanged: already done",
                     "01. Inbox/Tokens.md", "40. Projects/")

    def test_clash(self):
        self.promote(3, "", "01. Inbox/Tokens.md", "30. Knowledge")
        self.assert_err("USER ERROR: promote.py: name clash")
        self.assert_bytes(self.v / "01. Inbox" / "Tokens.md", self.fixture_bytes("01. Inbox/Tokens.md"))

    def test_clash_case_and_nfc(self):
        # Obsidian links ignore case, and macOS may store NFD names: both count as a clash
        (self.v / "40. Projects" / "TOKENS.md").write_bytes(b"x")
        self.promote(3, "", "01. Inbox/Tokens.md", "40. Projects")
        self.assert_err("USER ERROR: promote.py: name clash")
        nfc, nfd = "Café", "Café"
        (self.v / "01. Inbox" / f"{nfc}.md").write_bytes(b"---\nstatus: draft\n---\n")
        (self.v / "40. Projects" / f"{nfd}.md").write_bytes(b"other")
        self.promote(3, "", f"01. Inbox/{nfc}.md", "40. Projects")
        self.assert_err("USER ERROR: promote.py: name clash")
        self.assert_bytes(self.v / "40. Projects" / f"{nfd}.md", b"other")
        self.assertTrue((self.v / "01. Inbox" / f"{nfc}.md").exists())

    def test_not_portable(self):
        # checked before anything else, so the folders need not exist
        cases = [
            ("01. Inbox/aux.md", "40. Projects", "reserved Windows name"),
            ("01. Inbox/Tokens.md", "NUL", "reserved Windows name"),
            ("01. Inbox/Tokens.md", "COM1.x", "reserved Windows name"),
            ("01. Inbox/Tokens.md", "40. Projects.", "ends in a dot or space"),
            ("01. Inbox/Tokens.md", "40. Projects ", "ends in a dot or space"),
            ("01. Inbox/a?b.md", "40. Projects", "a character Windows does not allow"),
            ("01. Inbox/Tokens.md", "x" * 250, "longer than 259"),
        ]
        for note, folder, err in cases:
            with self.subTest(note=note, folder=folder):
                self.promote(3, "", note, folder)
                self.assert_err("USER ERROR: promote.py:")
                self.assertIn(err, self.err)
        self.assert_bytes(self.v / "01. Inbox" / "Tokens.md", self.fixture_bytes("01. Inbox/Tokens.md"))

    def test_move_never_replaces(self):
        # a file that appears after the clash check is never overwritten, also without hard links
        sys.path.insert(0, str(SCRIPTS))
        import promote
        src, dst = self.v / "src.md", self.v / "dst.md"
        real_link = promote.os.link

        def no_link(*_):
            raise OSError("no hard links")

        for link in (real_link, no_link):
            with self.subTest(hard_links=link is real_link):
                src.write_bytes(b"src")
                dst.write_bytes(b"dst")
                promote.os.link = link
                try:
                    with self.assertRaises(FileExistsError):
                        promote.move_no_replace(src, dst)
                    self.assertEqual((src.read_bytes(), dst.read_bytes()), (b"src", b"dst"))
                    dst.unlink()
                    promote.move_no_replace(src, dst)
                    self.assertEqual(dst.read_bytes(), b"src")
                    self.assertFalse(src.exists())
                finally:
                    promote.os.link = real_link

    def test_archive(self):
        self.promote(0, "path: 99. Archived/ACE notes.md\nstatus: archived",
                     "01. Inbox/ACE notes.md", "99. Archived", "archived")

    def test_keep_is_bad_status(self):
        self.promote(2, "", "01. Inbox/Idea.md", "40. Projects", "keep")
        self.assert_err("SYSTEM ERROR: promote.py: status must be review or archived")

    def test_resume_and_twin(self):
        # resume: an earlier run moved the draft but did not set the status
        (self.v / "01. Inbox" / "Idea.md").rename(self.v / "40. Projects" / "Idea.md")
        self.promote(0, "path: 40. Projects/Idea.md\nstatus: review", "01. Inbox/Idea.md", "40. Projects")
        # a same-name note with another status is not taken for done work
        self.promote(3, "", "01. Inbox/Nope.md", "99. Archived", "archived")
        self.promote(3, "", "01. Inbox/Idea.md", "40. Projects", "archived")
        self.assert_err("USER ERROR: promote.py: note not found: 01. Inbox/Idea.md, "
                        "and 40. Projects/Idea.md has status review")

    def test_bom(self):
        # a UTF-8 BOM before the frontmatter is kept and does not hide the status
        (self.v / "01. Inbox" / "Bom.md").write_bytes(b"\xef\xbb\xbf---\nstatus: draft\n---\n# Bom\n")
        self.promote(0, "path: 40. Projects/Bom.md\nstatus: review", "01. Inbox/Bom.md", "40. Projects")
        self.assert_bytes(self.v / "40. Projects" / "Bom.md", b"\xef\xbb\xbf---\nstatus: review\n---\n# Bom\n")

    def test_in_place(self):
        proj = self.v / "40. Projects" / "Proj.md"
        proj.write_bytes(proj.read_bytes().replace(b"status: review", b"status: archived"))
        self.promote(0, "path: 40. Projects/Proj.md\nstatus: review", "40. Projects/Proj.md", "40. Projects")
        self.assertIn(b"\nstatus: review\n", proj.read_bytes())

    def test_in_place_evergreen(self):
        # an evergreen merge target is never set back to review
        self.promote(3, "", "30. Knowledge/ACE.md", "30. Knowledge")
        self.assert_err("USER ERROR:")
        self.assertIn("is evergreen", self.err)
        self.assert_bytes(self.v / "30. Knowledge" / "ACE.md", self.fixture_bytes("30. Knowledge/ACE.md"))

    def test_user_errors(self):
        cases = [
            ("01. Inbox/Reviewed.md", "40. Projects", "USER ERROR: promote.py: 01. Inbox/Reviewed.md has status review"),
            ("01. Inbox/Sub/Deep.md", "40. Projects", "USER ERROR:"),
            ("01. Inbox/Reviewed.md", "01. Inbox", "USER ERROR:"),
            ("01. Inbox/Nope.md", "40. Projects", "USER ERROR:"),
            ("01. Inbox/Tokens.md", "50. Nowhere", "USER ERROR: promote.py: destination folder not found"),
            ("01. Inbox/No Status.md", "40. Projects", "USER ERROR: promote.py: 01. Inbox/No Status.md has no status"),
        ]
        for note, folder, err in cases:
            with self.subTest(note=note, folder=folder):
                self.promote(3, "", note, folder)
                self.assert_err(err)

    def test_bad_usage(self):
        self.promote(2, "", "01. Inbox/Tokens.md", "40. Projects", "evergreen")
        self.assert_err("SYSTEM ERROR:")
        self.promote(2, "", "01. Inbox/Tokens.md", "../x")
        self.assert_err("SYSTEM ERROR:")
        self.check(2, "", "promote", "01. Inbox/Tokens.md")
        self.assert_err("SYSTEM ERROR:")

    def test_vault_problem(self):
        self.config.unlink()
        self.promote(0, MISSING, "01. Inbox/Tokens.md", "40. Projects")
        self.use_vault(self.v / "01. Inbox")
        out = self.promote(0, None, "01. Inbox/Tokens.md", "40. Projects")
        self.assertTrue(out.startswith("ERROR: The configured vault folder has no CLAUDE.md"))
        self.assertTrue((self.v / "01. Inbox" / "Tokens.md").exists())

    def test_crlf(self):
        # a CRLF note keeps its line endings
        (self.v / "01. Inbox" / "Crlf.md").write_bytes(b"---\r\ntype: concept\r\nstatus: draft\r\n---\r\n# Crlf\r\n")
        self.promote(0, None, "01. Inbox/Crlf.md", "40. Projects")
        self.assert_bytes(self.v / "40. Projects" / "Crlf.md",
                          b"---\r\ntype: concept\r\nstatus: review\r\n---\r\n# Crlf\r\n")

    def test_add_status(self):
        # a note without status line gets one
        (self.v / "40. Projects" / "Target.md").write_bytes(b"---\ntype: concept\n---\n# Target\n")
        self.promote(0, "path: 40. Projects/Target.md\nstatus: review", "40. Projects/Target.md", "40. Projects")

    def test_no_frontmatter(self):
        (self.v / "40. Projects" / "Bare.md").write_bytes(b"# Bare\n")
        self.promote(3, "", "40. Projects/Bare.md", "40. Projects")
        self.assert_err("USER ERROR: promote.py: 40. Projects/Bare.md has no frontmatter")
        self.assert_bytes(self.v / "40. Projects" / "Bare.md", b"# Bare\n")


ACE_AFTER = b"""---
type: concept
aliases:
  - Agentic Context Engineering
  - ACE framework
status: evergreen
---
# Agentic Context Engineering

See [[ACE|ACE notes]], [[ACE|the notes]] and [[ACE#Part|ace notes]].
Not [[ACE notes long]] and not [[40. Projects/ACE notes]].

```
[[ACE notes]]
```
"""


class RelinkTest(Base):
    def setUp(self):
        super().setUp()
        self.fresh()

    def relink(self, want_code, want_out, *args):
        return self.check(want_code, want_out, "relink", *args)

    def test_relink_and_again(self):
        self.relink(0, """changed: 01. Inbox/Tokens.md
changed: 30. Knowledge/ACE.md
changed: 40. Projects/Proj.md
links: 5""", "01. Inbox/ACE notes.md", "ACE")
        self.assert_bytes(self.v / "30. Knowledge" / "ACE.md", ACE_AFTER)
        proj = (self.v / "40. Projects" / "Proj.md").read_text(encoding="utf-8")
        self.assertIn('related: ["[[ACE]]"]', proj)
        self.relink(0, "links: 0", "01. Inbox/ACE notes.md", "ACE")

    def test_no_target(self):
        self.relink(3, "", "01. Inbox/ACE notes.md", "Nope")
        self.assert_err("USER ERROR:")

    def test_bad_usage(self):
        for args in (["ACE", "ace"], ["A|B", "ACE"], ["ACE"]):
            with self.subTest(args=args):
                self.relink(2, "", *args)
                self.assert_err("SYSTEM ERROR:")

    def test_vault_problem(self):
        self.config.unlink()
        self.relink(0, MISSING, "01. Inbox/ACE notes.md", "ACE")
        self.assert_bytes(self.v / "30. Knowledge" / "ACE.md", (FIXTURE / "30. Knowledge" / "ACE.md").read_bytes())

    def test_ambiguous(self):
        # two notes named Tokens: a bare [[Tokens]] is ambiguous and stays, the path link is rewritten
        self.relink(0, None, "01. Inbox/ACE notes.md", "ACE")
        links = self.v / "40. Projects" / "Links.md"
        links.write_bytes(b"# Links\n\n[[Tokens]] and [[01. Inbox/Tokens|t]]\n")
        self.relink(0, "changed: 40. Projects/Links.md\nlinks: 1\nskipped-ambiguous: 1",
                    "01. Inbox/Tokens.md", "ACE")
        self.assert_bytes(links, b"# Links\n\n[[Tokens]] and [[ACE|t]]\n")

    def test_inline_code(self):
        # links inside `code` and ``co`de`` spans stay, links next to them change
        links = self.v / "40. Projects" / "Links.md"
        links.write_bytes(b"`[[ACE notes]]` [[ACE notes]] ``a`[[ACE notes]]`` `open [[ACE notes]]\n")
        self.relink(0, None, "01. Inbox/ACE notes.md", "ACE")
        self.assert_bytes(links, b"`[[ACE notes]]` [[ACE|ACE notes]] ``a`[[ACE notes]]`` `open [[ACE|ACE notes]]\n")

    def test_display_text_and_markdown_links(self):
        # bare and heading links keep the old name as display text (\| in a table row),
        # embeds and existing display text stay; Markdown links get the target's path
        links = self.v / "40. Projects" / "Links.md"
        links.write_bytes(
            b"See [[ACE notes]], [[ACE notes|kept]], [[ACE notes#Part]] and ![[ACE notes]].\n"
            b"| [[ACE notes]] | [[ACE notes\\|t]] |\n"
            b"[a](01.%20Inbox/ACE%20notes.md) [b](<01. Inbox/ACE notes.md#Part>) [c](ACE%20notes.md)\n"
            b"[d](../01.%20Inbox/ACE%20notes.md \"t\") ![e](ACE%20notes.md)\n"
            b"[x](https://e.com/ACE%20notes.md) `[y](ACE%20notes.md)` [z](40.%20Projects/ACE%20notes.md)\n")
        out = self.relink(0, None, "01. Inbox/ACE notes.md", "ACE")
        self.assertIn("changed: 40. Projects/Links.md", out)
        self.assertIn("links: 16", out)  # 5 in the fixture, 11 here
        self.assert_bytes(links,
            b"See [[ACE|ACE notes]], [[ACE|kept]], [[ACE#Part|ACE notes]] and ![[ACE]].\n"
            b"| [[ACE\\|ACE notes]] | [[ACE\\|t]] |\n"
            b"[a](30.%20Knowledge/ACE.md) [b](<30. Knowledge/ACE.md#Part>) [c](ACE.md)\n"
            b"[d](../30.%20Knowledge/ACE.md \"t\") ![e](ACE.md)\n"
            b"[x](https://e.com/ACE%20notes.md) `[y](ACE%20notes.md)` [z](40.%20Projects/ACE%20notes.md)\n")

    def test_frontmatter_links_keep_quoting(self):
        # related entries only change the target: quotes and list form stay, no display text
        self.proj = self.v / "40. Projects" / "Proj.md"
        self.proj.write_bytes(b"---\r\nstatus: review\r\nrelated:\r\n  - \"[[ACE notes]]\"\r\n"
                              b"  - '[[ACE notes#Part]]'\r\n  - [[ACE notes]]\r\n---\r\n# Proj\r\n")
        self.relink(0, None, "01. Inbox/ACE notes.md", "ACE")
        self.assert_bytes(self.proj, b"---\r\nstatus: review\r\nrelated:\r\n  - \"[[ACE]]\"\r\n"
                          b"  - '[[ACE#Part]]'\r\n  - [[ACE]]\r\n---\r\n# Proj\r\n")

    def test_ambiguous_target(self):
        # two notes named Tokens: the new bare [[Tokens]] links are ambiguous, the script says so
        out = self.relink(0, None, "01. Inbox/ACE notes.md", "Tokens")
        self.assertTrue(out.endswith("\nambiguous-target: 2"), out)


class MergeTest(Base):
    def setUp(self):
        super().setUp()
        self.fresh()
        self.proj = self.v / "40. Projects" / "Proj.md"
        self.target = self.v / "30. Knowledge" / "Target.md"
        self.target.write_bytes(b"---\ntype: concept\naliases:\n    - \"T one\"\nstatus: draft\n---\n# Target\n")

    def merge(self, want_code, want_out, source, target, archive="99. Archived"):
        return self.check(want_code, want_out, "merge", source, target, archive)

    def test_merge_and_again(self):
        idea = self.v / "01. Inbox" / "Idea.md"
        idea.write_bytes(b"---\nstatus: draft\n---\n# Loose idea: one\n")
        self.proj.write_bytes(b"---\nstatus: review\n---\n# Proj\n[[Idea]] and [[01. Inbox/Idea|i]]\n")
        done = "archived: 99. Archived/Idea.md\ntarget-status: review"
        self.merge(0, f"changed: 30. Knowledge/Target.md\nchanged: 40. Projects/Proj.md\nlinks: 2\n{done}",
                   "01. Inbox/Idea.md", "Target")
        self.assert_bytes(self.target, b'---\ntype: concept\naliases:\n    - "T one"\n    - Idea\n'
                          b'    - "Loose idea: one"\nstatus: review\n---\n# Target\n')
        self.assertIn(b"[[Target|Idea]] and [[Target|i]]", self.proj.read_bytes())
        self.assertIn(b"status: archived", (self.v / "99. Archived" / "Idea.md").read_bytes())
        self.assertFalse(idea.exists())
        self.merge(0, f"links: 0\n{done}", "01. Inbox/Idea.md", "Target")

    def test_resume_after_move(self):
        # a crash after the move, before the status: the rerun finishes the work
        (self.v / "01. Inbox" / "Idea.md").rename(self.v / "99. Archived" / "Idea.md")
        self.merge(0, "changed: 30. Knowledge/Target.md\nlinks: 0\narchived: 99. Archived/Idea.md\n"
                   "target-status: review", "01. Inbox/Idea.md", "Target")
        self.assertIn(b"status: archived", (self.v / "99. Archived" / "Idea.md").read_bytes())

    def test_aliases_forms(self):
        # the source name joins the target's aliases as a YAML list, a flow list stays one
        cases = [
            (b"---\nstatus: review\n---\n", b"---\nstatus: review\naliases:\n  - Idea\n---\n"),
            (b"---\naliases: []\nstatus: review\n---\n", b"---\naliases:\n  - Idea\nstatus: review\n---\n"),
            (b"---\naliases: other\nstatus: review\n---\n",
             b"---\naliases:\n  - other\n  - Idea\nstatus: review\n---\n"),
            (b"---\r\naliases: [a, \"b\"]\r\nstatus: review\r\n---\r\n",
             b"---\r\naliases: [a, \"b\", Idea]\r\nstatus: review\r\n---\r\n"),
            (b"---\naliases: [IDEA]\nstatus: review\n---\n", b"---\naliases: [IDEA]\nstatus: review\n---\n"),
        ]
        for before, after in cases:
            with self.subTest(before=before):
                self.fresh()
                self.target.write_bytes(before)
                self.merge(0, None, "01. Inbox/Idea.md", "Target")
                self.assert_bytes(self.target, after)

    def test_evergreen_flagged_first(self):
        out = self.merge(0, None, "01. Inbox/ACE notes.md", "ACE")
        self.assertTrue(out.startswith("evergreen-target: 30. Knowledge/ACE.md\n"), out)
        self.assertTrue(out.endswith("target-status: evergreen"), out)
        self.assertIn(b"status: evergreen", (self.v / "30. Knowledge" / "ACE.md").read_bytes())

    def test_refused_writes_nothing(self):
        cases = [
            ("01. Inbox/Idea.md", "Nope", "99. Archived", 'no note named "Nope"'),
            ("01. Inbox/Idea.md", "Tokens", "99. Archived", 'several notes are named "Tokens"'),
            ("01. Inbox/ACE notes.md", "Idea", "99. Archived", "is in 01. Inbox"),
            ("01. Inbox/Reviewed.md", "Target", "99. Archived", "has status review"),
            ("01. Inbox/Nope.md", "Target", "99. Archived", "merge source not found"),
            ("01. Inbox/Idea.md", "Target", "50. Nowhere", "destination folder not found"),
            ("01. Inbox/Idea.md", "Target", "99. Archived", "name clash"),
        ]
        for source, target, archive, err in cases:
            with self.subTest(source=source, target=target, archive=archive):
                if err == "name clash":
                    (self.v / "99. Archived" / "IDEA.md").write_bytes(b"x")
                before = {p: p.read_bytes() for p in self.v.rglob("*.md")}
                self.merge(3, "", source, target, archive)
                self.assert_err("USER ERROR: merge.py:")
                self.assertIn(err, self.err)
                self.assertEqual({p: p.read_bytes() for p in self.v.rglob("*.md")}, before)

    def test_bad_usage(self):
        for args in (["Idea.md", "Target", "99. Archived"], ["01. Inbox/Idea.md", "Idea", "99. Archived"],
                     ["01. Inbox/Idea.md", "A|B", "99. Archived"], ["01. Inbox/Idea.md", "Target", "../x"],
                     ["01. Inbox/Idea.md", "Target"]):
            with self.subTest(args=args):
                self.check(2, "", "merge", *args)
                self.assert_err("SYSTEM ERROR: merge.py:")


class FrontmatterTest(Base):
    def setUp(self):
        super().setUp()
        self.fresh()
        self.tokens = self.v / "01. Inbox" / "Tokens.md"

    def fm(self, want_code, want_out, *args):
        return self.check(want_code, want_out, "frontmatter", *args)

    def test_canonical_and_again(self):
        self.tokens.write_bytes(b"---\nstatus: draft\ntags: [ai, \"#AI\"]\nsource: web\nnote: keep me\n"
                                b"  second line\ntype: concept\naliases: tok\ntags:\n  - llm\n"
                                b"related: [[ACE]]\ncreated: 2026/9/2\n---\n# Tokens\n")
        self.fm(0, "frontmatter: 01. Inbox/Tokens.md", "01. Inbox/Tokens.md", "topic=AI", "aliases+=Tok",
                "aliases+=token count", "tags+=#llm", "related+=Context Window", "related+=[[ACE]]")
        self.assert_bytes(self.tokens, b"---\ntype: concept\ntopic: AI\naliases:\n  - tok\n  - token count\n"
                          b"tags:\n  - ai\n  - llm\ncreated: 2026-09-02\nrelated:\n  - \"[[ACE]]\"\n"
                          b"  - \"[[Context Window]]\"\nsource: web\nstatus: draft\nnote: keep me\n"
                          b"  second line\n---\n# Tokens\n")
        self.fm(0, "unchanged: 01. Inbox/Tokens.md", "01. Inbox/Tokens.md", "tags+=AI")

    def test_set_replaces_and_file_date(self):
        idea = self.v / "01. Inbox" / "Idea.md"
        idea.write_bytes(b"\xef\xbb\xbf---\r\nstatus: draft\r\ntags: [old]\r\n---\r\n# Idea\r\n")
        self.fm(0, None, "01. Inbox/Idea.md", "type=how-to", "tags=a", "tags=b", "source=https://x.y/z?q")
        date = file_date(idea).encode()
        self.assert_bytes(idea, b"\xef\xbb\xbf---\r\ntype: how-to\r\ntopic:\r\naliases: []\r\n"
                          b"tags:\r\n  - a\r\n  - b\r\ncreated: " + date + b"\r\nrelated: []\r\n"
                          b"source: \"https://x.y/z?q\"\r\nstatus: draft\r\n---\r\n# Idea\r\n")

    def test_type_rule(self):
        self.fm(3, "", "01. Inbox/Idea.md", "type=recipe")
        self.assert_err("USER ERROR: frontmatter.py: type 'recipe' is not in the vault's allowed types")
        self.assert_bytes(self.v / "01. Inbox" / "Idea.md", (FIXTURE / "01. Inbox" / "Idea.md").read_bytes())
        self.fm(0, "frontmatter: 01. Inbox/Idea.md", "--new-type", "01. Inbox/Idea.md", "type=recipe")

    def test_scope(self):
        before = (self.v / "30. Knowledge" / "ACE.md").read_bytes()
        for note in ("30. Knowledge/ACE.md", "01. Inbox/Reviewed.md", "01. Inbox/Sub/Deep.md", "01. Inbox/Nope.md"):
            with self.subTest(note=note):
                self.fm(3, "", note, "topic=x")
                self.assert_err("USER ERROR: frontmatter.py:")
        self.assertEqual((self.v / "30. Knowledge" / "ACE.md").read_bytes(), before)
        self.fm(0, "frontmatter: 30. Knowledge/ACE.md", "--approved", "30. Knowledge/ACE.md", "topic=x")
        self.assertIn(b"\nstatus: evergreen\n", (self.v / "30. Knowledge" / "ACE.md").read_bytes())
        self.fm(3, "", "--approved", "01. Inbox/No Status.md", "topic=x")
        self.assert_err("USER ERROR: frontmatter.py: 01. Inbox/No Status.md has no frontmatter")

    def test_bad_usage(self):
        for args in (["01. Inbox/Tokens.md", "status=review"], ["01. Inbox/Tokens.md", "color=red"],
                     ["01. Inbox/Tokens.md", "created=yesterday"], ["01. Inbox/Tokens.md", "topic+=x"],
                     ["01. Inbox/Tokens.md", "topic"], ["../x.md"], [], ["--run", "a b", "01. Inbox/Tokens.md"]):
            with self.subTest(args=args):
                self.fm(2, "", *args)
                self.assert_err("SYSTEM ERROR: frontmatter.py:")


class LedgerTest(Base):
    def setUp(self):
        super().setUp()
        self.fresh()

    def test_run(self):
        # every script records into the ledger of the run id select.py printed; moves are remapped
        self.check(0, None, "select", "all")
        run = ["--run", self.run_id]
        self.check(0, None, "frontmatter", *run, "01. Inbox/Idea.md", "type=concept")
        self.check(0, None, "promote", *run, "01. Inbox/Idea.md", "40. Projects", "review")
        self.check(3, "", "promote", *run, "01. Inbox/Tokens.md", "30. Knowledge", "review")
        self.check(0, None, "merge", *run, "01. Inbox/ACE notes.md", "ACE", "99. Archived")
        self.check(0, """file: 40. Projects/Idea.md
file: 01. Inbox/Tokens.md
file: 30. Knowledge/ACE.md
file: 40. Projects/Proj.md
file: 99. Archived/ACE notes.md
file: 40. Projects/Orphan.md
failed: 01. Inbox/Tokens.md | USER ERROR: promote.py: name clash: 30. Knowledge/Tokens.md already exists, \
01. Inbox/Tokens.md stays in 01. Inbox
Moved from draft to review:
- `40. Projects/Idea.md`""", "ledger", *run, "40. Projects/Orphan.md")
        self.assertFalse(list(self.v.rglob("*.log")), "the ledger must stay outside the vault")

    def test_missing_ledger_and_usage(self):
        self.check(0, "No notes moved from draft to review.", "ledger", "--run", "nothing-here")
        for args in ([], ["--run"], ["--run", "../x"]):
            with self.subTest(args=args):
                self.check(2, "", "ledger", *args)
                self.assert_err("SYSTEM ERROR: ledger.py:")



ROWS = """Tokens | draft | actions: formatter | 30. Knowledge
Tokens | draft | new links: [[Proj]] | 30. Knowledge
Idea | draft | actions: new type: recipe | 40. Projects
Idea | draft | actions: set topic: AI | 40. Projects
Proj | orphan | new links: [[Idea]] | anything
ACE notes | draft | merge with: ACE | 99. Archived
"""

TABLE = """## Changes to ingest

| id | note | state | change | destination |
|---|---|---|---|---|
| 1 | Tokens | draft | actions: formatter | keep, name clash in 30. Knowledge |
| 2 | Tokens | draft | new links: [[Proj]] | keep, name clash in 30. Knowledge |
| 3 | Idea | draft | actions: new type: recipe | 40. Projects |
| 4 | Idea | draft | actions: set topic: AI | 40. Projects |
| 5 | Proj | orphan | new links: [[Idea]] | keep, orphan stays in 40. Projects |
| 6 | ACE notes | draft | merge with: ACE | 99. Archived |"""


class PlanTest(Base):
    def setUp(self):
        super().setUp()
        self.fresh()
        self.check(0, None, "select", "all")
        self.run_ = ["--run", self.run_id]

    def plan(self, want_code, want_out, *args, rows=None):
        return self.check(want_code, want_out, "plan", *self.run_, *args, input=rows)

    def test_propose_table(self):
        # a name clash and an orphan get their destination rewritten; a JSON list works too
        self.plan(0, TABLE, rows=ROWS)
        json_rows = json.dumps([line.split(" | ") for line in ROWS.splitlines()])
        self.plan(0, TABLE, rows=json_rows)
        self.plan(0, None, rows="| 1 | Idea | draft | none | keep, later |\nTokens | draft | none | keep, x\n"
                  "ACE notes | draft | none | keep, y")

    def test_refused_rows(self):
        rows = ("Tokens | draft | actions: set status: review | 30. Knowledge\n"
                "Idea | draft | actions: new type: concept | 01. Inbox\n"
                "Idea | draft | actions: set type: recipe | 50. Nowhere\n"
                "Bob | orphan | new links: [[Idea]] | keep, x\n"
                "Proj | orphan | merge with: ACE | keep, x\n"
                "Tokens | maybe | none | keep, x\n"
                "Tokens | draft | merge with: Nope | 99. Archived\n"
                "Tokens | draft | actions: dance | keep\n")
        self.plan(3, "", rows=rows)
        for err in ("row 1 (Tokens): ingest never sets status", "row 2 (Idea): type 'concept' is allowed already",
                    "row 3 (Idea): type 'recipe' is not allowed", "row 4 (Bob): no note named Bob",
                    "row 5 (Proj): an orphan row only adds links", "row 6 (Tokens): state must be draft, orphan or linked",
                    "row 7 (Tokens): merge target not found: Nope", "row 8 (Tokens): unknown action 'dance'",
                    "draft ACE notes has no row"):
            self.assertIn(err, self.err)
        self.assertNotIn("draft Idea has no row", self.err)
        self.plan(3, "", rows="Idea | draft | none | 01. Inbox\nTokens | draft | none | keep, x\n"
                  "ACE notes | draft | none | keep, y")
        self.assertIn("must not be 01. Inbox", self.err)
        self.plan(3, "", rows="Idea | draft | none | 30. Knowledge\nIdea | draft | actions: formatter | 40. Projects")
        self.assertIn("same destination", self.err)
        self.plan(2, "", "--approve")  # nothing was stored
        self.assert_err("SYSTEM ERROR: plan.py: no plan for this run yet")

    def test_approve_apply_finish(self):
        self.plan(0, None, rows=ROWS)
        self.plan(0, """approved: 5 rows
skipped: 4 | Idea | actions: set topic: AI
apply: 40. Projects/Proj.md | keep, orphan stays in 40. Projects
apply: 01. Inbox/Tokens.md | keep, name clash in 30. Knowledge
apply: 01. Inbox/Idea.md | 30. Knowledge
apply: 01. Inbox/ACE notes.md | 99. Archived""", "--approve", "--skip", "4", "--link", "2=Idea",
                  "--dest", "3=30. Knowledge")
        proj = (self.v / "40. Projects" / "Proj.md").read_bytes()
        self.plan(0, "edit: 40. Projects/Proj.md | new links: [[Idea]]", "--apply", "Proj")
        self.assert_bytes(self.v / "40. Projects" / "Proj.md", proj)  # an orphan link row keeps its frontmatter
        self.plan(0, "kept: 40. Projects/Proj.md | orphan stays in 40. Projects", "--finish", "Proj")
        self.plan(3, "", "--finish", "Idea")
        self.assert_err("USER ERROR: plan.py: run --apply 01. Inbox/Idea.md first")
        self.plan(0, "frontmatter: 01. Inbox/Idea.md\npath: 30. Knowledge/Idea.md\nstatus: review",
                  "--apply", "Idea")
        idea = (self.v / "30. Knowledge" / "Idea.md").read_text(encoding="utf-8")
        self.assertIn("type: recipe\ntopic:\n", idea)  # the skipped topic row is not applied
        self.plan(0, "frontmatter: 01. Inbox/Tokens.md\nedit: 01. Inbox/Tokens.md | actions: formatter\n"
                  "edit: 01. Inbox/Tokens.md | new links: [[Proj]], [[Idea]]", "--apply", "Tokens")
        self.assertIn('related:\n  - "[[Proj]]"\n  - "[[Idea]]"\n',
                      (self.v / "01. Inbox" / "Tokens.md").read_text(encoding="utf-8"))
        self.plan(0, "kept: 01. Inbox/Tokens.md | name clash in 30. Knowledge", "--finish", "Tokens")
        out = self.plan(0, None, "--apply", "ACE notes")
        self.assertIn("archived: 99. Archived/ACE notes.md", out)
        self.check(0, """file: 40. Projects/Proj.md
file: 30. Knowledge/Idea.md
file: 01. Inbox/Tokens.md
file: 30. Knowledge/ACE.md
file: 99. Archived/ACE notes.md
Moved from draft to review:
- `30. Knowledge/Idea.md`""", "ledger", *self.run_)

    def test_linked_rows(self):
        # a linked row adds links to a mentioned-in note of select.py only, and keeps it in place
        (self.v / "40. Projects" / "Plan.md").write_text("# Plan\n\nSee the Idea here.\n", encoding="utf-8")
        self.check(0, None, "select", "all")
        self.run_ = ["--run", self.run_id]
        drafts = "Idea | draft | none | keep, x\nTokens | draft | none | keep, x\nACE notes | draft | none | keep, y\n"
        self.plan(3, "", rows=drafts + "Proj | linked | new links: [[Idea]] | keep, x\n"
                  "Plan | linked | actions: formatter | keep, x")
        for err in ("row 4 (Proj): a linked row only adds new links:", "row 5 (Plan): a linked row only"):
            self.assertIn(err, self.err)
        out = self.plan(0, None, rows=drafts + "Plan | linked | new links: [[Idea]] | anything")
        self.assertIn("| 4 | Plan | linked | new links: [[Idea]] | keep, links only in 40. Projects |", out)
        out = self.plan(0, None, "--approve")
        self.assertIn("apply: 40. Projects/Plan.md | keep, links only in 40. Projects", out.split("\n")[1])
        self.plan(0, "edit: 40. Projects/Plan.md | new links: [[Idea]]", "--apply", "Plan")
        self.plan(0, "kept: 40. Projects/Plan.md | links only in 40. Projects", "--finish", "Plan")

    def test_merge_skip_keeps_note(self):
        self.plan(0, None, rows="Idea | draft | none | keep, later\nTokens | draft | none | keep, x\n"
                  "ACE notes | draft | actions: formatter | 99. Archived\n"
                  "ACE notes | draft | merge with: ACE | 99. Archived")
        out = self.plan(0, None, "--approve", "--skip", "4")
        self.assertIn("apply: 01. Inbox/ACE notes.md | keep, merge skipped", out)
        self.plan(3, "", "--approve", "--skip", "9")
        self.assert_err("USER ERROR: plan.py: there is no id 9")

    def test_changed_since_plan(self):
        idea = self.v / "01. Inbox" / "Idea.md"
        self.plan(0, None, rows="Idea | draft | actions: set topic: AI | 40. Projects\n"
                  "Tokens | draft | none | keep, x\nACE notes | draft | none | keep, y")
        idea.write_bytes(idea.read_bytes() + b"edited in Obsidian\n")
        self.plan(3, "", "--approve")
        self.assert_err("USER ERROR: plan.py: 01. Inbox/Idea.md changed since the plan was shown")
        idea.write_bytes((FIXTURE / "01. Inbox" / "Idea.md").read_bytes())
        self.plan(0, None, "--approve")
        idea.write_bytes(idea.read_bytes() + b"edited in Obsidian\n")
        before = idea.read_bytes()
        self.plan(3, "", "--apply", "Idea")
        self.assert_err("USER ERROR: plan.py: 01. Inbox/Idea.md changed since the plan was shown")
        self.assert_bytes(idea, before)

    def test_bad_usage(self):
        self.plan(2, "", "--apply", "Idea")
        self.assert_err("SYSTEM ERROR: plan.py: no approved plan")
        for args in (["--skip", "1"], ["--approve", "--skip", "x"], ["--dest", "x"], ["--nope"]):
            with self.subTest(args=args):
                self.plan(2, "", *args)
        self.check(2, "", "plan", "--run", "no-select-run", input="Idea | draft | none | keep, x")
        self.assert_err("SYSTEM ERROR: plan.py: no select.py run")
        self.check(2, "", "plan", input="")


class WriteCheckTest(Base):
    """A note that changes between read and replace (an autosave, a sync) is never overwritten."""

    def setUp(self):
        super().setUp()
        self.fresh()
        sys.path.insert(0, str(SCRIPTS))

    def test_write_note(self):
        import relink
        note = self.v / "01. Inbox" / "Idea.md"
        before = note.read_bytes()
        with self.assertRaises(relink.Fail) as caught:
            relink.write_note(note, "01. Inbox/Idea.md", "new", "what the script read earlier")
        self.assertEqual(caught.exception.code, 3)
        self.assertIn("changed while ingest was writing it", str(caught.exception))
        self.assert_bytes(note, before)
        self.assertEqual([p.name for p in note.parent.iterdir() if p.name.startswith("Idea")], ["Idea.md"])

    def test_set_status(self):
        import promote
        note = self.v / "01. Inbox" / "Idea.md"
        real = promote.read_text
        calls = []

        def edited_meanwhile(path):
            calls.append(path)
            return real(path) + ("x" if len(calls) > 1 else "")

        promote.read_text = edited_meanwhile
        try:
            with self.assertRaises(promote.Fail) as caught:
                promote.set_status(self.v, "01. Inbox/Idea.md", "review")
        finally:
            promote.read_text = real
        self.assertEqual(caught.exception.code, 3)
        self.assert_bytes(note, (FIXTURE / "01. Inbox" / "Idea.md").read_bytes())

    def test_select_records_hashes(self):
        self.check(0, None, "select", "Idea")
        rows = (self.tmp / f"wiki-ingest-{self.run_id}.log").read_text(encoding="utf-8").splitlines()
        digest = hashlib.sha256((self.v / "01. Inbox" / "Idea.md").read_bytes()).hexdigest()
        self.assertEqual(rows, ["select\tname", f"candidate\t01. Inbox/Idea.md\t{digest}"])


if __name__ == "__main__":
    unittest.main()
