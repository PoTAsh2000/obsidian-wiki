#!/usr/bin/env python3
"""usage: overwrite.py [--force] <vault-path>

Replace the vault path in ~/.claude/obsidian-wiki/vault-path, which all
obsidian-wiki skills read. Never touches the vault itself. vault.py cleans
the path first: one pair of surrounding quotes ("..." or '...') goes,
backslashes become slashes and trailing slashes are removed. A leading ~ is
the home folder. On Windows the path is stored as C:/..., also when typed
as /c/..., /mnt/c/... (WSL) or c:/... Then . and .. collapse lexically,
without following symlinks.

arguments:
  <vault-path>  absolute path to the vault root, like C:/Notes/Vault, /home/you/Vault or ~/Vault
options:
  --force       save even when the folder does not exist (never for a file,
                a drive root, the home folder or a path inside ~/.claude)
  -h, --help    show this help

output (exit 0):
  path: <saved path>
  old: <previous path, or none>
  reply: <line to show the user as is>
         Vault configured: <path>[ (was: <old>)], or Vault unchanged: <path>
         when the stored path is already the same folder, also through a
         symlink or junction (file left alone), plus a note when the path is
         a link, a warning when the folder has no CLAUDE.md or no .obsidian
         folder or lives inside WSL, and a hint when a parent folder (or the
         only child folder) looks like the vault root

output (exit 3), on stderr:
  USER ERROR: <problem>
  ask: <question to ask the user as is>
  on-yes: <path>  (only for folder not found, when the parent holds exactly
         one folder with a near-matching name: yes means run again with this
         path, anyway means run again with --force)
  on-no: <reply when the user says no>  (only for folder not found: a yes
         means run again with --force, unless there is an on-yes: line)
  The ask also says so when the parent folder is missing too.

exit codes:
  0  saved, or unchanged when the path was already the same
  1  system error (cannot read, create or write the config file)
  2  bad usage (wrong arguments)
  3  user error (path empty, not absolute or with a line break, not a folder,
     a drive root or the home folder, inside ~/.claude, or folder not found
     without --force)

example: overwrite.py "D:/Obsidian/MyVault"
"""

import difflib
import os
import re
import stat
import sys
import unicodedata
from pathlib import Path

# vault.py lives in the plugin's scripts folder: plugins/wiki-vault/scripts.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import VaultError, clean_path, config_file, stored_path, to_native  # noqa: E402

USAGE = "usage: overwrite.py [--force] <vault-path>"
NO_RULES = (" Warning: this folder has no CLAUDE.md yet; "
            "the wiki skills stop until you add one.")
NO_OBSIDIAN = " Warning: no .obsidian folder, this may not be an Obsidian vault."
IN_WSL = (" Warning: this vault is inside a WSL filesystem; "
          "Git Bash tools may be slow or fail there.")
ASK_PATH = "{0}. Which absolute path to the vault root folder should I use instead?"
ON_NO = "Run /wiki-vault:overwrite later when you are ready to configure the vault."


class Fail(Exception):
    """Stop with an error line on stderr and an exit code.
    A user error (3) adds an ask: line and, when given, on-yes: and on-no: lines."""

    def __init__(self, code, message, ask=None, on_no=None, on_yes=None):
        if code == 3:
            problem = message.removeprefix("USER ERROR: ")
            ask = ask or ASK_PATH.format(problem[0].upper() + problem[1:])
            message += f"\nask: {ask}" + (f"\non-yes: {on_yes}" if on_yes else "")
            message += f"\non-no: {on_no}" if on_no else ""
        super().__init__(message)
        self.code = code


def parse_args(argv):
    """Return (force, path). Options may come before or after the path."""
    force = False
    args = []
    for arg in argv:
        if arg in ("-h", "--help"):
            print(__doc__.strip())
            raise SystemExit(0)
        if arg == "--force":
            force = True
        elif arg.startswith("-"):
            raise Fail(2, f"SYSTEM ERROR: overwrite.py: unknown option '{arg}', see --help")
        else:
            args.append(arg)
    if len(args) != 1:
        raise Fail(2, f"SYSTEM ERROR: {USAGE}")
    return force, args[0]


def check(raw, force):
    """Return the path in native form, or raise Fail when it cannot be saved."""
    config = config_file()
    try:
        path = clean_path(raw)
    except VaultError as err:
        raise Fail(3, f"USER ERROR: {err}")
    # Lexical only: . and .. collapse without following symlinks.
    path = os.path.normpath(path).replace("\\", "/")
    folder = Path(path)
    if folder.exists() and not folder.is_dir():
        raise Fail(3, f"USER ERROR: not a folder: {path}")
    # A vault inside ~/.claude would put notes into plugin files or Claude config.
    claude = same_key(config.parents[1].resolve().as_posix())
    resolved = folder.resolve()
    key = same_key(resolved.as_posix())
    if key == claude or key.startswith(claude.rstrip("/") + "/"):
        raise Fail(3, f"USER ERROR: vault path is inside the Claude config folder: {path}")
    # A root or home vault would make the other skills walk and edit the whole disk.
    if resolved.parent == resolved or key == same_key(config.parents[2].resolve().as_posix()):
        raise Fail(3, f"USER ERROR: vault path is a drive root or your home folder: {path}")
    if not force and not folder.is_dir():
        not_found(path, folder)
    return path


def not_found(path, folder):
    """Raise folder not found, naming a near-miss sibling or a missing parent."""
    ask, on_yes = f"The folder {path} does not exist. Configure it anyway?", None
    parent = folder.parent
    if not parent.is_dir():
        ask = (f"The folder {path} does not exist, and neither does {parent.as_posix()} "
               "(wrong drive letter or a share that is not mounted?). Configure it anyway? "
               "Every wiki skill will stop until it exists.")
    else:
        try:
            names = {c.name.casefold(): c.name for c in parent.iterdir() if c.is_dir()}
        except OSError:
            names = {}
        # Two close matches are a guess, not a typo: then suggest nothing.
        close = difflib.get_close_matches(folder.name.casefold(), names, n=2, cutoff=0.8)
        if len(close) == 1:
            on_yes = (parent / names[close[0]]).as_posix()
            ask = (f"The folder {path} does not exist. Did you mean {on_yes}? Answer yes "
                   f"to use it, anyway to configure {path} anyway, or no to stop.")
    raise Fail(3, f"USER ERROR: folder not found: {path}", ask=ask, on_no=ON_NO, on_yes=on_yes)


def read_old(config):
    """The currently stored path, or an empty string when there is none."""
    try:
        return stored_path(config)
    except (OSError, UnicodeDecodeError) as err:
        raise Fail(1, f"SYSTEM ERROR: overwrite.py: cannot read {config}: {err}")


def same_key(path):
    """Compare key: native form; on Windows also case-folded and NFC-normalized."""
    native = to_native(path)
    if sys.platform == "win32":
        return unicodedata.normalize("NFC", native).casefold()
    return native


def same_folder(a, b):
    """True when both exist and are the same directory (device and inode).
    Inode 0 (FAT, exFAT, some network shares) proves nothing, so then False."""
    try:
        sa, sb = os.stat(a), os.stat(b)
    except OSError:
        return False
    return sa.st_ino != 0 and (sa.st_dev, sa.st_ino) == (sb.st_dev, sb.st_ino)


def link_target(path):
    """Where the path points when it is itself a symlink or Windows junction."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    junction = getattr(st, "st_reparse_tag", 0) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)
    if not (stat.S_ISLNK(st.st_mode) or junction):
        return None
    return to_native(Path(os.path.realpath(path)).as_posix())


def vault_root(folder):
    """Closest parent folder with a CLAUDE.md or a .obsidian folder, or None."""
    for parent in folder.parents:
        if (parent / "CLAUDE.md").is_file() or (parent / ".obsidian").is_dir():
            return parent.as_posix()
    return None


def vault_child(folder):
    """The only direct child folder with a CLAUDE.md or a .obsidian folder, or None."""
    try:
        found = [c for c in folder.iterdir() if c.is_dir() and
                 ((c / "CLAUDE.md").is_file() or (c / ".obsidian").is_dir())]
    except OSError:
        return None
    return found[0].as_posix() if len(found) == 1 else None


def notes(path, typed):
    """Note on the typed path, then warnings and hint on the saved one."""
    folder = Path(path)
    text = ""
    target = link_target(typed)
    if target:
        text += f" Note: {typed} points to {target}."
    if re.match(r"//wsl(\$|\.localhost)/", path, re.IGNORECASE):
        text += IN_WSL
    rules = (folder / "CLAUDE.md").is_file()
    if not rules:
        text += NO_RULES
    root = None if rules else vault_root(folder)
    if root:
        text += (f" This looks like a subfolder of {root}; "
                 f'run /wiki-vault:overwrite "{root}" to use the vault root.')
    elif folder.is_dir() and not (folder / ".obsidian").is_dir():
        child = None if rules else vault_child(folder)
        text += (f" The vault looks like {child}; "
                 f'run /wiki-vault:overwrite "{child}" to use it.') if child else NO_OBSIDIAN
    return text


def save(config, path):
    """Write the path atomically through a temp file next to the config."""
    try:
        config.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise Fail(1, f"SYSTEM ERROR: overwrite.py: cannot create {config.parent}")
    tmp = config.with_name(f"{config.name}.tmp.{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(path + "\n")
        os.replace(tmp, config)
    except OSError:
        tmp.unlink(missing_ok=True)  # allow-delete: temp file of a failed atomic write
        raise Fail(1, f"SYSTEM ERROR: overwrite.py: cannot write {config}")


def main(argv):
    # UTF-8 and LF output on every OS: Windows pipes default to cp1252 and CRLF.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    try:
        force, raw = parse_args(argv)
        path = typed = check(raw, force)
        config = config_file()
        old = read_old(config)
        if old and (same_key(old) == same_key(path) or same_folder(to_native(old), path)):
            path = old
            reply = f"Vault unchanged: {path}"
        else:
            save(config, path)
            reply = f"Vault configured: {path}" + (f" (was: {old})" if old else "")
    except Fail as err:
        print(err, file=sys.stderr)
        return err.code
    reply += notes(to_native(path), typed)
    print(f"path: {path}")
    print(f"old: {old or 'none'}")
    print(f"reply: {reply}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
