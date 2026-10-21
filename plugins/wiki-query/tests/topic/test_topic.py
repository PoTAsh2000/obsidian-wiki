"""Tests for skills/topic/scripts/topic.py with a temp HOME and a copy of the fixture vault.

Also covers the vault.py call that the topic skill injects for the vault CLAUDE.md.
"""

import hashlib
import io
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[1]
TOPIC = PLUGIN / "skills" / "topic" / "scripts" / "topic.py"
VAULT_PY = PLUGIN / "scripts" / "vault.py"
EXPECTED = (HERE / "expected" / "topic.txt").read_text(encoding="utf-8")
RULES = "# Vault rules\nNever write.\n"
MISSING = ("Vault path is missing. Install wiki-vault@obsidian-wiki and use "
           "/wiki-vault:add <vault path> to configure your vault.")

sys.path.insert(0, str(TOPIC.parent))
import topic  # noqa: E402


def snapshot(folder):
    """Map every file under folder to its md5, to prove the vault is unchanged."""
    return {p.relative_to(folder).as_posix(): hashlib.md5(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


class TopicTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)  # allow-delete: temp test dir
        self.vault = self.tmp / "vault"
        shutil.copytree(HERE / "fixture-vault", self.vault)
        (self.vault / "CLAUDE.md").write_text(RULES, encoding="utf-8", newline="\n")
        self.home = self.tmp / "home"
        self.conf = self.home / ".claude" / "obsidian-wiki" / "vault-path"
        self.conf.parent.mkdir(parents=True)
        self.set_conf(f"{self.vault}\n")
        self.before = snapshot(self.vault)

    def tearDown(self):
        self.assertEqual(snapshot(self.vault), self.before, "vault changed")

    def set_conf(self, text):
        self.conf.write_text(text, encoding="utf-8", newline="")

    def run_script(self, script, *args, stdin=""):
        env = dict(os.environ, HOME=str(self.home))
        done = subprocess.run([sys.executable, str(script), *args], env=env, input=stdin,
                              capture_output=True, text=True, encoding="utf-8")
        return done.returncode, done.stdout.rstrip("\n"), done.stderr

    def write_note(self, name, text):
        (self.vault / "30. Knowledge" / name).write_text(text, encoding="utf-8", newline="\n")
        self.before = snapshot(self.vault)

    def check(self, want_code, want_out, *args, script=TOPIC, stdin=""):
        code, out, err = self.run_script(script, *args, stdin=stdin)
        self.assertEqual(code, want_code, err)
        self.assertEqual(out, want_out.rstrip("\n"))
        return err

    # lookups

    def test_found(self):
        self.check(0, EXPECTED, "EDI")

    def test_found_lower(self):
        self.check(0, EXPECTED.replace("EDI:", "edi:", 1), "edi")

    def test_several(self):
        self.check(0, EXPECTED + "missing:\n- nothing found\n", "EDI", "missing")

    def test_several_in_one_argument(self):
        self.check(0, EXPECTED + "missing:\n- nothing found\n", "EDI  missing")

    def test_empty_argument(self):
        self.check(0, "ERROR: no topic given\nknown topics: AI (5), EDI (2)", "")

    def test_comma_separated(self):
        (self.vault / "30. Knowledge" / "Ctx.md").write_text(
            "---\ntopic: [Context Engineering]\n---\n", encoding="utf-8", newline="\n")
        self.before = snapshot(self.vault)
        self.check(0, "Context Engineering:\n- 30. Knowledge/Ctx.md\n" + EXPECTED,
                   "Context Engineering, EDI")
        self.check(0, "Context Engineering:\n- 30. Knowledge/Ctx.md", " Context Engineering ,")

    def test_skips_vault_claude_md(self):
        (self.vault / "CLAUDE.md").write_text("---\ntopic: EDI\n---\n" + RULES,
                                              encoding="utf-8", newline="\n")
        self.before = snapshot(self.vault)
        self.check(0, EXPECTED, "EDI")
        self.check(0, "ERROR: no topic given\nknown topics: AI (5), EDI (2)")

    @unittest.skipUnless(shutil.which("bash"), "needs bash")
    def test_skill_inject_does_not_expand_arguments(self):
        skill = (PLUGIN / "skills" / "topic" / "SKILL.md").read_text(encoding="utf-8")
        block = re.search(r"^```!\n(.*?topic\.py.*?)^```$", skill, re.M | re.S).group(1)
        self.assertIn("<<'WIKI_TOPIC_ARGS_END'\n$ARGUMENTS\nWIKI_TOPIC_ARGS_END\n", block)
        self.assertNotIn("'$ARGUMENTS'", skill)
        self.write_note("OR.md", "---\ntopic: \"O'Reilly\"\n---\n")
        payloads = [
            ("EDI; touch p1 $(touch p2) `touch p3` > p4 *", "Nothing found.\ndid you mean: EDI (2)"),
            ("x'; touch p5; ' $HOME \\", "Nothing found."),
            ("O'Reilly,", "O'Reilly:\n- 30. Knowledge/OR.md"),
            ("EDI", EXPECTED),
        ]
        work = self.tmp / "work"
        work.mkdir()
        env = dict(os.environ, HOME=str(self.home), CLAUDE_SKILL_DIR=str(TOPIC.parents[1]))
        for payload, want in payloads:
            cmd = block.replace("python3", shlex.quote(sys.executable), 1).replace("$ARGUMENTS", payload)
            done = subprocess.run([shutil.which("bash"), "-c", cmd], cwd=work, env=env,
                                  capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout.rstrip("\n"), want.rstrip("\n"), payload)
            self.assertEqual(list(work.iterdir()), [], payload)

    def test_stdin_lines(self):
        self.check(0, EXPECTED + "missing:\n- nothing found\n", stdin="EDI\nmissing\n")
        self.check(0, "ERROR: no topic given\nknown topics: AI (5), EDI (2)", stdin="\n")

    def test_unicode_and_order(self):
        for name, value in [("b.md", "Straße"), ("A.md", "Café"), ("c.md", "café")]:
            self.write_note(name, f"---\ntopic: {value}\n---\n")
        self.check(0, "STRASSE:\n- 30. Knowledge/b.md", "STRASSE")
        both = "- 30. Knowledge/A.md\n- 30. Knowledge/c.md"
        self.check(0, f"café:\n{both}", "café")
        self.check(0, f"CAFÉ:\n{both}", "CAFÉ")
        self.check(0, "ERROR: no topic given\nknown topics: AI (5), "
                      "Café (2), EDI (2), Straße (1)")

    def test_wikilink_topics(self):
        self.write_note("Link.md", '---\ntopic: [[EDI]]\n---\n')
        self.write_note("Alias.md", '---\ntopic:\n  - "[[30. Knowledge/EDI.md|edi]]"\n---\n')
        self.write_note("Path.md", "---\ntopic: ['[[30. Knowledge/EDI.md]]', AI]\n---\n")
        links = "".join(f"- 30. Knowledge/{n}.md\n" for n in ("Alias", "Link", "Path"))
        self.check(0, EXPECTED.replace("- 40.", links + "- 40.", 1), "EDI")

    def test_comments(self):
        self.write_note("C.md", "---\ntopic: C# # language\nstatus: draft # todo\n---\n")
        self.write_note("Q.md", "---\ntopic: # list below\n  - 'C# #1' # quoted\n---\n")
        self.check(0, "C#:\n- 30. Knowledge/C.md (draft)", "C#")
        self.check(0, "C# #1:\n- 30. Knowledge/Q.md", "C# #1,")

    def test_nothing(self):
        self.check(0, "Nothing found.", "missing")

    def test_did_you_mean_misspelled(self):
        self.check(0, "Nothing found.\ndid you mean: EDI (2)", "EDU")
        self.check(0, EXPECTED + "EDU:\n- nothing found\ndid you mean: EDI (2)", "EDI", "EDU")

    def test_did_you_mean_partial(self):
        self.write_note("Ctx.md", "---\ntopic: Context Engineering\n---\n")
        self.check(0, "Nothing found.\ndid you mean: Context Engineering (1)", "engineering")

    def test_skips_dot_attachment_and_template_folders(self):
        self.check(0, "AI:\n- 30. Knowledge/Context Engineering.md (review)\n"
                      "- 30. Knowledge/Playbook.md (evergreen)\n- 30. Knowledge/Tokens.md (draft)\n"
                      "- 30. Knowledge/Window Size.md (evergreen)\n"
                      "- 99. Archived/Old Context.md (archived)", "AI")

    def test_no_topic(self):
        self.check(0, "ERROR: no topic given\nknown topics: AI (5), EDI (2)")

    def test_no_topic_empty_vault(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        (bare / "CLAUDE.md").write_text(RULES, encoding="utf-8")
        self.set_conf(str(bare))
        self.check(0, "ERROR: no topic given")

    def test_no_rules_marker(self):
        _, out, _ = self.run_script(TOPIC, "EDI")
        self.assertNotIn("--- vault CLAUDE.md ---", out)
        self.assertNotIn("Never write.", out)

    def test_help(self):
        code, out, _ = self.run_script(TOPIC, "--help")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("topic.py:"))
        self.assertEqual(self.run_script(TOPIC, "-h"), (0, out, ""))

    # vault CLAUDE.md, injected through vault.py (was topic.sh --rules)

    def test_rules(self):
        self.check(0, f"vault: {self.vault.as_posix()}\n--- vault CLAUDE.md ---\n{RULES}",
                   script=VAULT_PY)

    def test_rules_no_config(self):
        self.conf.unlink()  # allow-delete: temp vault-path file, tests a missing config
        self.check(0, f"ERROR: {MISSING}", script=VAULT_PY)

    # usage errors

    def test_bad_option(self):
        err = self.check(2, "", "--color")
        self.assertTrue(err.startswith("SYSTEM ERROR: topic.py: unknown option: --color"), err)

    def test_rules_option_gone(self):
        err = self.check(2, "", "--rules", "EDI")
        self.assertTrue(err.startswith("SYSTEM ERROR: topic.py: unknown option: --rules"), err)

    def test_inject_option_gone(self):
        err = self.check(2, "", "--inject", "EDI")
        self.assertTrue(err.startswith("SYSTEM ERROR: topic.py: unknown option: --inject"), err)

    # vault path variants

    def test_crlf_and_spaces(self):
        raw = str(self.vault)
        if sys.platform == "win32":
            raw = raw.replace("/", "\\")
        self.set_conf(f"  {raw} \r\n")
        self.check(0, EXPECTED, "EDI")

    def test_no_newline_config(self):
        self.set_conf(str(self.vault))
        self.check(0, "Nothing found.", "missing")

    # vault problems: "ERROR: <message>" on stdout, exit 0, from vault.require_vault()

    def no_rules(self, folder):
        """The ERROR line vault.py prints for a vault folder without CLAUDE.md."""
        return (f"ERROR: The configured vault folder has no CLAUDE.md: {folder}. "
                "Use /wiki-vault:overwrite <vault path> to fix the vault path.")

    def test_no_config(self):
        self.conf.unlink()  # allow-delete: temp vault-path file, tests a missing config
        err = self.check(0, f"ERROR: {MISSING}", "EDI")
        self.assertEqual(err, "")

    def test_empty_config(self):
        self.set_conf("")
        self.check(0, f"ERROR: {MISSING}", "EDI")

    def test_no_folder(self):
        nope = self.tmp / "nope"
        self.set_conf(str(nope))
        self.check(0, self.no_rules(nope), "EDI")

    def test_no_claude_md(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        self.set_conf(str(bare))
        self.check(0, self.no_rules(bare), "EDI")

    # unreadable notes and folder links

    def test_unreadable_note_is_skipped(self):
        real = Path.read_text

        def read_text(path, *args, **kwargs):
            if path.name == "RBH.md":
                raise PermissionError("locked")
            return real(path, *args, **kwargs)

        with mock.patch.dict(os.environ, {"HOME": str(self.home)}), \
                mock.patch.object(Path, "read_text", read_text), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(topic.main(["EDI"]), 0)
        self.assertEqual(out.getvalue(), "EDI:\n- 40. Projects/proj-edi.md (draft)\n"
                                         "skipped: 1 unreadable note: 20. Customers/RBH.md\n")

    def test_folder_link_not_followed(self):
        loop = self.vault / "30. Knowledge" / "loop"
        try:
            if sys.platform == "win32":
                import _winapi
                _winapi.CreateJunction(str(self.vault), str(loop))
            else:
                loop.symlink_to(self.vault, target_is_directory=True)
        except (OSError, AttributeError) as err:
            self.skipTest(f"cannot create a folder link: {err}")
        try:
            self.check(0, EXPECTED, "EDI")
        finally:  # before tearDown walks the vault
            (os.rmdir if sys.platform == "win32" else os.unlink)(loop)  # allow-delete: temp folder link made by this test

    # system error

    def test_unreadable_root(self):
        def walk(top, onerror):
            onerror(OSError(2, "gone", str(top)))
            return iter(())

        with mock.patch.object(topic.os, "walk", walk), self.assertRaises(OSError):
            list(topic.notes(self.vault, []))

    def test_lookup_fails(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}), \
                mock.patch.object(topic, "lookup", side_effect=OSError("disk gone")), \
                redirect_stderr(io.StringIO()) as err:
            self.assertEqual(topic.main(["EDI"]), 1)
        self.assertTrue(err.getvalue().startswith("SYSTEM ERROR: topic.py: lookup failed"))


class ParseTest(unittest.TestCase):
    def test_frontmatter_forms(self):
        text = "---\r\ntopic:\r\n  - 'EDI'\r\n  - AI\r\ntags: [x]\r\n- stray\r\n---\r\ntopic: late\r\n"
        self.assertEqual(topic.frontmatter(text), (["EDI", "AI"], ""))
        self.assertEqual(topic.frontmatter('---\ntopic: [ "a", b ,, ]\nstatus: "draft"\n---\n'),
                         (["a", "b"], "draft"))
        self.assertEqual(topic.frontmatter("no frontmatter\ntopic: x\n"), ([], ""))
        self.assertEqual(topic.frontmatter("---\ntopic: x\nstatus: review\n# never closed\n"),
                         ([], ""))

    def test_frontmatter_yaml(self):
        fm = topic.frontmatter
        self.assertEqual(fm("﻿---\ntopic: EDI\nstatus: draft\n---\n"), (["EDI"], "draft"))
        self.assertEqual(fm("---\ntopic: EDI\n...\nbody\n"), (["EDI"], ""))
        self.assertEqual(fm("---\ntopic: 'customer''s EDI'\n---\n"), (["customer's EDI"], ""))
        self.assertEqual(fm('---\ntopic: "a \\"b\\" c\\\\d"\n---\n'), (['a "b" c\\d'], ""))
        self.assertEqual(fm('---\ntopic: ["Supply Chain, EU", EDI, \'it\'\'s, ok\', "q\\", x"]\n---\n'),
                         (["Supply Chain, EU", "EDI", "it's, ok", 'q", x'], ""))
        self.assertEqual(fm("---\ntopic: [[[A]], \"[[x/B|b]]\"] # c\nstatus: 'it''s #1' #c\n---\n"),
                         (["A", "b"], "it's #1"))

    def test_suggest(self):
        known = [("AI", 5), ("Context Engineering", 4), ("EDI", 2), ("Engine", 1), ("Prompt Engineering", 1)]
        self.assertEqual(topic.suggest("engineering", known),
                         [("Prompt Engineering", 1), ("Context Engineering", 4), ("Engine", 1)])
        self.assertEqual(topic.suggest("zzz", known), [])

    def test_parse_args(self):
        self.assertEqual(topic.parse_args(["ai tooling"]), ["ai", "tooling"])
        self.assertEqual(topic.parse_args(["Supply Chain, EDI,"]), ["Supply Chain", "EDI"])
        self.assertEqual(topic.parse_args(["--help"]), None)

    def test_vocabulary_spelling(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, value in [("a", "edi"), ("b", "EDI"), ("c", "EDI"), ("d", "[ai, AI]")]:
                Path(tmp, f"{name}.md").write_text(f"---\ntopic: {value}\n---\n", encoding="utf-8")
            self.assertEqual(topic.vocabulary(list(topic.scan(Path(tmp), []))), [("AI", 1), ("EDI", 3)])


if __name__ == "__main__":
    unittest.main()
