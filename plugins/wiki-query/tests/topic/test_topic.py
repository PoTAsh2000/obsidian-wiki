"""Tests for skills/topic/scripts/topic.py with a temp HOME and a copy of the fixture vault.

Also covers the vault.py call that the topic skill injects for the vault CLAUDE.md.
"""

import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
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
        self.addCleanup(shutil.rmtree, self.tmp, True)
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

    def run_script(self, script, *args):
        env = dict(os.environ, HOME=str(self.home))
        done = subprocess.run([sys.executable, str(script), *args], env=env,
                              capture_output=True, text=True, encoding="utf-8")
        return done.returncode, done.stdout.rstrip("\n"), done.stderr

    def check(self, want_code, want_out, *args, script=TOPIC):
        code, out, err = self.run_script(script, *args)
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

    def test_nothing(self):
        self.check(0, "Nothing found.", "missing")

    def test_skips_dot_attachment_and_template_folders(self):
        self.check(0, "AI:\n- 30. Knowledge/Context Engineering.md\n- 30. Knowledge/Playbook.md\n"
                      "- 30. Knowledge/Tokens.md\n- 30. Knowledge/Window Size.md\n"
                      "- 99. Archived/Old Context.md", "AI")

    def test_no_topic(self):
        self.check(0, "ERROR: no topic given")

    def test_no_topic_inject(self):
        self.check(0, "ERROR: no topic given", "--inject")

    def test_inject_found(self):
        self.check(0, EXPECTED, "--inject", "EDI")

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
        self.conf.unlink()
        self.check(0, f"ERROR: {MISSING}", script=VAULT_PY)

    # usage errors

    def test_bad_option(self):
        err = self.check(2, "", "--color")
        self.assertTrue(err.startswith("SYSTEM ERROR: topic.py: unknown option: --color"), err)

    def test_rules_option_gone(self):
        err = self.check(2, "", "--rules", "EDI")
        self.assertTrue(err.startswith("SYSTEM ERROR: topic.py: unknown option: --rules"), err)

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

    # user errors

    def test_no_config(self):
        self.conf.unlink()
        err = self.check(3, "", "EDI")
        self.assertEqual(err, f"USER ERROR: {MISSING}\n")

    def test_empty_config(self):
        self.set_conf("")
        err = self.check(3, "", "EDI")
        self.assertTrue(err.startswith("USER ERROR: Vault path is missing."), err)

    def test_no_folder(self):
        self.set_conf(str(self.tmp / "nope"))
        err = self.check(3, "", "EDI")
        self.assertTrue(err.startswith("USER ERROR: The configured vault folder has no CLAUDE.md"), err)

    def test_no_claude_md(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        self.set_conf(str(bare))
        err = self.check(3, "", "EDI")
        self.assertTrue(err.startswith("USER ERROR: The configured vault folder has no CLAUDE.md"), err)
        self.check(0, f"ERROR: The configured vault folder has no CLAUDE.md: {bare}. "
                      "Use /wiki-vault:overwrite <vault path> to fix the vault path.",
                   "--inject", "EDI")

    def test_no_config_inject(self):
        self.conf.unlink()
        self.check(0, f"ERROR: {MISSING}", "--inject", "EDI")

    # system error

    def test_lookup_fails(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}), \
                mock.patch.object(topic, "lookup", side_effect=OSError("disk gone")), \
                redirect_stderr(io.StringIO()) as err:
            self.assertEqual(topic.main(["EDI"]), 1)
        self.assertTrue(err.getvalue().startswith("SYSTEM ERROR: topic.py: lookup failed"))


class ParseTest(unittest.TestCase):
    def test_frontmatter_forms(self):
        text = "---\r\ntopic:\r\n  - 'EDI'\r\n  - AI\r\ntags: [x]\r\n- stray\r\n---\r\ntopic: late\r\n"
        self.assertEqual(topic.topics_of(text), ["EDI", "AI"])
        self.assertEqual(topic.topics_of('---\ntopic: [ "a", b ,, ]\n---\n'), ["a", "b"])
        self.assertEqual(topic.topics_of("no frontmatter\ntopic: x\n"), [])


if __name__ == "__main__":
    unittest.main()
