#!/usr/bin/env python3
"""usage: status.py

Print the vault path stored in ~/.claude/obsidian-wiki/vault-path.
Read-only. Injected by /wiki-vault:add before the model starts.

output:
  configured: <path>   a path is stored
  configured: none     file missing or empty

exit codes:
  0  printed the state
  1  system error (file not readable)
  2  bad usage (arguments given)

example: status.py
"""

import sys
from pathlib import Path

# vault.py lives in the plugin's scripts folder and knows how to read the file.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import config_file, stored_path  # noqa: E402


def main(argv):
    # UTF-8 and LF output on every OS: Windows pipes default to cp1252 and CRLF.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if argv:
        print("usage: status.py (no arguments)", file=sys.stderr)
        return 2
    try:
        path = stored_path()
    except (OSError, UnicodeDecodeError) as err:
        print(f"SYSTEM ERROR: status.py: cannot read {config_file().as_posix()}: {err}",
              file=sys.stderr)
        return 1
    print(f"configured: {path or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
