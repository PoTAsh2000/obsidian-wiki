"""Tests for the wiki-ingest:apply skill: vault.py as its context script and apply.py.

Every test uses a temp HOME and a copy of the fixture vault, so the fixtures never change.
"""

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
APPLY_PY = PLUGIN / "skills" / "apply" / "scripts" / "apply.py"
FIXTURE = HERE / "fixture-vault"
EXPECTED = HERE / "expected-vault"

MISSING = ("ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use "
           "/wiki-vault:add <vault path> to configure your vault.")


def snapshot(folder):
    """Every file below folder as {relative path: bytes}."""
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in sorted(folder.rglob("*")) if p.is_file()}


class ApplyTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.config = self.home / ".claude" / "obsidian-wiki" / "vault-path"
        self.config.parent.mkdir(parents=True)
        self.vault = self.tmp / "v"
        shutil.copytree(FIXTURE, self.vault)
        self.set_path(f"{self.vault}\n")
        self.before = snapshot(self.vault)

    def set_path(self, content):
        self.config.write_bytes(content.encode("utf-8"))

    def run_script(self, script, *args):
        env = dict(os.environ, HOME=str(self.home), PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, str(script), *args], env=env,
                                capture_output=True, text=True, encoding="utf-8")
        return result.returncode, result.stdout.rstrip("\n"), result.stderr

    def expect(self, result, code, stdout, stderr_prefix=""):
        rc, out, err = result
        self.assertEqual(rc, code, f"stderr: {err}")
        self.assertEqual(out, stdout)
        self.assertTrue(err.startswith(stderr_prefix), f"stderr {err!r} does not start with {stderr_prefix!r}")

    def assert_unchanged(self):
        self.assertEqual(snapshot(self.vault), self.before)


class VaultContextTest(ApplyTestCase):
    """vault.py is injected into SKILL.md as the read-only context."""

    def test_help(self):
        for flag in ("--help", "-h"):
            rc, out, _ = self.run_script(VAULT_PY, flag)
            self.assertEqual(rc, 0)
            self.assertTrue(out.startswith("vault.py:"))

    def test_usage(self):
        self.expect(self.run_script(VAULT_PY, "extra"), 2, "", "SYSTEM ERROR:")

    def test_ok(self):
        rules = (self.vault / "CLAUDE.md").read_text(encoding="utf-8").rstrip("\n")
        self.expect(self.run_script(VAULT_PY), 0,
                    f"vault: {self.vault.as_posix()}\n--- vault CLAUDE.md ---\n{rules}")
        self.assert_unchanged()

    def test_crlf_path(self):
        self.set_path(f"{self.vault}\r\n")
        rc, out, _ = self.run_script(VAULT_PY)
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith(f"vault: {self.vault.as_posix()}\n"))

    def test_empty_path(self):
        self.set_path("")
        self.expect(self.run_script(VAULT_PY), 0, MISSING)

    def test_no_path(self):
        self.config.unlink()
        self.expect(self.run_script(VAULT_PY), 0, MISSING)

    def test_no_claude_md(self):
        self.set_path(f"{self.tmp}\n")
        rc, out, _ = self.run_script(VAULT_PY)
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("ERROR: The configured vault folder has no CLAUDE.md"))
        self.assert_unchanged()


class ApplyErrorsTest(ApplyTestCase):
    """Usage, system and user errors change nothing."""

    def tearDown(self):
        self.assert_unchanged()

    def test_help(self):
        for flag in ("--help", "-h"):
            rc, out, _ = self.run_script(APPLY_PY, flag)
            self.assertEqual(rc, 0)
            self.assertTrue(out.startswith("usage:"))

    def test_usage(self):
        self.expect(self.run_script(APPLY_PY, "Twin", "Draft"), 2, "", "SYSTEM ERROR:")

    def test_no_path(self):
        self.config.unlink()
        self.expect(self.run_script(APPLY_PY), 1, "", "SYSTEM ERROR:")

    def test_no_claude_md(self):
        self.set_path(f"{self.tmp}\n")
        self.expect(self.run_script(APPLY_PY), 1, "", "SYSTEM ERROR:")

    def test_not_found(self):
        self.expect(self.run_script(APPLY_PY, "Missing"), 3, "", "USER ERROR:")

    def test_evergreen(self):
        self.expect(self.run_script(APPLY_PY, "Evergreen"), 3, "",
                    "USER ERROR: apply.py: 30. Knowledge/Evergreen.md has status evergreen")

    def test_draft(self):
        self.expect(self.run_script(APPLY_PY, "draft"), 3, "",
                    "USER ERROR: apply.py: 01. Inbox/Draft.md has status draft")

    def test_body_status(self):
        self.expect(self.run_script(APPLY_PY, "Body Status"), 3, "", "USER ERROR:")

    def test_no_status(self):
        self.expect(self.run_script(APPLY_PY, "No Status"), 3, "",
                    "USER ERROR: apply.py: 30. Knowledge/No Status.md has no status")

    def test_no_frontmatter(self):
        self.expect(self.run_script(APPLY_PY, "No Frontmatter"), 3, "", "USER ERROR:")

    def test_dot_folder(self):
        self.expect(self.run_script(APPLY_PY, "Hidden"), 3, "", "USER ERROR: apply.py: no note named")

    def test_several(self):
        self.expect(self.run_script(APPLY_PY, "twin"), 3,
                    "match: 30. Knowledge/Twin.md\nmatch: 40. Projects/Twin.md",
                    "USER ERROR: apply.py: several notes")


class ApplyChangesTest(ApplyTestCase):
    def test_full_run(self):
        # One note by name: case-insensitive, spaces trimmed, .md suffix dropped.
        self.expect(self.run_script(APPLY_PY, "  reviewed ONE.md "), 0,
                    "evergreen: 30. Knowledge/Reviewed One.md\ncount: 1")
        name = "30. Knowledge/Reviewed One.md"
        self.assertEqual((self.vault / name).read_bytes(), (EXPECTED / name).read_bytes())

        # One note by path, .md added.
        self.expect(self.run_script(APPLY_PY, "40. Projects/Twin"), 0,
                    "evergreen: 40. Projects/Twin.md\ncount: 1")
        self.expect(self.run_script(APPLY_PY, "Reviewed One"), 3, "",
                    "USER ERROR: apply.py: 30. Knowledge/Reviewed One.md has status evergreen")

        # No argument changes the rest; the vault then equals expected-vault byte for byte.
        self.expect(self.run_script(APPLY_PY, ""), 0,
                    "evergreen: 20. Customers/Quoted.md\n"
                    "evergreen: 30. Knowledge/Reviewed CRLF.md\n"
                    "evergreen: 30. Knowledge/Twin.md\n"
                    "count: 3")
        self.assertEqual(snapshot(self.vault), snapshot(EXPECTED))

        # Idempotent: a second run changes nothing.
        self.before = snapshot(self.vault)
        self.expect(self.run_script(APPLY_PY), 0, "count: 0")
        self.assert_unchanged()

    def test_fixture_untouched(self):
        changed = [p for p in FIXTURE.rglob("*.md")
                   if p.name != "Evergreen.md" and "evergreen" in p.read_text(encoding="utf-8")]
        self.assertEqual(changed, [])


if __name__ == "__main__":
    unittest.main()
