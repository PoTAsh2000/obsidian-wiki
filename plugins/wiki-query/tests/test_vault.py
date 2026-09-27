"""Tests for scripts/vault.py. Identical copy in every plugin at tests/test_vault.py."""

import io
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
            code = vault.main(argv)
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

    def test_git_bash_path(self):
        with mock.patch.object(vault.sys, "platform", "win32"):
            self.assertEqual(vault.to_native("/c/Users/x"), "C:/Users/x")
        with mock.patch.object(vault.sys, "platform", "linux"):
            self.assertEqual(vault.to_native("/c/Users/x"), "/c/Users/x")


if __name__ == "__main__":
    unittest.main()
