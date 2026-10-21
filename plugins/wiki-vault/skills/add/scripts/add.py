#!/usr/bin/env python3
"""usage: add.py [--force] <vault-path>

Save the vault path in ~/.claude/obsidian-wiki/vault-path, which all
obsidian-wiki skills read. Only adds: never changes a path that is already
stored. Never touches the vault itself. The path is stored in one canonical
form: a leading ~ becomes the home folder, backslashes become slashes,
trailing slashes go, a Git Bash /c/... becomes C:/... on Windows, the drive
letter is upper case, Unicode is NFC, and an existing folder keeps the case it has on disk.

arguments:
  <vault-path>  absolute path to the vault root, like C:/Notes/Vault or ~/Vault
options:
  --force       save even when the folder does not exist or has no .obsidian
  -h, --help    show this help

output (stdout, the lines after path: are meant for the user):
  path: <saved path>                       exit 0
  reply: Vault configured: <path>          exit 0
  warning: no .obsidian folder in <path>   exit 0, no parent has one either; with
                                           "; its subfolders <a>, <b> are vaults"
                                           when several direct subfolders are
  warning: <path> is not writable; ...     exit 0, os.access says so
  warning: no CLAUDE.md in <path>          exit 0, the other skills will stop
  notice: <path> links to <target>         exit 0, symlink or junction
  notice: <path> is a network share; ...   exit 0, UNC path like //server/share
  reply: <message>                         exit 3, user error, nothing saved
  ask: <question>                          exit 3, nothing saved, followed by
  yes: <arguments>                           the arguments to rerun with on yes
  no: <arguments>                            and on no (no such line: do not rerun)

exit codes:
  0  saved
  1  system error on stderr (cannot read the config, create its folder or write it)
  2  bad usage on stderr (wrong arguments)
  3  user error: path empty, not absolute, with a control character, a
     character or name a Windows folder cannot have (< > : " | ? *, a part
     ending in a dot or space, CON, NUL, COM1 ...), a WSL /mnt/... path that
     is not a drive on Windows, already configured, not a
     vault folder (inside ~/.claude, this plugin, or a vault's .obsidian, .trash
     or .git), not a folder (a file), parent folder not found, and without
     --force folder not found, subfolder of a vault, or a folder
     whose only vault is one direct subfolder

example: add.py "D:/Obsidian/MyVault"
"""

import os
import re
import stat
import sys
import unicodedata
from pathlib import Path

# vault.py lives in the plugin's scripts folder: plugins/wiki-vault/scripts.
# It knows where the config file is and how to read it; writing happens here.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import VaultError, clean_path, config_file, stored_path, to_native  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]

USAGE = "usage: add.py [--force] <vault-path>"

# Names Windows cannot have as a folder, also with an extension (CON.txt).
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"{d}{i}" for d in ("COM", "LPT") for i in range(1, 10))}
# Obsidian's own folders and other non-note folders inside a vault.
SYSTEM_DIRS = {".obsidian", ".trash", ".git"}


class Fail(Exception):
    """Stop with an exit code. Code 3 lines go to stdout for the user, others to stderr."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def parse_args(argv):
    """Return (force, raw path). Options may come before or after the path."""
    force = False
    args = []
    for arg in argv:
        if arg in ("-h", "--help"):
            print(__doc__.strip())
            raise SystemExit(0)
        if arg == "--force":
            force = True
        elif arg.startswith("-"):
            raise Fail(2, f"SYSTEM ERROR: add.py: unknown option '{arg}', see --help")
        else:
            args.append(arg)
    if len(args) != 1:
        raise Fail(2, f"SYSTEM ERROR: {USAGE}")
    return force, args[0]


def expand_home(raw, home):
    """A leading ~ becomes the home folder (the one vault.py takes from HOME)."""
    raw = raw.strip()
    if raw == "~" or raw.startswith(("~/", "~\\")):
        return home.as_posix() + raw[1:]
    return raw


def real_case(path):
    """The path with each part in the case it has on disk. Links are not resolved."""
    p = Path(path)
    cur = Path(p.anchor)
    for name in p.parts[1:]:
        try:
            names = os.listdir(cur)
        except OSError:
            return path
        if name not in names:
            # No single match (like a short name USERNA~1): keep the part as typed.
            match = [n for n in names if n.lower() == name.lower()]
            if len(match) == 1:
                name = match[0]
        cur = cur / name
    return cur.as_posix()


def canonical(raw, home):
    """The one stored form of a typed path, or Fail when it is unusable."""
    try:
        path = to_native(clean_path(expand_home(raw, home)))
    except VaultError as err:
        msg = str(err)
        raise Fail(3, f"reply: {msg[:1].upper()}{msg[1:]}")
    path = unicodedata.normalize("NFC", path)
    if sys.platform == "win32" and re.match(r"/mnt(/|$)", path):
        # to_native turns a WSL /mnt/c/... into C:/...; anything left is not a Windows path.
        raise Fail(3, f"reply: Not a Windows path: {path}. Use the Windows form, like C:/Users/...")
    check_portable(path)
    if re.match(r"[a-z]:/", path):
        path = path[0].upper() + path[1:]
    return real_case(path) if os.path.isdir(path) else path


def check_portable(path):
    """Refuse control characters and names a Windows folder cannot have, on every OS.

    A double quote would also break the quoted rerun line in ask: replies.
    """
    if any(unicodedata.category(c) == "Cc" for c in path):
        raise Fail(3, "reply: Vault path contains a control character")
    rest = path[2:] if re.match(r"[A-Za-z]:/", path) else path
    bad = sorted(set(rest) & set('<>:"|?*'))
    if bad:
        raise Fail(3, f"reply: Vault path contains a character a folder name cannot have: {''.join(bad)}")
    for part in rest.split("/"):
        if part.endswith((".", " ")) and part not in (".", ".."):
            raise Fail(3, f"reply: Vault path has a part that ends in a dot or space: {part}")
        if part.split(".")[0].strip().upper() in RESERVED:
            raise Fail(3, f"reply: Vault path has a part Windows reserves: {part}")


def check_not_configured(config):
    """Refuse when the config file already holds a path."""
    try:
        old = stored_path(config)
    except (OSError, UnicodeDecodeError) as err:
        raise Fail(1, f"SYSTEM ERROR: add.py: cannot read {config.as_posix()}: {err}")
    if old:
        raise Fail(3, f"reply: Vault is already configured: {old}. "
                      "Use /wiki-vault:overwrite to change it.")


def norm(path):
    """Compare form: real path, NFC, case-folded, forward slashes, no trailing slash."""
    real = os.path.realpath(to_native(str(path))).replace("\\", "/").rstrip("/")
    return unicodedata.normalize("NFC", real).casefold()


def check_not_claude_dir(path, config):
    """Refuse ~/.claude, the plugin root and anything inside them, even with --force.

    Skills write notes into the vault; inside a plugin folder an update would delete them.
    """
    target = norm(path)
    for root in (config.parents[1], PLUGIN_ROOT):
        r = norm(root)
        if target == r or target.startswith(r + "/"):
            raise Fail(3, f"reply: Not a vault folder: {path}")


def is_link(folder):
    """Symlink or Windows junction; Python before 3.12 reports a junction as a plain folder."""
    tag = getattr(os.lstat(folder), "st_reparse_tag", 0)
    return folder.is_symlink() or tag == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)


def check_folder(path, force):
    """Refuse a vault system folder, a file and a missing parent always,
    a missing folder or a vault subfolder unless --force.

    Return the warning and notice lines.
    """
    folder = Path(path)
    for p in (folder, *folder.parents):
        if p.name.lower() in SYSTEM_DIRS and (p.parent / ".obsidian").is_dir():
            raise Fail(3, f"reply: Not a vault folder: {path}. Use {p.parent.as_posix()} instead.")
    if folder.exists() and not folder.is_dir():
        raise Fail(3, f"reply: Not a folder: {path}")
    if not folder.parent.is_dir():
        raise Fail(3, f"reply: Parent folder not found: {folder.parent.as_posix()}")
    if not folder.is_dir():
        if not force:
            raise Fail(3, f"ask: Folder not found: {path}. Configure it anyway?\n"
                          f'yes: --force "{path}"')
        return []
    warnings = []
    if path.startswith("//"):
        warnings.append(f"notice: {path} is a network share; "
                        "the skills may be slow or fail when it is offline")
    if is_link(folder):
        warnings.append(f"notice: {path} links to {Path(os.path.realpath(folder)).as_posix()}")
    if not force and not (folder / ".obsidian").is_dir():
        root = next((p for p in folder.resolve().parents if (p / ".obsidian").is_dir()), None)
        if root:
            root = root.as_posix()
            raise Fail(3, f"ask: {path} is inside the vault {root}. Use {root} instead?\n"
                          f'yes: "{root}"\nno: --force "{path}"')
        try:
            subs = sorted(n for n in os.listdir(folder) if (folder / n / ".obsidian").is_dir())
        except OSError:
            subs = []
        if len(subs) == 1:
            sub = f"{path}/{subs[0]}"
            raise Fail(3, f"ask: {path} has no .obsidian, but its subfolder {sub} is a vault. "
                          f'Use {sub} instead?\nyes: "{sub}"\nno: --force "{path}"')
        vaults = f"; its subfolders {', '.join(subs)} are vaults" if subs else ""
        warnings.append(f"warning: no .obsidian folder in {path}{vaults}")
    if not os.access(folder, os.W_OK):
        warnings.append(f"warning: {path} is not writable; the skills that write notes will fail")
    if not (folder / "CLAUDE.md").is_file():
        warnings.append(f"warning: no CLAUDE.md in {path}")
    return warnings


def save(config, path):
    """Write the path atomically through a temp file next to the config."""
    try:
        config.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise Fail(1, f"SYSTEM ERROR: add.py: cannot create {config.parent.as_posix()}")
    tmp = config.with_name(f"{config.name}.tmp.{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(path + "\n")
        os.replace(tmp, config)
    except OSError:
        tmp.unlink(missing_ok=True)  # allow-delete: temp file of a failed atomic write
        raise Fail(1, f"SYSTEM ERROR: add.py: cannot write {config.as_posix()}")


def main(argv):
    # UTF-8 and LF output on every OS: Windows pipes default to cp1252 and CRLF.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    try:
        force, raw = parse_args(argv)
        config = config_file()
        path = canonical(raw, config.parents[2])
        check_not_claude_dir(path, config)
        check_not_configured(config)
        warnings = check_folder(path, force)
        save(config, path)
    except Fail as err:
        print(err, file=sys.stdout if err.code == 3 else sys.stderr)
        return err.code
    print(f"path: {path}")
    print(f"reply: Vault configured: {path}")
    for line in warnings:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
