"""Tests for skills/status/scripts/status.py with a temp HOME and a temp copy of the fixture vault."""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[1]
SCRIPT = PLUGIN / "skills" / "status" / "scripts" / "status.py"
FIXTURE = HERE / "fixture-vault"
EXPECTED = (HERE / "expected" / "status.txt").read_text(encoding="utf-8").rstrip("\n")
MISSING = ("ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use "
           "/wiki-vault:add <vault path> to configure your vault.")
NO_RULES = "ERROR: The configured vault folder has no CLAUDE.md"


def run(script, home, *args):
    """Run a status script with HOME set. Returns (exit code, stdout, stderr)."""
    env = dict(os.environ, HOME=str(home))
    proc = subprocess.run([sys.executable, str(script), *args], env=env,
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, proc.stdout.rstrip("\n"), proc.stderr


def make_home(root, name, content):
    """Create root/name/.claude/obsidian-wiki/vault-path with content. Returns the home folder."""
    home = root / name
    config = home / ".claude" / "obsidian-wiki" / "vault-path"
    config.parent.mkdir(parents=True)
    config.write_bytes(content.encode("utf-8"))
    return home


def tree_hash(folder):
    """Hash of every file path and content below folder."""
    digest = hashlib.md5()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        digest.update(path.relative_to(folder).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class StatusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.vault = cls.tmp / "vault"
        shutil.copytree(FIXTURE, cls.vault)
        (cls.vault / "CLAUDE.md").write_bytes(b"# Vault rules\r\nKeep notes short.\r\n")
        cls.home = make_home(cls.tmp, "home", f"  {cls.vault}  \r\n")
        cls.before = tree_hash(cls.vault)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def header(self, found):
        return "\n".join([
            f"vault: {self.vault.as_posix()}",
            "--- vault CLAUDE.md ---",
            "# Vault rules",
            "Keep notes short.",
            "--- end CLAUDE.md ---",
            f"found: {found}",
            "--- result ---",
        ])

    def test_found_separate_arguments(self):
        self.assertEqual(run(SCRIPT, self.home, "review", "draft")[:2],
                         (0, f"{self.header('yes')}\n{EXPECTED}"))

    def test_found_one_string(self):
        self.assertEqual(run(SCRIPT, self.home, "review draft")[:2],
                         (0, f"{self.header('yes')}\n{EXPECTED}"))

    def test_nothing_found(self):
        self.assertEqual(run(SCRIPT, self.home, "missing")[:2],
                         (0, f"{self.header('no')}\nNothing found."))

    def test_help(self):
        code, out, _ = run(SCRIPT, self.home, "--help")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("usage: status.py"))

    def test_help_short(self):
        self.assertEqual(run(SCRIPT, self.home, "-h")[0], 0)

    def test_no_path(self):
        self.assertEqual(run(SCRIPT, self.tmp / "nohome", "review")[:2], (0, MISSING))

    def test_empty_path(self):
        home = make_home(self.tmp, "empty", "")
        self.assertEqual(run(SCRIPT, home, "review")[:2], (0, MISSING))

    def test_bad_folder(self):
        home = make_home(self.tmp, "gone", f"{self.tmp / 'missing'}\n")
        code, out, _ = run(SCRIPT, home, "review")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith(NO_RULES), out)

    def test_no_claude_md(self):
        home = make_home(self.tmp, "noclaude", f"{FIXTURE}\n")
        code, out, _ = run(SCRIPT, home, "review")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith(NO_RULES), out)

    def test_no_status(self):
        self.assertEqual(run(SCRIPT, self.home)[:2], (0, "ERROR: no status given"))

    def test_no_status_empty_string(self):
        self.assertEqual(run(SCRIPT, self.home, "")[:2], (0, "ERROR: no status given"))

    def test_invalid_status(self):
        code, out, _ = run(SCRIPT, self.home, "rev;iew")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("ERROR: invalid status 'rev;iew'"), out)

    def test_unknown_option(self):
        code, _, err = run(SCRIPT, self.home, "--bogus")
        self.assertEqual(code, 2)
        self.assertIn("SYSTEM ERROR:", err)

    def test_system_error_without_vault_py(self):
        plugin = self.tmp / "plug"
        script = plugin / "skills" / "status" / "scripts" / "status.py"
        script.parent.mkdir(parents=True)
        shutil.copy(SCRIPT, script)
        code, _, err = run(script, self.home, "review")
        self.assertEqual(code, 1)
        self.assertIn("SYSTEM ERROR: status.py: vault.py not found", err)

    def test_zz_vault_unchanged(self):
        self.assertEqual(tree_hash(self.vault), self.before)


if __name__ == "__main__":
    unittest.main()
