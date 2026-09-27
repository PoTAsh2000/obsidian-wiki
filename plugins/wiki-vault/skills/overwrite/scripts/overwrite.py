#!/usr/bin/env python3
"""usage: overwrite.py [--force] <vault-path>

Replace the vault path in ~/.claude/obsidian-wiki/vault-path, which all
obsidian-wiki skills read. Never touches the vault itself. vault.py cleans the
path first: backslashes become slashes and trailing slashes are removed.

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
  1  system error (cannot read, create or write the config file)
  2  bad usage (wrong arguments)
  3  user error (path empty, not absolute or with a line break,
     or folder not found without --force)

example: overwrite.py "D:/Obsidian/MyVault"
"""

import os
import sys
from pathlib import Path

# vault.py lives in the plugin's scripts folder: plugins/wiki-vault/scripts.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import VaultError, clean_path, config_file, stored_path, to_native  # noqa: E402

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


def check(raw, force):
    """Return the cleaned path, or raise Fail when it cannot be saved."""
    try:
        path = clean_path(raw)
    except VaultError as err:
        raise Fail(3, f"USER ERROR: {err}")
    # to_native turns a Git Bash path like /c/Notes into C:/Notes on Windows.
    if not force and not Path(to_native(path)).is_dir():
        raise Fail(3, f"USER ERROR: folder not found: {path}")
    return path


def read_old(config):
    """The currently stored path, or an empty string when there is none."""
    try:
        return stored_path(config)
    except (OSError, UnicodeDecodeError) as err:
        raise Fail(1, f"SYSTEM ERROR: overwrite.py: cannot read {config}: {err}")


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
    # UTF-8 and LF output on every OS: Windows pipes default to cp1252 and CRLF.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    try:
        force, raw = parse_args(argv)
        path = check(raw, force)
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
