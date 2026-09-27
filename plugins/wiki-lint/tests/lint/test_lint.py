"""Tests for skills/lint/scripts/lint.py, run as a subprocess against copies of fixture-vault."""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[1]
LINT = PLUGIN / "skills" / "lint" / "scripts" / "lint.py"
VAULT_PY = PLUGIN / "scripts" / "vault.py"
MISSING = ("Vault path is missing. Install wiki-vault@obsidian-wiki and use "
           "/wiki-vault:add <vault path> to configure your vault.")
NO_RULES = ("The configured vault folder has no CLAUDE.md: {vault}. "
            "Use /wiki-vault:overwrite <vault path> to fix the vault path.")
FILES_ARGS = ["--files", "30. Knowledge/Bad Frontmatter.md", "10. Daily/", "30. Knowledge/Stray Draft.md"]


def tree(root):
    """{relative path: bytes} for every file under root, hidden ones included."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class LintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.vault = self.tmp / "v"
        shutil.copytree(HERE / "fixture-vault", self.vault)
        self.home = self.tmp / "home"
        self.configure(self.vault)

    def configure(self, vault):
        """Store vault as the configured vault path in the temp HOME, or remove it when None."""
        config = self.home / ".claude" / "obsidian-wiki" / "vault-path"
        config.parent.mkdir(parents=True, exist_ok=True)
        if vault is None:
            config.unlink(missing_ok=True)
        else:
            config.write_text(f"{vault}\r\n", encoding="utf-8")

    def run_script(self, script, *args):
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run([sys.executable, str(script), *args], capture_output=True, env=env)

    def lint(self, *args):
        return self.run_script(LINT, *args)

    def expect(self, result, code, prefix=None):
        self.assertEqual(result.returncode, code, result.stderr.decode(errors="replace"))
        if prefix:
            self.assertTrue(result.stderr.decode().startswith(prefix), result.stderr)

    def expect_vault_error(self, result, message):
        """A vault problem: one ERROR line on stdout, exit 0."""
        self.expect(result, 0)
        self.assertEqual(result.stdout.decode().strip(), f"ERROR: {message}")

    # 1. --dry-run: expected JSON, exit 4, no file changed
    def test_dry_run(self):
        before = tree(self.vault)
        r = self.lint("--dry-run")
        self.expect(r, 4)
        self.assertEqual(r.stdout.decode(), (HERE / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual(tree(self.vault), before)

    # 2 and 3. Real run: same JSON, fixed vault equals expected-vault; a second run fixes nothing
    def test_run_fixes_vault(self):
        r = self.lint()
        self.expect(r, 4)
        self.assertEqual(r.stdout.decode(), (HERE / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual(tree(self.vault), tree(HERE / "expected-vault"))
        again = json.loads(self.lint().stdout)
        self.assertEqual(again["movedToInbox"], [])
        self.assertEqual(again["removedDeadLinks"], [])

    # 4. --files mode: a note, a folder and a stray draft
    def test_files_mode(self):
        r = self.lint("--dry-run", *FILES_ARGS)
        self.expect(r, 4)
        self.assertEqual(r.stdout.decode(), (HERE / "expected-files.json").read_text(encoding="utf-8"))

    # 5. Clean note: exit 0
    def test_clean_note(self):
        self.expect(self.lint("--files", "01. Inbox/Good Draft.md"), 0)

    # 6. --help: exit 0, usage on stdout
    def test_help(self):
        for flag in ("--help", "-h"):
            r = self.lint(flag)
            self.expect(r, 0)
            self.assertTrue(r.stdout.decode().startswith("usage: lint.py"))

    # 7. Usage errors: exit 2
    def test_usage_errors(self):
        for label, args in (("unknown flag", ["--bogus"]),
                            ("--files without paths", ["--files"])):
            with self.subTest(label):
                self.expect(self.lint(*args), 2, "SYSTEM ERROR:")

    # 8. User errors: exit 3
    def test_user_errors(self):
        self.expect(self.lint("--files", "No Such.md"), 3, "USER ERROR:")
        (self.vault / "CLAUDE.md").write_text("# Rules\n\nNo lists here.\n", encoding="utf-8")
        self.expect(self.lint("--dry-run"), 3, "USER ERROR:")

    # 8b. Vault problems: the ERROR line from vault.py on stdout, exit 0, nothing changed
    def test_vault_errors(self):
        (self.vault / "CLAUDE.md").unlink()
        before = tree(self.vault)
        self.expect_vault_error(self.lint(), NO_RULES.format(vault=self.vault))
        gone = self.tmp / "nope"
        self.configure(gone)
        self.expect_vault_error(self.lint("--dry-run"), NO_RULES.format(vault=gone))
        self.configure(None)
        self.expect_vault_error(self.lint(), MISSING)
        self.assertEqual(tree(self.vault), before)

    # 9. System error: exit 1 when a note cannot be written, that note unchanged
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write read-only files")
    def test_write_failure(self):
        note = self.vault / "30. Knowledge" / "Dead Links.md"
        before = note.read_bytes()
        os.chmod(note, stat.S_IREAD)
        self.addCleanup(os.chmod, note, stat.S_IREAD | stat.S_IWRITE)
        r = self.lint()
        self.expect(r, 1, "SYSTEM ERROR:")
        self.assertEqual(note.read_bytes(), before)

    # 10. vault.py gives the injected context for step 1 of SKILL.md
    def test_vault_context(self):
        r = self.run_script(VAULT_PY)
        self.expect(r, 0)
        rules = (self.vault / "CLAUDE.md").read_text(encoding="utf-8").rstrip("\n")
        want = f"vault: {self.vault.as_posix()}\n--- vault CLAUDE.md ---\n{rules}\n"
        self.assertEqual(r.stdout.decode("utf-8").replace("\r\n", "\n"), want)
        self.assertEqual(tree(self.vault), tree(HERE / "fixture-vault"))


if __name__ == "__main__":
    unittest.main()
