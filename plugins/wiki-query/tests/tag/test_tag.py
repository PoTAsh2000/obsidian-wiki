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

    def run_tag(self, *args, stdin=None):
        """Run tag.py with argv, or with '-' and stdin like SKILL.md. Returns (exit code, stdout, stderr)."""
        env = dict(os.environ, HOME=str(self.home))
        proc = subprocess.run([sys.executable, str(TAG), *args], capture_output=True, input=stdin or "",
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
        """No tags: the vault's tags with counts, most used first, then by name, children under parents."""
        code, out, _ = self.run_tag()
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[:6], ["need: tags", "tags: begin", "- ai (3)", "- llm (2)", "- proj (2)",
                                     "  - proj/edi (1)"])
        self.assertEqual(lines[6], "    - proj/edi/mapping (1)")
        self.assertEqual(lines[-1], "tags: end")

    def test_inventory_branches(self):
        """A parent counts each note with it or a child once, also when no note has the parent itself."""
        sys.path.insert(0, str(TAG.parent))
        self.addCleanup(sys.path.remove, str(TAG.parent))
        from tag import branch_counts, inventory
        notes = [("a.md", {"area/x", "area/y"}, ""), ("b.md", {"area/y"}, ""), ("c.md", {"zed", "2026/q1"}, "")]
        self.assertEqual(inventory(branch_counts(notes)),
                         ["- area (2)", "  - area/y (2)", "  - area/x (1)", "- 2026/q1 (1)", "- zed (1)"])

    def test_inventory_cap(self):
        sys.path.insert(0, str(TAG.parent))
        self.addCleanup(sys.path.remove, str(TAG.parent))
        from collections import Counter
        from tag import MAX_INVENTORY, inventory
        lines = inventory(Counter({f"t{i:03}": 1 for i in range(MAX_INVENTORY + 5)}))
        self.assertEqual(len(lines), MAX_INVENTORY + 1)
        self.assertEqual(lines[-1], "- ... 5 more")

    def test_result_cap(self):
        """A block with more notes than MAX_RESULT shows the first ones by path and a '... N more' line."""
        sys.path.insert(0, str(TAG.parent))
        self.addCleanup(sys.path.remove, str(TAG.parent))
        from tag import MAX_RESULT
        bulk = self.vault / "70. Bulk"
        bulk.mkdir()
        for i in range(MAX_RESULT + 3):
            (bulk / f"n{i:03}.md").write_text("---\ntags: [bulk]\n---\n", encoding="utf-8")
        out = self.run_tag("bulk")[1]
        lines = result_block(out).splitlines()
        self.assertEqual(len(lines), MAX_RESULT + 2)
        self.assertEqual(lines[1], "- 70. Bulk/n000.md (no status)")
        self.assertEqual(lines[MAX_RESULT], f"- 70. Bulk/n{MAX_RESULT - 1:03}.md (no status)")
        self.assertEqual(lines[-1], "- ... 3 more")

    def test_nested(self):
        """A parent tag finds child tags and names them; a full nested tag matches exactly."""
        out = self.run_tag("proj proj/edi")[1]
        self.assertEqual(result_block(out), expected("tag-nested.txt"))
        self.assert_line(self.run_tag("pro")[1], "found: no")

    def test_did_you_mean(self):
        out = self.run_tag("tolling edi/mapping")[1]
        self.assert_line(out, "found: no")
        self.assertEqual(result_block(out), "Nothing found.\n"
                         "did you mean tolling: tooling (1)\n"
                         "did you mean edi/mapping: proj/edi/mapping (1)")
        self.assertNotIn("did you mean", self.run_tag("zzzz")[1])

    def test_several(self):
        code, out, _ = self.run_tag("ai", "tooling", "missing")
        self.assertEqual(code, 0)
        self.assert_line(out, "found: yes")
        self.assertEqual(result_block(out), expected("tag-several.txt"))

    def test_no_vault_output(self):
        """vault.py prints the vault and its CLAUDE.md; tag.py prints only its own lines."""
        out = self.run_tag("ai")[1]
        self.assertTrue(out.startswith("found: yes\n"), out)
        for line in ("--- vault CLAUDE.md ---", "English only.", f"vault: {self.vault.as_posix()}"):
            self.assertNotIn(line, out.splitlines())

    def test_mixed_case_hash(self):
        self.assertEqual(result_block(self.run_tag("#AI")[1]), expected("tag-mixed-case.txt"))

    def test_nothing(self):
        code, out, _ = self.run_tag("missing")
        self.assertEqual(code, 0)
        self.assert_line(out, "found: no")
        self.assertEqual(result_block(out), expected("nothing.txt"))

    def test_inline_opt_in(self):
        """--inline also reads body tags, marked 'inline', skipping code, headings, URLs and wikilinks."""
        terms = ("inline-tag fm-tag proj after-fence first-line not-frontmatter fm-tag+inline-tag heading-skip "
                 "code-skip url-skip wikilink-skip alias-skip glued-skip fence-skip tilde-skip")
        self.assertEqual(result_block(self.run_tag("-", stdin=f"{terms} --INLINE\n")[1]), expected("tag-inline.txt"))
        self.assertEqual(result_block(self.run_tag("--inline", "inline-tag")[1]),
                         "inline-tag:\n- 70. Inline/Inline Tags.md (review, inline)")
        self.assert_line(self.run_tag("inline-tag")[1], "found: no")
        self.assertEqual(result_block(self.run_tag("fm-tag")[1]), "fm-tag:\n- 70. Inline/Inline Tags.md (review)")
        out = self.run_tag("--inline")[1].splitlines()
        self.assert_line("\n".join(out), "  - proj/inline (1)")
        self.assertNotIn("- 2026 (1)", out)
        self.assertNotIn("  - proj/inline (1)", self.run_tag()[1].splitlines())

    def test_tag_formats(self):
        """CRLF, CR and BOM notes, 'tag:', comma scalars, '#' items and trailing comments."""
        out = self.run_tag("crlf cr bom singular comma-a comma-b hashed commented")[1]
        self.assertEqual(result_block(out), expected("tag-formats.txt"))

    def test_frontmatter_tags_spellings(self):
        sys.path.insert(0, str(TAG.parent))
        self.addCleanup(sys.path.remove, str(TAG.parent))
        from tag import frontmatter_tags
        cases = {
            "---\r\ntags: [ai]\r\n---\r\n": ["ai"],
            "---\rtags:\r  - ai\r---\r": ["ai"],
            "﻿---\ntags: [ai]\n---\n": ["ai"],
            "---\ntag: ai\n---\n": ["ai"],
            "---\ntags: ai, 'tooling'\n---\n": ["ai", "tooling"],
            "---\ntags:\n  - \"#ai\"\n  - x # note\n---\n": ["ai", "x"],
            "---\ntags: [ai, \"#b\"] # note\n---\n": ["ai", "b"],
            "---\ntags: \"2026\"\n---\n": ["2026"],
            "---\ntagline: ai\n---\n": [],
        }
        for text, want in cases.items():
            self.assertEqual(frontmatter_tags(text), want, repr(text))

    def test_upper_case_suffix(self):
        """A note saved as .MD on Windows is read like .md."""
        self.assertEqual(result_block(self.run_tag("upper-suffix")[1]), "upper-suffix:\n- 50. Formats/Upper.MD (draft)")

    def test_reads_only_frontmatter(self):
        """read_frontmatter stops at the closing fence, or after the first line without frontmatter."""
        sys.path.insert(0, str(TAG.parent))
        self.addCleanup(sys.path.remove, str(TAG.parent))
        from tag import read_frontmatter
        f = io.StringIO("---\ntags: [ai]\n---\nbody\n")
        self.assertEqual(read_frontmatter(f), (["ai"], "no status"))
        self.assertEqual(f.read(), "body\n")
        f = io.StringIO("# Title\n---\ntags: [ai]\n---\n")
        self.assertEqual(read_frontmatter(f), ([], "no status"))
        self.assertEqual(f.read(), "---\ntags: [ai]\n---\n")

    def test_unreadable_note_skipped(self):
        """A note that cannot be opened is skipped; the other notes are still read."""
        sys.path.insert(0, str(TAG.parent))
        self.addCleanup(sys.path.remove, str(TAG.parent))
        import tag
        real_open = open

        def fake_open(path, *args, **kwargs):
            if Path(path).name == "Proj.md":
                raise PermissionError("locked")
            return real_open(path, *args, **kwargs)
        with mock.patch("builtins.open", fake_open):
            paths = [p for p, _, _ in tag.read_notes(self.vault)]
        self.assertNotIn("60. Nested/Proj.md", paths)
        self.assertIn("60. Nested/EDI Mapping.md", paths)

    def test_frontmatter_status(self):
        sys.path.insert(0, str(TAG.parent))
        self.addCleanup(sys.path.remove, str(TAG.parent))
        from tag import read_frontmatter
        cases = {
            "---\nstatus: review\n---\n": "review",
            "---\nstatus: \"draft\" # new\n---\n": "draft",
            "---\nstatus:\n---\n": "no status",
            "---\ntags: [ai]\n---\nstatus: review\n": "no status",
            "no frontmatter": "no status",
        }
        for text, want in cases.items():
            self.assertEqual(read_frontmatter(text)[1], want, repr(text))

    def test_invalid_tags(self):
        for arg in ("a;b", "[x]"):
            code, out, _ = self.run_tag(arg)
            self.assertEqual(code, 0)
            self.assertTrue(out.startswith("ERROR: Invalid tag"), out)
        self.assertTrue(self.run_tag("a;b")[1].startswith("ERROR: Invalid tag 'a;b'"))

    def test_obsidian_tag_rules(self):
        """Digit-only tags are no tags, repeats give one block, casefold matches non-ASCII tags."""
        for arg in ("2026", "#2026", "a.b", "a:b"):
            self.assertTrue(self.run_tag(arg)[1].startswith("ERROR: Invalid tag"), arg)
        self.assertNotIn("- 2026 (1)", self.run_tag()[1].splitlines())
        self.assertEqual(result_block(self.run_tag("ai AI #ai")[1]),
                         expected("tag-several.txt").split("tooling:")[0].rstrip("\n"))
        self.assertEqual(result_block(self.run_tag("-", stdin="CAFÉ\n")[1]),
                         "CAFÉ:\n- 50. Formats/Numeric.md (draft)")

    def test_all_tags(self):
        """'a+b' gives one block of the notes with every tag, nested matching per part; repeats dropped."""
        out = self.run_tag("ai+tooling proj+proj/edi ai+missing tooling+#AI")[1]
        self.assertEqual(result_block(out), expected("tag-all.txt"))
        self.assertEqual(result_block(self.run_tag("tolling+ai")[1]),
                         "Nothing found.\ndid you mean tolling: tooling (1)")
        self.assertTrue(self.run_tag("ai+2026")[1].startswith("ERROR: Invalid tag '2026'"))

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

    def test_stdin_form(self):
        """SKILL.md feeds the raw arguments through a quoted heredoc: no shell quoting involved."""
        self.assertEqual(result_block(self.run_tag("-", stdin="ai tooling missing\n")[1]), expected("tag-several.txt"))
        self.assert_line(self.run_tag("-", stdin="\n")[1], "need: tags")
        out = self.run_tag("-", stdin="ai it's$HOME`x`\n")[1]
        self.assertEqual(out, "ERROR: Invalid tag 'it's$HOME`x`'. Use letters, digits, _ - or / "
                         "(not only digits), separated by spaces.\n")

    def test_unreadable_note_is_system_error(self):
        """A note that cannot be read stops with exit 1 and nothing on stdout."""
        sys.path.insert(0, str(TAG.parent))
        self.addCleanup(sys.path.remove, str(TAG.parent))
        import tag
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}), \
                mock.patch.object(tag, "read_notes", side_effect=OSError("boom")), \
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
