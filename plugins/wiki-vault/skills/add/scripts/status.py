#!/usr/bin/env python3
"""usage: status.py

Print the vault path stored in ~/.claude/obsidian-wiki/vault-path.
Read-only. Injected by /wiki-vault:add before the model starts.

output:
  reply: Vault is already configured: <path>. Use /wiki-vault:overwrite to change it.
  reply: Vault is configured as <path>, but that folder no longer exists. Use ...
  reply: Vault is configured as <path>, but that folder has no CLAUDE.md. Use ...
  configured: none     file missing or empty, followed by
  candidate: <path>    first the vault the current folder is in (it or a parent
                       has .obsidian), marked " (current folder)", then each
                       vault from Obsidian's own obsidian.json whose folder
                       exists (open vault first, then newest last-opened, then
                       the rest in file order), cleaned like add.py does, with " (has CLAUDE.md)"
                       at the end when it has one; obsidian.json missing or
                       unreadable: no candidate lines

exit codes:
  0  printed the state
  1  system error (file not readable)
  2  bad usage (arguments given)

example: status.py
"""

import json
import os
import sys
from pathlib import Path

# vault.py lives in the plugin's scripts folder and knows how to read the file.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import config_file, home_dir, stored_path  # noqa: E402
from add import Fail, canonical, norm  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "current" / "scripts"))
from current import problem  # noqa: E402


def obsidian_json(home):
    """Obsidian's vault registry for this OS."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / "obsidian" / "obsidian.json"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    return Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "obsidian" / "obsidian.json"


def current_vault(home):
    """The vault the current folder is in, in canonical form, or None."""
    try:
        here = Path(os.path.realpath(Path.cwd()))  # long names, like add.py stores
        root = next((p for p in (here, *here.parents) if (p / ".obsidian").is_dir()), None)
        return canonical(str(root), home) if root else None
    except (OSError, Fail):
        return None


def recent(vault):
    """Sort key: the open vault first, then newest last-opened ts, then the rest (stable)."""
    ts = vault.get("ts")
    ts = ts if isinstance(ts, (int, float)) and not isinstance(ts, bool) else None
    if vault.get("open") is True:
        return (0, -(ts or 0))
    return (1, -ts) if ts is not None else (2, 0)


def candidates():
    """Existing vault folders Obsidian knows, in canonical form. Read-only; any problem: []."""
    home = home_dir()
    try:
        vaults = json.loads(obsidian_json(home).read_text(encoding="utf-8"))["vaults"].values()
        raw = [v["path"] for v in sorted(vaults, key=recent) if isinstance(v.get("path"), str)]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []
    found = []
    for r in raw:
        try:
            path = canonical(r, home)
        except Fail:
            continue
        if os.path.isdir(path) and path not in found:
            found.append(path)
    return found


def state(path):
    """The reply for a stored path: healthy, folder gone, or no CLAUDE.md."""
    why = problem(path)
    if not why:
        return f"Vault is already configured: {path}. Use /wiki-vault:overwrite to change it."
    return (f"Vault is configured as {path}, but {why}. "
            "Use /wiki-vault:overwrite to point to the new location.")


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
    if path:
        print(f"reply: {state(path)}")
    else:
        print("configured: none")
        here = current_vault(home_dir())
        seen = norm(here) if here else None
        for path in [here] * bool(here) + [c for c in candidates() if norm(c) != seen]:
            mark = " (current folder)" if path == here else ""
            mark += " (has CLAUDE.md)" if (Path(path) / "CLAUDE.md").is_file() else ""
            print(f"candidate: {path}{mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
