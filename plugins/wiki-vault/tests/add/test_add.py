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

    def test_no_home_falls_back_to_os_home(self):
        # Read-only: the real config is only read, never written.
        result = self.run_script(STATUS, home=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("configured: "))

    def test_config_not_a_file(self):
        self.config.mkdir(parents=True)
        self.check(self.run_script(STATUS), 1, stderr="SYSTEM ERROR: status.py: cannot read")


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
        self.check(result, 0, f"path: {posix}")
        self.assertEqual(self.stored(), posix)

    def test_trailing_slashes_removed(self):
        posix = self.vault.as_posix()
        self.check(self.run_script(ADD, posix + "//"), 0, f"path: {posix}")
        self.assertEqual(self.stored(), posix)

    def test_no_temp_file_left(self):
        self.run_script(ADD, str(self.vault))
        self.assertEqual([p.name for p in self.config.parent.iterdir()], ["vault-path"])

    def test_already_configured(self):
        posix = self.vault.as_posix()
        self.run_script(ADD, posix)
        other = str(self.tmp / "other")
        self.check(self.run_script(ADD, "--force", other), 3,
                   stderr=f"USER ERROR: already configured: {posix}")
        self.check(self.run_script(ADD, posix), 3, stderr="already configured")
        self.assertEqual(self.stored(), posix)

    def test_empty_file_counts_as_not_configured(self):
        self.make_config(b"")
        posix = self.vault.as_posix()
        self.check(self.run_script(ADD, posix), 0, f"path: {posix}")

    def test_missing_folder(self):
        nope = (self.tmp / "nope").as_posix()
        self.check(self.run_script(ADD, nope), 3,
                   stderr=f"USER ERROR: folder not found: {nope}")
        self.assertFalse(self.config.exists())
        self.check(self.run_script(ADD, "--force", nope), 0, f"path: {nope}")
        self.assertEqual(self.stored(), nope)

    def test_force_after_path(self):
        nope = (self.tmp / "nope").as_posix()
        self.check(self.run_script(ADD, nope, "--force"), 0, f"path: {nope}")
        self.assertEqual(self.stored(), nope)

    def test_usage_errors_write_nothing(self):
        vault = str(self.vault)
        cases = [
            ((), "SYSTEM ERROR: usage: add.py [--force] <vault-path>"),
            (("a", "b"), "SYSTEM ERROR: usage: add.py [--force] <vault-path>"),
            (("--allow-missing", vault), "SYSTEM ERROR: add.py: unknown option '--allow-missing', see --help"),
            (("--", vault), "unknown option '--'"),
            (("-x", vault), "unknown option '-x'"),
        ]
        for args, message in cases:
            with self.subTest(args=args):
                self.check(self.run_script(ADD, *args), 2, stderr=message)
        self.assertFalse((self.home / ".claude").exists())

    def test_bad_paths_write_nothing(self):
        vault = str(self.vault)
        cases = [
            ("", "USER ERROR: vault path is empty"),
            (vault + "\nx","USER ERROR: vault path contains a line break"),
            ("relative/vault", "USER ERROR: vault path is not absolute: relative/vault"),
        ]
        for arg, message in cases:
            with self.subTest(arg=arg):
                self.check(self.run_script(ADD, "--force", arg), 3, stderr=message)
        self.assertFalse((self.home / ".claude").exists())

    def test_no_home_needs_no_check(self):
        # Without HOME there is no own check any more: a usage error still comes first.
        self.check(self.run_script(ADD, home=False), 2, stderr="SYSTEM ERROR: usage:")

    def test_config_not_a_file(self):
        self.config.mkdir(parents=True)
        self.check(self.run_script(ADD, str(self.vault)), 1,
                   stderr="SYSTEM ERROR: add.py: cannot read")


if __name__ == "__main__":
    unittest.main()
