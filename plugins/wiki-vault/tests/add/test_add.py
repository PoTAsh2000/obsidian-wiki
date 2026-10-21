"""Tests for skills/add/scripts/status.py and add.py with a temp HOME."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "add" / "scripts"
STATUS = SCRIPTS / "status.py"
ADD = SCRIPTS / "add.py"


class AddTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.config = self.home / ".claude" / "obsidian-wiki" / "vault-path"
        self.vault = self.tmp / "My Vault"
        (self.vault / ".obsidian").mkdir(parents=True)
        (self.vault / "CLAUDE.md").write_text("rules\n", encoding="utf-8")

    def run_script(self, script, *args, home=True, cwd=None):
        env = dict(os.environ)
        env.pop("HOME", None)
        if home:
            env["HOME"] = str(self.home)
            # Obsidian's registry is looked up under the temp home, never the real one.
            env["APPDATA"] = str(self.home / "AppData" / "Roaming")
            env["XDG_CONFIG_HOME"] = str(self.home / ".config")
        # cwd outside any vault unless a test says otherwise: status.py looks there.
        return subprocess.run([sys.executable, str(script), *args], env=env, cwd=cwd or self.tmp,
                              capture_output=True, text=True, encoding="utf-8")

    def check(self, result, code, stdout="", stderr=""):
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertEqual(result.stdout.rstrip("\n"), stdout)
        self.assertIn(stderr, result.stderr)

    def make_config(self, content):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_bytes(content)

    def stored(self):
        return self.config.read_text(encoding="utf-8").rstrip("\n")


class StatusTest(AddTestBase):
    def test_help(self):
        full = self.run_script(STATUS, "--help")
        self.check(self.run_script(STATUS, "-h"), 0, full.stdout.rstrip("\n"))
        self.assertTrue(full.stdout.startswith("usage:"))

    def test_none(self):
        self.check(self.run_script(STATUS), 0, "configured: none")

    def test_empty_file(self):
        self.make_config(b"")
        self.check(self.run_script(STATUS), 0, "configured: none")

    def test_set(self):
        posix = self.vault.as_posix()
        self.make_config(posix.encode() + b"\r\n")
        self.check(self.run_script(STATUS), 0, f"reply: Vault is already configured: {posix}. "
                   "Use /wiki-vault:overwrite to change it.")

    def test_set_but_broken(self):
        posix = self.vault.as_posix()
        gone = (self.tmp / "gone").as_posix()
        note = (self.vault / "CLAUDE.md").as_posix()
        fix = "Use /wiki-vault:overwrite to point to the new location."
        cases = ((gone, "that folder no longer exists"),
                 (note, "that folder no longer exists"),
                 ((self.vault / ".obsidian").as_posix(), "that folder has no CLAUDE.md"))
        for stored, why in cases:
            with self.subTest(stored=stored):
                self.make_config(stored.encode() + b"\n")
                self.check(self.run_script(STATUS), 0,
                           f"reply: Vault is configured as {stored}, but {why}. {fix}")
        self.assertTrue(Path(note).is_file())

    def write_registry(self, text):
        sub = {"win32": "AppData/Roaming", "darwin": "Library/Application Support"}
        folder = self.home / sub.get(sys.platform, ".config") / "obsidian"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "obsidian.json").write_text(text, encoding="utf-8")
        return folder / "obsidian.json"

    def test_candidates_from_obsidian_registry(self):
        plain = self.tmp / "Plain"
        plain.mkdir()
        vaults = {"a": {"path": str(self.vault) + os.sep, "open": True},
                  "b": {"path": plain.as_posix()},
                  "c": {"path": (self.tmp / "gone").as_posix()},
                  "d": {"path": self.vault.as_posix()},
                  "e": {"path": "relative/vault"},
                  "f": {"ts": 1}}
        registry = self.write_registry(json.dumps({"vaults": vaults}))
        before = registry.read_bytes()
        self.check(self.run_script(STATUS), 0, "\n".join([
            "configured: none",
            f"candidate: {self.vault.as_posix()} (has CLAUDE.md)",
            f"candidate: {plain.as_posix()}"]))
        self.assertEqual(registry.read_bytes(), before)

    def test_current_folder_vault_first(self):
        notes = self.vault / "notes"
        notes.mkdir()
        other = self.tmp / "Other"
        (other / ".obsidian").mkdir(parents=True)
        self.write_registry(json.dumps({"vaults": {"a": {"path": other.as_posix()},
                                                   "b": {"path": self.vault.as_posix()}}}))
        posix = Path(os.path.realpath(self.vault)).as_posix()
        self.check(self.run_script(STATUS, cwd=notes), 0, "\n".join([
            "configured: none",
            f"candidate: {posix} (current folder) (has CLAUDE.md)",
            f"candidate: {other.as_posix()}"]))
        self.assertEqual(sorted(p.name for p in notes.iterdir()), [])

    def test_candidates_open_then_recent_first(self):
        names = ("Old", "Plain1", "New", "Open", "Plain2", "Flag")
        for name in names:
            (self.tmp / name).mkdir()
        vaults = {"o": {"path": (self.tmp / "Old").as_posix(), "ts": 100},
                  "p1": {"path": (self.tmp / "Plain1").as_posix()},
                  "n": {"path": (self.tmp / "New").as_posix(), "ts": 300},
                  "x": {"path": (self.tmp / "Open").as_posix(), "ts": 50, "open": True},
                  "p2": {"path": (self.tmp / "Plain2").as_posix(), "ts": "bad"},
                  "f": {"path": (self.tmp / "Flag").as_posix(), "ts": True, "open": "yes"}}
        self.write_registry(json.dumps({"vaults": vaults}))
        order = ("Open", "New", "Old", "Plain1", "Plain2", "Flag")
        self.check(self.run_script(STATUS), 0, "\n".join(
            ["configured: none"] + [f"candidate: {(self.tmp / n).as_posix()}" for n in order]))

    def test_bad_registry_prints_no_candidates(self):
        for text in ("{not json", "[]", '{"vaults": []}', '{"vaults": {"a": "x"}}'):
            with self.subTest(text=text):
                self.write_registry(text)
                self.check(self.run_script(STATUS), 0, "configured: none")

    def test_no_candidates_when_configured(self):
        self.write_registry(json.dumps({"vaults": {"a": {"path": self.vault.as_posix()}}}))
        self.make_config(self.vault.as_posix().encode() + b"\n")
        self.assertNotIn("candidate:", self.run_script(STATUS).stdout)

    def test_usage(self):
        self.check(self.run_script(STATUS, "extra"), 2, stderr="usage:")

    def test_no_home_falls_back_to_os_home(self):
        # Read-only: the real config is only read, never written.
        result = self.run_script(STATUS, home=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith(("configured: none", "reply: ")))

    def test_config_not_a_file(self):
        self.config.mkdir(parents=True)
        self.check(self.run_script(STATUS), 1, stderr="SYSTEM ERROR: status.py: cannot read")


def ok(path, *extra):
    return "\n".join([f"path: {path}", f"reply: Vault configured: {path}", *extra])


class AddTest(AddTestBase):
    def tearDown(self):
        # The vault itself is never touched.
        self.assertEqual(sorted(p.name for p in self.vault.iterdir()), [".obsidian", "CLAUDE.md"])

    def test_help(self):
        full = self.run_script(ADD, "--help")
        self.check(self.run_script(ADD, "-h"), 0, full.stdout.rstrip("\n"))
        self.assertTrue(full.stdout.startswith("usage:"))

    def test_ok_with_spaces_and_backslashes(self):
        posix = self.vault.as_posix()
        result = self.run_script(ADD, posix.replace("/", "\\"))
        self.check(result, 0, ok(posix))
        self.assertEqual(self.stored(), posix)

    def test_trailing_slashes_removed(self):
        posix = self.vault.as_posix()
        self.check(self.run_script(ADD, posix + "//"), 0, ok(posix))
        self.assertEqual(self.stored(), posix)

    def test_no_temp_file_left(self):
        self.run_script(ADD, str(self.vault))
        self.assertEqual([p.name for p in self.config.parent.iterdir()], ["vault-path"])

    def test_already_configured(self):
        posix = self.vault.as_posix()
        self.run_script(ADD, posix)
        other = str(self.tmp / "other")
        again = (f"reply: Vault is already configured: {posix}. "
                 "Use /wiki-vault:overwrite to change it.")
        self.check(self.run_script(ADD, "--force", other), 3, again)
        self.check(self.run_script(ADD, posix), 3, again)
        self.assertEqual(self.stored(), posix)

    def test_empty_file_counts_as_not_configured(self):
        self.make_config(b"")
        posix = self.vault.as_posix()
        self.check(self.run_script(ADD, posix), 0, ok(posix))

    def test_missing_folder(self):
        nope = (self.tmp / "nope").as_posix()
        self.check(self.run_script(ADD, nope), 3,
                   f'ask: Folder not found: {nope}. Configure it anyway?\nyes: --force "{nope}"')
        self.assertFalse(self.config.exists())
        self.check(self.run_script(ADD, "--force", nope), 0, ok(nope))
        self.assertEqual(self.stored(), nope)

    def test_force_after_path(self):
        nope = (self.tmp / "nope").as_posix()
        self.check(self.run_script(ADD, nope, "--force"), 0, ok(nope))
        self.assertEqual(self.stored(), nope)

    def test_usage_errors_write_nothing(self):
        vault = str(self.vault)
        cases = [
            ((), "SYSTEM ERROR: usage: add.py [--force] <vault-path>"),
            (("a", "b"), "SYSTEM ERROR: usage: add.py [--force] <vault-path>"),
            (("--allow-missing", vault), "SYSTEM ERROR: add.py: unknown option '--allow-missing', see --help"),
            (("--", vault), "unknown option '--'"),
            (("-x", vault), "unknown option '-x'"),
        ]
        for args, message in cases:
            with self.subTest(args=args):
                self.check(self.run_script(ADD, *args), 2, stderr=message)
        self.assertFalse((self.home / ".claude").exists())

    def test_bad_paths_write_nothing(self):
        vault = str(self.vault)
        cases = [
            ("", "reply: Vault path is empty"),
            (vault + "\nx", "reply: Vault path contains a line break"),
            ("relative/vault", "reply: Vault path is not absolute: relative/vault"),
            ("~user/vault", "reply: Vault path is not absolute: ~user/vault"),
        ]
        for arg, message in cases:
            with self.subTest(arg=arg):
                self.check(self.run_script(ADD, "--force", arg), 3, message)
        self.assertFalse((self.home / ".claude").exists())

    def test_unsafe_paths_write_nothing(self):
        vault = self.vault.as_posix()
        cases = [
            (vault + "\tx", "reply: Vault path contains a control character"),
            (vault + "\x1fx", "reply: Vault path contains a control character"),
            (vault + '/a"b', "reply: Vault path contains a character a folder name cannot have: \""),
            (vault + "/a?b|c", "reply: Vault path contains a character a folder name cannot have: ?|"),
            (vault + "/CON", "reply: Vault path has a part Windows reserves: CON"),
            (vault + "/com1.txt/x", "reply: Vault path has a part Windows reserves: com1.txt"),
            (vault + "/x./y", "reply: Vault path has a part that ends in a dot or space: x."),
            (vault + "/x /y", "reply: Vault path has a part that ends in a dot or space: x "),
        ]
        for arg, message in cases:
            with self.subTest(arg=arg):
                self.check(self.run_script(ADD, "--force", arg), 3, message)
        self.assertFalse((self.home / ".claude").exists())

    def test_nfd_spelling_of_claude_dir_refused(self):
        self.home = self.tmp / "Caf\u00e9"
        (self.home / ".claude").mkdir(parents=True)
        self.config = self.home / ".claude" / "obsidian-wiki" / "vault-path"
        typed = (self.tmp / "CAFE\u0301" / ".claude").as_posix()
        result = self.run_script(ADD, "--force", typed)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("reply: Not a vault folder: ", result.stdout)
        self.assertFalse(self.config.exists())

    def test_path_stored_nfc(self):
        nfd = (self.tmp / "Cafe\u0301").as_posix()
        nfc = (self.tmp / "Caf\u00e9").as_posix()
        self.check(self.run_script(ADD, "--force", nfd), 0, ok(nfc))
        self.assertEqual(self.stored(), nfc)

    def test_missing_parent_refused_even_with_force(self):
        parent = (self.tmp / "gone").as_posix()
        for args in ((parent + "/Vault",), ("--force", parent + "/Vault")):
            with self.subTest(args=args):
                self.check(self.run_script(ADD, *args), 3, f"reply: Parent folder not found: {parent}")
        note = (self.vault / "CLAUDE.md").as_posix()
        self.check(self.run_script(ADD, "--force", note + "/x"), 3,
                   f"reply: Parent folder not found: {note}")
        self.assertFalse(self.config.exists())

    def test_vault_system_folder_refused_even_with_force(self):
        root = self.vault.as_posix()
        plugins = self.vault / ".obsidian" / "plugins"
        plugins.mkdir()
        (self.vault / ".trash").mkdir()
        for sub in (".obsidian", ".obsidian/plugins", ".trash", ".obsidian/missing"):
            path = f"{root}/{sub}"
            for args in ((path,), ("--force", path)):
                with self.subTest(args=args):
                    self.check(self.run_script(ADD, *args), 3,
                               f"reply: Not a vault folder: {path}. Use {root} instead.")
        self.assertFalse(self.config.exists())
        plugins.rmdir()
        (self.vault / ".trash").rmdir()

    def test_subfolder_of_vault(self):
        inbox = self.vault / "01. Inbox"
        inbox.mkdir()
        sub, root = inbox.as_posix(), self.vault.resolve().as_posix()
        self.check(self.run_script(ADD, sub), 3,
                   f"ask: {sub} is inside the vault {root}. Use {root} instead?\n"
                   f'yes: "{root}"\nno: --force "{sub}"')
        self.assertFalse(self.config.exists())
        self.check(self.run_script(ADD, "--force", sub), 0,
                   ok(sub, f"warning: no CLAUDE.md in {sub}"))
        inbox.rmdir()

    def test_plain_folder_warns(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        posix = plain.as_posix()
        self.check(self.run_script(ADD, posix), 0,
                   ok(posix, f"warning: no .obsidian folder in {posix}",
                      f"warning: no CLAUDE.md in {posix}"))
        self.assertEqual(self.stored(), posix)

    def test_parent_of_one_vault(self):
        posix, sub = self.tmp.as_posix(), self.vault.as_posix()
        self.check(self.run_script(ADD, posix), 3,
                   f"ask: {posix} has no .obsidian, but its subfolder {sub} is a vault. "
                   f'Use {sub} instead?\nyes: "{sub}"\nno: --force "{posix}"')
        self.assertFalse(self.config.exists())
        self.check(self.run_script(ADD, "--force", posix), 0,
                   ok(posix, f"warning: no CLAUDE.md in {posix}"))

    def test_parent_of_several_vaults_warns(self):
        (self.tmp / "B Vault" / ".obsidian").mkdir(parents=True)
        posix = self.tmp.as_posix()
        self.check(self.run_script(ADD, posix), 0,
                   ok(posix, f"warning: no .obsidian folder in {posix}; "
                             "its subfolders B Vault, My Vault are vaults",
                      f"warning: no CLAUDE.md in {posix}"))

    def test_read_only_folder_warns(self):
        os.chmod(self.vault, 0o555)
        self.addCleanup(os.chmod, self.vault, 0o755)
        if os.access(self.vault, os.W_OK):
            self.skipTest("folder stays writable here (Windows or root)")
        posix = self.vault.as_posix()
        self.check(self.run_script(ADD, posix), 0,
                   ok(posix, f"warning: {posix} is not writable; "
                             "the skills that write notes will fail"))
        self.assertEqual(self.stored(), posix)

    def test_claude_dir_refused_even_with_force(self):
        claude = self.home / ".claude"
        cache = claude / "plugins" / "cache" / "x"
        cache.mkdir(parents=True)
        win = str(cache).replace("/", "\\")
        for arg in (str(claude), cache.as_posix().upper(), win + "\\", str(SCRIPTS.parents[1])):
            with self.subTest(arg=arg):
                result = self.run_script(ADD, "--force", arg)
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertIn("reply: Not a vault folder: ", result.stdout)
        self.assertFalse(self.config.exists())

    def test_tilde_expands_to_home(self):
        vault = self.home / "Vault"
        (vault / ".obsidian").mkdir(parents=True)
        (vault / "CLAUDE.md").write_text("rules\n", encoding="utf-8")
        for arg in ("~/Vault", "~\\Vault\\"):
            with self.subTest(arg=arg):
                self.config.unlink(missing_ok=True)
                self.check(self.run_script(ADD, arg), 0, ok(vault.as_posix()))
                self.assertEqual(self.stored(), vault.as_posix())

    def test_git_bash_path_stored_native(self):
        if sys.platform != "win32":
            self.skipTest("Git Bash drive paths only on Windows")
        nope = (self.tmp / "nope").as_posix()
        typed = "/" + nope[0].lower() + nope[2:]
        self.check(self.run_script(ADD, "--force", typed), 0, ok(nope))
        self.assertEqual(self.stored(), nope)

    def test_wsl_mount_path_refused_on_windows(self):
        if sys.platform != "win32":
            self.skipTest("WSL paths only on Windows")
        for typed in ("/mnt/wsl/Vault", "/mnt"):
            with self.subTest(typed=typed):
                self.check(self.run_script(ADD, "--force", typed), 3,
                           f"reply: Not a Windows path: {typed}. "
                           "Use the Windows form, like C:/Users/...")
        self.assertFalse(self.config.exists())

    def test_network_share_notice(self):
        posix = self.vault.as_posix()
        if sys.platform != "win32" or not re.match(r"[A-Z]:/", posix):
            self.skipTest("Windows admin shares only")
        share = f"//localhost/{posix[0]}$" + posix[2:]
        if not Path(share).is_dir():
            self.skipTest("admin share not reachable")
        result = self.run_script(ADD, share.replace("/", "\\"))
        self.assertEqual(result.returncode, 0, result.stderr)
        stored = self.stored()
        self.assertTrue(stored.lower().startswith("//localhost/"), stored)
        self.assertIn(f"notice: {stored} is a network share; the skills may be slow "
                      "or fail when it is offline", result.stdout)

    def test_drive_letter_upper_case(self):
        if sys.platform != "win32":
            self.skipTest("Windows drive letters only")
        posix = self.vault.as_posix()
        self.check(self.run_script(ADD, posix[0].lower() + posix[1:]), 0, ok(posix))

    def test_folder_case_from_disk(self):
        posix = self.vault.as_posix()
        typed = posix[:-len("My Vault")] + "my vault"
        if not Path(typed).is_dir():
            self.skipTest("case-sensitive file system")
        self.check(self.run_script(ADD, typed), 0, ok(posix))

    def test_file_is_not_a_folder_even_with_force(self):
        note = (self.vault / "CLAUDE.md").as_posix()
        for args in ((note,), ("--force", note)):
            with self.subTest(args=args):
                self.check(self.run_script(ADD, *args), 3, f"reply: Not a folder: {note}")
        self.assertFalse(self.config.exists())

    def test_symlink_notice(self):
        link = self.tmp / "link"
        try:
            link.symlink_to(self.vault, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create symlinks here")
        posix = link.as_posix()
        target = Path(os.path.realpath(self.vault)).as_posix()
        self.check(self.run_script(ADD, posix), 0,
                   ok(posix, f"notice: {posix} links to {target}"))
        self.assertEqual(self.stored(), posix)

    def test_junction_notice(self):
        if sys.platform != "win32":
            self.skipTest("Windows junctions only")
        link = self.tmp / "junction"
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(self.vault)],
                              capture_output=True)
        if made.returncode:
            self.skipTest("cannot create junctions here")
        posix = link.as_posix()
        result = self.run_script(ADD, posix)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"notice: {posix} links to ", result.stdout)
        self.assertEqual(self.stored(), posix)

    def test_no_home_needs_no_check(self):
        # Without HOME there is no own check any more: a usage error still comes first.
        self.check(self.run_script(ADD, home=False), 2, stderr="SYSTEM ERROR: usage:")

    def test_config_not_a_file(self):
        self.config.mkdir(parents=True)
        self.check(self.run_script(ADD, str(self.vault)), 1,
                   stderr="SYSTEM ERROR: add.py: cannot read")


if __name__ == "__main__":
    unittest.main()
