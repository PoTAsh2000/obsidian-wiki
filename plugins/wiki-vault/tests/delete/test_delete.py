"""Tests for skills/delete/scripts/delete.py, run as a subprocess with a temp HOME."""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[2] / "skills" / "delete" / "scripts" / "delete.py"


def removed(path):
    return f"Vault path removed: {path}\nTo restore it, run /wiki-vault:add {path}"


class DeleteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.cfg = self.home / ".claude" / "obsidian-wiki" / "vault-path"
        self.cfg.parent.mkdir(parents=True)

    def run_script(self, *args):
        env = dict(os.environ, HOME=str(self.home))
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
        self.check(0, removed(vault))
        self.assertFalse(self.cfg.exists())
        self.assertEqual((vault / "note.md").read_text(encoding="utf-8"), "keep\n")

    def test_again_reports_none(self):
        self.write_cfg("/v\n")
        self.check(0, removed("/v"))
        self.check(0, "No vault path configured.")

    def test_no_config_folder(self):
        shutil.rmtree(self.home / ".claude")
        self.check(0, "No vault path configured.")

    def test_crlf_and_spaces(self):
        self.write_cfg("C:/My Vault/Wiki\r\n")
        self.check(0, removed("C:/My Vault/Wiki"))

    def test_empty_file(self):
        self.write_cfg("")
        self.check(0, "No vault path configured.")
        self.assertFalse(self.cfg.exists())

    def test_blank_file(self):
        self.write_cfg("  \t\n")
        self.check(0, "No vault path configured.")

    def test_help(self):
        for flag in ("--help", "-h"):
            res = self.check(0, self.run_script(flag).stdout.rstrip("\n"), flag)
            self.assertTrue(res.stdout.startswith("usage: delete.py"))

    def test_usage_keeps_file(self):
        self.write_cfg("/v\n")
        res = self.check(2, "", "extra")
        self.assert_system_error(res)
        self.assertTrue(self.cfg.exists())

    def test_not_a_file(self):
        self.cfg.mkdir()
        res = self.check(1, "")
        self.assert_system_error(res)

    def test_no_claim_left_behind_and_empty_folder_removed(self):
        self.write_cfg("/v\n")
        self.check(0, removed("/v"))
        self.assertFalse(self.cfg.parent.exists())
        self.assertTrue((self.home / ".claude").is_dir())

    def test_folder_with_other_files_kept(self):
        (self.cfg.parent / "notes.txt").write_text("keep\n", encoding="utf-8")
        self.write_cfg("/v\n")
        self.check(0, removed("/v"))
        self.assertEqual(list(self.cfg.parent.iterdir()), [self.cfg.parent / "notes.txt"])

    def test_empty_folder_kept_on_dry_run(self):
        self.check(0, "No vault path configured.", "--dry-run")
        self.assertTrue(self.cfg.parent.is_dir())
        self.check(0, "No vault path configured.")
        self.assertFalse(self.cfg.parent.exists())

    def test_existing_claim_name_untouched(self):
        old = [self.cfg.parent / f"vault-path.del.{n}" for n in (os.getpid(), 1, "x")]
        for f in old:
            f.write_text("old\n", encoding="utf-8")
        self.write_cfg("/v\n")
        self.check(0, removed("/v"))
        self.assertFalse(self.cfg.exists())
        self.assertEqual(sorted(self.cfg.parent.iterdir()), sorted(old))
        for f in old:
            self.assertEqual(f.read_text(encoding="utf-8"), "old\n")

    def test_dry_run_keeps_file(self):
        self.write_cfg("/v\n")
        self.check(0, "Would remove vault path: /v", "--dry-run")
        self.assertTrue(self.cfg.exists())
        self.assertEqual(list(self.cfg.parent.iterdir()), [self.cfg])
        self.check(0, removed("/v"))

    def test_dry_run_none(self):
        self.check(0, "No vault path configured.", "--dry-run")

    def test_dry_run_with_other_argument(self):
        self.write_cfg("/v\n")
        for args in (("--dry-run", "x"), ("x", "--dry-run"), ("--dry-run", "--dry-run")):
            self.assert_system_error(self.check(2, "", *args))
        self.assertTrue(self.cfg.exists())

    def test_dry_run_not_a_file(self):
        self.cfg.mkdir()
        self.assert_system_error(self.check(1, "", "--dry-run"))

    def stale(self, name, age=3600):
        f = self.cfg.parent / name
        f.write_text("/old\n", encoding="utf-8")
        t = f.stat().st_mtime - age
        os.utime(f, (t, t))
        return f

    def test_cleans_stale_temp_files_only(self):
        self.write_cfg("/v\n")
        stale = [self.stale("vault-path.tmp.123"), self.stale("vault-path.tmp.9")]
        keep = [self.stale("notes.txt"), self.stale("vault-path.tmp.x"),
                self.stale("vault-path.tmp.1.bak"), self.stale("vault-path.tmp.5", age=0)]
        (self.cfg.parent / "vault-path.tmp.77").mkdir()
        keep.append(self.cfg.parent / "vault-path.tmp.77")
        self.check(0, "Would remove vault path: /v\nWould clean up 2 leftover temp file(s).",
                   "--dry-run")
        self.assertTrue(all(f.exists() for f in stale))
        self.check(0, removed("/v") + "\nCleaned up 2 leftover temp file(s).")
        self.assertFalse(any(f.exists() for f in stale))
        self.assertEqual(sorted(self.cfg.parent.iterdir()), sorted(keep))

    def test_cleans_stale_claims_only(self):
        self.write_cfg("/v\n")
        stale = self.stale("vault-path.del.ab_12xyz")
        keep = [self.stale("vault-path.del.abc12xyz", age=0), self.stale("vault-path.del.short"),
                self.stale("vault-path.del.ab_12xyz9")]
        self.check(0, "Would remove vault path: /v\nWould clean up 1 leftover temp file(s).",
                   "--dry-run")
        self.assertTrue(stale.exists())
        self.check(0, removed("/v") + "\nCleaned up 1 leftover temp file(s).")
        self.assertEqual(sorted(self.cfg.parent.iterdir()), sorted(keep))

    def test_control_characters_escaped(self):
        self.write_cfg("/v\x1b[31mred\x00‮" + "x" * 400 + "\n")
        out = "/v\\x1b[31mred\\x00\\u202e" + "x" * (300 - 23) + "..."
        self.check(0, f"Would remove vault path: {out}", "--dry-run")
        self.check(0, removed(out))
        self.assertFalse(self.cfg.exists())

    def test_retries_sharing_violation(self):
        spec = importlib.util.spec_from_file_location("delete_mod", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.write_cfg("/v\n")
        real, calls = os.replace, []

        def flaky(*args):
            calls.append(args)
            if len(calls) <= 2:
                raise PermissionError(32, "sharing violation")
            return real(*args)

        with mock.patch.object(mod.os, "replace", flaky), mock.patch.object(mod.time, "sleep"):
            self.assertEqual(mod.remove_config(self.cfg), "/v")
        self.assertEqual(len(calls), 3)
        self.assertEqual(list(self.cfg.parent.iterdir()), [])

    def test_cleans_without_config(self):
        self.stale("vault-path.tmp.4")
        self.check(0, "No vault path configured.\nCleaned up 1 leftover temp file(s).")
        self.assertFalse(self.cfg.parent.exists())

    def symlink(self, link, target, is_dir=False):
        try:
            os.symlink(target, link, target_is_directory=is_dir)
        except (OSError, NotImplementedError) as err:
            self.skipTest(f"cannot create symlinks here: {err}")

    def test_symlinked_file_refused(self):
        target = self.tmp / "real-vault-path"
        target.write_text("/v\n", encoding="utf-8")
        self.symlink(self.cfg, target)
        for args in ((), ("--dry-run",)):
            res = self.check(1, "", *args)
            self.assert_system_error(res)
            self.assertIn("vault-path is a link", res.stderr)
        self.assertTrue(os.path.lexists(self.cfg))
        self.assertTrue(target.exists())

    def test_symlinked_folder_refused(self):
        real = self.tmp / "real-folder"
        real.mkdir()
        (real / "vault-path").write_text("/v\n", encoding="utf-8")
        self.cfg.parent.rmdir()
        self.symlink(self.cfg.parent, real, is_dir=True)
        res = self.check(1, "")
        self.assert_system_error(res)
        self.assertIn("obsidian-wiki is a link", res.stderr)
        self.assertTrue((real / "vault-path").exists())

    @unittest.skipUnless(sys.platform == "win32", "junctions are Windows only")
    def test_junction_folder_refused(self):
        real = self.tmp / "real-folder"
        real.mkdir()
        (real / "vault-path").write_text("/v", encoding="utf-8")
        self.cfg.parent.rmdir()
        subprocess.run(["cmd", "/c", "mklink", "/J", str(self.cfg.parent), str(real)],
                       check=True, capture_output=True)
        for args in ((), ("--dry-run",)):
            res = self.check(1, "", *args)
            self.assert_system_error(res)
            self.assertIn("obsidian-wiki is a link", res.stderr)
        self.assertTrue((real / "vault-path").exists())


if __name__ == "__main__":
    unittest.main()
