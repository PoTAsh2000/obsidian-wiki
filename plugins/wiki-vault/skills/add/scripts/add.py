#!/usr/bin/env python3
"""usage: add.py [--allow-missing] [--] <vault path>

Store <vault path> in ~/.claude/obsidian-wiki/vault-path.
Only adds: never changes a path that is already stored.
Every "\\" in the path becomes "/". Never touches the vault itself.

arguments:
  <vault path>     path to the vault root folder, one argument (quote it)
  --allow-missing  store the path even if the folder does not exist
  --               end of options, the next argument is the path

output:
  configured: <path>
  folder: found|missing

exit codes:
  0  stored
  1  system error (HOME not set, cannot write the file)
  2  bad usage (wrong arguments, empty path, newline in path)
  3  user error: "already configured: <path>" or "folder not found: <path>"

example: add.py "C:/Users/me/Documents/Obsidian/MyVault"
"""

import os
import sys
from pathlib import Path

# The shared reader lives in the plugin's scripts folder. vault.py stays
# read-only: writing the config file happens here.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import config_file, to_native  # noqa: E402


class Fail(Exception):
    """Stop with an exit code; the message goes to stderr."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def usage_error(message):
    return Fail(2, f"usage: add.py [--allow-missing] <vault path>\nadd.py: {message}")


def parse_args(argv):
    """Return (allow_missing, path), or None when help was asked."""
    allow = False
    paths = []
    options = True
    for arg in argv:
        if not options:
            paths.append(arg)
        elif arg == "--":
            options = False
        elif arg in ("-h", "--help"):
            return None
        elif arg == "--allow-missing":
            allow = True
        elif arg.startswith("--"):
            raise usage_error(f"unknown option: {arg}")
        else:
            paths.append(arg)
    if len(paths) != 1:
        raise usage_error(f"expected one vault path, got {len(paths)} (quote a path with spaces)")
    path = paths[0].replace("\\", "/")
    if not path:
        raise usage_error("empty vault path")
    if "\n" in path or "\r" in path:
        raise usage_error("newline in vault path")
    return allow, path


def check_not_configured(config):
    """Refuse when the config file already holds a path."""
    if config.exists() and not config.is_file():
        raise Fail(1, f"SYSTEM ERROR: add.py: {config.as_posix()} is not a regular file")
    if not config.exists():
        return
    try:
        lines = config.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        raise Fail(1, f"SYSTEM ERROR: add.py: cannot read {config.as_posix()}")
    old = lines[0].strip() if lines else ""
    if old:
        raise Fail(3, f"USER ERROR: add.py: already configured: {old}")


def write_config(config, path):
    try:
        config.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise Fail(1, f"SYSTEM ERROR: add.py: cannot create {config.parent.as_posix()}")
    try:
        config.write_text(path + "\n", encoding="utf-8", newline="\n")
    except OSError:
        raise Fail(1, f"SYSTEM ERROR: add.py: cannot write {config.as_posix()}")


def add(argv):
    parsed = parse_args(argv)
    if parsed is None:
        print(__doc__.strip())
        return
    allow, path = parsed
    if not os.environ.get("HOME"):
        raise Fail(1, "SYSTEM ERROR: add.py: HOME is not set")
    config = config_file()
    check_not_configured(config)
    found = Path(to_native(path)).is_dir()
    if not found and not allow:
        raise Fail(3, f"USER ERROR: add.py: folder not found: {path}")
    write_config(config, path)
    print(f"configured: {path}")
    print(f"folder: {'found' if found else 'missing'}")


def main(argv):
    # UTF-8 and LF output on every OS: Windows pipes default to cp1252 and CRLF.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    try:
        add(argv)
    except Fail as err:
        print(err, file=sys.stderr)
        return err.code
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
