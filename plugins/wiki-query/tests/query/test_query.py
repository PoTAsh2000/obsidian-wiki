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
CITE = PLUGIN / "skills" / "query" / "scripts" / "cite.py"
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


def make_home(base, content=None):
    """Temp HOME under base, with a vault-path file holding content when given."""
    home = Path(base) / "home"
    conf = home / ".claude" / "obsidian-wiki"
    conf.mkdir(parents=True)
    if content is not None:
        (conf / "vault-path").write_bytes(content.encode("utf-8"))
    return home


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
    """search.py with HOME pointing at a vault-path file that holds the fixture vault."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = make_home(self.tmp.name, str(FIXTURE))

    def check(self, case, *args):
        code, out, _ = run(SEARCH, *args, home=self.home)
        self.assertEqual(code, 0)
        self.assertEqual(out, expected(case))

    def check_code(self, want, prefix, *args):
        code, _, err = run(SEARCH, *args, home=self.home)
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

    def test_excerpts_links(self):
        # headings, a code fence, a long line, a duplicate filename, archived after an equal
        # score, related entries, an unresolved link, a template target and inbound links
        self.check("search-excerpts-links", "--excerpts", "3", "--links", "2", "seal", "warm")

    def test_bad_excerpts(self):
        self.check_code(2, "SYSTEM ERROR:", "--excerpts", "21", "edi")

    def test_bad_links(self):
        self.check_code(2, "SYSTEM ERROR:", "--links", "0", "edi")

    def test_links_no_number(self):
        self.check_code(2, "SYSTEM ERROR:", "edi", "--links")

    def test_limit_leading_zero(self):
        self.check_code(2, "SYSTEM ERROR:", "--limit", "08", "edi")

    def test_help(self):
        self.check_code(0, None, "--help")

    def test_help_short(self):
        self.check_code(0, None, "-h")

    def test_no_term(self):
        self.check_code(2, "SYSTEM ERROR:")

    def test_no_vault(self):
        home = make_home(Path(self.tmp.name) / "empty")
        self.assertEqual(run(SEARCH, "edi", home=home)[:2], (0, MISSING + "\n"))

    def test_bad_limit(self):
        self.check_code(2, "SYSTEM ERROR:", "--limit", "0", "edi")

    def test_bad_option(self):
        self.check_code(2, "SYSTEM ERROR:", "--color", "edi")

    def test_empty_term(self):
        self.check_code(2, "SYSTEM ERROR:", " ")

    def test_missing_vault(self):
        missing = FIXTURE / "missing"
        home = make_home(Path(self.tmp.name) / "gone", str(missing))
        code, out, _ = run(SEARCH, "edi", home=home)
        self.assertEqual(code, 0)
        self.assertEqual(out, f"ERROR: The configured vault folder has no CLAUDE.md: {missing}. "
                              "Use /wiki-vault:overwrite <vault path> to fix the vault path.\n")


class SuggestTest(QueryTestCase):
    """suggest: lines when no note has a whole-word hit."""

    setUp = SearchTest.setUp

    def suggestions(self, *terms):
        return [line for line in run(SEARCH, *terms, home=self.home)[1].splitlines()
                if line.startswith("suggest:")]

    def test_typos(self):
        self.assertEqual(self.suggestions("maping", "edifakt"), [
            "suggest: maping = mapping, old mapping, edi mapping",
            "suggest: edifakt = edifact, edits, credit, edi"])

    def test_part_word_only(self):
        self.assertEqual(self.suggestions("map"), ["suggest: map = mapping"])

    def test_whole_word_hit(self):
        self.assertEqual(self.suggestions("edi", "zzzq"), [])


class SectionTest(QueryTestCase):
    """Excerpt section ranges: same or higher level heading ends a section, fences ignored."""

    def test_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            (vault / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
            (vault / "Note.md").write_text(
                "---\nstatus: draft\n---\nkey intro\n# Top\nkey top\n## A\nkey a\n"
                "### A1\n```\n# not a heading\n```\nkey a1\n## B\nkey b\n",
                encoding="utf-8")
            out = run(SEARCH, "--excerpts", "9", "key", home=make_home(tmp, str(vault)))[1]
        self.assertEqual([line for line in out.splitlines() if line.startswith("  ")], [
            "  4 | - (4-4) | key intro", "  6 | Top (5-15) | key top",
            "  8 | A (7-13) | key a", "  13 | A1 (9-13) | key a1", "  15 | B (14-15) | key b"])


def temp_vault(tmp, notes):
    """Vault under tmp with a CLAUDE.md and notes {filename: text}; return its HOME."""
    vault = Path(tmp) / "vault"
    vault.mkdir()
    (vault / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
    for name, text in notes.items():
        (vault / name).write_text(text, encoding="utf-8")
    return make_home(tmp, str(vault))


class FreshTest(QueryTestCase):
    """created, updated/modified and source/url frontmatter on each result line."""

    def test_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = temp_vault(tmp, {
                "A.md": "---\ncreated: 2026-01-05\nmodified: '2026-03-02'\n"
                        "url:\n  - https://Example.org/X\n  - https://other\n---\nkey a\n",
                "B.md": "---\nupdated: 2026-04-01\nmodified: 2025-01-01\n"
                        "source: \"[[Some Book]]\"\nurl: https://ignored\n---\nkey b\n",
                "C.md": "key c\n"})
            out = run(SEARCH, "key", home=home)[1]
        rows = {line[2:].split(" | ")[0]: line for line in out.splitlines() if line.startswith("- ")}
        self.assertIn(" | created: 2026-01-05 | updated: 2026-03-02 | source: https://Example.org/X"
                      " | link: [[A]]", rows["A.md"])
        self.assertIn(" | updated: 2026-04-01 | source: [[Some Book]] | link: [[B]]", rows["B.md"])
        self.assertNotRegex(rows["C.md"], "created|updated|source")


class BestExcerptTest(QueryTestCase):
    """Excerpts are the best lines, one per section first, printed in line order."""

    def test_best_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = temp_vault(tmp, {"Note.md": (
                "Our credit policy.\nSome edits.\n# A\nThe EDI mapping lives here.\n"
                "EDI mapping again.\n# B\nmapping only.\n")})
            out = run(SEARCH, "--excerpts", "2", "edi", "mapping", home=home)[1]
        self.assertEqual([line for line in out.splitlines() if line.startswith("  ")], [
            "  4 | A (3-5) | The EDI mapping lives here.", "  7 | B (6-7) | mapping only."])


class SectionBonusTest(QueryTestCase):
    """Terms that meet in one section rank a note above one with the terms apart."""

    def test_together_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = temp_vault(tmp, {
                "Apart.md": "# A\nEDI is a format.\n# B\nmapping is a task.\n# C\nEDI.\n",
                # same hits as Apart.md, so without the bonus Apart.md wins on path order
                "Together.md": "# A\nEDI is a format.\n# B\nmapping is a task for EDI.\n",
                "Other.md": "nothing here\n"})
            out = run(SEARCH, "edi", "mapping", home=home)[1]
        rows = [line[2:].split(" | ")[0] for line in out.splitlines() if line.startswith("- ")]
        self.assertEqual(rows, ["Together.md", "Apart.md"])


class UnicodeTest(QueryTestCase):
    """Decomposed accents (macOS sync) and sharp s match composed, other-case terms."""

    def test_nfd_and_casefold(self):
        name = "Cafe\u0301 Mu\u0308ller.md"  # decomposed e-acute and u-umlaut
        with tempfile.TemporaryDirectory() as tmp:
            home = temp_vault(tmp, {name: "Die Gro\u00dfe cafe\u0301 rule by Mu\u0308ller.\n"})
            for term in ("caf\u00e9", "M\u00dcLLER", "GROSSE"):
                out = run(SEARCH, "--excerpts", "1", term, home=home)[1]
                self.assertIn("matches: 1\n", out, term)
                # output keeps the original text
                self.assertIn(f"- {name} |", out, term)
                self.assertIn("  1 | - (1-1) | Die Gro\u00dfe cafe\u0301 rule by Mu\u0308ller.", out, term)


class CiteTest(QueryTestCase):
    """cite.py: quiet on good links, one line per bad link."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = make_home(self.tmp.name, str(FIXTURE))

    def test_ok(self):
        self.assertEqual(run(CITE, "[[Seals#habitat]] [[seals]]", "[[EDI Mapping|x]]",
                             "[[40. Projects/Blubber#Blubber]]", home=self.home)[:2], (0, ""))

    def test_findings(self):
        code, out, _ = run(CITE, "[[Seals#Habitatt]]", "[[Blubber]]", "[[Seels]]",
                           "[[Seals#Nope Nope Nope]]", "[[Zzzq]]", "Seals#^abc", home=self.home)
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), [
            "heading: [[Seals#Habitatt]] -> [[Seals#Habitat]]",
            "ambiguous: [[Blubber]] -> [[40. Projects/Blubber]] or [[99. Archived/Blubber]]",
            "unresolved: [[Seels]] -> [[Seals]]",
            "heading: [[Seals#Nope Nope Nope]] -> no such heading in 30. Knowledge/Seals.md",
            "unresolved: [[Zzzq]]",
            "heading: [[Seals#^abc]] -> no such block ^abc in 30. Knowledge/Seals.md"])

    def test_no_link(self):
        code, _, err = run(CITE, " ", home=self.home)
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("SYSTEM ERROR:"), err)

    def test_no_vault(self):
        home = make_home(Path(self.tmp.name) / "empty")
        self.assertEqual(run(CITE, "[[Seals]]", home=home)[:2], (0, MISSING + "\n"))


class RankingTest(QueryTestCase):
    """Fixed questions against the fixture vault: each expected note must be in the top 3."""

    QUESTIONS = (
        (("edifact", "mapping"), ("30. Knowledge/EDI Mapping.md", "40. Projects/Invoice Flow.md")),
        (("edi",), ("30. Knowledge/EDI Mapping.md", "40. Projects/Empty EDI.md",
                    "40. Projects/proj-orders.md")),
        (("seal", "warm"), ("30. Knowledge/Seals.md", "40. Projects/Blubber.md", "Loose Note.md")),
        (("message mapping",), ("30. Knowledge/EDI Mapping.md", "99. Archived/Old Mapping.md")),
    )

    def test_top3(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, str(FIXTURE))
            misses = []
            for terms, want in self.QUESTIONS:
                out = run(SEARCH, "--limit", "3", "--", *terms, home=home)[1]
                top = [line[2:].split(" | ")[0] for line in out.splitlines()
                       if line.startswith("- ")]
                misses += [f"{' '.join(terms)}: {note}" for note in want if note not in top]
        self.assertEqual(misses, [])


class LimitsTest(QueryTestCase):
    """Query size limits and notes that resolve outside the vault."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = make_home(self.tmp.name, str(FIXTURE))

    def check_usage(self, *args):
        code, _, err = run(SEARCH, *args, home=self.home)
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("SYSTEM ERROR:"), err)

    def test_too_many_terms(self):
        self.check_usage(*[f"t{n}" for n in range(21)])

    def test_twenty_terms(self):
        self.assertEqual(run(SEARCH, *[f"t{n}" for n in range(20)], home=self.home)[0], 0)

    def test_long_term(self):
        self.check_usage("x" * 201)

    def test_term_at_limit(self):
        self.assertEqual(run(SEARCH, "x" * 200, home=self.home)[0], 0)

    def test_symlink_outside(self):
        base = Path(self.tmp.name)
        vault, outside = base / "vault", base / "outside"
        vault.mkdir()
        (outside / "dir").mkdir(parents=True)
        (vault / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
        (vault / "Inside.md").write_text("secret inside\n", encoding="utf-8")
        (outside / "Leak.md").write_text("secret outside\n", encoding="utf-8")
        (outside / "dir" / "Deep.md").write_text("secret deep\n", encoding="utf-8")
        try:
            (vault / "Link.md").symlink_to(outside / "Leak.md")
            (vault / "Folder").symlink_to(outside / "dir", target_is_directory=True)
        except (OSError, NotImplementedError) as err:
            self.skipTest(f"cannot create symlinks: {err}")
        out = run(SEARCH, "secret", home=make_home(base / "h", str(vault)))[1]
        self.assertIn("- Inside.md |", out)
        self.assertIn("matches: 1\n", out)


class ContextTest(QueryTestCase):
    """The skill injects vault.py for its vault and vault CLAUDE.md context."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def home(self, content=None):
        """Temp HOME, with a vault-path file when content is given."""
        return make_home(self.tmp.name, content)

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
