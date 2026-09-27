"""Tests for gather.py and save.py on a copy of the fixture vault with a temp HOME."""

import hashlib
import os
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

    def run_script(self, script, *args, want):
        """Run a script, check its exit code, keep stdout and stderr."""
        env = dict(os.environ, HOME=str(self.home), PYTHONIOENCODING="utf-8")
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
        self.set_config(f"{self.vault}\n")
        self.run_script(GATHER, want=0)
        self.assertRegex(self.out, r"^ERROR: .*01\. Inbox.*/wiki-vault:overwrite")

    def test_ok(self):
        self.set_config(f"{self.vault}/\r\n")
        before = sums(self.vault)
        self.run_script(GATHER, want=0)
        self.assertLine(f"vault: {self.vault.as_posix()}")
        self.assertLine(f"today: {TODAY}")
        self.assertLine("--- vault CLAUDE.md ---")
        self.assertLine("# Fixture vault rules")
        self.assertRegex(self.out, r"(?m)^topics: (AI|ai), Docker$")
        self.assertRegex(self.out, r"(?m)^draft_file: .*wiki-save-.*\.md$")
        self.assertEqual(before, sums(self.vault), "gather changed the vault")


class SaveTest(VaultCase):
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
        self.save(self.vault, "Only Two", want=2)

    def test_no_draft(self):
        self.save(self.vault, "New", self.tmp / "missing.md", want=2)

    def test_not_draft_status(self):
        d = self.draft("nostatus", "---\ntype: knowledge\nstatus: review\n---\nBody.\n")
        self.save(self.vault, "New", d, want=2)

    def test_empty_body(self):
        d = self.draft("nobody", "---\nstatus: draft\n---\n# Title only\n")
        self.save(self.vault, "New", d, want=2)

    def test_dead_link(self):
        d = self.draft("badlink", '---\nstatus: draft\nrelated: ["[[Docker Basics]]", "[[Nope]]"]\n'
                                  "---\nSee [[Missing Note|x]].\n")
        self.save(self.vault, "New", d, want=2)
        self.assertIn("Nope", self.err)
        self.assertIn("Missing Note", self.err)

    def test_no_inbox(self):
        (self.tmp / "noinbox").mkdir()
        d = self.draft("ok", "---\nstatus: draft\n---\nBody.\n")
        self.save(self.tmp / "noinbox", "New", d, want=1)

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
        self.save(self.vault, "ACE vs SOP", d, want=0)
        self.assertLine("saved: 01. Inbox/ACE vs SOP.md")
        self.assertLine("renamed: no")
        want = ('---\ntype: knowledge\ntopic: AI\nstatus: draft\nrelated: ["[[docker basics]]"]\n---\n'
                "# ACE vs SOP\n\nSee [[Context Engineering#Intro|CE]].\n\n## Part\n\nText.\n")
        self.assertEqual(self.note("01. Inbox/ACE vs SOP.md"), want)
        self.assertFalse(d.exists(), "kept the draft file")

    def test_rename(self):
        d = self.draft("ren", "---\nstatus: draft\n---\nBody.\n")
        self.save(self.vault, "A/B: c? [x] #y^ ", d, want=0)
        self.assertLine("saved: 01. Inbox/A-B- c- -x- -y-.md")
        self.assertLine("renamed: yes")
        self.assertIn("# A-B- c- -x- -y-", self.note("01. Inbox/A-B- c- -x- -y-.md").splitlines())

    def test_no_usable_title(self):
        d = self.draft("dots", "---\nstatus: draft\n---\nBody.\n")
        self.save(self.vault, " ... ", d, want=3)

    # collisions (user errors), nothing overwritten

    def test_collisions(self):
        self.test_create()
        d = self.draft("dots", "---\nstatus: draft\n---\nBody.\n")
        before = sums(self.vault)
        with self.subTest("save-again"):
            self.save(self.vault, "ace vs sop", d, want=3)
            self.assertLine("exists: 01. Inbox/ACE vs SOP.md")
            self.assertLine("appendable: yes")
        with self.subTest("save-evergreen"):
            self.save(self.vault, "DOCKER basics", d, want=3)
            self.assertLine("exists: 20. Knowledge/Docker Basics.md")
            self.assertLine("status: evergreen")
            self.assertLine("appendable: no")
        with self.subTest("save-inbox-review"):
            self.save(self.vault, "Stuck Review", d, want=3)
            self.assertLine("status: review")
            self.assertLine("appendable: no")
        with self.subTest("append-review"):
            self.save("--append", self.vault, "Stuck Review", d, want=3)
        with self.subTest("append-evergreen"):
            self.save("--append", self.vault, "Docker Basics", d, want=3)
        with self.subTest("append-none"):
            self.save("--append", self.vault, "No Such Note", d, want=3)
        self.assertEqual(before, sums(self.vault), "collisions changed the vault")

    # append

    def test_append(self):
        d = self.draft("app", "---\nstatus: draft\n---\n# Existing Draft\n\nNew text.\n")
        self.save("--append", self.vault, "existing draft", d, want=0)
        self.assertLine("appended: 01. Inbox/Existing Draft.md")
        want = ("---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n# Existing Draft\n\n"
                f"Old text.\n\n## {TODAY}\n\nNew text.\n")
        self.assertEqual(self.note("01. Inbox/Existing Draft.md"), want)
        self.assertFalse(d.exists(), "kept the draft file")
        with self.subTest("append-rerun"):
            self.save("--append", self.vault, "Existing Draft", d, want=2)

    def test_append_keeps_crlf(self):
        note = self.vault / "01. Inbox" / "Existing Draft.md"
        note.write_bytes(note.read_bytes().replace(b"\n", b"\r\n"))
        d = self.draft("app", "---\nstatus: draft\n---\nNew text.\n")
        self.save("--append", self.vault, "Existing Draft", d, want=0)
        self.assertTrue(note.read_bytes().endswith(f"Old text.\r\n\r\n## {TODAY}\r\n\r\nNew text.\r\n".encode()))

    def test_append_adds_missing_newline(self):
        note = self.vault / "01. Inbox" / "Existing Draft.md"
        note.write_bytes(note.read_bytes().rstrip(b"\n"))
        d = self.draft("app", "---\nstatus: draft\n---\nNew text.\n")
        self.save("--append", self.vault, "Existing Draft", d, want=0)
        self.assertTrue(self.note("01. Inbox/Existing Draft.md").endswith(f"Old text.\n\n## {TODAY}\n\nNew text.\n"))

    # links in code, a self link and a quoted status are fine

    def test_code_links(self):
        d = self.draft("code", '---\nstatus: "draft"\nrelated: []\n---\nSee [[Code Links]] and `x = [[1]]`.\n\n'
                               "```python\ny = [[1, 2]]\n```\n")
        self.save(self.vault, "Code Links", d, want=0)
        self.assertLine("saved: 01. Inbox/Code Links.md")

    # the same name in two folders: never appendable

    def test_duplicate_name(self):
        (self.vault / "30. Projects").mkdir()
        shutil.copy(self.vault / "01. Inbox" / "Existing Draft.md",
                    self.vault / "30. Projects" / "existing draft.md")
        d = self.draft("dup", "---\nstatus: draft\n---\nMore.\n")
        before = sums(self.vault)
        self.save(self.vault, "Existing Draft", d, want=3)
        self.assertLine("exists: 01. Inbox/Existing Draft.md")
        self.assertLine("exists: 30. Projects/existing draft.md")
        self.assertLine("appendable: no")
        with self.subTest("append-dup"):
            self.save("--append", self.vault, "Existing Draft", d, want=3)
        self.assertEqual(before, sums(self.vault), "duplicate name changed the vault")


def tearDownModule():
    # Every test works on a copy, so the fixture vault must never change.
    if sums(FIXTURE) != FIXTURE_SUMS:
        raise AssertionError("fixture vault changed")


if __name__ == "__main__":
    unittest.main()
