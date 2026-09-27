"""Tests for skills/delete/scripts/delete.py, run as a subprocess with a temp HOME."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "skills" / "delete" / "scripts" / "delete.py"


class DeleteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.cfg = self.home / ".claude" / "obsidian-wiki" / "vault-path"
        self.cfg.parent.mkdir(parents=True)

    def run_script(self, *args, home=True):
        env = dict(os.environ)
        env.pop("HOME", None)
        if home:
            env["HOME"] = str(self.home)
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env,
                              capture_output=True, text=True, encoding="utf-8")

    def write_cfg(self, text):
        self.cfg.write_bytes(text.encode("utf-8"))

    def check(self, want_code, want_out, *args):
        res = self.run_script(*args)
        self.assertEqual(res.returncode, want_code, res.stderr)
        self.assertEqual(res.stdout.rstrip("\n"), want_out)
        return res

    def assert_system_error(self, res):
        lines = res.stderr.splitlines()
        self.assertEqual(len(lines), 1, res.stderr)
        self.assertTrue(lines[0].startswith("SYSTEM ERROR:"), res.stderr)

    def test_removed_and_vault_untouched(self):
        vault = self.tmp / "vault"
        vault.mkdir()
        (vault / "note.md").write_text("keep\n", encoding="utf-8")
        self.write_cfg(f"{vault}\n")
        self.check(0, f"removed: {vault}")
        self.assertFalse(self.cfg.exists())
        self.assertEqual((vault / "note.md").read_text(encoding="utf-8"), "keep\n")

    def test_again_reports_none(self):
        self.write_cfg("/v\n")
        self.check(0, "removed: /v")
        self.check(0, "removed: none")

    def test_no_config_folder(self):
        shutil.rmtree(self.home / ".claude")
        self.check(0, "removed: none")

    def test_crlf_and_spaces(self):
        self.write_cfg("C:/My Vault/Wiki\r\n")
        self.check(0, "removed: C:/My Vault/Wiki")

    def test_empty_file(self):
        self.write_cfg("")
        self.check(0, "removed: none")
        self.assertFalse(self.cfg.exists())

    def test_blank_file(self):
        self.write_cfg("  \t\n")
        self.check(0, "removed: none")

    def test_help(self):
        for flag in ("--help", "-h"):
            res = self.check(0, self.run_script(flag).stdout.rstrip("\n"), flag)
            self.assertTrue(res.stdout.startswith("usage: delete.py"))

    def test_usage_keeps_file(self):
        self.write_cfg("/v\n")
        res = self.check(2, "", "extra")
        self.assert_system_error(res)
        self.assertTrue(self.cfg.exists())

    def test_no_home(self):
        res = self.run_script(home=False)
        self.assertEqual(res.returncode, 1)
        self.assertEqual(res.stdout, "")
        self.assert_system_error(res)

    def test_not_a_file(self):
        self.cfg.mkdir()
        res = self.check(1, "")
        self.assert_system_error(res)


if __name__ == "__main__":
    unittest.main()
