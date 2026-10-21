"""Tests for the wiki-ingest:apply skill: vault.py as its context script and apply.py.

Every test uses a temp HOME and a copy of the fixture vault, so the fixtures never change.
"""

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
VAULT_PY = PLUGIN / "scripts" / "vault.py"
APPLY_PY = PLUGIN / "skills" / "apply" / "scripts" / "apply.py"
FIXTURE = HERE / "fixture-vault"
EXPECTED = HERE / "expected-vault"

MISSING = ("ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use "
           "/wiki-vault:add <vault path> to configure your vault.")


STUCK = ("Still in 01. Inbox, left as review (run /wiki-ingest:ingest first):\n"
         "- `01. Inbox/Stuck.md`")
# Full runs list these fixture notes and leave them as they are.
STUCK_UNCLEAR = STUCK + (
    "\nStatus looks like review but is not exact, left as is:\n"
    "- `30. Knowledge/Near Review.md` (status: review # checked)\n"
    "Duplicate status, left as is (fix by hand):\n"
    "- `30. Knowledge/Duplicate.md` (status: review, draft)\n"
    "Unclosed frontmatter, left as is:\n"
    "- `30. Knowledge/Unclosed.md`")


def moved(*paths, heading="Moved from review to evergreen"):
    """The report heading with one backticked path per line."""
    return "\n".join([heading + ":", *(f"- `{p}`" for p in paths)])


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

    def refuse(self, result, text):
        """Exit 3: stdout is the reply for the user, stderr the same reason after the tag."""
        self.expect(result, 3, text, f"USER ERROR: apply.py: {text}\n")

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

    def test_split_argument_joined(self):
        # Split words, and one joined argument as the skill passes it.
        for args in (("--dry-run", "Reviewed", "One"), ("--dry-run Reviewed One",), (" --dry-run  Reviewed One ",)):
            self.expect(self.run_script(APPLY_PY, *args), 0,
                        moved("30. Knowledge/Reviewed One.md", heading="Would move from review to evergreen (dry run)"))
        # A name that only starts with the flag text is a name.
        self.refuse(self.run_script(APPLY_PY, "--dry-runner"),
                    'No note named "--dry-runner" in the vault. Nothing changed.')

    def test_inbox_review(self):
        stuck = "`01. Inbox/Stuck.md` is still in 01. Inbox, run /wiki-ingest:ingest first. Nothing changed."
        self.refuse(self.run_script(APPLY_PY, "Stuck"), stuck)
        self.refuse(self.run_script(APPLY_PY, "--dry-run", "01. Inbox/Stuck.md"), stuck)
        self.refuse(self.run_script(APPLY_PY, "--dry-run 01. Inbox/Stuck.md"), stuck)

    def test_dry_run(self):
        self.expect(self.run_script(APPLY_PY, "--dry-run"), 0,
                    moved("20. Customers/Quoted.md", "30. Knowledge/Reviewed CRLF.md",
                          "30. Knowledge/Reviewed One.md", "30. Knowledge/Twin.md", "40. Projects/Twin.md",
                          heading="Would move from review to evergreen (dry run)") + "\n" + STUCK_UNCLEAR)
        for name in ("Evergreen", "twin", "Missing"):
            self.assertEqual(self.run_script(APPLY_PY, "--dry-run", name)[0], 3)

    def test_no_path(self):
        self.config.unlink()
        self.expect(self.run_script(APPLY_PY), 0, MISSING)
        self.expect(self.run_script(APPLY_PY, "--dry-run"), 0, MISSING)
        self.expect(self.run_script(APPLY_PY, "Reviewed One"), 0, MISSING)

    def test_empty_path(self):
        self.set_path("")
        self.expect(self.run_script(APPLY_PY), 0, MISSING)

    def test_no_claude_md(self):
        self.set_path(f"{self.tmp}\n")
        rc, out, _ = self.run_script(APPLY_PY)
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("ERROR: The configured vault folder has no CLAUDE.md"))

    def test_not_found(self):
        self.refuse(self.run_script(APPLY_PY, "Missing"), 'No note named "Missing" in the vault. Nothing changed.')

    def test_evergreen(self):
        self.refuse(self.run_script(APPLY_PY, "Evergreen"),
                    "`30. Knowledge/Evergreen.md` has status evergreen, not review. Nothing changed.")

    def test_draft(self):
        self.refuse(self.run_script(APPLY_PY, "draft"),
                    "`01. Inbox/Draft.md` has status draft, not review. Nothing changed.")

    def test_body_status(self):
        self.refuse(self.run_script(APPLY_PY, "Body Status"),
                    "`40. Projects/Body Status.md` has status draft, not review. Nothing changed.")

    def test_no_status(self):
        self.refuse(self.run_script(APPLY_PY, "No Status"),
                    "`30. Knowledge/No Status.md` has no status in its frontmatter. Nothing changed.")

    def test_unclosed(self):
        # The body line "status: review" is not frontmatter without a closing fence.
        self.refuse(self.run_script(APPLY_PY, "Unclosed"),
                    "`30. Knowledge/Unclosed.md` frontmatter is not closed (no second ---). Nothing changed.")

    def test_duplicate(self):
        self.refuse(self.run_script(APPLY_PY, "Duplicate"),
                    "`30. Knowledge/Duplicate.md` has more than one status line (review, draft), "
                    "fix it by hand. Nothing changed.")

    def test_near_review(self):
        self.refuse(self.run_script(APPLY_PY, "Near Review"),
                    '`30. Knowledge/Near Review.md` has status "review # checked", which is not exactly '
                    "review (only lowercase review with no # comment counts). Nothing changed.")

    def test_no_frontmatter(self):
        self.refuse(self.run_script(APPLY_PY, "No Frontmatter"),
                    "`30. Knowledge/No Frontmatter.md` has no status in its frontmatter. Nothing changed.")

    def test_dot_folder(self):
        self.refuse(self.run_script(APPLY_PY, "Hidden"), 'No note named "Hidden" in the vault. Nothing changed.')

    def test_several(self):
        self.expect(self.run_script(APPLY_PY, "twin"), 3,
                    'Several notes are named "twin":\n- `30. Knowledge/Twin.md`\n- `40. Projects/Twin.md`\n'
                    "Which one? Run /wiki-ingest:apply with its path.",
                    'USER ERROR: apply.py: several notes named "twin"\n')


class ApplyChangesTest(ApplyTestCase):
    def test_full_run(self):
        # One note by name: case-insensitive, spaces trimmed, .md suffix dropped.
        self.expect(self.run_script(APPLY_PY, "  reviewed ONE.md "), 0,
                    moved("30. Knowledge/Reviewed One.md"))
        name = "30. Knowledge/Reviewed One.md"
        self.assertEqual((self.vault / name).read_bytes(), (EXPECTED / name).read_bytes())

        # One note by path, .md added.
        self.expect(self.run_script(APPLY_PY, "40. Projects/Twin"), 0,
                    moved("40. Projects/Twin.md"))
        self.refuse(self.run_script(APPLY_PY, "Reviewed One"),
                    "`30. Knowledge/Reviewed One.md` has status evergreen, not review. Nothing changed.")

        # No argument changes the rest; the vault then equals expected-vault byte for byte.
        self.expect(self.run_script(APPLY_PY, ""), 0,
                    moved("20. Customers/Quoted.md", "30. Knowledge/Reviewed CRLF.md",
                          "30. Knowledge/Twin.md") + "\n" + STUCK_UNCLEAR)
        self.assertEqual(snapshot(self.vault), snapshot(EXPECTED))

        # Idempotent: a second run changes nothing.
        self.before = snapshot(self.vault)
        self.expect(self.run_script(APPLY_PY), 0, "No notes moved from review to evergreen.\n" + STUCK_UNCLEAR)
        self.assert_unchanged()

    def test_fixture_untouched(self):
        changed = [p for p in FIXTURE.rglob("*.md")
                   if p.name != "Evergreen.md" and "evergreen" in p.read_text(encoding="utf-8")]
        self.assertEqual(changed, [])


REVIEW = b"---\nstatus: review\n---\n# Note\n"


def load_apply():
    """apply.py as a module, to fake a failing write in-process."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("apply_under_test", APPLY_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ParseTest(unittest.TestCase):
    def test_parse_status(self):
        parse = load_apply().parse_status
        self.assertEqual(parse("---\ntitle: x\n\n# body\nstatus: review\n"), (0, "", "unclosed"))
        self.assertEqual(parse("---\nstatus: review\nstatus: draft\n---\n"), (2, "review, draft", "duplicate"))
        self.assertEqual(parse("---\na:\n  status: x\nstatus: review\n---\n"), (4, "review", ""))
        self.assertEqual(parse("---\na: 1\n---\nstatus: review\n"), (0, "", ""))

    def test_near_review(self):
        near = load_apply().near_review
        for value in ("Review", "REVIEW", "review # checked", "reviewed", "'Review' # x"):
            self.assertTrue(near(value), value)
        for value in ("review", "draft", "evergreen", "", "in review", "'draft' # review"):
            self.assertFalse(near(value), value)


class ApplyEdgeTest(ApplyTestCase):
    def test_bom(self):
        note = self.vault / "30. Knowledge" / "Bom.md"
        note.write_bytes(b"\xef\xbb\xbf" + REVIEW)
        self.expect(self.run_script(APPLY_PY, "Bom"), 0, moved("30. Knowledge/Bom.md"))
        self.assertEqual(note.read_bytes(), b"\xef\xbb\xbf---\nstatus: evergreen\n---\n# Note\n")

    def test_skipped(self):
        (self.vault / "CLAUDE.md").write_bytes(REVIEW)
        (self.vault / "30. Knowledge" / ".Dot.md").write_bytes(REVIEW)
        links = []
        try:
            os.symlink(self.vault / "30. Knowledge" / "Twin.md", self.vault / "Link.md")
            links.append("Link")
        except (OSError, NotImplementedError):
            pass  # no symlink rights (Windows without developer mode)
        self.before = snapshot(self.vault)
        for name in ["CLAUDE", ".Dot", *links]:
            self.refuse(self.run_script(APPLY_PY, name), f'No note named "{name}" in the vault. Nothing changed.')
        self.assert_unchanged()
        rc, out, _ = self.run_script(APPLY_PY)
        self.assertEqual(rc, 0)
        self.assertNotIn("CLAUDE.md", out)
        self.assertNotIn("Dot.md", out)
        self.assertNotIn("Link.md", out)
        self.assertEqual((self.vault / "CLAUDE.md").read_bytes(), REVIEW)

    def test_partial_failure(self):
        apply = load_apply()
        real_replace, calls = apply.os.replace, []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError("disk full")
            real_replace(src, dst)

        out = io.StringIO()
        with mock.patch.dict(os.environ, HOME=str(self.home)), \
                mock.patch.object(apply.os, "replace", flaky), redirect_stdout(out):
            with self.assertRaises(apply.Exit) as stop:
                apply.run([])
        self.assertEqual(stop.exception.code, 1)
        self.assertIn("edit failed for 30. Knowledge/Reviewed CRLF.md", str(stop.exception))
        self.assertEqual(out.getvalue(), moved("20. Customers/Quoted.md",
                                               heading="Moved from review to evergreen before the error")
                         + "\n" + STUCK_UNCLEAR + "\n")
        name = "30. Knowledge/Reviewed CRLF.md"
        self.assertEqual((self.vault / name).read_bytes(), self.before[name])
        leftovers = [p.name for p in (self.vault / "30. Knowledge").iterdir() if not p.name.endswith(".md")]
        self.assertEqual(leftovers, [])

    def run_in_process(self, apply, argv):
        """apply.run(argv) with the temp HOME; returns (exit code, stdout)."""
        out = io.StringIO()
        with mock.patch.dict(os.environ, HOME=str(self.home)), redirect_stdout(out):
            try:
                return apply.run(argv), out.getvalue()
            except apply.Exit as stop:
                return stop.code, out.getvalue()

    def test_changed_between_read_and_write(self):
        apply = load_apply()
        real_select = apply.select
        twin = self.vault / "30. Knowledge" / "Twin.md"
        edited = b"---\ntype: knowledge\ntitle: moved down\nstatus: review\n---\n# Twin\n"

        def select_then_edit(*args):
            selected = real_select(*args)
            twin.write_bytes(edited)  # an Obsidian or sync edit after the read
            return selected

        with mock.patch.object(apply, "select", select_then_edit):
            code, out = self.run_in_process(apply, [])
        self.assertEqual(code, 0)
        self.assertEqual(out, moved("20. Customers/Quoted.md", "30. Knowledge/Reviewed CRLF.md",
                                    "30. Knowledge/Reviewed One.md", "40. Projects/Twin.md")
                         + "\nChanged during the run, left as review (run again):\n"
                           "- `30. Knowledge/Twin.md`\n" + STUCK_UNCLEAR + "\n")
        self.assertEqual(twin.read_bytes(), edited)

        twin.write_bytes(self.before["30. Knowledge/Twin.md"])
        with mock.patch.object(apply, "select", select_then_edit):
            code, out = self.run_in_process(apply, ["30. Knowledge/Twin.md"])
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertEqual(twin.read_bytes(), edited)

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_mode_kept(self):
        note = self.vault / "30. Knowledge" / "Reviewed One.md"
        note.chmod(0o664)
        self.expect(self.run_script(APPLY_PY, "Reviewed One"), 0,
                    moved("30. Knowledge/Reviewed One.md"))
        self.assertEqual(note.stat().st_mode & 0o777, 0o664)

    def test_locked_retry(self):
        apply = load_apply()
        real_replace, fails = apply.os.replace, []

        def locked(times):
            def replace(src, dst):
                if len(fails) < times:
                    fails.append(dst)
                    raise PermissionError("in use by another process")
                real_replace(src, dst)
            return replace

        name = "30. Knowledge/Reviewed One.md"
        with mock.patch.object(apply.time, "sleep"), \
                mock.patch.object(apply.os, "replace", locked(2)):
            code, out = self.run_in_process(apply, ["Reviewed One"])
        self.assertEqual((code, out), (0, moved(name) + "\n"))
        self.assertEqual((self.vault / name).read_bytes(), (EXPECTED / name).read_bytes())

        # Locked on every try: system error, note and folder as before.
        fails.clear()
        name = "30. Knowledge/Twin.md"
        with mock.patch.object(apply.time, "sleep"), \
                mock.patch.object(apply.os, "replace", locked(99)):
            code, out = self.run_in_process(apply, [name])
        self.assertEqual((code, out), (1, "No notes moved from review to evergreen.\n"))
        self.assertEqual(len(fails), len(apply.RETRY_WAITS) + 1)
        self.assertEqual((self.vault / name).read_bytes(), self.before[name])
        leftovers = [p.name for p in (self.vault / "30. Knowledge").iterdir() if not p.name.endswith(".md")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
