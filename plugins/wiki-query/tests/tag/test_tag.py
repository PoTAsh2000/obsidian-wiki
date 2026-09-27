"""Tests for skills/tag/scripts/tag.py with a temp HOME and a copy of the fixture vault."""

import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[1]
TAG = PLUGIN / "skills" / "tag" / "scripts" / "tag.py"
EXPECTED = HERE / "expected"
MISSING = ("ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use "
           "/wiki-vault:add <vault path> to configure your vault.")
USAGE = "usage: tag.py ['<tag> <tag>...']"


def expected(name):
    return (EXPECTED / name).read_text(encoding="utf-8").rstrip("\n")


def result_block(out):
    """Lines between 'result: begin' and 'result: end'."""
    lines = out.splitlines()
    return "\n".join(lines[lines.index("result: begin") + 1:lines.index("result: end")])


def checksums(folder):
    return {p.relative_to(folder).as_posix(): hashlib.md5(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


class TagTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.config = self.home / ".claude" / "obsidian-wiki" / "vault-path"
        self.config.parent.mkdir(parents=True)
        self.vault = self.tmp / "vault"
        shutil.copytree(HERE / "fixture-vault", self.vault)
        (self.vault / "CLAUDE.md").write_bytes(b"# Vault rules\nEnglish only.\n")
        self.config.write_bytes(f"{self.vault}\r\n".encode("utf-8"))

    def run_tag(self, *args):
        """Run tag.py like SKILL.md does. Returns (exit code, stdout, stderr)."""
        env = dict(os.environ, HOME=str(self.home))
        proc = subprocess.run([sys.executable, str(TAG), *args], capture_output=True,
                              text=True, encoding="utf-8", env=env)
        return proc.returncode, proc.stdout, proc.stderr

    def assert_line(self, out, line):
        self.assertIn(line, out.splitlines(), out)

    def test_help(self):
        for flag in ("--help", "-h"):
            code, out, _ = self.run_tag(flag)
            self.assertEqual(code, 0)
            self.assert_line(out, USAGE)

    def test_no_path_file(self):
        self.config.unlink()
        self.assertEqual(self.run_tag("ai")[:2], (0, MISSING + "\n"))

    def test_empty_path_file(self):
        self.config.write_text("", encoding="utf-8")
        self.assertEqual(self.run_tag("ai")[:2], (0, MISSING + "\n"))

    def test_no_claude_md(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        self.config.write_text(f"{bare}\n", encoding="utf-8")
        code, out, _ = self.run_tag("ai")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"^ERROR: .*has no CLAUDE\.md.*/wiki-vault:overwrite")

    def test_no_tags(self):
        code, out, _ = self.run_tag()
        self.assertEqual(code, 0)
        self.assertEqual(out, f"vault: {self.vault.as_posix()}\nneed: tags\n")

    def test_several(self):
        code, out, _ = self.run_tag("ai", "tooling", "missing")
        self.assertEqual(code, 0)
        self.assert_line(out, f"vault: {self.vault.as_posix()}")
        self.assert_line(out, "found: yes")
        self.assert_line(out, "--- vault CLAUDE.md ---")
        self.assert_line(out, "English only.")
        self.assertEqual(result_block(out), expected("tag-several.txt"))

    def test_mixed_case_hash(self):
        self.assertEqual(result_block(self.run_tag("#AI")[1]), expected("tag-mixed-case.txt"))

    def test_nothing(self):
        code, out, _ = self.run_tag("missing")
        self.assertEqual(code, 0)
        self.assert_line(out, "found: no")
        self.assertEqual(result_block(out), expected("nothing.txt"))

    def test_invalid_tags(self):
        for arg in ("a;b", "[x]"):
            code, out, _ = self.run_tag(arg)
            self.assertEqual(code, 0)
            self.assertTrue(out.startswith("ERROR: Invalid tag"), out)
        self.assertTrue(self.run_tag("a;b")[1].startswith("ERROR: Invalid tag 'a;b'"))

    def test_only_hash(self):
        self.assert_line(self.run_tag("#")[1], "need: tags")

    def test_nested_and_dash_tags(self):
        for arg in ("area/sub", "-ai"):
            self.assert_line(self.run_tag(arg)[1], "found: no")

    def test_injection_form(self):
        """SKILL.md pastes the arguments into '...' as one string."""
        self.assertEqual(result_block(self.run_tag("ai tooling missing")[1]), expected("tag-several.txt"))
        self.assertEqual(result_block(self.run_tag("#AI")[1]), expected("tag-mixed-case.txt"))
        self.assert_line(self.run_tag("")[1], "need: tags")
        for arg in ("*", "a;b"):
            self.assertTrue(self.run_tag(arg)[1].startswith("ERROR: Invalid tag"), arg)

    def test_unreadable_note_is_system_error(self):
        """A note that cannot be read stops with exit 1 and nothing on stdout."""
        sys.path.insert(0, str(TAG.parent))
        self.addCleanup(sys.path.remove, str(TAG.parent))
        import tag
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}), \
                mock.patch.object(tag, "find_tagged", side_effect=OSError("boom")), \
                mock.patch.object(sys, "stderr", err), redirect_stdout(io.StringIO()) as out, \
                mock.patch.object(sys.stdout, "reconfigure", create=True):
            code = tag.main(["ai"])
        self.assertEqual(code, 1)
        self.assertRegex(err.getvalue(), r"^SYSTEM ERROR: tag\.py: .*boom")
        self.assertEqual(out.getvalue(), "")

    def test_vault_unchanged(self):
        before = checksums(self.vault)
        for args in (["ai", "tooling", "missing"], ["#AI"], ["missing"], []):
            self.run_tag(*args)
        self.assertEqual(checksums(self.vault), before)


if __name__ == "__main__":
    unittest.main()
