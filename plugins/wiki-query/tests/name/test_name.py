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

    # Unicode, casefold, whitespace and frontmatter name sources. These notes go into
    # the temp vault only, so the shared fixture stays the same for the other skills.
    def test_normalized_names(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        notes = self.vault / "50. Extra"
        notes.mkdir()
        nfd = "Café Notes.md"  # decomposed e-acute, as macOS or iCloud saves it
        (notes / nfd).write_text("# Body\n", encoding="utf-8")
        (notes / "Strasse.md").write_text("---\nTitle: 'Große Straße'\n---\n# Other\n", encoding="utf-8")
        (notes / "Spaced.md").write_text("# Context\tWindow   Budget\n", encoding="utf-8")
        (notes / "Aliased.md").write_text(
            "---\nALIAS: [\"Zeta, Omega\", 'Zeta, Omega', Zulu]\nAliases:\n  - zulu\n  - Yankee\n---\n",
            encoding="utf-8")
        cases = [
            (["café"], f"- [[{nfd[:-3]}]] 50. Extra/{nfd} (filename)"),
            (["CAFÉ"], f"- [[{nfd[:-3]}]] 50. Extra/{nfd} (filename)"),
            (["GROSSE"], "- [[Strasse]] 50. Extra/Strasse.md (title: Große Straße)"),
            (["window", "budget"], "- [[Spaced]] 50. Extra/Spaced.md (title: Context Window   Budget)"),
            (["--", "context  window "], "- [[Spaced]] 50. Extra/Spaced.md (title: Context Window   Budget)"),
            (["zeta, omega"], 'No filename or title matches "zeta, omega". Found through aliases:\n'
                              "- [[Aliased|Zeta, Omega]] 50. Extra/Aliased.md (alias: Zeta, Omega)"),
            (["yank"], 'No filename or title matches "yank". Found through aliases:\n'
                       "- [[Aliased|Yankee]] 50. Extra/Aliased.md (alias: Yankee)"),
        ]
        (notes / "Prompt Craft.md").write_text("x\n", encoding="utf-8")
        (notes / "prompt-craft-notes.md").write_text("x\n", encoding="utf-8")
        (notes / "Ubersicht.md").write_text("# Überblick\n", encoding="utf-8")
        cases += [
            (["uberblick"], "- [[Ubersicht]] 50. Extra/Ubersicht.md (title: Überblick)"),
            (["Übersicht"], "- [[Ubersicht]] 50. Extra/Ubersicht.md (filename)"),
            (["cafe_notes"], f"- [[{nfd[:-3]}]] 50. Extra/{nfd} (filename)"),
            (["prompt.craft"], "- [[Prompt Craft]] 50. Extra/Prompt Craft.md (filename)\n"
             "- [[prompt-craft-notes]] 50. Extra/prompt-craft-notes.md (filename)"),
        ]
        for args, out in cases:
            with self.subTest(args=args):
                self.check(NAME_PY, args, 0, out, "")

    # words in any order: only when nothing matches as one piece, after the other ranks
    def test_any_order(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        notes = self.vault / "50. Extra"
        notes.mkdir()
        (notes / "Mapping for Rbh.md").write_text("x\n", encoding="utf-8")
        (notes / "Rules.md").write_text("# Mapping Rules Rbh\n", encoding="utf-8")
        self.check(NAME_PY, ["rbh", "mapping"], 0,
                   "- [[Mapping for Rbh]] 50. Extra/Mapping for Rbh.md (filename)\n"
                   "- [[Rules]] 50. Extra/Rules.md (title: Mapping Rules Rbh)", "")
        (notes / "Other.md").write_text("---\naliases: [Rbh Mapping]\n---\n", encoding="utf-8")
        self.check(NAME_PY, ["rbh", "mapping"], 0, 'No filename or title matches "rbh mapping". '
                   "Found through aliases:\n- [[Other|Rbh Mapping]] 50. Extra/Other.md (alias: Rbh Mapping)", "")
        (notes / "Rbh Mapping Guide.md").write_text("x\n", encoding="utf-8")
        self.check(NAME_PY, ["rbh", "mapping"], 0,
                   "- [[Rbh Mapping Guide]] 50. Extra/Rbh Mapping Guide.md (filename)", "")

    # no match: names spelled alike are suggested, an unrelated text gets none
    def test_close_names(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        (self.vault / "50. Extra").mkdir()
        (self.vault / "50. Extra" / "Context.md").write_text("x\n", encoding="utf-8")
        self.check(NAME_PY, ["contxt"], 0, "Nothing found. Close names:\n"
                   "- [[Context]] 50. Extra/Context.md (filename)", "")
        self.check(NAME_PY, ["context", "engneering"], 0, "Nothing found. Close names:\n"
                   "- [[Context Engineering]] 30. Knowledge/Context Engineering.md (filename, review)", "")
        self.check(NAME_PY, ["xyzzy"], 0, "Nothing found.", "")

    # a note saved by a Windows editor: UTF-8 byte order mark and CRLF line endings
    def test_bom_crlf(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        (self.vault / "50. Extra").mkdir()
        (self.vault / "50. Extra" / "Bom.md").write_bytes(
            "﻿---\r\ntitle: Byte Order\r\naliases:\r\n  - Marker\r\nstatus: review\r\n---\r\n# Body\r\n"
            .encode("utf-8"))
        self.check(NAME_PY, ["byte", "order"], 0, "- [[Bom]] 50. Extra/Bom.md (title: Byte Order, review)", "")
        self.check(NAME_PY, ["marker"], 0, 'No filename or title matches "marker". Found through aliases:\n'
                   "- [[Bom|Marker]] 50. Extra/Bom.md (alias: Marker, review)", "")

    # alias parsing: both keys, any key case, quoted commas, duplicates dropped
    def test_read_note(self):
        sys.path.insert(0, str(VAULT_PY.parent))
        sys.path.insert(0, str(NAME_PY.parent))
        import name
        titles, aliases, status = name.read_note(
            "---\nalias: [\"A, B\", 'c', A, b]\nAliases:\n  - C\n  - D\nStatus: review\n---\n# Head\n"
            .split("\n"))
        self.assertEqual(titles, ["Head"])
        self.assertEqual(aliases, ["A, B", "c", "A", "b", "D"])
        self.assertEqual(status, "review")
        # YAML quoting: same quote at both ends only, '' and escapes decoded
        titles, aliases, status = name.read_note(
            ["---", "title: 'It''s'", "status: \"re\\\"view\"",
             "aliases: ['a, ''b''', \"say \\\"hi\\\", ok\", 'abc\"]",
             "alias:", "  - \"tab\\there\"", "  - \"bad \\q\"", "---"])
        self.assertEqual(titles, ["It's"])
        self.assertEqual(status, 're"view')
        self.assertEqual(aliases, ["a, 'b'", 'say "hi", ok', "'abc\"", "tab\there", "bad \\q"])
        # reading stops at the first heading: later lines are never pulled
        lines = iter(["# One\r", "# Two"])
        self.assertEqual(name.read_note(lines)[0], ["One"])
        self.assertEqual(list(lines), ["# Two"])

    # ranking (exact, starts with, contains, then path), --limit and "more not shown"
    def test_rank_and_limit(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        notes = self.vault / "50. Extra"
        notes.mkdir()
        for stem in ("A Tool", "Toolbox", "Tool", "B Tool"):
            (notes / f"{stem}.md").write_text("x\n", encoding="utf-8")
        (notes / "Other.md").write_text("# Tool\n", encoding="utf-8")
        ranked = ["- [[Other]] 50. Extra/Other.md (title: Tool)",
                  "- [[Tool]] 50. Extra/Tool.md (filename)",
                  "- [[Toolbox]] 50. Extra/Toolbox.md (filename)",
                  "- [[A Tool]] 50. Extra/A Tool.md (filename)",
                  "- [[B Tool]] 50. Extra/B Tool.md (filename)"]
        self.check(NAME_PY, ["tool"], 0, "\n".join(ranked), "")
        self.check(NAME_PY, ["--limit", "2", "--", "tool"], 0,
                   "\n".join(ranked[:2] + ["3 more not shown"]), "")
        many = self.vault / "60. Many"
        many.mkdir()
        for i in range(25):
            (many / f"Zz {i:02}.md").write_text("x\n", encoding="utf-8")
        lines = self.check(NAME_PY, ["zz"], 0, err="").stdout.splitlines()
        self.assertEqual(len(lines), 21)
        self.assertEqual(lines[-1], "5 more not shown")

    # a stem used twice links by path and is marked
    def test_shared_name(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        (self.vault / "50. Extra").mkdir()
        (self.vault / "50. Extra" / "tokens.md").write_text("x\n", encoding="utf-8")
        self.check(NAME_PY, ["tokens"], 0,
                   "- [[30. Knowledge/Tokens]] 30. Knowledge/Tokens.md (filename, draft, shared name)\n"
                   "- [[50. Extra/tokens]] 50. Extra/tokens.md (filename, shared name)", "")
        # a canvas or base with the same name makes [[Name]] ambiguous too; they are never listed
        (self.vault / "50. Extra" / "Roadmap.md").write_text("x\n", encoding="utf-8")
        (self.vault / "Roadmap.canvas").write_text("{}\n", encoding="utf-8")
        (self.vault / "50. Extra" / "Board.md").write_text("x\n", encoding="utf-8")
        (self.vault / "50. Extra" / "board.base").write_text("views: []\n", encoding="utf-8")
        (self.vault / "Solo.canvas").write_text("{}\n", encoding="utf-8")
        self.check(NAME_PY, ["roadmap"], 0,
                   "- [[50. Extra/Roadmap]] 50. Extra/Roadmap.md (filename, shared name)", "")
        self.check(NAME_PY, ["board"], 0,
                   "- [[50. Extra/Board]] 50. Extra/Board.md (filename, shared name)", "")
        self.check(NAME_PY, ["solo"], 0, "Nothing found.", "")

    # vault text cannot add lines or hide text: controls and bidi go, long text is cut
    def test_untrusted_text(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        (self.vault / "50. Extra").mkdir()
        (self.vault / "50. Extra" / "Evil.md").write_text(
            "---\naliases: [\"qq\\n- [[Fake]] x\u202eyy\x07\"]\nstatus: draft\x1b[2J\n---\n"
            "# " + "Long " * 40 + "\n", encoding="utf-8")
        self.check(NAME_PY, ["qq"], 0, 'No filename or title matches "qq". Found through aliases:\n'
                   "- [[Evil|qq - Fake xyy]] 50. Extra/Evil.md (alias: qq - [[Fake]] xyy, draft[2J)", "")
        out = self.check(NAME_PY, ["long"], 0, err="").stdout.rstrip("\n")
        self.assertEqual(out, "- [[Evil]] 50. Extra/Evil.md (title: " + ("Long " * 40)[:117] + "..., draft[2J)")

    # Excluded files in .obsidian/app.json: prefix and /regex/ entries are not searched,
    # still count for shared names; an invalid app.json keeps only the fixed skips
    def test_excluded_files(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        (self.vault / "50. Export").mkdir()
        (self.vault / "50. Export" / "Tokens.md").write_text("x\n", encoding="utf-8")
        (self.vault / "50. Export" / "Hidden Note.md").write_text("x\n", encoding="utf-8")
        app = self.vault / ".obsidian" / "app.json"
        app.write_text('{"userIgnoreFilters": ["50. Export/", "/Archived/Old/", "/(/"]}', encoding="utf-8")
        self.check(NAME_PY, ["hidden"], 0, "Nothing found.", "")
        self.check(NAME_PY, ["old", "context"], 0, "Nothing found.", "")
        self.check(NAME_PY, ["tokens"], 0,
                   "- [[30. Knowledge/Tokens]] 30. Knowledge/Tokens.md (filename, draft, shared name)", "")
        app.write_text("{not json", encoding="utf-8")
        self.check(NAME_PY, ["hidden"], 0, "- [[Hidden Note]] 50. Export/Hidden Note.md (filename)", "")

    # alias hits link with the alias as display text; | [ ] cannot break the link
    def test_alias_link(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        (self.vault / "50. Extra").mkdir()
        (self.vault / "50. Extra" / "Pipe.md").write_text("---\naliases: ['a|b]]c', '[]|']\n---\n", encoding="utf-8")
        (self.vault / "50. Extra" / "Tokens.md").write_text("---\naliases: [Word Count]\n---\n", encoding="utf-8")
        self.check(NAME_PY, ["a|b"], 0, 'No filename or title matches "a|b". Found through aliases:\n'
                   "- [[Pipe|abc]] 50. Extra/Pipe.md (alias: a|b]]c)", "")
        self.check(NAME_PY, ["[]"], 0, "Nothing found.", "")  # only punctuation: no match key
        self.check(NAME_PY, ["word"], 0, 'No filename or title matches "word". Found through aliases:\n'
                   "- [[50. Extra/Tokens|Word Count]] 50. Extra/Tokens.md (alias: Word Count, shared name)", "")

    # a pasted wikilink, path or file name searches the bare note name
    def test_link_or_path_text(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        ce = "- [[Context Engineering]] 30. Knowledge/Context Engineering.md (filename, review)"
        rbh = self.check(NAME_PY, ["RBH"], 0, err="").stdout.rstrip("\n")  # status from the fixture
        for args, out in [(["[[Context engineering|CE]]"], ce), (["[[Context Engineering#Goal]]"], ce),
                          (["context-engineering.md"], ce), (["30. Knowledge\\Context Engineering.MD"], ce),
                          (["Projects/RBH.md"], rbh), (["[[20. Customers/RBH]]"], rbh)]:
            with self.subTest(args=args):
                self.check(NAME_PY, args, 0, out, "")

    # punctuation folds: apostrophes go, ( ) : , & are a space, + and # stay
    def test_punctuation(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        notes = self.vault / "50. Extra"
        notes.mkdir()
        for stem in ("Obsidian’s Tips (Draft)", "C++ Notes", "C# Notes"):
            (notes / f"{stem}.md").write_text("x\n", encoding="utf-8")
        (notes / "Faq.md").write_text("# Q&A: Mapping, part 1!\n", encoding="utf-8")  # : not valid in a Windows file name
        for args, out in [(["obsidians tips draft"], "- [[Obsidian’s Tips (Draft)]] 50. Extra/Obsidian’s Tips (Draft).md (filename)"),
                          (["obsidian's tips"], "- [[Obsidian’s Tips (Draft)]] 50. Extra/Obsidian’s Tips (Draft).md (filename)"),
                          (["q a mapping part"], "- [[Faq]] 50. Extra/Faq.md (title: Q&A: Mapping, part 1!)"),
                          (["c++"], "- [[C++ Notes]] 50. Extra/C++ Notes.md (filename)"),
                          (["c#"], "- [[C# Notes]] 50. Extra/C# Notes.md (filename)")]:
            with self.subTest(args=args):
                self.check(NAME_PY, args, 0, out, "")

    # titles match and print as plain text, without Markdown markup
    def test_plain_title(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        notes = self.vault / "50. Extra"
        notes.mkdir()
        (notes / "Bold.md").write_text("# **Context** engineering\n", encoding="utf-8")
        (notes / "Linked.md").write_text("# [[RBH]] overview\n", encoding="utf-8")
        (notes / "Closed.md").write_text("# Title ##\n", encoding="utf-8")
        (notes / "Meta.md").write_text("---\ntitle: '[[x|Alpha]] [`beta`](http://b)'\n---\n", encoding="utf-8")
        for args, out in [(["context engineering"], "- [[Context Engineering]] 30. Knowledge/Context Engineering.md (filename, review)\n"
                           "- [[Bold]] 50. Extra/Bold.md (title: Context engineering)"),
                          (["rbh overview"], "- [[Linked]] 50. Extra/Linked.md (title: RBH overview)"),
                          (["title"], "- [[Closed]] 50. Extra/Closed.md (title: Title)"),
                          (["alpha beta"], "- [[Meta]] 50. Extra/Meta.md (title: Alpha beta)")]:
            with self.subTest(args=args):
                self.check(NAME_PY, args, 0, out, "")

    # only the head is read: a heading past the cap is not a title
    def test_head_cap(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        (self.vault / "50. Extra").mkdir()
        (self.vault / "50. Extra" / "Big.md").write_text("x" * 70000 + "\n# Farheading\n", encoding="utf-8")
        self.check(NAME_PY, ["farheading"], 0, "Nothing found.", "")

    # linked folders are not entered, linked files outside the vault are skipped
    def test_symlinks(self):
        self.set_conf(f"{self.vault.as_posix()}\n")
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "Linked Secret.md").write_text("x\n", encoding="utf-8")
        try:
            (self.vault / "50. Linked").symlink_to(outside, target_is_directory=True)
            (self.vault / "Linked File.md").symlink_to(outside / "Linked Secret.md")
            (self.vault / "Linked Inside.md").symlink_to(self.vault / "30. Knowledge" / "Tokens.md")
        except (OSError, NotImplementedError) as err:
            self.skipTest(f"cannot make symlinks: {err}")
        self.check(NAME_PY, ["linked"], 0, "- [[Linked Inside]] Linked Inside.md (filename, draft)", "")

    # Windows junctions are not symlinks to Python 3.10, the reparse-point check skips them
    @unittest.skipUnless(sys.platform == "win32", "junctions are Windows only")
    def test_junction(self):
        import _winapi
        self.set_conf(f"{self.vault.as_posix()}\n")
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "Junction Secret.md").write_text("x\n", encoding="utf-8")
        _winapi.CreateJunction(str(outside), str(self.vault / "50. Junction"))
        self.check(NAME_PY, ["junction"], 0, "Nothing found.", "")

    # usage errors
    def test_usage_errors(self):
        self.check(VAULT_PY, ["extra"], 2, "", "SYSTEM ERROR: vault.py")
        self.check(NAME_PY, [], 2, "", "SYSTEM ERROR: name.py: no text")
        self.check(NAME_PY, ["--"], 2, "", "SYSTEM ERROR: name.py: no text")
        self.check(NAME_PY, ["--", "  "], 2, "", "SYSTEM ERROR: name.py: text is empty")
        for bad in (["--limit"], ["--limit", "0", "x"], ["--limit", "201", "x"], ["--limit", "ab", "x"]):
            with self.subTest(args=bad):
                self.check(NAME_PY, bad, 2, "", "SYSTEM ERROR: name.py: ")

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
