#!/usr/bin/env python3
"""usage: add.py [--force] <vault-path>

Save the vault path in ~/.claude/obsidian-wiki/vault-path, which all
obsidian-wiki skills read. Only adds: never changes a path that is already
stored. Never touches the vault itself. Backslashes become slashes and
trailing slashes are removed before saving.

arguments:
  <vault-path>  absolute path to the vault root, like C:/Notes/Vault or /home/me/Vault
options:
  --force       save even when the folder does not exist
  -h, --help    show this help

output (exit 0):
  path: <saved path>

exit codes:
  0  saved
  1  system error (cannot read the config, create its folder or write it)
  2  bad usage (wrong arguments)
  3  user error: path empty, not absolute or with a line break,
     "already configured: <path>", or "folder not found: <path>" without --force

example: add.py "D:/Obsidian/MyVault"
"""

import os
import sys
from pathlib import Path

# vault.py lives in the plugin's scripts folder: plugins/wiki-vault/scripts.
# It knows where the config file is and how to read it; writing happens here.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import VaultError, clean_path, config_file, stored_path, to_native  # noqa: E402

USAGE = "usage: add.py [--force] <vault-path>"


class Fail(Exception):
    """Stop with an error line on stderr and an exit code."""

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


def clean(raw):
    """The path in the form to store, or Fail when it is unusable."""
    try:
        return clean_path(raw)
    except VaultError as err:
        raise Fail(3, f"USER ERROR: {err}")


def check_not_configured(config):
    """Refuse when the config file already holds a path."""
    try:
        old = stored_path(config)
    except (OSError, UnicodeDecodeError) as err:
        raise Fail(1, f"SYSTEM ERROR: add.py: cannot read {config.as_posix()}: {err}")
    if old:
        raise Fail(3, f"USER ERROR: already configured: {old}")


def check_folder(path, force):
    """Refuse a folder that does not exist, unless --force."""
    # to_native turns a Git Bash path like /c/Notes into C:/Notes on Windows.
    if not force and not Path(to_native(path)).is_dir():
        raise Fail(3, f"USER ERROR: folder not found: {path}")


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
        tmp.unlink(missing_ok=True)
        raise Fail(1, f"SYSTEM ERROR: add.py: cannot write {config.as_posix()}")


def main(argv):
    # UTF-8 and LF output on every OS: Windows pipes default to cp1252 and CRLF.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    try:
        force, raw = parse_args(argv)
        path = clean(raw)
        config = config_file()
        check_not_configured(config)
        check_folder(path, force)
        save(config, path)
    except Fail as err:
        print(err, file=sys.stderr)
        return err.code
    print(f"path: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
