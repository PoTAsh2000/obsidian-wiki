"""Tests for scripts/vault.py. Identical copy in every plugin at tests/test_vault.py."""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vault  # noqa: E402


class VaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.config = self.tmp / "home" / ".claude" / "obsidian-wiki" / "vault-path"
        self.config.parent.mkdir(parents=True)
        self.vault = self.tmp / "My Vault"
        self.vault.mkdir()

    def run_main(self, argv):
        out = io.StringIO()
        with mock.patch.dict(vault.os.environ, {"HOME": str(self.tmp / "home")}), redirect_stdout(out):
            try:
                code = vault.main(argv)
            except SystemExit as stop:  # require_vault() exits on a vault problem
                code = stop.code
        return code, out.getvalue()

    def test_missing_config(self):
        self.assertEqual(self.run_main([]), (0, f"ERROR: {vault.MISSING}\n"))

    def test_empty_config(self):
        self.config.write_text("  \r\n", encoding="utf-8")
        self.assertEqual(self.run_main([]), (0, f"ERROR: {vault.MISSING}\n"))

    def test_no_claude_md(self):
        self.config.write_text(str(self.vault), encoding="utf-8")
        code, out = self.run_main([])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("ERROR: The configured vault folder has no CLAUDE.md"))

    def test_prints_vault_and_rules(self):
        (self.vault / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")
        self.config.write_text(f"{self.vault}\r\n", encoding="utf-8")
        code, out = self.run_main([])
        self.assertEqual(code, 0)
        self.assertEqual(out, f"vault: {self.vault.as_posix()}\n{vault.MARKER}\n# Rules\n")

    def test_path_only(self):
        (self.vault / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")
        self.config.write_text(str(self.vault), encoding="utf-8")
        self.assertEqual(self.run_main(["--path"]), (0, f"vault: {self.vault.as_posix()}\n"))

    def test_bad_usage(self):
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(vault.main(["--nope"]), 2)

    def test_non_ascii_rules_piped(self):
        (self.vault / "CLAUDE.md").write_text("café →\n", encoding="utf-8")
        self.config.write_text(str(self.vault), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
        env["HOME"] = str(self.tmp / "home")
        run = subprocess.run([sys.executable, vault.__file__], env=env, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(run.stdout.endswith("café →\n".encode("utf-8")))

    def test_require_vault_prints_error_and_exits_0(self):
        out = io.StringIO()
        with mock.patch.dict(vault.os.environ, {"HOME": str(self.tmp / "home")}), redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                vault.require_vault()
        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(out.getvalue(), f"ERROR: {vault.MISSING}\n")

    def test_require_vault_returns_path(self):
        (self.vault / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")
        self.config.write_text(str(self.vault), encoding="utf-8")
        with mock.patch.dict(vault.os.environ, {"HOME": str(self.tmp / "home")}):
            self.assertEqual(vault.require_vault(), self.vault)

    def test_stored_path(self):
        self.assertEqual(vault.stored_path(self.config), "")
        self.config.write_text("\ufeff  D:/Notes  \r\nsecond\r\n", encoding="utf-8")
        self.assertEqual(vault.stored_path(self.config), "D:/Notes")

    def test_stored_path_uses_home(self):
        self.config.write_text("/x/vault\n", encoding="utf-8")
        with mock.patch.dict(vault.os.environ, {"HOME": str(self.tmp / "home")}):
            self.assertEqual(vault.stored_path(), "/x/vault")

    def test_clean_path(self):
        self.assertEqual(vault.clean_path("C:\\Notes\\Vault\\"), "C:/Notes/Vault")
        self.assertEqual(vault.clean_path(" /home/me/Vault// "), "/home/me/Vault")
        self.assertEqual(vault.clean_path("C:/"), "C:/")
        self.assertEqual(vault.clean_path("/"), "/")
        self.assertEqual(vault.clean_path("d:\\Notes"), "D:/Notes")
        self.assertEqual(vault.clean_path(' "C:\\My Notes\\" '), "C:/My Notes")
        self.assertEqual(vault.clean_path("'/home/me/Vault'"), "/home/me/Vault")
        self.assertEqual(vault.clean_path("/a\"b\""), "/a\"b\"")

    def test_clean_path_collapses_dots(self):
        self.assertEqual(vault.clean_path("C:/Notes/./Old/../Vault/"), "C:/Notes/Vault")
        self.assertEqual(vault.clean_path("c:\\.."), "C:/")
        self.assertEqual(vault.clean_path("/home/me/../you/Vault"), "/home/you/Vault")
        self.assertEqual(vault.clean_path("/.."), "/")
        self.assertEqual(vault.clean_path("//server/share/./Vault"), "//server/share/Vault")

    def test_clean_path_home_and_git_bash(self):
        home = (self.tmp / "home").as_posix()
        with mock.patch.dict(vault.os.environ, {"HOME": home}):
            self.assertEqual(vault.clean_path("~"), home)
            self.assertEqual(vault.clean_path(" ~/Vault/ "), home + "/Vault")
            self.assertEqual(vault.clean_path("~\\Vault"), home + "/Vault")
            self.assertEqual(vault.clean_path("/srv/~/v"), "/srv/~/v")
        with mock.patch.object(vault.sys, "platform", "win32"):
            self.assertEqual(vault.clean_path("/c/Notes"), "C:/Notes")
            self.assertEqual(vault.clean_path("/c"), "C:/")
        with mock.patch.object(vault.sys, "platform", "linux"):
            self.assertEqual(vault.clean_path("/c/Notes"), "/c/Notes")

    def test_clean_path_rejects(self):
        for raw, text in (("", "empty"), ("  ", "empty"), ("Notes/Vault", "not absolute"),
                          ("C:Notes", "not absolute"), ("/a\nb", "line break"),
                          ("~user/Vault", "not absolute")):
            with self.assertRaises(vault.VaultError) as caught:
                vault.clean_path(raw)
            self.assertIn(text, str(caught.exception))

    def test_git_bash_path(self):
        with mock.patch.object(vault.sys, "platform", "win32"):
            self.assertEqual(vault.to_native("/c/Users/x"), "C:/Users/x")
            self.assertEqual(vault.to_native("/mnt/d/Notes"), "D:/Notes")
            self.assertEqual(vault.to_native("/mnt/c"), "C:/")
            self.assertEqual(vault.to_native("/mnt/wsl/x"), "/mnt/wsl/x")
            self.assertEqual(vault.to_native("/mnt"), "/mnt")
            self.assertEqual(vault.clean_path("/mnt/c/Notes/"), "C:/Notes")
        with mock.patch.object(vault.sys, "platform", "linux"):
            self.assertEqual(vault.to_native("/c/Users/x"), "/c/Users/x")
            self.assertEqual(vault.to_native("/mnt/c/Users/x"), "/mnt/c/Users/x")


if __name__ == "__main__":
    unittest.main()
