"""Tests for gather.py and save.py on a copy of the fixture vault with a temp HOME."""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixture-vault"
SCRIPTS = HERE.parents[1] / "skills" / "save" / "scripts"
GATHER = SCRIPTS / "gather.py"
SAVE = SCRIPTS / "save.py"
TODAY = date.today().isoformat()
MISSING = ("ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use "
           "/wiki-vault:add <vault path> to configure your vault.")


def sums(folder):
    """Hash of every file in a folder, to prove nothing changed."""
    return {p.relative_to(folder).as_posix(): hashlib.md5(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


FIXTURE_SUMS = sums(FIXTURE)


class VaultCase(unittest.TestCase):
    """Fresh vault copy ("my vault", with a space) and HOME per test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vault = self.tmp / "my vault"
        shutil.copytree(FIXTURE, self.vault)
        self.home = self.tmp / "home"
        self.cfg = self.home / ".claude" / "obsidian-wiki" / "vault-path"

    def run_script(self, script, *args, want, env=None):
        """Run a script, check its exit code, keep stdout and stderr."""
        env = dict(os.environ, HOME=str(self.home), PYTHONIOENCODING="utf-8", **(env or {}))
        proc = subprocess.run([sys.executable, str(script), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8", env=env)
        self.out, self.err = proc.stdout, proc.stderr
        self.assertEqual(proc.returncode, want, f"stdout: {self.out}\nstderr: {self.err}")
        return self.out

    def assertLine(self, line):
        self.assertIn(line, self.out.splitlines(), self.out)

    def set_config(self, text):
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_bytes(text.encode("utf-8"))

    def use_vault(self, vault=None):
        """Point the temp HOME at a vault (default: the vault copy)."""
        self.set_config(f"{(vault or self.vault).as_posix()}\n")


class GatherTest(VaultCase):
    def test_help(self):
        self.run_script(GATHER, "--help", want=0)

    def test_args(self):
        self.run_script(GATHER, "extra", want=2)

    def test_no_config(self):
        self.run_script(GATHER, want=0)
        self.assertLine(MISSING)

    def test_empty_config(self):
        self.set_config("")
        self.run_script(GATHER, want=0)
        self.assertLine(MISSING)

    def test_bad_vault(self):
        self.set_config(f"{self.tmp / 'nowhere'}\n")
        self.run_script(GATHER, want=0)
        self.assertRegex(self.out, r"^ERROR: .*/wiki-vault:overwrite")

    def test_no_inbox(self):
        shutil.rmtree(self.vault / "01. Inbox")
        self.use_vault()
        self.run_script(GATHER, want=0)
        self.assertRegex(self.out, r"^ERROR: .*01\. Inbox.*/wiki-vault:overwrite")

    def test_ok(self):
        self.set_config(f"{self.vault}/\r\n")
        before = sums(self.vault)
        self.run_script(GATHER, want=0)
        self.assertLine(f"today: {TODAY}")
        self.assertRegex(self.out, r"(?m)^topics: (AI|ai), Docker$")
        self.assertRegex(self.out, r"(?m)^draft_file: .*wiki-save-.*\.md$")
        self.assertEqual(before, sums(self.vault), "gather changed the vault")

    @unittest.skipUnless(os.name == "nt", "8.3 short paths exist only on Windows")
    def test_draft_file_long_path(self):
        # Write refuses 8.3 paths like C:/Users/USERNA~1/..., so draft_file must be long.
        import ctypes
        long_dir = self.tmp / "Long Temp Folder"
        long_dir.mkdir()
        buf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.kernel32.GetShortPathNameW(str(long_dir), buf, 1024)
        if "~" not in buf.value:
            self.skipTest("8.3 names are disabled on this volume")
        self.use_vault()
        self.run_script(GATHER, want=0, env={k: buf.value for k in ("TMPDIR", "TEMP", "TMP")})
        self.assertRegex(self.out, "(?m)^draft_file: "
                         + re.escape(long_dir.resolve().as_posix()) + r"/wiki-save-[^/~]*\.md$")

    def related(self, *words):
        self.run_script(GATHER, "--related", *words, want=0)
        return [line for line in self.out.splitlines() if line.startswith("related: ")]

    def test_related(self):
        self.use_vault()
        before = sums(self.vault)
        k8s = "related: 20. Knowledge/Kubernetes.md"
        docker = "related: 20. Knowledge/Docker Basics.md"
        self.assertEqual(self.related("DOCKER"), [f"{docker} (filename, heading)"])
        self.assertEqual(self.related("k8s"), [f"{k8s} (alias)"])
        self.assertEqual(self.related("scheduling"), [f"{k8s} (heading)"])
        self.assertEqual(self.related("container", "zzz"),
                         [f"{docker} (alias)", f"{k8s} (alias)"])
        # Templates and dot folders are skipped.
        self.assertEqual(self.related("note", "hidden", "secret"), ["related: none"])
        self.assertEqual(before, sums(self.vault), "gather --related changed the vault")

    def test_related_nfc(self):
        self.use_vault()
        (self.vault / "20. Knowledge" / "Café Notes.md").write_text("Text.\n", encoding="utf-8")
        self.assertEqual(self.related("CAFÉ"), ["related: 20. Knowledge/Café Notes.md (filename)"])

    def test_related_no_words(self):
        self.use_vault()
        self.run_script(GATHER, "--related", want=2)

    def test_no_vault_context(self):
        # The vault line and CLAUDE.md come from vault.py only.
        self.use_vault()
        self.run_script(GATHER, want=0)
        self.assertNotIn("--- vault CLAUDE.md ---", self.out)
        self.assertNotIn("# Fixture vault rules", self.out)
        self.assertNotRegex(self.out, r"(?m)^vault:")


class SaveTest(VaultCase):
    def setUp(self):
        super().setUp()
        self.use_vault()

    def draft(self, name, text):
        path = self.tmp / f"{name}.md"
        path.write_bytes(text.encode("utf-8"))
        return path

    def save(self, *args, want):
        return self.run_script(SAVE, *args, want=want)

    def note(self, rel):
        return (self.vault / rel).read_bytes().decode("utf-8")

    # usage and system errors

    def test_help(self):
        self.save("-h", want=0)

    def test_args(self):
        self.save("Only Two", want=2)

    def test_no_draft(self):
        self.save("New", self.tmp / "missing.md", want=2)

    def test_not_draft_status(self):
        d = self.draft("nostatus", "---\ntype: knowledge\nstatus: review\n---\nBody.\n")
        self.save("New", d, want=2)

    def test_empty_body(self):
        d = self.draft("nobody", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n# Title only\n")
        self.save("New", d, want=2)

    def test_dead_link(self):
        d = self.draft("badlink", '---\ntype: knowledge\ntopic: AI\nstatus: draft\nrelated: ["[[Docker Basics]]", "[[Nope]]"]\n'
                                  "---\nSee [[Missing Note|x]].\n")
        self.save("New", d, want=2)
        self.assertIn("Nope", self.err)
        self.assertIn("Missing Note", self.err)
        self.assertNotIn("suggest:", self.out)

    def test_dead_link_suggest(self):
        d = self.draft("sug", '---\ntype: knowledge\ntopic: AI\nstatus: draft\nrelated: ["[[docker basic]]"]\n---\n'
                              "See [[Kubernetis]], [[Containr Orchestration|x]] and [[Nope]].\n")
        self.save("New", d, want=2)
        self.assertEqual(self.out.splitlines(), [
            "suggest: Containr Orchestration -> Kubernetes",
            "suggest: Kubernetis -> Kubernetes",
            "suggest: docker basic -> Docker Basics",
        ])
        self.assertIn("Nope", self.err)
        self.assertTrue(d.exists(), "removed the draft file")

    def test_no_inbox(self):
        noinbox = self.tmp / "noinbox"
        noinbox.mkdir()
        (noinbox / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
        self.use_vault(noinbox)
        d = self.draft("ok", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save("New", d, want=1)

    def test_no_config(self):
        self.cfg.unlink()
        d = self.draft("ok", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save("New", d, want=0)
        self.assertEqual(self.out.strip(), MISSING)
        self.assertTrue(d.exists(), "removed the draft file")

    def test_bad_vault(self):
        self.use_vault(self.tmp / "nowhere")
        d = self.draft("ok", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save("New", d, want=0)
        self.assertRegex(self.out, r"^ERROR: .*/wiki-vault:overwrite")

    def test_failed_saves_keep_vault(self):
        before = sums(self.vault)
        self.test_not_draft_status()
        self.test_empty_body()
        self.test_dead_link()
        self.assertEqual(before, sums(self.vault), "failed saves changed the vault")

    # create

    def test_create(self):
        d = self.draft("ok", '---\ntype: knowledge\ntopic: AI\nstatus: draft\nrelated: ["[[docker basics]]"]\n'
                             "---\n# Whatever Heading\n\nSee [[Context Engineering#Intro|CE]].\n\n"
                             "## Part\n\nText.\n")
        self.save("ACE vs SOP", d, want=0)
        self.assertLine("saved: 01. Inbox/ACE vs SOP.md")
        self.assertLine("renamed: no")
        want = ('---\ntype: knowledge\ntopic: AI\nstatus: draft\nrelated: ["[[docker basics]]"]\n---\n'
                "# ACE vs SOP\n\nSee [[Context Engineering#Intro|CE]].\n\n## Part\n\nText.\n")
        self.assertEqual(self.note("01. Inbox/ACE vs SOP.md"), want)
        self.assertFalse(d.exists(), "kept the draft file")

    def test_title_from_heading(self):
        # No title argument: the first "# " line is the title, quotes and all.
        d = self.draft("head", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n\n# It's \"quoted\" $HOME\n\nBody.\n")
        self.save(d, want=0)
        self.assertLine("saved: 01. Inbox/It's -quoted- $HOME.md")
        self.assertLine("renamed: yes")
        self.assertEqual(self.note("01. Inbox/It's -quoted- $HOME.md"),
                         "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n# It's -quoted- $HOME\n\nBody.\n")

    def test_no_title(self):
        d = self.draft("notitle", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save(d, want=2)
        self.assertIn("no title", self.err)
        self.assertTrue(d.exists(), "removed the draft file")

    def test_rename(self):
        d = self.draft("ren", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save("A/B: c? [x] #y^ ", d, want=0)
        self.assertLine("saved: 01. Inbox/A-B- c- -x- -y-.md")
        self.assertLine("renamed: yes")
        self.assertIn("# A-B- c- -x- -y-", self.note("01. Inbox/A-B- c- -x- -y-.md").splitlines())

    def test_strip_md_suffix(self):
        d = self.draft("md", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save("Foo.MD", d, want=0)
        self.assertLine("saved: 01. Inbox/Foo.md")
        self.assertLine("renamed: yes")
        self.assertIn("# Foo", self.note("01. Inbox/Foo.md").splitlines())

    def test_no_usable_title(self):
        d = self.draft("dots", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save(" ... ", d, want=3)

    def test_reserved_title(self):
        for title in ("CON", "nul", "Com1.md", "LPT9 "):
            with self.subTest(title):
                d = self.draft("res", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
                self.save(title, d, want=3)
                self.assertIn("not a usable filename", self.err)
        d = self.draft("res", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save("CONTEXT", d, want=0)

    def test_invisible_chars(self):
        d = self.draft("inv", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save("A\tB​C‮ D\x07", d, want=0)
        self.assertLine("saved: 01. Inbox/ABC D.md")
        self.assertLine("renamed: yes")

    def test_leading_dots(self):
        d = self.draft("dot", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save(" ..hidden note", d, want=0)
        self.assertLine("saved: 01. Inbox/hidden note.md")
        self.assertLine("renamed: yes")

    def test_nfc_title(self):
        d = self.draft("nfc", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save("Café", d, want=0)
        self.assertLine("saved: 01. Inbox/Café.md")
        self.assertLine("renamed: yes")

    def test_nfc_duplicate(self):
        (self.vault / "20. Knowledge" / "Café.md").write_text("---\nstatus: review\n---\n",
                                                                   encoding="utf-8")
        d = self.draft("nfc", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save("CAFÉ", d, want=3)
        self.assertLine("exists: 20. Knowledge/Café.md")

    def test_long_title(self):
        d = self.draft("long", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save("wordy " * 60 + "end", d, want=0)
        name = self.out.splitlines()[0].removeprefix("saved: 01. Inbox/").removesuffix(".md")
        self.assertLessEqual(len(name.encode("utf-8")), 200)
        self.assertEqual(set(name.split(" ")), {"wordy"}, name)
        self.assertLine("renamed: yes")

    def test_long_vault_path(self):
        deep = self.tmp / ("v" * 120)
        shutil.copytree(self.vault, deep)
        self.use_vault(deep)
        d = self.draft("deep", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        self.save("alpha " * 40 + "omega", d, want=0)
        rel = self.out.splitlines()[0].removeprefix("saved: ")
        full = str(deep / rel)
        self.assertLessEqual(len(full), 259, full)
        self.assertGreater(len(full), 240, full)
        self.assertEqual(set(Path(rel).stem.split(" ")), {"alpha"}, rel)

    # collisions (user errors), nothing overwritten

    def test_collisions(self):
        self.test_create()
        d = self.draft("dots", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nBody.\n")
        before = sums(self.vault)
        with self.subTest("save-again"):
            self.save("ace vs sop", d, want=3)
            self.assertLine("exists: 01. Inbox/ACE vs SOP.md")
            self.assertLine("appendable: yes")
        with self.subTest("save-evergreen"):
            self.save("DOCKER basics", d, want=3)
            self.assertLine("exists: 20. Knowledge/Docker Basics.md")
            self.assertLine("status: evergreen")
            self.assertLine("appendable: no")
        with self.subTest("save-inbox-review"):
            self.save("Stuck Review", d, want=3)
            self.assertLine("status: review")
            self.assertLine("appendable: no")
        with self.subTest("append-review"):
            self.save("--append", "Stuck Review", d, want=3)
        with self.subTest("append-evergreen"):
            self.save("--append", "Docker Basics", d, want=3)
        with self.subTest("append-none"):
            self.save("--append", "No Such Note", d, want=3)
        self.assertEqual(before, sums(self.vault), "collisions changed the vault")

    # append

    def test_append(self):
        d = self.draft("app", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n# Existing Draft\n\nNew text.\n")
        self.save("--append", "existing draft", d, want=0)
        self.assertLine("appended: 01. Inbox/Existing Draft.md")
        want = ("---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n# Existing Draft\n\n"
                f"Old text.\n\n## {TODAY}\n\nNew text.\n")
        self.assertEqual(self.note("01. Inbox/Existing Draft.md"), want)
        self.assertFalse(d.exists(), "kept the draft file")
        with self.subTest("append-from-heading"):
            d2 = self.draft("app2", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n# existing draft\n\nMore.\n")
            self.save("--append", d2, want=0)
            self.assertLine("appended: 01. Inbox/Existing Draft.md")
            self.assertTrue(self.note("01. Inbox/Existing Draft.md").endswith("\n\nMore.\n"))
        with self.subTest("append-rerun"):
            self.save("--append", "Existing Draft", d, want=2)

    def test_append_keeps_crlf(self):
        note = self.vault / "01. Inbox" / "Existing Draft.md"
        note.write_bytes(note.read_bytes().replace(b"\n", b"\r\n"))
        d = self.draft("app", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nNew text.\n")
        self.save("--append", "Existing Draft", d, want=0)
        self.assertTrue(note.read_bytes().endswith(f"Old text.\r\n\r\n## {TODAY}\r\n\r\nNew text.\r\n".encode()))

    def test_append_adds_missing_newline(self):
        note = self.vault / "01. Inbox" / "Existing Draft.md"
        note.write_bytes(note.read_bytes().rstrip(b"\n"))
        d = self.draft("app", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nNew text.\n")
        self.save("--append", "Existing Draft", d, want=0)
        self.assertTrue(self.note("01. Inbox/Existing Draft.md").endswith(f"Old text.\n\n## {TODAY}\n\nNew text.\n"))

    # links in code, a self link and a quoted status are fine

    def test_code_links(self):
        d = self.draft("code", '---\ntype: knowledge\ntopic: AI\nstatus: "draft"\nrelated: []\n---\nSee [[Code Links]] and `x = [[1]]`.\n\n'
                               "```python\ny = [[1, 2]]\n```\n")
        self.save("Code Links", d, want=0)
        self.assertLine("saved: 01. Inbox/Code Links.md")

    # the same name in two folders: never appendable

    def test_duplicate_name(self):
        (self.vault / "30. Projects").mkdir()
        shutil.copy(self.vault / "01. Inbox" / "Existing Draft.md",
                    self.vault / "30. Projects" / "existing draft.md")
        d = self.draft("dup", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nMore.\n")
        before = sums(self.vault)
        self.save("Existing Draft", d, want=3)
        self.assertLine("exists: 01. Inbox/Existing Draft.md")
        self.assertLine("exists: 30. Projects/existing draft.md")
        self.assertLine("appendable: no")
        with self.subTest("alias"):
            self.save("CONTAINER orchestration", d, want=3)
            self.assertEqual(self.out.splitlines(), [
                "exists: 20. Knowledge/Kubernetes.md", "status: evergreen", "appendable: no"])
        with self.subTest("archived-alias"):
            (self.vault / "99. Archived").mkdir()
            shutil.move(self.vault / "20. Knowledge" / "Docker Basics.md",
                        self.vault / "99. Archived" / "Docker Basics.md")
            self.save("Containers", d, want=0)
            self.assertLine("saved: 01. Inbox/Containers.md")
            before = sums(self.vault)
            d = self.draft("dup", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\nMore.\n")
        with self.subTest("append-dup"):
            self.save("--append", "Existing Draft", d, want=3)
        self.assertEqual(before, sums(self.vault), "duplicate name changed the vault")


class SafetyTest(VaultCase):
    """Secret scan, strict frontmatter and no temp files left behind."""

    draft, save, note = SaveTest.draft, SaveTest.save, SaveTest.note

    def setUp(self):
        super().setUp()
        self.use_vault()

    def test_secrets(self):
        cases = {
            "-----BEGIN OPENSSH PRIVATE KEY-----": "private key",
            "curl -H 'Authorization: Bearer abc123def456'": "authorization header",
            "token is bearer eyJhbGciOiJIUzI1NiJ9abcdef": "bearer token",
            "key sk-ant-api03-abcdefghijklmnopqrstuvwx": "api key",
            "AKIAABCDEFGHIJKLMNOP": "api key",
            "password=hunter2": "password or secret",
            'db: {"password": "x9y"}': "password or secret",
            "postgres://bob:pw1@db/app": "url with password",
        }
        before = sums(self.vault)
        for line, kind in cases.items():
            with self.subTest(line):
                d = self.draft("sec", f"---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n# Sec\n\n```\n{line}\n```\n")
                self.save(d, want=3)
                self.assertEqual(self.out.splitlines(), [f"secret: line 9: {kind}"])
                self.assertNotIn(line.split()[-1].strip("'\"}"), self.out + self.err)
                self.assertTrue(d.exists(), "removed the draft file")
        self.assertEqual(before, sums(self.vault), "secret draft changed the vault")
        self.save("--allow-secrets", d, want=0)
        self.assertLine("saved: 01. Inbox/Sec.md")

    def test_no_false_secrets(self):
        d = self.draft("ok", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n# Fine\n\nThe secret: keep it short.\n"
                             "Use password=<your password> or pwd=$(pwd).\n"
                             "api_key = os.environ['KEY'] and password = get_password().\n"
                             "Bearer tokens expire.\n")
        self.save(d, want=0)

    def test_unclosed_frontmatter(self):
        d = self.draft("open", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n# Open\n\nBody.\n")
        self.save(d, want=2)
        self.assertIn("no closing ---", self.err)
        self.assertNotIn("no body", self.err)

    def test_bad_frontmatter(self):
        d = self.draft("bad", "---\ntype: knowledge\ntopic: AI\nstatus: draft\ncreated: 2026-1-5\nupdated: 2026-02-30\n"
                              "status: draft\nrelated: [[Docker Basics]]\nrelated2: x\n"
                              "due_date: soon\n---\n# Bad\n\nBody.\n")
        before = sums(self.vault)
        self.save(d, want=2)
        self.assertEqual(self.out.splitlines(), [
            "frontmatter: line 5: created is not YYYY-MM-DD: 2026-1-5",
            "frontmatter: line 6: updated is not YYYY-MM-DD: 2026-02-30",
            "frontmatter: line 7: duplicate key status (first on line 4)",
            'frontmatter: line 8: related entry is not a quoted "[[link]]": [[Docker Basics]]',
            "frontmatter: line 10: due_date is not YYYY-MM-DD: soon",
        ])
        d = self.draft("bad2", '---\ntype: knowledge\ntopic: AI\nstatus: draft\nrelated:\n  - "[[Kubernetes]]"\n'
                               "  - Docker Basics\n---\n# Bad2\n\nBody.\n")
        self.save(d, want=2)
        self.assertEqual(self.out.splitlines(), [
            'frontmatter: line 5: related entry is not a quoted "[[link]]": Docker Basics'])
        self.assertEqual(before, sums(self.vault), "bad frontmatter changed the vault")

    def test_tags_normalized(self):
        d = self.draft("tags", f"---\ntype: knowledge\ntopic: AI\nstatus: draft\ncreated: '{TODAY}'\n"
                               "tags: [AI Tools, '#Foo_Bar']\naliases:\n  - Big Name\n---\n"
                               "# Tags\n\nBody.\n")
        self.save(d, want=0)
        self.assertLine("normalized: tags")
        self.assertIn("tags: [ai-tools, foo-bar]\naliases:\n  - Big Name\n",
                      self.note("01. Inbox/Tags.md"))
        d = self.draft("tags2", "---\ntype: knowledge\ntopic: AI\nstatus: draft\ntags:\n  - Big Tag\n  - ok\n---\n"
                                "# Tags2\n\nBody.\n")
        self.save(d, want=0)
        self.assertIn("tags:\n  - big-tag\n  - ok\n---", self.note("01. Inbox/Tags2.md"))
        d = self.draft("tags3", "---\ntype: knowledge\ntopic: AI\nstatus: draft\ntags: [ok]\n---\n# Tags3\n\nBody.\n")
        self.save(d, want=0)
        self.assertNotIn("normalized: tags", self.out)

    def test_required_keys_and_type(self):
        before = sums(self.vault)
        d = self.draft("req", "---\nstatus: draft\ntopic:\n---\n# Req\n\nBody.\n")
        self.save(d, want=2)
        self.assertEqual(self.out.splitlines(), ["frontmatter: line 1: no type",
                                                 "frontmatter: line 1: no topic"])
        d = self.draft("req", "---\ntype: 'Recipe'\ntopic:\n  - AI\nstatus: draft\n---\n"
                              "# Req\n\nBody.\n")
        self.save(d, want=2)
        self.assertEqual(self.out.splitlines(), [
            "frontmatter: line 2: type Recipe is not in the vault CLAUDE.md list: how-to, knowledge"])
        self.assertEqual(before, sums(self.vault), "bad frontmatter changed the vault")
        (self.vault / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")
        self.save(d, want=0)  # no type list in the vault CLAUDE.md: any type

    def test_empty_sections(self):
        d = self.draft("sec", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n# Sec\n\n"
                              "## Empty\n\n<!-- todo -->\n^block-1\n## Code\n```\n## not a heading\n"
                              "```\n## Parent\n### Child\nText.\n### Last\n\n")
        before = sums(self.vault)
        self.save(d, want=2)
        self.assertEqual(self.out.splitlines(), ["section: line 8: ## Empty is empty",
                                                 "section: line 19: ### Last is empty"])
        self.assertEqual(before, sums(self.vault), "empty sections changed the vault")
        with self.subTest("append"):
            self.save("--append", "Existing Draft", d, want=2)
        self.assertEqual(before, sums(self.vault), "empty sections changed the vault")

    def test_all_problems_in_one_run(self):
        d = self.draft("all", "---\ntype: knowledge\ntopic: AI\nstatus: draft\ncreated: 2026-13-01\n---\n"
                              "# All\n\n## Empty\n\n## Full\nSee [[Kubernetis]].\n")
        before = sums(self.vault)
        self.save(d, want=2)
        self.assertEqual(self.out.splitlines(), [
            "frontmatter: line 5: created is not YYYY-MM-DD: 2026-13-01",
            "section: line 9: ## Empty is empty",
            "suggest: Kubernetis -> Kubernetes",
        ])
        self.assertEqual(len(self.err.splitlines()), 3, self.err)
        self.assertEqual(before, sums(self.vault), "bad draft changed the vault")

    def test_no_temp_left(self):
        d = self.draft("t", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n# Temp\n\nBody.\n")
        self.save(d, want=0)
        d = self.draft("t", "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n# Temp\n\nMore.\n")
        self.save("--append", d, want=0)
        self.assertTrue(self.note("01. Inbox/Temp.md").endswith("\n\nMore.\n"))
        self.assertEqual([p.name for p in (self.vault / "01. Inbox").iterdir()
                          if p.name.startswith(".")], [])


def load_save():
    """save.py as a module, for failure injection in-process."""
    import importlib.util
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))  # save.py imports gather.py next to it
    spec = importlib.util.spec_from_file_location("save_script", SAVE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def no_link(*_):
    raise OSError("hard links not supported")


class AtomicTest(unittest.TestCase):
    """Failures during create and append never leave a partial or changed note."""

    def setUp(self):
        self.mod = load_save()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inbox = self.tmp / "01. Inbox"
        self.inbox.mkdir()

    def patch(self, obj, name, value):
        self.addCleanup(setattr, obj, name, getattr(obj, name))
        setattr(obj, name, value)

    def names(self):
        return sorted(p.name for p in self.inbox.iterdir())

    def fail_code(self, func, *args):
        with self.assertRaises(self.mod.Fail) as cm:
            func(*args)
        return cm.exception.code

    def test_create_exists(self):
        (self.inbox / "N.md").write_bytes(b"mine")
        self.assertEqual(self.fail_code(self.mod.create_note, self.tmp, "N", "---\n---", "b"), 3)
        self.assertEqual((self.inbox / "N.md").read_bytes(), b"mine")
        self.assertEqual(self.names(), ["N.md"])

    def test_create_without_hard_links(self):
        self.patch(self.mod.os, "link", no_link)
        self.mod.create_note(self.tmp, "N", "---\n---", "b")
        self.assertEqual((self.inbox / "N.md").read_bytes(), b"---\n---\n# N\n\nb\n")
        self.assertEqual(self.names(), ["N.md"])

    def test_create_fallback_write_error(self):
        calls = []

        def failing(out, data):
            calls.append(1)
            out.write(data[:3])
            if len(calls) == 2:  # the temp file works, the direct write fails halfway
                raise OSError("disk full")
            out.write(data[3:])
        self.patch(self.mod.os, "link", no_link)
        self.patch(self.mod, "write_full", failing)
        self.assertEqual(self.fail_code(self.mod.create_note, self.tmp, "N", "---\n---", "b"), 1)
        self.assertEqual(self.names(), [], "left a partial note")

    def test_append_changed_meanwhile(self):
        note = self.inbox / "D.md"
        note.write_bytes(b"old\n")
        real = self.mod.write_temp

        def racing(folder, data):
            note.write_bytes(b"old\nobsidian edit\n")
            return real(folder, data)
        self.patch(self.mod, "write_temp", racing)
        self.assertEqual(self.fail_code(self.mod.append_note, self.tmp, "01. Inbox/D.md", "x"), 1)
        self.assertEqual(note.read_bytes(), b"old\nobsidian edit\n")
        self.assertEqual(self.names(), ["D.md"])

    def test_append_write_error_keeps_note(self):
        note = self.inbox / "D.md"
        note.write_bytes(b"old\n")

        def failing(out, data):
            out.write(data[:2])
            raise OSError("disk full")
        self.patch(self.mod, "write_full", failing)
        self.assertEqual(self.fail_code(self.mod.append_note, self.tmp, "01. Inbox/D.md", "x"), 1)
        self.assertEqual(note.read_bytes(), b"old\n")
        self.assertEqual(self.names(), ["D.md"])


def tearDownModule():
    # Every test works on a copy, so the fixture vault must never change.
    if sums(FIXTURE) != FIXTURE_SUMS:
        raise AssertionError("fixture vault changed")


if __name__ == "__main__":
    unittest.main()
