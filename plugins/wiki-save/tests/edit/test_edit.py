"""Tests for edit.py on a copy of the fixture vault with a temp HOME."""

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
EDIT = HERE.parents[1] / "skills" / "edit" / "scripts" / "edit.py"
TODAY = date.today().isoformat()
MISSING = ("ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use "
           "/wiki-vault:add <vault path> to configure your vault.")
DOCKER = "20. Knowledge/Docker Basics.md"


def sums(folder):
    """Hash of every file in a folder, to prove nothing changed."""
    return {p.relative_to(folder).as_posix(): hashlib.md5(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


class VaultCase(unittest.TestCase):
    """Fresh vault copy ("my vault", with a space) and HOME per test (copied from test_save.py)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vault = self.tmp / "my vault"
        shutil.copytree(FIXTURE, self.vault)
        self.home = self.tmp / "home"
        self.cfg = self.home / ".claude" / "obsidian-wiki" / "vault-path"

    def run_script(self, script, *args, want, env=None):
        """Run a script, check its exit code, keep stdout and stderr."""
        env = dict(os.environ, HOME=str(self.home), PYTHONIOENCODING="utf-8",
                   TMPDIR=str(self.tmp), TEMP=str(self.tmp), TMP=str(self.tmp), **(env or {}))
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


class EditTest(VaultCase):
    def setUp(self):
        super().setUp()
        self.use_vault()

    def edit(self, *args, want):
        return self.run_script(EDIT, *args, want=want)

    def prepare(self, note, want=0):
        self.edit("prepare", note, want=want)
        return dict(line.split(": ", 1) for line in self.out.splitlines() if ": " in line)

    def note(self, rel):
        return (self.vault / rel).read_bytes().decode("utf-8")

    def change(self, info, old, new):
        """Edit the draft file the way the model does."""
        draft = Path(info["draft_file"])
        draft.write_bytes(draft.read_bytes().replace(old.encode(), new.encode()))
        return draft

    def publish(self, info, *extra, want=0):
        return self.edit("publish", *extra, info["note"], info["draft_file"], info["sha"], want=want)

    # usage and vault problems

    def test_help(self):
        self.edit("--help", want=0)

    def test_args(self):
        before = sums(self.vault)
        self.edit(want=2)
        self.edit("prepare", want=2)
        self.edit("prepare", "a", "b", want=2)
        self.edit("publish", "a", "b", want=2)
        self.edit("fix", "a", want=2)
        self.edit("prepare", "../outside", want=2)
        self.edit("prepare", ".obsidian/x.md", want=2)
        self.assertEqual(before, sums(self.vault))

    def test_no_config(self):
        self.cfg.unlink()
        before = sums(self.vault)
        self.edit("prepare", "Docker Basics", want=0)
        self.assertEqual(self.out.strip(), MISSING)
        self.assertEqual(before, sums(self.vault))

    def test_no_inbox(self):
        shutil.rmtree(self.vault / "01. Inbox")
        self.edit("prepare", "Docker Basics", want=0)
        self.assertRegex(self.out, r"^ERROR: .*01\. Inbox.*/wiki-vault:overwrite")

    # prepare

    def test_prepare_forms(self):
        before = sums(self.vault)
        for form in ("docker basics", "DOCKER BASICS", "Containers 101", DOCKER,
                     "[[Docker Basics|x]]", "[[20. Knowledge/Docker Basics#Part]]"):
            info = self.prepare(form)
            self.assertEqual(info["note"], DOCKER, form)
        self.assertEqual(info["status"], "evergreen")
        self.assertEqual(info["target"], "01. Inbox/Docker Basics.md")
        self.assertEqual(Path(info["draft_file"]).read_bytes(), (self.vault / DOCKER).read_bytes())
        self.assertEqual(info["sha"], hashlib.sha256((self.vault / DOCKER).read_bytes()).hexdigest())
        self.assertEqual(before, sums(self.vault))

    def test_prepare_nfc(self):
        (self.vault / "20. Knowledge" / "Café Notes.md").write_text("Text.\n", encoding="utf-8")
        self.assertEqual(self.prepare("CAFÉ NOTES")["note"], "20. Knowledge/Café Notes.md")

    def test_prepare_unknown(self):
        self.edit("prepare", "Docker Basic", want=3)
        self.assertLine("suggest: Docker Basic -> Docker Basics")

    def test_template_never_found(self):
        self.edit("prepare", "Note", want=3)
        self.edit("prepare", "90. Templates/Note.md", want=3)

    def test_several(self):
        self.edit("prepare", "twin", want=3)
        self.assertEqual(self.out.splitlines(), ["match: 01. Inbox/Twin.md (status: draft)",
                                                 "match: 20. Knowledge/Twin.md (status: evergreen)"])

    def test_inbox_clash(self):
        self.edit("prepare", "20. Knowledge/Twin.md", want=3)
        self.assertLine("exists: 01. Inbox/Twin.md")

    # publish

    def test_publish_moves(self):
        info = self.prepare("Docker Basics")
        draft = self.change(info, "See [[Twin]].", "See [[Twin]].\n\n## Volumes\n\nKeep data.")
        self.publish(info)
        self.assertEqual(self.out.splitlines(), [
            "edited: 01. Inbox/Docker Basics.md", f"from: {DOCKER}",
            "status: draft (was evergreen)", "path-link: 30. Projects/Linker.md"])
        text = self.note("01. Inbox/Docker Basics.md")
        self.assertIn("status: draft\n", text)
        self.assertIn(f"updated: {TODAY}\n", text)
        self.assertIn("## Volumes\n\nKeep data.", text)
        self.assertFalse((self.vault / DOCKER).exists())
        self.assertFalse(draft.exists())

    def test_publish_archived(self):
        info = self.prepare("Old Idea")
        self.publish(info)
        self.assertLine("status: draft (was archived)")
        self.assertIn("status: draft\n", self.note("01. Inbox/Old Idea.md"))
        self.assertFalse((self.vault / "99. Archived/Old Idea.md").exists())

    def test_publish_in_place(self):
        for name, was in (("Inbox Draft", "draft"), ("Inbox Review", "review")):
            info = self.prepare(name)
            self.change(info, "Text.", "New text.")
            self.publish(info)
            rel = f"01. Inbox/{name}.md"
            self.assertEqual(self.out.splitlines()[:3],
                             [f"edited: {rel}", f"from: {rel}", f"status: draft (was {was})"])
            self.assertEqual(self.note(rel), "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n"
                                             f"# {name}\n\nNew text.\n")

    def test_publish_inbox_subfolder(self):
        (self.vault / "01. Inbox" / "sub").mkdir()
        (self.vault / "01. Inbox" / "sub" / "Deep.md").write_text("Deep.\n", encoding="utf-8")
        self.publish(self.prepare("Deep"))
        self.assertTrue((self.vault / "01. Inbox/Deep.md").exists())
        self.assertFalse((self.vault / "01. Inbox/sub/Deep.md").exists())

    def test_publish_no_frontmatter(self):
        self.publish(self.prepare("Plain"))
        self.assertEqual(self.note("01. Inbox/Plain.md"),
                         "---\nstatus: draft\n---\n# Plain\n\nNo frontmatter here.\n")

    def test_publish_no_status(self):
        self.publish(self.prepare("No Status"))
        self.assertLine("status: draft (was none)")
        self.assertEqual(self.note("01. Inbox/No Status.md"),
                         "---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n# No Status\n\nText.\n")

    def test_publish_crlf(self):
        crlf = b"---\r\ntype: knowledge\r\nstatus: review\r\nupdated: 2024-01-01\r\n---\r\nBody.\r\n"
        (self.vault / "20. Knowledge/Crlf.md").write_bytes(crlf)
        self.publish(self.prepare("Crlf"))
        self.assertEqual((self.vault / "01. Inbox/Crlf.md").read_bytes(),
                         crlf.replace(b"review", b"draft").replace(b"2024-01-01", TODAY.encode()))

    # failures keep the vault and the draft

    def test_changed_after_prepare(self):
        info = self.prepare("Docker Basics")
        with open(self.vault / DOCKER, "a", encoding="utf-8") as f:
            f.write("Synced.\n")
        before = sums(self.vault)
        self.publish(info, want=3)
        self.assertEqual(before, sums(self.vault))
        self.assertTrue(Path(info["draft_file"]).exists())

    def test_secrets(self):
        info = self.prepare("Docker Basics")
        self.change(info, "See [[Twin]].", "password=hunter22")
        before = sums(self.vault)
        self.publish(info, want=3)
        self.assertLine("secret: line 10: password or secret")
        self.assertEqual(before, sums(self.vault))
        self.publish(info, "--allow-secrets")

    def test_new_dead_link(self):
        info = self.prepare("Docker Basics")
        self.change(info, "See [[Twin]].", "See [[Twin]] and [[Kubernetis]].")
        before = sums(self.vault)
        self.publish(info, want=2)
        self.assertIn("Kubernetis", self.err)
        self.assertNotIn("Gone Note", self.err)  # a dead link the note already had passes
        self.assertEqual(before, sums(self.vault))
        self.assertTrue(Path(info["draft_file"]).exists())

    def test_inbox_name_taken_after_prepare(self):
        info = self.prepare("Docker Basics")
        (self.vault / "01. Inbox/Docker Basics.md").write_text("Other.\n", encoding="utf-8")
        before = sums(self.vault)
        self.publish(info, want=3)
        self.assertEqual(before, sums(self.vault))

    def test_unclosed_frontmatter(self):
        info = self.prepare("Docker Basics")
        self.change(info, "---\n# Docker", "# Docker")
        before = sums(self.vault)
        self.publish(info, want=2)
        self.assertEqual(before, sums(self.vault))

    def test_prepare_unclosed(self):
        (self.vault / "20. Knowledge/Broken.md").write_text("---\nstatus: review\nBody.\n", encoding="utf-8")
        before = sums(self.vault)
        self.edit("prepare", "Broken", want=2)
        self.assertIn("closing ---", self.err)
        self.assertEqual(before, sums(self.vault))

    def test_draft_lost_content(self):
        for old, new in (("---\ntype: knowledge\ntopic: Docker\nstatus: evergreen\nupdated: 2024-01-01\n"
                          "aliases: [Containers 101]\n---\n", ""),
                         ("# Docker Basics\n\nSee [[Twin]]. Old dead link [[Gone Note]].\n", "\n")):
            info = self.prepare("Docker Basics")
            self.change(info, old, new)
            before = sums(self.vault)
            self.publish(info, want=2)
            self.assertEqual(before, sums(self.vault))
            self.assertTrue(Path(info["draft_file"]).exists())

    def test_draft_missing(self):
        info = self.prepare("Docker Basics")
        Path(info["draft_file"]).unlink()
        self.publish(info, want=2)


if __name__ == "__main__":
    unittest.main()
