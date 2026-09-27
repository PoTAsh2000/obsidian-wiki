"""Tests for the wiki-ingest:ingest scripts and the vault.py injection.

Scripts run as subprocesses with a temp HOME whose vault-path file points at the
vault under test (use_vault). Tests that write use a temp copy of the fixture
vault; the fixture itself must stay unchanged.

run: python3 -m unittest discover -s plugins/wiki-ingest/tests -t plugins/wiki-ingest
"""

import hashlib
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

    def run_script(self, script, *args, env=None):
        path = VAULT_PY if script == "vault" else SCRIPTS / f"{script}.py"
        full_env = {**os.environ, "HOME": str(self.home)}
        full_env.pop("INGEST_INDEX_LIMIT", None)
        full_env.update(env or {})
        proc = subprocess.run([sys.executable, str(path), *args], capture_output=True,
                              env=full_env, encoding="utf-8")
        self.err = proc.stderr
        return proc.returncode, proc.stdout.rstrip("\n")

    def check(self, want_code, want_out, script, *args, env=None):
        """Assert exit code and (unless want_out is None) the whole stdout."""
        code, out = self.run_script(script, *args, env=env)
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
        for script in ("vault", "select", "promote", "relink"):
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


INDEX = """note: 01. Inbox/No Status.md
note: 01. Inbox/Reviewed.md | status: review
note: 01. Inbox/Sub/Deep.md | status: draft
note: 30. Knowledge/ACE.md | status: evergreen | aliases: Agentic Context Engineering, ACE framework | title: Agentic Context Engineering
note: 30. Knowledge/Tokens.md | status: review
note: 40. Projects/Proj.md | status: review
note: 99. Archived/Old.md | status: archived"""


class SelectTest(Base):
    def setUp(self):
        super().setUp()
        self.use_vault(FIXTURE)

    def test_all(self):
        want = f"""candidate: 01. Inbox/ACE notes.md
candidate: 01. Inbox/Idea.md
candidate: 01. Inbox/Tokens.md | same name: 30. Knowledge/Tokens.md
candidates: 3
{INDEX}
notes: 7"""
        self.check(0, want, "select")
        self.check(0, want, "select", "all")

    def test_name(self):
        self.check(0, """candidate: 01. Inbox/Idea.md
candidates: 1
note: 01. Inbox/ACE notes.md | status: draft
note: 01. Inbox/No Status.md
note: 01. Inbox/Reviewed.md | status: review
note: 01. Inbox/Sub/Deep.md | status: draft
note: 01. Inbox/Tokens.md | status: draft | aliases: tok, token count
note: 30. Knowledge/ACE.md | status: evergreen | aliases: Agentic Context Engineering, ACE framework | title: Agentic Context Engineering
note: 30. Knowledge/Tokens.md | status: review
note: 40. Projects/Proj.md | status: review
note: 99. Archived/Old.md | status: archived
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

    def test_cap(self):
        # each line is 26 chars, limit 100 gives 4 lines
        big = self.make_vault("big") / "30. Knowledge"
        big.mkdir()
        for i in range(1, 7):
            (big / f"N{i}.md").write_bytes(b"")
        self.check(0, """candidates: 0
note: 30. Knowledge/N1.md
note: 30. Knowledge/N2.md
note: 30. Knowledge/N3.md
note: 30. Knowledge/N4.md
notes: 6
index: first 4 of 6 notes listed (output limit), search the vault for the rest""",
                   "select", env={"INGEST_INDEX_LIMIT": "100"})
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
        self.promote(0, "path: 30. Knowledge/ACE.md\nstatus: review", "30. Knowledge/ACE.md", "30. Knowledge")
        want = self.fixture_bytes("30. Knowledge/ACE.md").replace(b"\nstatus: evergreen\n", b"\nstatus: review\n")
        self.assert_bytes(self.v / "30. Knowledge" / "ACE.md", want)

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

See [[ACE]], [[ACE|the notes]] and [[ACE#Part]].
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


if __name__ == "__main__":
    unittest.main()
