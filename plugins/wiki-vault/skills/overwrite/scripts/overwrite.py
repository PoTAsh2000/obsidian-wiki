#!/usr/bin/env python3
"""usage: overwrite.py [--force] <vault-path>

Replace the vault path in ~/.claude/obsidian-wiki/vault-path, which all
obsidian-wiki skills read. Never touches the vault itself. Backslashes become
slashes and trailing slashes are removed before saving.

arguments:
  <vault-path>  absolute path to the vault root, like C:/Notes/Vault or /home/me/Vault
options:
  --force       save even when the folder does not exist
  -h, --help    show this help

output (exit 0):
  path: <saved path>
  old: <previous path, or none>

exit codes:
  0  saved (also when the path was already the same)
  1  system error (cannot create the config folder or write the file)
  2  bad usage (wrong arguments)
  3  user error (path not absolute, or folder not found without --force)

example: overwrite.py "D:/Obsidian/MyVault"
"""

import os
import re
import sys
from pathlib import Path

# vault.py lives in the plugin's scripts folder: plugins/wiki-vault/scripts.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import config_file, to_native  # noqa: E402

USAGE = "usage: overwrite.py [--force] <vault-path>"


class Fail(Exception):
    """Stop with an error line on stderr and an exit code."""

    def __init__(self, code, message):
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


def normalize(raw):
    """Backslashes to slashes, drop trailing slashes but keep a root like / or C:/."""
    path = raw.replace("\\", "/")
    while path.endswith("/") and path != "/" and not re.fullmatch(r"[A-Za-z]:/", path):
        path = path[:-1]
    return path


def check(path, force):
    """Raise Fail when the path cannot be saved."""
    if not path:
        raise Fail(2, "SYSTEM ERROR: overwrite.py: empty vault path")
    if "\n" in path or "\r" in path:
        raise Fail(3, "USER ERROR: vault path contains a line break")
    if not (path.startswith("/") or re.match(r"[A-Za-z]:/", path)):
        raise Fail(3, f"USER ERROR: vault path is not absolute: {path}")
    # to_native turns a Git Bash path like /c/Notes into C:/Notes on Windows.
    if not force and not Path(to_native(path)).is_dir():
        raise Fail(3, f"USER ERROR: folder not found: {path}")


def read_old(config):
    """First line of the current config without CR, or an empty string."""
    if not config.is_file():
        return ""
    lines = config.read_text(encoding="utf-8-sig").splitlines()
    return lines[0] if lines else ""


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
        tmp.unlink(missing_ok=True)
        raise Fail(1, f"SYSTEM ERROR: overwrite.py: cannot write {config}")


def main(argv):
    try:
        force, raw = parse_args(argv)
        path = normalize(raw)
        check(path, force)
        config = config_file()
        old = read_old(config)
        save(config, path)
    except Fail as err:
        print(err, file=sys.stderr)
        return err.code
    print(f"path: {path}")
    print(f"old: {old or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
