#!/usr/bin/env python3
"""usage: delete.py

Remove the obsidian-wiki vault path file ~/.claude/obsidian-wiki/vault-path.
Never touches the vault folder itself. Safe to run again: nothing to remove is not an error.
Run when the user asks to remove or forget the vault path.

arguments: none

output (stdout, one line):
  removed: <path>   the file held <path> and is now removed
  removed: none     no path was configured (file missing or empty; an empty file is removed)

exit codes:
  0  done (see output)
  1  system error (HOME not set, file could not be read or removed)
  2  bad usage (any argument)

example: python3 delete.py
"""

import os
import sys
from pathlib import Path

# vault.py lives in the plugin scripts folder: plugins/wiki-vault/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import config_file  # noqa: E402


class DeleteError(Exception):
    """A system error: the message goes to stderr and the exit code is 1."""


def configured_path(config):
    """First line of the config file, trimmed. Empty string when blank."""
    try:
        lines = config.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as err:
        raise DeleteError(f"cannot read {config}: {err}")
    return lines[0].strip() if lines else ""


def remove_config(config):
    """Remove the config file and return the path it held ('' when none)."""
    if not config.exists():
        return ""
    if not config.is_file():
        raise DeleteError(f"{config} is not a regular file")
    path = configured_path(config)
    try:
        config.unlink()
    except OSError as err:
        raise DeleteError(f"cannot remove {config}: {err}")
    if config.exists():
        raise DeleteError(f"{config} still exists after remove")
    return path


def main(argv):
    # UTF-8 and LF output on every OS: Windows pipes default to cp1252 and CRLF.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    if argv:
        if argv[0] in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        print("SYSTEM ERROR: delete.py: takes no arguments, see --help", file=sys.stderr)
        return 2
    # config_file() would fall back to the OS home folder; keep the old strict check.
    if not os.environ.get("HOME"):
        print("SYSTEM ERROR: delete.py: HOME is not set", file=sys.stderr)
        return 1
    try:
        path = remove_config(config_file())
    except DeleteError as err:
        print(f"SYSTEM ERROR: delete.py: {err}", file=sys.stderr)
        return 1
    print(f"removed: {path or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
