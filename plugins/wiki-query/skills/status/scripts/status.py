#!/usr/bin/env python3
"""usage: status.py <status>...

List notes in the configured Obsidian vault by frontmatter status. Read-only.
Reads the vault path with ../../../scripts/vault.py, prints the vault
CLAUDE.md and the lookup result. Run by the status skill.

arguments:
  <status>  one or more of draft, review, evergreen, archived (any word of
            letters, digits, _ or -). Several may also come as one
            space-separated argument.

output (stdout):
  vault: <path>, then the vault CLAUDE.md between "--- vault CLAUDE.md ---"
  and "--- end CLAUDE.md ---", then found: yes|no, then the lookup result
  after "--- result ---".
  A user error prints one line "ERROR: <message>" instead, with exit 0.

exit codes:
  0  done (also for "Nothing found." and for ERROR: lines)
  1  system error (vault.py missing, a file cannot be read)
  2  bad usage (unknown option)

example: status.py review draft
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
try:
    from vault import MARKER, VaultError, read_vault
except ImportError:
    MARKER = VaultError = read_vault = None

END_MARKER = "--- end CLAUDE.md ---"
RESULT_MARKER = "--- result ---"
STATUS_WORD = re.compile(r"[A-Za-z0-9_-]+", re.ASCII)
# Folders at the vault root that are never searched. Dot folders are skipped at any depth.
SKIPPED_ROOT_FOLDERS = {"Attachments", "90. Templates"}
FENCE_LINE = re.compile(r"^---[ \t]*$")
KEY_LINE = re.compile(r"^([A-Za-z_]+):[ \t]*(.*)$")
LIST_ITEM = re.compile(r"^[ \t]*-[ \t]*(.*)$")


class UsageError(Exception):
    """Bad command line: exit 2."""


def parse_words(argv):
    """Split all arguments on whitespace, so "$ARGUMENTS" may arrive as one string.

    Returns the words, or None when help was asked. Raises UsageError on an unknown option.
    """
    words = " ".join(argv).split()
    for word in words:
        if word in ("-h", "--help"):
            return None
        if word.startswith("-"):
            raise UsageError(f"unknown option '{word}'")
    return words


def note_files(folder, at_root=True):
    """Yield every .md file below folder, skipping dot folders, Attachments and 90. Templates."""
    for path in sorted(folder.iterdir()):
        if path.is_dir():
            if path.name.startswith(".") or (at_root and path.name in SKIPPED_ROOT_FOLDERS):
                continue
            yield from note_files(path, at_root=False)
        elif path.name.endswith(".md") and path.is_file():
            yield path


def clean(value):
    """Trim blanks, then one leading and one trailing quote."""
    value = value.strip(" \t")
    value = re.sub(r"^[\"']", "", value)
    return re.sub(r"[\"']$", "", value)


def split_values(value):
    """A value like [a, "b"] becomes a list of items; any other value is one item."""
    if value.startswith("[") and value.endswith("]"):
        return value[1:-1].split(",")
    return [value]


def note_statuses(path):
    """Return the non-empty status values in the note's frontmatter.

    Frontmatter only counts when the first line is ---. Supports inline values,
    [a, b] lists and indented "- item" lists below an empty "status:" key.
    """
    lines = path.open(encoding="utf-8", errors="replace", newline="").read().split("\n")
    lines = [line[:-1] if line.endswith("\r") else line for line in lines]
    if not lines or not FENCE_LINE.match(lines[0]):
        return []
    found = []
    list_key = ""
    for line in lines[1:]:
        if FENCE_LINE.match(line):
            break
        key = KEY_LINE.match(line)
        if key:
            list_key = ""
            if key.group(1) == "status":
                if key.group(2) == "":
                    list_key = "status"
                else:
                    found.extend(split_values(key.group(2)))
        elif list_key:
            item = LIST_ITEM.match(line)
            if item:
                found.append(item.group(1))
    return [v for v in (clean(v) for v in found) if v]


def lookup(vault, wanted):
    """Return (found, lines): one block per wanted status, paths sorted, or "Nothing found."."""
    hits = {i: set() for i in range(len(wanted))}
    for path in note_files(vault):
        rel = path.relative_to(vault).as_posix()
        for value in note_statuses(path):
            for i, want in enumerate(wanted):
                if value.lower() == want.lower():
                    hits[i].add(rel)
    if not any(hits.values()):
        return False, ["Nothing found."]
    lines = []
    for i, want in enumerate(wanted):
        lines.append(f"{want}:")
        if not hits[i]:
            lines.append("- nothing found")
        lines.extend(f"- {rel}" for rel in sorted(hits[i]))
    return True, lines


def run(argv):
    """Do the work. Returns the exit code."""
    try:
        words = parse_words(argv)
    except UsageError as err:
        print(f"SYSTEM ERROR: status.py: {err}", file=sys.stderr)
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if words is None:
        print(__doc__.strip())
        return 0
    if read_vault is None:
        print("SYSTEM ERROR: status.py: vault.py not found in the plugin scripts folder", file=sys.stderr)
        return 1

    try:
        vault = read_vault()
    except VaultError as err:
        print(f"ERROR: {err}")
        return 0
    if not words:
        print("ERROR: no status given")
        return 0
    for word in words:
        if not STATUS_WORD.fullmatch(word):
            print(f"ERROR: invalid status '{word}': use words of letters, digits, _ or -")
            return 0

    try:
        rules = (vault / "CLAUDE.md").read_text(encoding="utf-8-sig")
        found, result = lookup(vault, words)
    except OSError as err:
        print(f"SYSTEM ERROR: status.py: {err}", file=sys.stderr)
        return 1

    print(f"vault: {vault.as_posix()}")
    print(MARKER)
    print(rules.rstrip("\n"))
    print(END_MARKER)
    print(f"found: {'yes' if found else 'no'}")
    print(RESULT_MARKER)
    print("\n".join(result))
    return 0


def main():
    # Notes may hold any Unicode; always write UTF-8 with LF line ends.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
