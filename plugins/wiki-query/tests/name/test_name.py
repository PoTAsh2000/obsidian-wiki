"""Tests for the name skill: vault.py injection and skills/name/scripts/name.py.

Scripts run as subprocesses with a temp HOME and a copy of the fixture vault.
"""

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
VAULT_PY = PLUGIN / "scripts" / "vault.py"
NAME_PY = PLUGIN / "skills" / "name" / "scripts" / "name.py"
FIXTURE = HERE.parent / "fixture-vault"  # shared with other query skills
EXPECTED = HERE.parent / "expected"
MISSING = ("Vault path is missing. Install wiki-vault@obsidian-wiki and use "
           "/wiki-vault:add <vault path> to configure your vault.")


def file_hashes(root, skip=()):
    """Map of relative path to md5 for every file under root."""
    return {p.relative_to(root).as_posix(): hashlib.md5(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and p.name not in skip}


class NameSkillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vault = self.tmp / "vault"
        shutil.copytree(FIXTURE, self.vault)
        (self.vault / "CLAUDE.md").write_bytes(b"# Vault rules\r\nBe kind.\r\n")
        self.home = self.tmp / "home"
        self.conf = self.home / ".claude" / "obsidian-wiki" / "vault-path"
        self.conf.parent.mkdir(parents=True)
        (self.tmp / "nocm").mkdir()

    def set_conf(self, text):
        self.conf.write_bytes(text.encode("utf-8"))

    def run_script(self, script, *args):
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run([sys.executable, str(script), *args], env=env,
                              capture_output=True, text=True, encoding="utf-8")

    def check(self, script, args, code, out=None, err=None):
        """Run a script and check exit code, exact stdout and stderr start."""
        res = self.run_script(script, *args)
        self.assertEqual(res.returncode, code, res.stderr)
        if out is not None:
            self.assertEqual(res.stdout.rstrip("\n"), out)
        if err is not None:
            self.assertTrue(res.stderr.startswith(err), res.stderr)
        return res

    def expected(self, case):
        return (EXPECTED / f"{case}.txt").read_text(encoding="utf-8").rstrip("\n")

    # --help
    def test_help(self):
        for script in (VAULT_PY, NAME_PY):
            for flag in ("--help", "-h"):
                self.check(script, [flag], 0)

    # vault path missing, empty, folder missing, no CLAUDE.md
    def test_no_conf(self):
        self.check(VAULT_PY, [], 0, f"ERROR: {MISSING}", "")
        self.check(NAME_PY, ["context"], 0, f"ERROR: {MISSING}", "")

    def test_empty_conf(self):
        self.set_conf("  \r\n\n")
        self.check(VAULT_PY, [], 0, f"ERROR: {MISSING}", "")
        self.check(NAME_PY, ["context"], 0, f"ERROR: {MISSING}", "")

    def test_no_folder(self):
        gone = (self.tmp / "gone").as_posix()
        self.set_conf(gone + "\n")
        res = self.check(VAULT_PY, [], 0)
        self.assertTrue(res.stdout.startswith(f"ERROR: The configured vault folder has no CLAUDE.md: {gone}"))
        self.assertIn("/wiki-vault:overwrite", res.stdout)
        res = self.check(NAME_PY, ["context"], 0, err="")
        self.assertTrue(res.stdout.startswith(f"ERROR: The configured vault folder has no CLAUDE.md: {gone}"))

    def test_no_claude_md(self):
        nocm = (self.tmp / "nocm").as_posix()
        self.set_conf(nocm + "\n")
        self.check(VAULT_PY, [], 0, f"ERROR: The configured vault folder has no CLAUDE.md: {nocm}. "
                   "Use /wiki-vault:overwrite <vault path> to fix the vault path.", "")
        self.check(NAME_PY, ["context"], 0, f"ERROR: The configured vault folder has no CLAUDE.md: {nocm}. "
                   "Use /wiki-vault:overwrite <vault path> to fix the vault path.", "")

    # configured vault, CRLF and surrounding spaces in the vault-path file
    def test_vault_ok(self):
        self.set_conf(f"  {self.vault.as_posix()}  \r\n")
        self.check(VAULT_PY, [], 0, f"vault: {self.vault.as_posix()}\n"
                   "--- vault CLAUDE.md ---\n# Vault rules\nBe kind.", "")

    # lookups, exit 0 also for nothing found
    def test_lookups(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        cases = [
            (["--", "engine"], "name-middle"),
            (["CONTEXT", "ENG"], "name-mixed-case-spaces"),
            (["context"], "name-filename-beats-alias"),
            (["mapping"], "name-title"),
            (["loose"], "name-title-after-code"),
            (["sop"], "name-alias-only"),
            (["--", "not", "a", "title"], "nothing"),
            (["--", "-zz-"], "nothing"),
        ]
        for args, case in cases:
            with self.subTest(args=args):
                self.check(NAME_PY, args, 0, self.expected(case), "")

    # usage errors
    def test_usage_errors(self):
        self.check(VAULT_PY, ["extra"], 2, "", "SYSTEM ERROR: vault.py")
        self.check(NAME_PY, [], 2, "", "SYSTEM ERROR: name.py: no text")
        self.check(NAME_PY, ["--"], 2, "", "SYSTEM ERROR: name.py: no text")
        self.check(NAME_PY, ["--", "  "], 2, "", "SYSTEM ERROR: name.py: text is empty")

    # system error: vault.py missing (copy of the skill script without the plugin script)
    def test_no_vault_py(self):
        scripts = self.tmp / "plug" / "skills" / "name" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy(NAME_PY, scripts)
        res = self.check(scripts / "name.py", ["context"], 1, "")
        self.assertIn("No module named 'vault'", res.stderr)

    # read-only: the vault copy is unchanged
    def test_read_only(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        self.run_script(NAME_PY, "context")
        self.assertEqual(file_hashes(FIXTURE), file_hashes(self.vault, skip={"CLAUDE.md"}))


if __name__ == "__main__":
    unittest.main()
