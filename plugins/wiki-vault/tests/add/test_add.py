"""Tests for skills/add/scripts/status.py and add.py with a temp HOME."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "add" / "scripts"
STATUS = SCRIPTS / "status.py"
ADD = SCRIPTS / "add.py"


class AddTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.config = self.home / ".claude" / "obsidian-wiki" / "vault-path"
        self.vault = self.tmp / "My Vault"
        self.vault.mkdir()

    def run_script(self, script, *args, home=True):
        env = dict(os.environ)
        env.pop("HOME", None)
        if home:
            env["HOME"] = str(self.home)
        return subprocess.run([sys.executable, str(script), *args], env=env,
                              capture_output=True, text=True, encoding="utf-8")

    def check(self, result, code, stdout="", stderr=""):
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertEqual(result.stdout.rstrip("\n"), stdout)
        self.assertIn(stderr, result.stderr)

    def make_config(self, content):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_bytes(content)

    def stored(self):
        return self.config.read_text(encoding="utf-8").rstrip("\n")


class StatusTest(AddTestBase):
    def test_help(self):
        full = self.run_script(STATUS, "--help")
        self.check(self.run_script(STATUS, "-h"), 0, full.stdout.rstrip("\n"))
        self.assertTrue(full.stdout.startswith("usage:"))

    def test_none(self):
        self.check(self.run_script(STATUS), 0, "configured: none")

    def test_empty_file(self):
        self.make_config(b"")
        self.check(self.run_script(STATUS), 0, "configured: none")

    def test_set(self):
        self.make_config(b"C:/Vault\r\n")
        self.check(self.run_script(STATUS), 0, "configured: C:/Vault")

    def test_usage(self):
        self.check(self.run_script(STATUS, "extra"), 2, stderr="usage:")

    def test_no_home(self):
        self.check(self.run_script(STATUS, home=False), 1, stderr="SYSTEM ERROR:")


class AddTest(AddTestBase):
    def tearDown(self):
        # The vault itself is never touched.
        self.assertEqual(list(self.vault.iterdir()), [])

    def test_help(self):
        full = self.run_script(ADD, "--help")
        self.check(self.run_script(ADD, "-h"), 0, full.stdout.rstrip("\n"))
        self.assertTrue(full.stdout.startswith("usage:"))

    def test_ok_with_spaces_and_backslashes(self):
        posix = self.vault.as_posix()
        result = self.run_script(ADD, posix.replace("/", "\\"))
        self.check(result, 0, f"configured: {posix}\nfolder: found")
        self.assertEqual(self.stored(), posix)

    def test_already_configured(self):
        posix = self.vault.as_posix()
        self.run_script(ADD, posix)
        other = str(self.tmp / "other")
        self.check(self.run_script(ADD, other), 3,
                   stderr=f"USER ERROR: add.py: already configured: {posix}")
        self.check(self.run_script(ADD, posix), 3, stderr="already configured")
        self.assertEqual(self.stored(), posix)

    def test_empty_file_counts_as_not_configured(self):
        self.make_config(b"")
        posix = self.vault.as_posix()
        self.check(self.run_script(ADD, posix), 0, f"configured: {posix}\nfolder: found")

    def test_missing_folder(self):
        nope = (self.tmp / "nope").as_posix()
        self.check(self.run_script(ADD, nope), 3,
                   stderr=f"USER ERROR: add.py: folder not found: {nope}")
        self.assertFalse(self.config.exists())
        self.check(self.run_script(ADD, "--allow-missing", nope), 0,
                   f"configured: {nope}\nfolder: missing")
        self.assertEqual(self.stored(), nope)

    def test_dashdash_ends_options(self):
        self.check(self.run_script(ADD, "--allow-missing", "--", "-h"), 0,
                   "configured: -h\nfolder: missing")
        self.assertEqual(self.stored(), "-h")

    def test_usage_errors_write_nothing(self):
        vault = str(self.vault)
        cases = [
            ((), "expected one vault path"),
            (("a", "b"), "expected one vault path"),
            (("",), "empty vault path"),
            ((vault + "\nx",), "newline"),
            (("--force", vault), "unknown option"),
        ]
        for args, message in cases:
            with self.subTest(args=args):
                self.check(self.run_script(ADD, *args), 2, stderr=message)
        self.assertFalse((self.home / ".claude").exists())

    def test_no_home(self):
        self.check(self.run_script(ADD, str(self.vault), home=False), 1, stderr="SYSTEM ERROR:")

    def test_config_not_a_file(self):
        self.config.mkdir(parents=True)
        self.check(self.run_script(ADD, str(self.vault)), 1, stderr="SYSTEM ERROR:")


if __name__ == "__main__":
    unittest.main()
