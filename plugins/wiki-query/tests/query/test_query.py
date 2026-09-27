"""Tests for the query skill: skills/query/scripts/search.py and scripts/vault.py (its context)."""

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[1]
SEARCH = PLUGIN / "skills" / "query" / "scripts" / "search.py"
VAULT_PY = PLUGIN / "scripts" / "vault.py"
FIXTURE = HERE / "fixture-vault"
EXPECTED = HERE / "expected"
MISSING = ("ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use "
           "/wiki-vault:add <vault path> to configure your vault.")


def run(script, *args, home=None):
    """Run a script, return (exit code, stdout, stderr) with LF line endings."""
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = str(home)
    proc = subprocess.run([sys.executable, str(script), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env)
    return proc.returncode, proc.stdout, proc.stderr


def expected(case):
    return (EXPECTED / f"{case}.txt").read_text(encoding="utf-8")


def fingerprint(folder):
    """Hash of every file in a folder, to prove the scripts never write."""
    return sorted((p.relative_to(folder).as_posix(), hashlib.md5(p.read_bytes()).hexdigest())
                  for p in folder.rglob("*") if p.is_file())


class QueryTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = fingerprint(FIXTURE)

    @classmethod
    def tearDownClass(cls):
        assert fingerprint(FIXTURE) == cls.before, "fixture vault changed"


class SearchTest(QueryTestCase):
    def check(self, case, *args):
        code, out, _ = run(SEARCH, "--vault", str(FIXTURE), *args)
        self.assertEqual(code, 0)
        self.assertEqual(out, expected(case))

    def check_code(self, want, prefix, *args):
        code, _, err = run(SEARCH, *args)
        self.assertEqual(code, want)
        if prefix:
            self.assertTrue(err.startswith(prefix), err)

    def test_two_terms(self):
        self.check("search-two-terms", "edi", "mapping")

    def test_phrase_limit(self):
        self.check("search-phrase-limit", "--limit", "1", "message mapping")

    def test_nothing(self):
        self.check("search-nothing", "zzzq")

    def test_dash_term(self):
        self.check("search-dash-term", "--", "-orders")

    def test_limit_leading_zero(self):
        self.check_code(2, "SYSTEM ERROR:", "--vault", str(FIXTURE), "--limit", "08", "edi")

    def test_help(self):
        self.check_code(0, None, "--help")

    def test_help_short(self):
        self.check_code(0, None, "-h")

    def test_no_term(self):
        self.check_code(2, "SYSTEM ERROR:", "--vault", str(FIXTURE))

    def test_no_vault(self):
        self.check_code(2, "SYSTEM ERROR:", "edi")

    def test_bad_limit(self):
        self.check_code(2, "SYSTEM ERROR:", "--vault", str(FIXTURE), "--limit", "0", "edi")

    def test_bad_option(self):
        self.check_code(2, "SYSTEM ERROR:", "--vault", str(FIXTURE), "--color", "edi")

    def test_empty_term(self):
        self.check_code(2, "SYSTEM ERROR:", "--vault", str(FIXTURE), " ")

    def test_missing_vault(self):
        self.check_code(3, "USER ERROR:", "--vault", str(FIXTURE / "missing"), "edi")


class ContextTest(QueryTestCase):
    """The skill injects vault.py for its vault and vault CLAUDE.md context."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def home(self, content=None):
        """Temp HOME, with a vault-path file when content is given."""
        home = Path(self.tmp.name) / "home"
        conf = home / ".claude" / "obsidian-wiki"
        conf.mkdir(parents=True)
        if content is not None:
            (conf / "vault-path").write_bytes(content.encode("utf-8"))
        return home

    def test_ok(self):
        code, out, _ = run(VAULT_PY, home=self.home(f"{FIXTURE}\r\n"))
        rules = (FIXTURE / "CLAUDE.md").read_text(encoding="utf-8").rstrip("\n")
        self.assertEqual(code, 0)
        self.assertEqual(out, f"vault: {FIXTURE.as_posix()}\n--- vault CLAUDE.md ---\n{rules}\n")

    def test_no_file(self):
        self.assertEqual(run(VAULT_PY, home=self.home())[:2], (0, MISSING + "\n"))

    def test_empty(self):
        self.assertEqual(run(VAULT_PY, home=self.home("  "))[:2], (0, MISSING + "\n"))

    def test_no_claude(self):
        code, out, _ = run(VAULT_PY, home=self.home(str(HERE)))
        self.assertEqual(code, 0)
        self.assertEqual(out, f"ERROR: The configured vault folder has no CLAUDE.md: {HERE}. "
                              "Use /wiki-vault:overwrite <vault path> to fix the vault path.\n")

    def test_help(self):
        self.assertEqual(run(VAULT_PY, "--help")[0], 0)

    def test_bad_arg(self):
        code, _, err = run(VAULT_PY, "extra")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("SYSTEM ERROR:"), err)


if __name__ == "__main__":
    unittest.main()
