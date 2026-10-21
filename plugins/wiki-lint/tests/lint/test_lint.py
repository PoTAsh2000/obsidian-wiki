"""Tests for skills/lint/scripts/lint.py, run as a subprocess against copies of fixture-vault."""

import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[1]
LINT = PLUGIN / "skills" / "lint" / "scripts" / "lint.py"
VAULT_PY = PLUGIN / "scripts" / "vault.py"
MISSING = ("Vault path is missing. Install wiki-vault@obsidian-wiki and use "
           "/wiki-vault:add <vault path> to configure your vault.")
NO_RULES = ("The configured vault folder has no CLAUDE.md: {vault}. "
            "Use /wiki-vault:overwrite <vault path> to fix the vault path.")
AS_OF = ["--as-of", "2026-10-20"]  # fixed date for the inbox-age cutoff
FILES_ARGS = ["--files", "30. Knowledge/Bad Frontmatter.md", "10. Daily/", "30. Knowledge/Stray Draft.md"]


def load_lint():
    """lint.py as a module, for its pure functions and to patch Lint.write."""
    spec = importlib.util.spec_from_file_location("lint_under_test", LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tree(root):
    """{relative path: bytes} for every file under root, hidden ones included."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class LintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.vault = self.tmp / "v"
        shutil.copytree(HERE / "fixture-vault", self.vault)
        self.home = self.tmp / "home"
        self.configure(self.vault)

    def configure(self, vault):
        """Store vault as the configured vault path in the temp HOME, or remove it when None."""
        config = self.home / ".claude" / "obsidian-wiki" / "vault-path"
        config.parent.mkdir(parents=True, exist_ok=True)
        if vault is None:
            config.unlink(missing_ok=True)
        else:
            config.write_text(f"{vault}\r\n", encoding="utf-8")

    def run_script(self, script, *args):
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run([sys.executable, str(script), *args], capture_output=True, env=env)

    def lint(self, *args):
        return self.run_script(LINT, *args)

    def expect(self, result, code, prefix=None):
        self.assertEqual(result.returncode, code, result.stderr.decode(errors="replace"))
        if prefix:
            self.assertTrue(result.stderr.decode().startswith(prefix), result.stderr)

    def expect_vault_error(self, result, message):
        """A vault problem: one ERROR line on stdout, exit 0."""
        self.expect(result, 0)
        self.assertEqual(result.stdout.decode().strip(), f"ERROR: {message}")

    # 1. --dry-run: expected JSON, exit 4, no file changed
    def test_dry_run(self):
        before = tree(self.vault)
        r = self.lint("--dry-run", *AS_OF)
        self.expect(r, 4)
        self.assertEqual(r.stdout.decode(), (HERE / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual(tree(self.vault), before)

    # 1b. --format text: the same report as plain text, same exit code, no file changed
    def test_text_format(self):
        before = tree(self.vault)
        r = self.lint("--dry-run", *AS_OF, "--format", "text")
        self.expect(r, 4)
        self.assertEqual(r.stdout.decode(), (HERE / "expected.txt").read_text(encoding="utf-8"))
        self.assertEqual(tree(self.vault), before)
        clean = self.lint("--format", "text", "--files", "01. Inbox/Good Draft.md")
        self.expect(clean, 0)
        self.assertEqual(clean.stdout.decode(), "lint: 1 notes, 0 links scanned\n")

    # 2 and 3. Real run: same JSON, fixed vault equals expected-vault; a second run fixes nothing
    def test_run_fixes_vault(self):
        r = self.lint(*AS_OF)
        self.expect(r, 4)
        self.assertEqual(r.stdout.decode(), (HERE / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual(tree(self.vault), tree(HERE / "expected-vault"))
        again = json.loads(self.lint().stdout)
        self.assertEqual(again["movedToInbox"], [])
        self.assertEqual(again["removedDeadLinks"], [])

    # 4. --files mode: a note, a folder and a stray draft
    def test_files_mode(self):
        r = self.lint("--dry-run", *AS_OF, *FILES_ARGS)
        self.expect(r, 4)
        self.assertEqual(r.stdout.decode(), (HERE / "expected-files.json").read_text(encoding="utf-8"))

    # 5. Clean note: exit 0
    def test_clean_note(self):
        self.expect(self.lint("--files", "01. Inbox/Good Draft.md"), 0)

    # 6. --help: exit 0, usage on stdout
    def test_help(self):
        for flag in ("--help", "-h"):
            r = self.lint(flag)
            self.expect(r, 0)
            self.assertTrue(r.stdout.decode().startswith("usage: lint.py"))

    # 7. Usage errors: exit 2
    def test_usage_errors(self):
        for label, args in (("unknown flag", ["--bogus"]),
                            ("--files without paths", ["--files"]),
                            ("--as-of without date", ["--as-of"]),
                            ("--as-of bad date", ["--as-of", "2026/10/20"]),
                            ("--format bad value", ["--format", "xml"]),
                            ("--format without value", ["--format"])):
            with self.subTest(label):
                self.expect(self.lint(*args), 2, "SYSTEM ERROR:")

    # 8. User errors: exit 3
    def test_user_errors(self):
        self.expect(self.lint("--files", "No Such.md"), 3, "USER ERROR:")
        (self.vault / "CLAUDE.md").write_text("# Rules\n\nNo lists here.\n", encoding="utf-8")
        self.expect(self.lint("--dry-run"), 3, "USER ERROR:")

    # 8b. Vault problems: the ERROR line from vault.py on stdout, exit 0, nothing changed
    def test_vault_errors(self):
        (self.vault / "CLAUDE.md").unlink()
        before = tree(self.vault)
        self.expect_vault_error(self.lint(), NO_RULES.format(vault=self.vault))
        gone = self.tmp / "nope"
        self.configure(gone)
        self.expect_vault_error(self.lint("--dry-run"), NO_RULES.format(vault=gone))
        self.configure(None)
        self.expect_vault_error(self.lint(), MISSING)
        self.assertEqual(tree(self.vault), before)

    # 9. System error: exit 1 when a note cannot be written, that note unchanged
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write read-only files")
    def test_write_failure(self):
        note = self.vault / "30. Knowledge" / "Dead Links.md"
        before = note.read_bytes()
        os.chmod(note, stat.S_IREAD)
        self.addCleanup(os.chmod, note, stat.S_IREAD | stat.S_IWRITE)
        r = self.lint()
        self.expect(r, 1, "SYSTEM ERROR:")
        self.assertEqual(note.read_bytes(), before)

    # 9b. A note changed between scan and write is reported and left untouched, no temp file left
    def test_changed_before_write(self):
        mod = load_lint()
        note = self.vault / "30. Knowledge" / "Dead Links.md"
        stray = self.vault / "30. Knowledge" / "Stray Draft.md"
        newer = b"newer edit from Obsidian\n"
        real_write = mod.Lint.write

        def write(run):
            note.write_bytes(newer)
            stray.write_bytes(stray.read_bytes() + b"more\n")
            real_write(run)

        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with mock.patch.object(mod.Lint, "write", write), mock.patch.object(sys, "stdout", out), \
                mock.patch.dict(os.environ, HOME=str(self.home)):
            code = mod.lint([])
        self.assertEqual(code, 4)
        result = json.loads(out.buffer.getvalue())
        self.assertEqual(note.read_bytes(), newer)
        self.assertTrue(stray.exists())
        self.assertNotIn({"from": "30. Knowledge/Stray Draft.md", "to": "01. Inbox/Stray Draft.md"},
                         result["movedToInbox"])
        skipped = {f["path"] for f in result["findings"] if f["category"] == "skipped-changed"}
        self.assertEqual(skipped, {"30. Knowledge/Dead Links.md", "30. Knowledge/Stray Draft.md"})
        self.assertFalse([d for d in result["removedDeadLinks"]
                          if d["path"] in ("30. Knowledge/Dead Links.md", "01. Inbox/Stray Draft.md")])
        self.assertFalse(list(self.vault.rglob("*.tmp")))
        # The other notes were still fixed.
        self.assertNotIn("[[CRLF Missing]]", (self.vault / "30. Knowledge" / "CRLF Note.md").read_text(encoding="utf-8"))

    # 9c. Undecodable bytes and control characters in links still give strictly valid JSON
    def test_strict_json(self):
        odd = self.vault / "30. Knowledge" / "Odd Bytes.md"
        odd.write_bytes(b"---\ntype: knowledge\nstatus: review\ncreated: 2026-09-01\n---\n"
                        b"# Odd\n\nLinks [[Bad\xff\x02Byte]] and [[Tab\tLink]].\n")
        r = self.lint("--dry-run", "--files", "30. Knowledge/Odd Bytes.md")
        self.expect(r, 4)
        self.assertIn(b"\\u0002", r.stdout)
        dead = [d["deadLink"] for d in json.loads(r.stdout.decode("utf-8"))["removedDeadLinks"]]
        self.assertEqual(dead, ["[[Bad\\udcff\x02Byte]]", "[[Tab\tLink]]"])

    # 9d. Lint ignore: kept links are listed, ignored paths are not scanned; no section, no effect
    def test_lint_ignore(self):
        r = self.lint("--dry-run", *AS_OF)
        self.assertNotIn(b"Clippings", r.stdout)
        self.assertEqual(json.loads(r.stdout)["summary"]["info"]["allowlistedLinks"], 4)
        rules = self.vault / "CLAUDE.md"
        rules.write_text(rules.read_text(encoding="utf-8").split("## Lint ignore")[0], encoding="utf-8")
        out = json.loads(self.lint("--dry-run", *AS_OF).stdout)
        self.assertEqual(out["allowlistedLinks"], [])
        self.assertIn({"from": "Clippings/Web Clip.md", "to": "01. Inbox/Web Clip.md"}, out["movedToInbox"])
        self.assertIn({"path": "30. Knowledge/Forward Links.md", "line": 8, "deadLink": "[[Planned Topic]]"},
                      out["removedDeadLinks"])

    # 9e. Unicode: an NFC link finds an NFD file (macOS sync), sharp s folds to ss; nothing unlinked
    def test_unicode_names(self):
        k = self.vault / "30. Knowledge"
        (k / "Cafe\u0301 Notes.md").write_text("# Cafe\n", encoding="utf-8")
        (k / "Straße.md").write_text("# Strasse\n", encoding="utf-8")
        (k / "Uni Links.md").write_text("---\ntype: knowledge\nstatus: review\ncreated: 2026-09-01\n---\n"
                                       "# Uni\n\nSee [[Café Notes]] and [[STRASSE]].\n", encoding="utf-8")
        r = self.lint("--files", "30. Knowledge/Uni Links.md")
        self.expect(r, 0)
        self.assertIn("[[Café Notes]] and [[STRASSE]]", (k / "Uni Links.md").read_text(encoding="utf-8"))

    # 9f. Frontmatter structure: BOM, unclosed block and duplicate key each get their own detail
    def test_frontmatter_structure(self):
        out = json.loads(self.lint("--dry-run", *AS_OF).stdout)
        got = {(f["path"], f["line"], f["detail"]) for f in out["findings"]}
        k = "30. Knowledge/"
        for want in ((k + "BOM Note.md", 1, "starts with a byte order mark"),
                     (k + "BOM Note.md", 4, "created '2026/09/01' is not YYYY-MM-DD"),
                     (k + "Unclosed Frontmatter.md", 1, "frontmatter not closed"),
                     (k + "Duplicate Key.md", 7, "duplicate key status at lines 3 and 7")):
            self.assertIn(want, got)
        self.assertFalse([f for f in out["findings"] if f["detail"] == "no frontmatter"
                          and f["path"] != "01. Inbox/No Frontmatter.md"])

    # 9g. Unsafe names: pure rules, then one real finding in a full run, not in --files mode
    def test_unsafe_names(self):
        mod = load_lint()
        nfd = "Cafe\u0301.md"
        got = dict(mod.unsafe_names(["CON.md", "a/lpt1.txt.md", "a:b.md", "Dot.", "x#y.md", "c\x01.md",
                                     nfd, "Dir/Note.md", "dir/note.md", "ok/Fine Name.md"]))
        self.assertEqual(got, {
            "CON.md": "Windows-reserved name",
            "a/lpt1.txt.md": "Windows-reserved name",
            "a:b.md": "character : that Windows forbids",
            "Dot.": "ends with a dot or space",
            "x#y.md": "character # that Obsidian links cannot carry",
            "c\x01.md": "control character",
            nfd: "not Unicode NFC",
            "Dir": "differs only in case from dir",
            "dir": "differs only in case from Dir",
            "Dir/Note.md": "differs only in case from note.md",
            "dir/note.md": "differs only in case from Note.md"})
        (self.vault / "30. Knowledge" / "Topic #1.md").write_text("# T\n", encoding="utf-8")
        (self.vault / "Clippings" / "Clip #2.md").write_text("# C\n", encoding="utf-8")
        out = json.loads(self.lint("--dry-run", *AS_OF).stdout)
        unsafe = [(f["path"], f["detail"]) for f in out["findings"] if f["category"] == "unsafe-name"]
        self.assertEqual(unsafe, [("30. Knowledge/Topic #1.md", "character # that Obsidian links cannot carry")])
        self.assertEqual(out["summary"]["broken-or-risky"]["unsafe-name"], 1)
        files = self.lint("--dry-run", "--files", "30. Knowledge/Topic #1.md").stdout
        self.assertNotIn(b"unsafe-name", files)

    # 9h. .obsidian/app.json: userIgnoreFilters and attachmentFolderPath skip notes; bad JSON is ignored
    def test_obsidian_settings(self):
        ignored = "Excluded/Ignored Note.md"
        app = self.vault / ".obsidian" / "app.json"

        def scanned():
            r = self.lint("--dry-run", *AS_OF)
            self.expect(r, 4)
            out = json.loads(r.stdout)  # a .md file in the attachment folder is an unused attachment
            return ignored in out["orphans"] + [f["path"] for f in out["findings"]
                                                 if f["category"] != "unused-attachment"]

        self.assertFalse(scanned())
        app.write_text('{"attachmentFolderPath": "Excluded"}', encoding="utf-8")
        self.assertFalse(scanned())
        app.write_text('{"attachmentFolderPath": "./", "userIgnoreFilters": "Excluded/"}', encoding="utf-8")
        self.assertTrue(scanned())
        app.write_text("{not json", encoding="utf-8")
        self.assertTrue(scanned())
        mod = load_lint()
        self.assertEqual(mod.obsidian_settings(self.vault), ("attachments", []))
        app.write_text('{"attachmentFolderPath": "/", "userIgnoreFilters": ["/x/", "A[1]"]}', encoding="utf-8")
        folder, ignored = mod.obsidian_settings(self.vault)  # prefix match, [ ] taken literally
        self.assertIsNone(folder)
        self.assertEqual([mod.matches(p, ignored) for p in ("a[1]/n.md", "A1/n.md", "x/n.md")],
                         [True, False, False])

    # 9i. --files mode: a typo link is kept with a suggestion, a link with two close names is
    # unlinked, and empty notes are reported on line 1
    def test_typo_and_empty_note_files_mode(self):
        k = "30. Knowledge/"
        r = self.lint("--files", k + "Typo Links.md", k + "Only Frontmatter.md", k + "Only Title.md")
        self.expect(r, 4)
        out = json.loads(r.stdout)
        got = {(f["category"], f["path"], f["line"], f["detail"]) for f in out["findings"]}
        self.assertIn(("likely-typo", k + "Typo Links.md", 10,
                       "[[Contex Engineering]] did you mean [[Context Engineering]]"), got)
        self.assertIn(("empty-note", k + "Only Frontmatter.md", 1, "no body text"), got)
        self.assertIn(("empty-note", k + "Only Title.md", 1, "no body text"), got)
        self.assertEqual([d["deadLink"] for d in out["removedDeadLinks"]], ["[[Sample Note]]"])
        text = (self.vault / (k + "Typo Links.md")).read_text(encoding="utf-8")
        self.assertIn("[[Contex Engineering]]", text)
        self.assertNotIn("[[Sample Note]]", text)

    # 9j. created after --as-of is invalid and inbox-age falls back to the file date; attachments
    # named in a canvas, base or ignored note, or under a Lint ignore path, are not unused; an
    # archived link whose name two active notes carry as alias gets no suggestion
    def test_created_attachments_archived(self):
        inbox = self.vault / "01. Inbox" / "Future.md"
        inbox.write_text("---\ntype: knowledge\nstatus: draft\ncreated: 2026-12-01\n---\n# F\n\nText.\n",
                         encoding="utf-8")
        os.utime(inbox, (0, 0))
        att = self.vault / "Attachments"
        for name in ("in-canvas.png", "in-base.png", "in-clip.png", "ignored.png"):
            (att / name).write_bytes(b"x")
        (self.vault / "30. Knowledge" / "Project Board.canvas").write_text(
            '{"nodes": [{"type": "file", "file": "Attachments/in-canvas.png"}], "edges": []}', encoding="utf-8")
        (self.vault / "30. Knowledge" / "Tasks.base").write_text("image: in-base.png\n", encoding="utf-8")
        (self.vault / "Clippings" / "Web Clip.md").write_text("![[in-clip.png]]\n", encoding="utf-8")
        rules = self.vault / "CLAUDE.md"
        rules.write_text(rules.read_text(encoding="utf-8").replace("`clippings/**`", "`clippings/**`, `*/ignored.png`"),
                         encoding="utf-8")
        (self.vault / "30. Knowledge" / "Old Twin.md").write_text("---\naliases: [Old Note]\n---\n# T\n",
                                                                   encoding="utf-8")
        out = json.loads(self.lint("--dry-run", *AS_OF).stdout)
        got = {(f["category"], f["path"], f["detail"]) for f in out["findings"]}
        self.assertIn(("frontmatter-invalid", "01. Inbox/Future.md", "created '2026-12-01' is after 2026-10-20"),
                      got)
        self.assertIn(("inbox-age", "01. Inbox/Future.md", "file date 1970-01-01, older than 7 days"), got)
        unused = sorted(p for c, p, _ in got if c == "unused-attachment")
        self.assertEqual(unused, ["Attachments/unused.png"])
        self.assertIn(("archived-link", "30. Knowledge/Archived Links.md",
                       "[[Old Note]] points to 99. Archived/Old Note.md"), got)
        files = self.lint("--dry-run", "--files", "30. Knowledge/Archived Links.md").stdout
        self.assertIn(b"archived-link", files)
        self.assertNotIn(b"unused-attachment", files)

    # 9k. A UTF-16 note is reported in --files mode too; a dead PDF link is kept as missing-attachment
    def test_encoding_and_attachment_files_mode(self):
        k = self.vault / "30. Knowledge"
        (k / "Wide.md").write_bytes("---\ntype: knowledge\n---\n# W\n".encode("utf-16"))
        (k / "Pdf.md").write_bytes(b"# P\n\nSee [[gone.pdf#page=2]] and [[Note v1.2]].\n")
        r = self.lint("--files", "30. Knowledge/Wide.md", "30. Knowledge/Pdf.md")
        self.expect(r, 4)
        out = json.loads(r.stdout)
        got = {(f["category"], f["path"], f["line"], f["detail"]) for f in out["findings"]}
        self.assertIn(("invalid-encoding", "30. Knowledge/Wide.md", 1,
                       "UTF-16 byte order mark, Obsidian needs UTF-8"), got)
        self.assertIn(("missing-attachment", "30. Knowledge/Pdf.md", 3,
                       "[[gone.pdf#page=2]] file gone.pdf not found"), got)
        self.assertEqual([d["deadLink"] for d in out["removedDeadLinks"]], ["[[Note v1.2]]"])
        self.assertEqual((k / "Pdf.md").read_bytes(), b"# P\n\nSee [[gone.pdf#page=2]] and Note v1.2.\n")

    # 9l. --format text caps each category at 25 lines plus an overflow line; --all lifts it
    def test_text_cap(self):
        (self.vault / "Many.md").write_bytes("".join(f"[[Gone {i}]]\n" for i in range(30)).encode())
        args = ("--dry-run", "--format", "text", "--files", "Many.md")
        capped = self.lint(*args).stdout.decode().splitlines()
        self.assertIn("changed (30):", capped)
        self.assertEqual(sum("removedDeadLinks  [[" in x for x in capped), 25)
        self.assertIn("... 5 more removedDeadLinks", capped)
        full = self.lint(*args, "--all").stdout.decode().splitlines()
        self.assertEqual(sum("removedDeadLinks  [[" in x for x in full), 30)
        self.assertFalse([x for x in full if x.startswith("...")])

    # 10. vault.py gives the injected context for step 1 of SKILL.md
    def test_vault_context(self):
        r = self.run_script(VAULT_PY)
        self.expect(r, 0)
        rules = (self.vault / "CLAUDE.md").read_text(encoding="utf-8").rstrip("\n")
        want = f"vault: {self.vault.as_posix()}\n--- vault CLAUDE.md ---\n{rules}\n"
        self.assertEqual(r.stdout.decode("utf-8").replace("\r\n", "\n"), want)
        self.assertEqual(tree(self.vault), tree(HERE / "fixture-vault"))


if __name__ == "__main__":
    unittest.main()
