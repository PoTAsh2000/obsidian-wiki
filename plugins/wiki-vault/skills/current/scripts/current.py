#!/usr/bin/env python3
"""usage: current.py

Show the vault path stored in ~/.claude/obsidian-wiki/vault-path and check it.
Read-only. Run by /wiki-vault:current; the output is the reply for the user.

output:
  Vault configured: <path>                    the folder exists and has a CLAUDE.md
  Warning: ...                                 after it, one line per soft finding
  Vault is not configured. Use /wiki-vault:add <vault path> to configure your vault.
  Vault is configured as <path>, but that folder no longer exists. Use /wiki-vault:overwrite ...
  Vault is configured as <path>, but that folder has no CLAUDE.md. Use /wiki-vault:overwrite ...

exit codes:
  0  printed the state (also when the vault is not configured or unusable)
  1  system error (file not readable)
  2  bad usage (arguments given)

example: current.py
"""

import os
import sys
from pathlib import Path

# vault.py lives in the plugin's scripts folder and knows how to read the file.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import config_file, stored_path, to_native  # noqa: E402


def problem(path):
    """Why a stored path cannot be used as the vault, or None when it can."""
    folder = Path(to_native(path))
    if not folder.is_dir():
        return "that folder no longer exists"
    if not (folder / "CLAUDE.md").is_file():
        return "that folder has no CLAUDE.md"
    return None


def warnings(path):
    """Soft findings for a usable vault folder."""
    folder = Path(to_native(path))
    found = []
    if not (folder / ".obsidian").is_dir():
        found.append(f"Warning: no .obsidian folder in {path}")
    if not os.access(folder, os.W_OK):
        found.append(f"Warning: {path} is not writable; the skills that write notes will fail")
    return found


def describe(path):
    """The reply lines for a stored path ("" means none stored)."""
    if not path:
        return ["Vault is not configured. Use /wiki-vault:add <vault path> to configure your vault."]
    why = problem(path)
    if why:
        return [f"Vault is configured as {path}, but {why}. "
                "Use /wiki-vault:overwrite to point to the new location."]
    return [f"Vault configured: {path}", *warnings(path)]


def main(argv):
    # UTF-8 and LF output on every OS: Windows pipes default to cp1252 and CRLF.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if argv:
        print("usage: current.py (no arguments)", file=sys.stderr)
        return 2
    try:
        path = stored_path()
    except (OSError, UnicodeDecodeError) as err:
        print(f"SYSTEM ERROR: current.py: cannot read {config_file().as_posix()}: {err}",
              file=sys.stderr)
        return 1
    print("\n".join(describe(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
