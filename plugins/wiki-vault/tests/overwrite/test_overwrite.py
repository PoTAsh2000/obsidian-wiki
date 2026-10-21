"""Tests for skills/overwrite/scripts/overwrite.py. Uses a temp HOME only."""

import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WARN = (" Warning: this folder has no CLAUDE.md yet; "
        "the wiki skills stop until you add one.")
NO_OBSIDIAN = " Warning: no .obsidian folder, this may not be an Obsidian vault."
SCRIPT = Path(__file__).resolve().parents[2] / "skills" / "overwrite" / "scripts" / "overwrite.py"


class OverwriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vault = (self.tmp / "My Vault").as_posix()
        self.other = (self.tmp / "Other").as_posix()
        self.nope = (self.tmp / "nope").as_posix()
        os.mkdir(self.vault)
        os.mkdir(self.other)
        for folder in (self.vault, self.other):
            Path(folder, "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
            os.mkdir(Path(folder, ".obsidian"))
        self.home = self.tmp / "home"
        self.cfg = self.home / ".claude" / "obsidian-wiki" / "vault-path"

    def run_script(self, *args, home=None):
        env = dict(os.environ, HOME=str(home or self.home))
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env,
                              capture_output=True, text=True, encoding="utf-8")

    def assertRun(self, args, code, stdout, home=None):
        res = self.run_script(*args, home=home)
        self.assertEqual(res.returncode, code, res.stderr)
        self.assertEqual(res.stdout, stdout)
        return res

    def out(self, path, old=None, reply=None, warn=False, extra=""):
        if reply is None:
            reply = f"Vault configured: {path}" + (f" (was: {old})" if old else "")
        if warn:
            reply += WARN
        reply += extra
        return f"path: {path}\nold: {old or 'none'}\nreply: {reply}\n"

    def assertConfig(self, want):
        got = self.cfg.read_text(encoding="utf-8") if self.cfg.is_file() else None
        self.assertEqual(got, None if want is None else want + "\n")

    def test_help(self):
        long = self.run_script("--help")
        self.assertEqual(long.returncode, 0)
        self.assertTrue(long.stdout.startswith("usage: overwrite.py"))
        self.assertRun(["-h"], 0, long.stdout)

    def test_bad_usage_writes_nothing(self):
        res = self.assertRun([], 2, "")
        self.assertIn("SYSTEM ERROR:", res.stderr)
        self.assertRun([self.vault, self.other], 2, "")
        self.assertRun(["--nope", self.vault], 2, "")
        self.assertConfig(None)

    def test_user_errors_write_nothing(self):
        res = self.assertRun(["some/folder"], 3, "")
        self.assertIn("USER ERROR: vault path is not absolute", res.stderr)
        res = self.assertRun([self.nope], 3, "")
        self.assertIn(f"USER ERROR: folder not found: {self.nope}", res.stderr)
        res = self.assertRun(["/a\nb"], 3, "")
        self.assertIn("USER ERROR: vault path contains a line break", res.stderr)
        res = self.assertRun([""], 3, "")
        self.assertIn("USER ERROR: vault path is empty", res.stderr)
        self.assertRun(["   "], 3, "")
        self.assertConfig(None)

    def test_save_sequence(self):
        # first save, no old path, config folder created
        self.assertRun([self.vault], 0, self.out(self.vault))
        self.assertConfig(self.vault)
        # overwrite shows the old path
        self.assertRun([self.other], 0, self.out(self.other, self.vault))
        self.assertConfig(self.other)
        # same path: unchanged, file left alone
        mtime = self.cfg.stat().st_mtime_ns
        self.assertRun([self.other + "/"], 0,
                       self.out(self.other, self.other, f"Vault unchanged: {self.other}"))
        self.assertEqual(self.cfg.stat().st_mtime_ns, mtime)
        # backslashes and trailing slashes normalized, warning without CLAUDE.md
        self.assertRun(["--force", "C:\\Users\\you\\Vault\\"], 0,
                       self.out("C:/Users/you/Vault", self.other, warn=True))
        self.assertConfig("C:/Users/you/Vault")
        # missing folder with --force is saved, option after the path works too
        self.assertRun([self.nope, "--force"], 0,
                       self.out(self.nope, "C:/Users/you/Vault", warn=True))
        self.assertConfig(self.nope)
        # missing folder without --force keeps the old path
        self.assertRun([self.nope + "2"], 3, "")
        self.assertConfig(self.nope)
        # no temp files left behind
        self.assertEqual([p.name for p in self.cfg.parent.iterdir()], ["vault-path"])

    def test_refuses_root_and_home(self):
        self.home.mkdir()
        roots = ["/", "//", self.home.as_posix(), self.home.as_posix() + "/"]
        if sys.platform == "win32":
            roots += ["C:/", "c:\\", "/c/", "/mnt/c", "Z:/"]
        for root in roots:
            for args in ([root], ["--force", root]):
                res = self.assertRun(args, 3, "")
                self.assertIn("USER ERROR: vault path is a drive root or your home folder",
                              res.stderr, root)
        self.assertConfig(None)
        # a folder inside home is fine
        inside = (self.home / "Vault").as_posix()
        self.assertRun(["--force", inside], 0, self.out(inside, warn=True))

    def test_user_errors_print_question(self):
        res = self.assertRun([self.nope], 3, "")
        self.assertEqual(res.stderr, f"USER ERROR: folder not found: {self.nope}\n"
                         f"ask: The folder {self.nope} does not exist. Configure it anyway?\n"
                         "on-no: Run /wiki-vault:overwrite later when you are ready "
                         "to configure the vault.\n")
        res = self.assertRun(["some/folder"], 3, "")
        self.assertEqual(res.stderr, "USER ERROR: vault path is not absolute: some/folder\n"
                         "ask: Vault path is not absolute: some/folder. Which absolute path "
                         "to the vault root folder should I use instead?\n")

    def ask_line(self, *args):
        res = self.assertRun(list(args), 3, "")
        return [l for l in res.stderr.splitlines() if not l.startswith("on-no: ")]

    def test_not_found_suggests_near_match(self):
        for typed in ("my-vault", "My Vaul", "MY VAULT!"):
            path = (self.tmp / typed).as_posix()
            self.assertEqual(self.ask_line(path), [
                f"USER ERROR: folder not found: {path}",
                f"ask: The folder {path} does not exist. Did you mean {self.vault}? "
                f"Answer yes to use it, anyway to configure {path} anyway, or no to stop.",
                f"on-yes: {self.vault}"], typed)
        self.assertConfig(None)

    def test_not_found_without_match_or_with_several(self):
        os.mkdir(self.tmp / "Notes1")
        os.mkdir(self.tmp / "Notes2")
        for typed in ("nope", "Notes"):
            path = (self.tmp / typed).as_posix()
            self.assertEqual(self.ask_line(path), [
                f"USER ERROR: folder not found: {path}",
                f"ask: The folder {path} does not exist. Configure it anyway?"], typed)

    def test_not_found_with_missing_parent(self):
        path = f"{self.nope}/Vault"
        self.assertEqual(self.ask_line(path), [
            f"USER ERROR: folder not found: {path}",
            f"ask: The folder {path} does not exist, and neither does {self.nope} "
            "(wrong drive letter or a share that is not mounted?). Configure it anyway? "
            "Every wiki skill will stop until it exists."])
        self.assertRun(["--force", path], 0, self.out(path, warn=True))

    def test_wsl_share_warns(self):
        # Limit: //wsl.localhost only; //wsl$ and unreachable shares cost seconds per stat
        typed = "//wsl.localhost/Ubuntu/home/you/Vault"
        res = self.run_script("--force", typed)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(res.stdout.startswith(f"path: {typed}\n"), res.stdout)
        self.assertIn(" Warning: this vault is inside a WSL filesystem; "
                      "Git Bash tools may be slow or fail there.", res.stdout)

    def test_warns_without_obsidian_folder(self):
        os.rmdir(Path(self.vault, ".obsidian"))
        self.assertRun([self.vault], 0, self.out(self.vault, extra=NO_OBSIDIAN))
        self.assertConfig(self.vault)

    def test_hints_vault_root_for_subfolder(self):
        hint = ' This looks like a subfolder of {0}; run /wiki-vault:overwrite "{0}" to use the vault root.'
        inbox = self.vault + "/01. Inbox"
        deep = inbox + "/topic"
        os.makedirs(deep)
        self.assertRun([deep], 0, self.out(deep, warn=True, extra=hint.format(self.vault)))
        self.assertConfig(deep)
        # a .obsidian folder alone also marks the root, the closest one wins
        os.mkdir(Path(inbox, ".obsidian"))
        self.assertRun([deep], 0, self.out(deep, deep, f"Vault unchanged: {deep}",
                                           warn=True, extra=hint.format(inbox)))

    def make_link(self, link, target):
        try:
            os.symlink(target, link, target_is_directory=True)
            return
        except (OSError, NotImplementedError):
            if sys.platform != "win32":
                raise
        res = subprocess.run(["cmd", "/c", "mklink", "/J", str(Path(link)), str(Path(target))],
                             capture_output=True)
        if res.returncode:
            self.skipTest("cannot create a symlink or junction")

    def test_link_alias_is_unchanged(self):
        link = (self.tmp / "Link").as_posix()
        self.make_link(link, self.vault)
        note = f" Note: {link} points to {Path(os.path.realpath(self.vault)).as_posix()}."
        self.assertRun([self.vault], 0, self.out(self.vault))
        mtime = self.cfg.stat().st_mtime_ns
        self.assertRun([link], 0, self.out(self.vault, self.vault,
                                           f"Vault unchanged: {self.vault}", extra=note))
        self.assertEqual(self.cfg.stat().st_mtime_ns, mtime)
        # a link to another folder is saved as typed, with the note
        self.cfg.write_text(self.other + "\n", encoding="utf-8")
        self.assertRun([link], 0, self.out(link, self.other, extra=note))
        self.assertConfig(link)

    def test_warns_without_claude_md(self):
        Path(self.vault, "CLAUDE.md").unlink()
        self.assertRun([self.vault], 0, self.out(self.vault, warn=True))
        self.assertConfig(self.vault)

    def test_file_is_not_a_folder(self):
        note = (self.tmp / "note.md").as_posix()
        Path(note).write_text("x", encoding="utf-8")
        for args in ([note], ["--force", note]):
            res = self.assertRun(args, 3, "")
            self.assertIn(f"USER ERROR: not a folder: {note}", res.stderr)
        self.assertConfig(None)

    def test_refuses_claude_config_folder(self):
        claude = self.home / ".claude"
        (claude / "plugins").mkdir(parents=True)
        for target in (claude, claude / "plugins", claude / "plugins" / "new"):
            res = self.assertRun(["--force", target.as_posix()], 3, "")
            self.assertIn("USER ERROR: vault path is inside the Claude config folder", res.stderr)
        self.assertConfig(None)
        # a sibling name that only starts with .claude is fine
        sibling = (self.home / ".claude-notes").as_posix()
        self.assertRun(["--force", sibling], 0, self.out(sibling, warn=True))

    def test_tilde_expands_to_home(self):
        home = self.home.as_posix()
        self.assertRun(["--force", "~/Vault"], 0, self.out(f"{home}/Vault", warn=True))
        self.assertRun(["--force", "~\\Other\\"], 0,
                       self.out(f"{home}/Other", f"{home}/Vault", warn=True))
        res = self.assertRun(["~user/Vault"], 3, "")
        self.assertIn("not absolute", res.stderr)

    def test_strips_one_pair_of_quotes(self):
        self.assertRun([f'"{self.vault}"'], 0, self.out(self.vault))
        self.assertRun([f"'{self.vault}/'"], 0, self.out(self.vault, self.vault,
                                                         f"Vault unchanged: {self.vault}"))
        res = self.assertRun([f"\"{self.vault}'"], 3, "")
        self.assertIn("not absolute", res.stderr)
        res = self.assertRun([f'""{self.vault}""'], 3, "")
        self.assertIn("not absolute", res.stderr)

    def test_collapses_dot_segments(self):
        self.assertRun([self.vault + "/./x/.."], 0, self.out(self.vault))
        self.assertConfig(self.vault)
        mtime = self.cfg.stat().st_mtime_ns
        self.assertRun([self.other + "/../My Vault/."], 0,
                       self.out(self.vault, self.vault, f"Vault unchanged: {self.vault}"))
        self.assertEqual(self.cfg.stat().st_mtime_ns, mtime)

    def test_hints_only_vault_child_of_parent(self):
        parent = (self.tmp / "parent").as_posix()
        hint = ' The vault looks like {0}; run /wiki-vault:overwrite "{0}" to use it.'
        os.makedirs(parent + "/Vault/.obsidian")
        os.makedirs(parent + "/plain")
        self.assertRun([parent], 0, self.out(parent, warn=True,
                                             extra=hint.format(parent + "/Vault")))
        self.assertConfig(parent)
        # two vault children: no guess, plain .obsidian warning
        os.makedirs(parent + "/Second/.obsidian")
        self.assertRun(["--force", parent + "/"], 0,
                       self.out(parent, parent, f"Vault unchanged: {parent}",
                                warn=True, extra=NO_OBSIDIAN))

    @unittest.skipUnless(sys.platform == "win32", "drive letters exist only on Windows")
    def test_windows_native_form(self):
        rest = self.vault[2:]
        self.assertRun([f"/{self.vault[0].lower()}{rest}"], 0, self.out(self.vault))
        self.assertConfig(self.vault)
        self.assertRun(["--force", "c:/Other/Vault"], 0,
                       self.out("C:/Other/Vault", self.vault, warn=True))
        self.assertConfig("C:/Other/Vault")
        # WSL form /mnt/<drive>/... becomes <DRIVE>:/...
        self.assertRun([f"/mnt/{self.vault[0].lower()}{rest}"], 0,
                       self.out(self.vault, "C:/Other/Vault"))
        self.assertConfig(self.vault)

    @unittest.skipUnless(sys.platform == "win32", "Windows paths are case-insensitive")
    def test_unchanged_windows_forms(self):
        self.cfg.parent.mkdir(parents=True)
        stored = f"/{self.vault[0].lower()}{self.vault[2:].upper()}"
        self.cfg.write_text(stored + "\n", encoding="utf-8")
        self.assertRun([self.vault], 0, self.out(stored, stored, f"Vault unchanged: {stored}"))
        self.assertConfig(stored)

    def test_crlf_old_config(self):
        self.cfg.parent.mkdir(parents=True)
        self.cfg.write_bytes(f"{self.vault}\r\n".encode("utf-8"))
        self.assertRun([self.other], 0, self.out(self.other, self.vault))

    def test_system_error_when_old_config_unreadable(self):
        self.cfg.mkdir(parents=True)
        res = self.assertRun([self.vault], 1, "")
        self.assertIn("SYSTEM ERROR: overwrite.py: cannot read", res.stderr)

    def test_system_error_when_config_folder_blocked(self):
        blocked = self.tmp / "blocked"
        blocked.mkdir()
        (blocked / ".claude").write_text("", encoding="utf-8")
        res = self.assertRun([self.vault], 1, "", home=blocked)
        self.assertIn("SYSTEM ERROR:", res.stderr)

    def test_script_hygiene(self):
        self.assertNotIn(b"\r", SCRIPT.read_bytes())
        py_compile.compile(str(SCRIPT), cfile=str(self.tmp / "overwrite.compiled"), doraise=True)


if __name__ == "__main__":
    unittest.main()
