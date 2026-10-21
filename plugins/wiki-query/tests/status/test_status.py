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
        shutil.rmtree(cls.tmp, ignore_errors=True)  # allow-delete: temp test folder

    def header(self, found):
        return f"found: {found}"

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

    def test_no_status_overview(self):
        # Lifecycle order first, then other values alphabetically, any case merged.
        # Notes without a usable status (none, empty, no frontmatter) come last; CLAUDE.md is no note.
        overview = ("found: yes\ndraft: 6\nreview: 3\nevergreen: 4\narchived: 1\n"
                    "mature: 1\nseed: 1\n(no status): 4")
        self.assertEqual(run(SCRIPT, self.home)[:2], (0, overview))
        self.assertEqual(run(SCRIPT, self.home, "")[:2], (0, overview))

    def small_vault(self, name, notes):
        """A temp vault with CLAUDE.md and {file: content} notes. Returns its home folder."""
        vault = self.tmp / name
        vault.mkdir()
        (vault / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
        for file, content in notes.items():
            (vault / file).write_text(content, encoding="utf-8")
        return make_home(self.tmp, name + "-home", f"{vault}\n")

    def test_overview_no_status_line_left_out_at_zero(self):
        home = self.small_vault("allstatus", {"A.md": "---\nstatus: draft\n---\n"})
        self.assertEqual(run(SCRIPT, home)[:2], (0, "found: yes\ndraft: 1"))

    def test_dates(self):
        # Datetime is cut to the date, a bad updated falls back to created,
        # an invalid calendar date is bad, undated and bad dates sort last.
        home = self.small_vault("dates", {
            "A.md": "---\nstatus: draft\nupdated: 2026-02-30\n---\n",
            "B.md": "---\nstatus: draft\nupdated: 2026-03-01 09:00\n---\n",
            "C.md": "---\nstatus: draft\nupdated: soon\ncreated: 2026-01-05\n---\n",
            "D.md": "---\nstatus: draft\n---\n",
        })
        self.assertEqual(run(SCRIPT, home, "draft")[:2],
                         (0, "found: yes\ndraft:\n- C.md (2026-01-05)\n- B.md (2026-03-01)\n"
                             "- A.md (bad date: 2026-02-30)\n- D.md"))

    def test_overview_empty_vault(self):
        home = self.small_vault("emptyvault", {})
        self.assertEqual(run(SCRIPT, home)[:2], (0, "found: no\nNothing found."))

    def test_only_top_block_counts(self):
        # A frontmatter-like block after the closing fence and a large body are ignored.
        body = "text\n" * 200000 + "---\nstatus: review\n---\n"
        home = self.small_vault("topblock", {"A.md": "---\nstatus: draft\n---\n" + body})
        self.assertEqual(run(SCRIPT, home, "draft", "review")[:2],
                         (0, "found: yes\ndraft:\n- A.md\nreview:\n- nothing found"))

    def test_did_you_mean_alone(self):
        self.assertEqual(run(SCRIPT, self.home, "reveiw")[:2],
                         (0, "found: no\nNothing found.\nreveiw: did you mean: review"))

    def test_did_you_mean_in_block(self):
        out = run(SCRIPT, self.home, "seeds", "draft")[1]
        self.assertTrue(out.startswith(
            "found: yes\nseeds:\n- nothing found\n- did you mean: seed\ndraft:"), out)

    def test_keys_any_case_first_spelling_wins(self):
        home = self.small_vault("keycase", {
            "A.md": "---\nSTATUS: Draft\nCreated: 2026-01-02\n---\n",
            "B.md": "---\nStatus: draft\nstatus: review\nUPDATED: 2026-03-04\n---\n",
            "C.md": "---\nStatus:\n  - draft\nstatus:\n  - review\n---\n",
        })
        self.assertEqual(run(SCRIPT, home, "draft", "review")[:2],
                         (0, "found: yes\ndraft:\n- A.md (2026-01-02)\n- B.md (2026-03-04)\n- C.md\n"
                             "review:\n- nothing found"))

    def test_block_cap(self):
        # 52 notes: the 50 oldest are shown, then "... and 2 more"; --all shows all 52.
        home = self.small_vault("cap", {
            f"N{i:02}.md": f"---\nstatus: evergreen\nupdated: 2026-{i // 28 + 1:02}-{i % 28 + 1:02}\n---\n"
            for i in range(52)})
        lines = run(SCRIPT, home, "evergreen draft")[1].splitlines()
        self.assertEqual(lines[:3], ["found: yes", "evergreen:", "- N00.md (2026-01-01)"])
        self.assertEqual(lines[51:], ["- N49.md (2026-02-22)", "- ... and 2 more", "draft:", "- nothing found"])
        lines = run(SCRIPT, home, "--all evergreen")[1].splitlines()
        self.assertEqual((len(lines), lines[-1]), (2 + 52, "- N51.md (2026-02-24)"))
        self.assertEqual(run(SCRIPT, home, "--all")[:2], (0, "found: yes\nevergreen: 52"))

    def test_no_hint_for_lifecycle_status(self):
        home = self.small_vault("nohint", {"A.md": "---\nstatus: archive\n---\n"})
        self.assertEqual(run(SCRIPT, home, "archived")[:2], (0, "found: no\nNothing found."))

    def test_date_quoted_and_list_status(self):
        self.assertEqual(run(SCRIPT, self.home, "SEED")[:2],
                         (0, "found: yes\nSEED:\n- 50. Edge/Seed.md (2026-07-01)"))

    def test_invalid_status(self):
        code, out, _ = run(SCRIPT, self.home, "rev;iew")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("ERROR: invalid status 'rev;iew'"), out)
        self.assertIn("letters, digits, _ or -", out)

    def test_unknown_option(self):
        code, _, err = run(SCRIPT, self.home, "--bogus")
        self.assertEqual(code, 2)
        self.assertIn("SYSTEM ERROR:", err)

    def test_no_vault_claude_md_printed(self):
        out = run(SCRIPT, self.home, "review")[1]
        self.assertNotIn("--- vault CLAUDE.md ---", out)
        self.assertNotIn("Keep notes short.", out)
        self.assertNotIn("vault: ", out)

    def test_system_error_without_vault_py(self):
        plugin = self.tmp / "plug"
        script = plugin / "skills" / "status" / "scripts" / "status.py"
        script.parent.mkdir(parents=True)
        shutil.copy(SCRIPT, script)
        code, _, err = run(script, self.home, "review")
        self.assertEqual(code, 1)
        self.assertIn("ModuleNotFoundError: No module named 'vault'", err)

    def test_frontmatter_edge_cases(self):
        # BOM and "..." closer count; unclosed block and body text do not.
        out = run(SCRIPT, self.home, "review", "draft", "evergreen")[1]
        self.assertIn("- 50. Edge/Bom.md", out)
        self.assertIn("- 50. Edge/Dots.md", out)
        self.assertNotIn("Unclosed.md", out)
        self.assertEqual(out.count("Body.md"), 1)
        self.assertGreater(out.index("Body.md"), out.index("evergreen:"))

    def test_arguments_not_executed_by_shell(self):
        # Render the SKILL.md injection block the way Claude Code does and run it in bash.
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash not available")
        skill = (PLUGIN / "skills" / "status" / "SKILL.md").read_text(encoding="utf-8")
        block = skill.split("```!\n", 1)[1].split("\n```", 1)[0]
        marker = self.tmp / "pwned"
        args = f"review' $(touch {marker.as_posix()}) `touch {marker.as_posix()}` '"
        python = Path(sys.executable).as_posix()
        command = block.replace("$ARGUMENTS", args).replace("python3 ", f'"{python}" ', 1)
        env = dict(os.environ, HOME=str(self.home), CLAUDE_SKILL_DIR=SCRIPT.parents[1].as_posix())
        proc = subprocess.run([bash, "-c", command], env=env, capture_output=True,
                              text=True, encoding="utf-8")
        self.assertFalse(marker.exists())
        self.assertTrue(proc.stdout.startswith("ERROR: invalid status 'review''"), proc.stdout)

    def test_zz_vault_unchanged(self):
        self.assertEqual(tree_hash(self.vault), self.before)


class WalkTest(unittest.TestCase):
    """Links are never followed; skipped root folders match case-insensitively on Windows."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "vault"
        (self.vault / "Notes").mkdir(parents=True)
        (self.vault / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
        (self.vault / "Notes" / "Real.md").write_text("---\nstatus: draft\n---\n", encoding="utf-8")
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        (self.outside / "Foreign.md").write_text("---\nstatus: draft\n---\n", encoding="utf-8")
        self.home = make_home(self.tmp, "home", f"{self.vault}\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)  # allow-delete: temp test folder

    def link(self, target, name, is_dir):
        try:
            os.symlink(target, self.vault / name, target_is_directory=is_dir)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not allowed")

    def expect_only_real(self):
        code, out, _ = run(SCRIPT, self.home, "draft")
        self.assertEqual((code, out), (0, "found: yes\ndraft:\n- Notes/Real.md"))

    def test_symlinked_folder_outside(self):
        self.link(self.outside, "Out", True)
        self.expect_only_real()

    def test_symlinked_file(self):
        self.link(self.outside / "Foreign.md", "Foreign.md", False)
        self.expect_only_real()

    def test_symlink_loop(self):
        self.link(self.vault, "Notes/Loop", True)
        self.expect_only_real()

    @unittest.skipUnless(os.name == "nt", "junctions are Windows only")
    def test_junction_outside(self):
        import _winapi
        _winapi.CreateJunction(str(self.outside), str(self.vault / "Junction"))
        self.expect_only_real()

    @unittest.skipUnless(os.name == "nt", "case-insensitive filesystem")
    def test_skipped_folders_any_case(self):
        for name in ("attachments", "90. TEMPLATES"):
            (self.vault / name).mkdir()
            (self.vault / name / "Skip.md").write_text("---\nstatus: draft\n---\n", encoding="utf-8")
        self.expect_only_real()


if __name__ == "__main__":
    unittest.main()
