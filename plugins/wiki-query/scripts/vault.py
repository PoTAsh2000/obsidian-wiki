#!/usr/bin/env python3
"""vault.py: read the configured Obsidian vault and its CLAUDE.md. Read-only.

Identical copy in every obsidian-wiki plugin at plugins/<plugin>/scripts/vault.py.
Never edit one copy alone: change all copies the same way.

The vault path comes from ~/.claude/obsidian-wiki/vault-path (written by wiki-vault only).
$HOME wins over the OS home folder, so tests can point it at a fixture.

CLI (for SKILL.md injection):
  python3 vault.py            print the vault and its CLAUDE.md
  python3 vault.py --path     print only the vault line

output:
  vault: <path>
  --- vault CLAUDE.md ---     then the vault CLAUDE.md (not with --path)
  ERROR: <message>            soft fail: path missing or vault has no CLAUDE.md

exit codes:
  0  context printed, or a soft ERROR line for the model to relay
  1  system error (cannot read a file)
  2  bad usage

Import:
  from vault import read_vault, VaultError
  vault = read_vault()        Path of the vault, or raises VaultError(message)
"""

import os
import re
import sys
from pathlib import Path

MARKER = "--- vault CLAUDE.md ---"
MISSING = ("Vault path is missing. Install wiki-vault@obsidian-wiki and use "
           "/wiki-vault:add <vault path> to configure your vault.")
NO_RULES = ("The configured vault folder has no CLAUDE.md: {vault}. "
            "Use /wiki-vault:overwrite <vault path> to fix the vault path.")


def config_file():
    """~/.claude/obsidian-wiki/vault-path. HOME wins over the OS default, so tests can set it."""
    home = os.environ.get("HOME") or str(Path.home())
    return Path(to_native(home)) / ".claude" / "obsidian-wiki" / "vault-path"


class VaultError(Exception):
    """Soft failure: the message is meant to be relayed to the user as is."""


def to_native(raw):
    """Turn a Git Bash path like /c/Users/x into C:/Users/x on Windows."""
    if sys.platform == "win32":
        m = re.match(r"^/([a-zA-Z])(/.*)?$", raw)
        if m:
            return f"{m.group(1).upper()}:{m.group(2) or '/'}"
    return raw


def read_vault(config=None):
    """Return the vault folder as a Path. Raise VaultError when it is unusable."""
    config = config or config_file()
    raw = ""
    if config.is_file():
        lines = config.read_text(encoding="utf-8-sig").splitlines()
        raw = lines[0].strip() if lines else ""
    if not raw:
        raise VaultError(MISSING)
    vault = Path(to_native(raw))
    if not (vault / "CLAUDE.md").is_file():
        raise VaultError(NO_RULES.format(vault=raw))
    return vault


def main(argv):
    # UTF-8 and LF output on every OS: Windows pipes default to cp1252 and CRLF.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    if argv in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if argv not in ([], ["--path"]):
        print("SYSTEM ERROR: vault.py: unknown arguments, see --help", file=sys.stderr)
        return 2
    try:
        vault = read_vault()
    except VaultError as err:
        print(f"ERROR: {err}")
        return 0
    try:
        rules = (vault / "CLAUDE.md").read_text(encoding="utf-8-sig")
    except OSError as err:
        print(f"SYSTEM ERROR: vault.py: cannot read {vault}/CLAUDE.md: {err}", file=sys.stderr)
        return 1
    print(f"vault: {vault.as_posix()}")
    if argv != ["--path"]:
        print(MARKER)
        print(rules.rstrip("\n"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
