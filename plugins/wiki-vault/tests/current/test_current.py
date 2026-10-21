"""Tests for skills/current/scripts/current.py with a temp HOME."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CURRENT = Path(__file__).resolve().parents[2] / "skills" / "current" / "scripts" / "current.py"


class CurrentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.config = self.home / ".claude" / "obsidian-wiki" / "vault-path"
        self.vault = self.tmp / "My Vault"
        (self.vault / ".obsidian").mkdir(parents=True)
        (self.vault / "CLAUDE.md").write_text("rules\n", encoding="utf-8")

    def run_current(self, *args):
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run([sys.executable, str(CURRENT), *args], env=env, cwd=self.tmp,
                              capture_output=True, text=True, encoding="utf-8")

    def store(self, path):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(f"{path}\n", encoding="utf-8")

    def check(self, result, code, stdout):
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertEqual(result.stdout.rstrip("\n"), stdout)

    def test_help(self):
        out = self.run_current("--help")
        self.assertEqual(out.returncode, 0)
        self.assertTrue(out.stdout.startswith("usage:"))

    def test_bad_usage(self):
        out = self.run_current("x")
        self.assertEqual(out.returncode, 2)
        self.assertIn("usage: current.py", out.stderr)

    def test_not_configured(self):
        self.check(self.run_current(), 0, "Vault is not configured. Use /wiki-vault:add "
                   "<vault path> to configure your vault.")

    def test_empty_file_is_not_configured(self):
        self.store("")
        self.assertIn("not configured", self.run_current().stdout)

    def test_ok(self):
        self.store(self.vault.as_posix())
        self.check(self.run_current(), 0, f"Vault configured: {self.vault.as_posix()}")

    def test_folder_gone(self):
        self.store((self.tmp / "gone").as_posix())
        self.check(self.run_current(), 0, f"Vault is configured as {(self.tmp / 'gone').as_posix()}, "
                   "but that folder no longer exists. Use /wiki-vault:overwrite to point to the new location.")

    def test_path_is_a_file(self):
        self.store((self.vault / "CLAUDE.md").as_posix())
        self.assertIn("no longer exists", self.run_current().stdout)

    def test_no_claude_md(self):
        (self.vault / "CLAUDE.md").unlink()
        self.store(self.vault.as_posix())
        self.assertIn("but that folder has no CLAUDE.md. Use /wiki-vault:overwrite", self.run_current().stdout)

    def test_no_obsidian_warns(self):
        (self.vault / ".obsidian").rmdir()
        self.store(self.vault.as_posix())
        self.check(self.run_current(), 0, f"Vault configured: {self.vault.as_posix()}\n"
                   f"Warning: no .obsidian folder in {self.vault.as_posix()}")

    def test_unreadable_config(self):
        self.config.mkdir(parents=True)  # a folder where the file should be
        out = self.run_current()
        self.assertEqual(out.returncode, 1)
        self.assertIn("SYSTEM ERROR: current.py", out.stderr)


if __name__ == "__main__":
    unittest.main()
