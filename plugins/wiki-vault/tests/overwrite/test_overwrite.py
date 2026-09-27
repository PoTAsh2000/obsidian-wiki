"""Tests for skills/overwrite/scripts/overwrite.py. Uses a temp HOME only."""

import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "skills" / "overwrite" / "scripts" / "overwrite.py"


class OverwriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vault = (self.tmp / "My Vault").as_posix()
        self.other = (self.tmp / "Other").as_posix()
        self.nope = (self.tmp / "nope").as_posix()
        os.mkdir(self.vault)
        os.mkdir(self.other)
        self.home = self.tmp / "home"
        self.cfg = self.home / ".claude" / "obsidian-wiki" / "vault-path"

    def run_script(self, *args, home=None):
        env = dict(os.environ, HOME=str(home or self.home))
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env,
                              capture_output=True, text=True, encoding="utf-8")

    def assertRun(self, args, code, stdout, home=None):
        res = self.run_script(*args, home=home)
        self.assertEqual(res.returncode, code, res.stderr)
        self.assertEqual(res.stdout, stdout)
        return res

    def assertConfig(self, want):
        got = self.cfg.read_text(encoding="utf-8") if self.cfg.is_file() else None
        self.assertEqual(got, None if want is None else want + "\n")

    def test_help(self):
        long = self.run_script("--help")
        self.assertEqual(long.returncode, 0)
        self.assertTrue(long.stdout.startswith("usage: overwrite.py"))
        self.assertRun(["-h"], 0, long.stdout)

    def test_bad_usage_writes_nothing(self):
        res = self.assertRun([], 2, "")
        self.assertIn("SYSTEM ERROR:", res.stderr)
        self.assertRun([self.vault, self.other], 2, "")
        self.assertRun(["--nope", self.vault], 2, "")
        self.assertRun([""], 2, "")
        self.assertConfig(None)

    def test_user_errors_write_nothing(self):
        res = self.assertRun(["some/folder"], 3, "")
        self.assertIn("USER ERROR: vault path is not absolute", res.stderr)
        res = self.assertRun([self.nope], 3, "")
        self.assertIn(f"USER ERROR: folder not found: {self.nope}", res.stderr)
        self.assertRun(["/a\nb"], 3, "")
        self.assertConfig(None)

    def test_save_sequence(self):
        # first save, no old path, config folder created
        self.assertRun([self.vault], 0, f"path: {self.vault}\nold: none\n")
        self.assertConfig(self.vault)
        # overwrite shows the old path
        self.assertRun([self.other], 0, f"path: {self.other}\nold: {self.vault}\n")
        self.assertConfig(self.other)
        # idempotent
        self.assertRun([self.other], 0, f"path: {self.other}\nold: {self.other}\n")
        self.assertConfig(self.other)
        # backslashes and trailing slashes normalized
        self.assertRun(["--force", "C:\\Users\\me\\Vault\\"], 0,
                       f"path: C:/Users/me/Vault\nold: {self.other}\n")
        self.assertConfig("C:/Users/me/Vault")
        # missing folder with --force is saved, option after the path works too
        self.assertRun([self.nope, "--force"], 0, f"path: {self.nope}\nold: C:/Users/me/Vault\n")
        self.assertConfig(self.nope)
        # missing folder without --force keeps the old path
        self.assertRun([self.nope + "2"], 3, "")
        self.assertConfig(self.nope)
        # no temp files left behind
        self.assertEqual([p.name for p in self.cfg.parent.iterdir()], ["vault-path"])

    def test_roots_keep_slash(self):
        self.assertRun(["--force", "C:/"], 0, "path: C:/\nold: none\n")
        self.assertRun(["--force", "//"], 0, "path: /\nold: C:/\n")

    def test_crlf_old_config(self):
        self.cfg.parent.mkdir(parents=True)
        self.cfg.write_bytes(f"{self.vault}\r\n".encode("utf-8"))
        self.assertRun([self.other], 0, f"path: {self.other}\nold: {self.vault}\n")

    def test_system_error_when_config_folder_blocked(self):
        blocked = self.tmp / "blocked"
        blocked.mkdir()
        (blocked / ".claude").write_text("", encoding="utf-8")
        res = self.assertRun([self.vault], 1, "", home=blocked)
        self.assertIn("SYSTEM ERROR:", res.stderr)

    def test_script_hygiene(self):
        self.assertNotIn(b"\r", SCRIPT.read_bytes())
        py_compile.compile(str(SCRIPT), cfile=str(self.tmp / "overwrite.pyc"), doraise=True)


if __name__ == "__main__":
    unittest.main()
