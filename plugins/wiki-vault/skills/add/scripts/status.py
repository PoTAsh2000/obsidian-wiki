#!/usr/bin/env python3
"""usage: status.py

Print the vault path stored in ~/.claude/obsidian-wiki/vault-path.
Read-only. Injected by /wiki-vault:add before the model starts.

output:
  configured: <path>   a path is stored
  configured: none     file missing or empty

exit codes:
  0  printed the state
  1  system error (HOME not set, file not readable)
  2  bad usage (arguments given)

example: status.py
"""

import os
import sys
from pathlib import Path

# The shared reader lives in the plugin's scripts folder.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import config_file  # noqa: E402


def stored_path(config):
    """First line of the config file without whitespace, or "" when missing or empty."""
    if not config.exists():
        return ""
    if not config.is_file():
        raise OSError("not a regular file")
    lines = config.read_text(encoding="utf-8-sig").splitlines()
    return lines[0].strip() if lines else ""


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if argv:
        print("usage: status.py (no arguments)", file=sys.stderr)
        return 2
    if not os.environ.get("HOME"):
        print("SYSTEM ERROR: status.py: HOME is not set", file=sys.stderr)
        return 1
    config = config_file()
    try:
        path = stored_path(config)
    except OSError:
        print(f"SYSTEM ERROR: status.py: cannot read {config.as_posix()}", file=sys.stderr)
        return 1
    print(f"configured: {path or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
