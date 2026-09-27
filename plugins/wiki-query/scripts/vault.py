#!/usr/bin/env python3
"""vault.py: read the configured Obsidian vault and its CLAUDE.md. Read-only.

Identical copy in every obsidian-wiki plugin at plugins/<plugin>/scripts/vault.py.
Never edit one copy alone: change all copies the same way.

The vault path comes from ~/.claude/obsidian-wiki/vault-path (written by wiki-vault only).
$HOME wins over the OS home folder, so tests can point it at a fixture.
This is the only place that knows where that file is and how to read it.

CLI (injected as the first step of every skill except wiki-vault):
  python3 vault.py            print the vault and its CLAUDE.md
  python3 vault.py --path     print only the vault line

output:
  vault: <path>
  --- vault CLAUDE.md ---     then the vault CLAUDE.md (not with --path)
  ERROR: <message>            vault problem: path missing or vault has no CLAUDE.md

exit codes:
  0  context printed, or an ERROR line for the model to relay
  1  system error (cannot read a file)
  2  bad usage

Import (add the plugin scripts folder to sys.path first):
  from vault import require_vault
  vault = require_vault()     Path of the vault. On a vault problem it prints the
                              same ERROR line as the CLI and exits 0, in every script.
  read_vault()                the same Path, or raises VaultError(message)
  stored_path()               the raw stored path, "" when none (wiki-vault)
  clean_path(raw)             a typed path made ready to store, or raises VaultError (wiki-vault)
  config_file()               Path of the vault-path file (wiki-vault)
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


class VaultError(Exception):
    """A vault problem: the message is meant to be relayed to the user as is."""


def config_file():
    """~/.claude/obsidian-wiki/vault-path. HOME wins over the OS default, so tests can set it."""
    home = os.environ.get("HOME") or str(Path.home())
    return Path(to_native(home)) / ".claude" / "obsidian-wiki" / "vault-path"


def to_native(raw):
    """Turn a Git Bash path like /c/Users/x into C:/Users/x on Windows."""
    if sys.platform == "win32":
        m = re.match(r"^/([a-zA-Z])(/.*)?$", raw)
        if m:
            return f"{m.group(1).upper()}:{m.group(2) or '/'}"
    return raw


def stored_path(config=None):
    """First line of the vault-path file without whitespace, or "" when missing or empty.

    Raises OSError when the file exists but cannot be read.
    """
    config = config or config_file()
    if not config.exists():
        return ""
    if not config.is_file():
        raise OSError(f"{config.as_posix()} is not a regular file")
    lines = config.read_text(encoding="utf-8-sig").splitlines()
    return lines[0].strip() if lines else ""


def clean_path(raw):
    """Make a vault path typed by the user ready to store. Raise VaultError when unusable.

    Backslashes become slashes and trailing slashes go, but a root like / or C:/ stays.
    The path must be absolute and on one line. Whether the folder exists is not checked here.
    """
    path = raw.strip().replace("\\", "/")
    while path.endswith("/") and path != "/" and not re.fullmatch(r"[A-Za-z]:/", path):
        path = path[:-1]
    if not path:
        raise VaultError("vault path is empty")
    if "\n" in path or "\r" in path:
        raise VaultError("vault path contains a line break")
    if not (path.startswith("/") or re.match(r"[A-Za-z]:/", path)):
        raise VaultError(f"vault path is not absolute: {path}")
    return path


def read_vault(config=None):
    """Return the vault folder as a Path. Raise VaultError when it is unusable."""
    try:
        raw = stored_path(config)
    except (OSError, UnicodeDecodeError) as err:
        raise VaultError(f"Cannot read the vault path file: {err}")
    if not raw:
        raise VaultError(MISSING)
    vault = Path(to_native(raw))
    if not (vault / "CLAUDE.md").is_file():
        raise VaultError(NO_RULES.format(vault=raw))
    return vault


def require_vault():
    """Return the vault Path. On a vault problem print "ERROR: <message>" and exit 0.

    Every script uses this, so a vault problem looks the same everywhere.
    """
    try:
        return read_vault()
    except VaultError as err:
        print(f"ERROR: {err}")
        sys.exit(0)


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
    vault = require_vault()
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
