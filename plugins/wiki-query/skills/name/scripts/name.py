#!/usr/bin/env python3
"""usage: name.py [--] <text>...

List notes in the vault configured by wiki-vault whose filename or title
contains <text> (case-insensitive), falling back to aliases. Read-only.

arguments:
  <text>  the text to look for; several words are joined with one space
  --      end of options, use before a text that starts with a dash

output (relay as printed):
  - <path>                                     one line per match
  No filename or title matches "<text>". Found through aliases:
  - <path> (alias: <alias>)                    alias fallback
  Nothing found.                               no match (still exit 0)

exit codes:
  0  lookup done (matches or "Nothing found.")
  1  system error (vault.py missing, a note cannot be read)
  2  bad usage (no text given)
  3  user error (vault path missing, vault folder or its CLAUDE.md missing)

example: name.py -- context engineering
"""

import os
import re
import sys
from pathlib import Path

# vault.py lives in the plugin scripts folder, three levels up from this file.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
try:
    from vault import read_vault, VaultError
except ImportError:
    read_vault = None

USAGE = "usage: name.py [--] <text>..."
# Folders at the vault root that are not notes. Dot folders are skipped everywhere.
SKIPPED_ROOT_DIRS = {"Attachments", "90. Templates"}
FRONTMATTER_FENCE = re.compile(r"^---[ \t]*$")
FRONTMATTER_KEY = re.compile(r"^([A-Za-z_]+):[ \t]*(.*)$")
LIST_ITEM = re.compile(r"^[ \t]*-[ \t]*(.*)$")
CODE_FENCE = re.compile(r"^[ \t]*(```|~~~)")


class ReadError(Exception):
    """A note cannot be read: system error, exit 1."""


def note_paths(vault):
    """Yield every note (*.md) as a path relative to the vault, with / separators."""
    for folder, dirs, files in os.walk(vault):
        at_root = Path(folder) == vault
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and not (at_root and d in SKIPPED_ROOT_DIRS)]
        for name in files:
            if name.endswith(".md"):
                yield (Path(folder) / name).relative_to(vault).as_posix()


def clean(value):
    """Trim spaces and one quote at each end."""
    value = value.strip(" \t")
    return re.sub(r"""^["']|["']$""", "", value)


def split_list(value):
    """A frontmatter value as a list: [a, b] gives two items, anything else one."""
    if value.startswith("[") and value.endswith("]"):
        return value[1:-1].split(",")
    return [value]


def read_note(text):
    """Return (title, aliases) of a note. Title is the first '# ' heading outside code."""
    lines = [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]
    aliases, title = [], ""
    start = 0
    if lines and FRONTMATTER_FENCE.match(lines[0]):
        start = len(lines)  # frontmatter that never closes covers the whole note
        list_key = ""
        for i in range(1, len(lines)):
            line = lines[i]
            if FRONTMATTER_FENCE.match(line):
                start = i + 1
                break
            key = FRONTMATTER_KEY.match(line)
            if key:
                list_key = ""
                if key.group(1) == "aliases":
                    if key.group(2) == "":
                        list_key = "aliases"
                    else:
                        aliases += split_list(key.group(2))
            elif list_key:
                item = LIST_ITEM.match(line)
                if item:
                    aliases.append(item.group(1))
    in_code = False
    for line in lines[start:]:
        if CODE_FENCE.match(line):
            in_code = not in_code
        elif not in_code and line.startswith("# "):
            title = clean(line[2:])
            break
    aliases = [a for a in (clean(a) for a in aliases) if a]
    return title, aliases


def lookup(vault, text):
    """Return the output lines for a search text."""
    query = text.lower()
    hits, alias_hits = [], {}
    for path in note_paths(vault):
        try:
            content = (vault / path).read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            raise ReadError(f"cannot read {path}: {err}")
        title, aliases = read_note(content)
        name = clean(Path(path).stem)
        if query in name.lower() or query in title.lower():
            hits.append(path)
            continue
        alias = next((a for a in aliases if query in a.lower()), None)
        if alias:
            alias_hits[path] = alias
    if hits:
        return [f"- {p}" for p in sorted(hits)]
    if alias_hits:
        head = f'No filename or title matches "{text}". Found through aliases:'
        return [head] + [f"- {p} (alias: {alias_hits[p]})" for p in sorted(alias_hits)]
    return ["Nothing found."]


def fail(prefix, message, code):
    print(f"{prefix}: {message}", file=sys.stderr)
    return code


def main(argv):
    # UTF-8 and LF on every OS: note paths may hold any character.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not argv:
        return fail("SYSTEM ERROR", f"name.py: no text given. {USAGE}", 2)
    text = " ".join(argv)
    if not text.strip():
        return fail("SYSTEM ERROR", f"name.py: text is empty. {USAGE}", 2)
    if read_vault is None:
        return fail("SYSTEM ERROR", "name.py: plugin script not found: vault.py", 1)
    try:
        vault = read_vault()
        print("\n".join(lookup(vault, text)))
    except VaultError as err:
        return fail("USER ERROR", str(err), 3)
    except ReadError as err:
        return fail("SYSTEM ERROR", f"name.py: {err}", 1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
