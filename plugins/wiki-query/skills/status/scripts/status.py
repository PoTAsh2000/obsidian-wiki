#!/usr/bin/env python3
"""usage: status.py [--all] [<status>...]
       status.py - <<'STATUS_END'   (arguments on stdin, the form SKILL.md uses)

List notes in the configured Obsidian vault by frontmatter status. Read-only.
Gets the vault with require_vault() from ../../../scripts/vault.py and
prints the lookup result. Run by the status skill.

arguments:
  <status>  zero or more of draft, review, evergreen, archived (any word of
            letters, digits, _ or -). Several may also come as one
            space-separated argument.
  -         read the arguments from stdin instead, so user text never passes
            through shell quoting (SKILL.md feeds it through a quoted heredoc)
  --all     show every note of a block; by default a block stops after
            the 50 oldest notes with "- ... and <n> more".

output (stdout):
  found: yes|no, then the lookup result: one block per status, at most
  50 notes (see --all), oldest first with their ISO updated (else
  created) date, undated and non-ISO dates last (shown as "bad date: <value>"), and a
  "did you mean" line for an unknown status close to one in the vault.
  Without a status: one "<status>: <count>" line per status in the vault,
  in lifecycle order, then any other status alphabetically, then
  "(no status): <count>" for notes without a status (left out when 0).
  A user error or a vault problem prints one line "ERROR: <message>"
  instead, with exit 0. An invalid status also prints the accepted form.

exit codes:
  0  done (also for "Nothing found." and for ERROR: lines)
  1  system error (a file cannot be read)
  2  bad usage (unknown option)

example: status.py review draft
         status.py --all evergreen
"""

import datetime
import difflib
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault  # noqa: E402

STATUS_WORD = re.compile(r"[A-Za-z0-9_-]+", re.ASCII)
# Folders at the vault root that are never searched. Dot folders are skipped at any depth.
# normcase: on Windows these match without regard to case, like its filesystem.
SKIPPED_ROOT_FOLDERS = {os.path.normcase(n) for n in ("Attachments", "90. Templates")}
FENCE_LINE = re.compile(r"^---[ \t]*$")
CLOSE_LINE = re.compile(r"^(---|\.\.\.)[ \t]*$")
KEY_LINE = re.compile(r"^([A-Za-z_]+):[ \t]*(.*)$")
BLOCK_CAP = 50
LIST_ITEM = re.compile(r"^[ \t]*-[ \t]*(.*)$")
LIFECYCLE = ("draft", "review", "evergreen", "archived")
ISO_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[T ].*)?", re.ASCII)


class UsageError(Exception):
    """Bad command line: exit 2."""


def parse_words(argv):
    """Split all arguments on whitespace, so "$ARGUMENTS" may arrive as one string.

    Returns (words, show all), or None when help was asked. Raises UsageError on an unknown option.
    """
    words = " ".join(argv).split()
    for word in words:
        if word in ("-h", "--help"):
            return None
        if word.startswith("-") and word != "--all":
            raise UsageError(f"unknown option '{word}'")
    return [w for w in words if w != "--all"], "--all" in words


def is_link(path):
    """True for a symlink, or a junction on Windows (readlink only works on links)."""
    try:
        os.readlink(path)
        return True
    except (OSError, ValueError):
        return False


def note_files(folder, at_root=True):
    """Yield every real .md file below folder, skipping links, dot folders, Attachments, 90. Templates
    and the vault CLAUDE.md.

    Links are never followed, so the walk stays inside the vault and cannot loop.
    """
    for path in sorted(folder.iterdir()):
        if is_link(path):
            continue
        if path.is_dir():
            name = os.path.normcase(path.name)
            if name.startswith(".") or (at_root and name in SKIPPED_ROOT_FOLDERS):
                continue
            yield from note_files(path, at_root=False)
        elif path.name.endswith(".md") and path.is_file() and not (at_root and path.name == "CLAUDE.md"):
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


def note_fields(path):
    """Return {key: [non-empty values]} for the keys in the note's frontmatter.

    Frontmatter only counts when the first line is --- (after an optional BOM)
    and a later --- or ... line closes it. Supports inline values,
    [a, b] lists and indented "- item" lists below an empty key.
    Keys are lowercased; when a key comes in two spellings, the first spelling wins.
    """
    lines = []
    with path.open(encoding="utf-8-sig", errors="replace", newline="\n") as handle:
        for line in handle:  # stop at the closing fence: the body is never read
            line = line.rstrip("\n")
            line = line[:-1] if line.endswith("\r") else line
            if not lines:
                if not FENCE_LINE.match(line):
                    return {}
            elif CLOSE_LINE.match(line):
                break
            lines.append(line)
        else:
            return {}
    found = {}
    spelling = {}
    list_key = ""
    for line in lines[1:]:
        key = KEY_LINE.match(line)
        if key:
            list_key = ""
            name = key.group(1).lower()
            if spelling.setdefault(name, key.group(1)) != key.group(1):
                continue
            values = found.setdefault(name, [])
            if key.group(2) == "":
                list_key = name
            else:
                values.extend(split_values(key.group(2)))
        elif list_key:
            item = LIST_ITEM.match(line)
            if item:
                found[list_key].append(item.group(1))
    return {k: [v for v in (clean(v) for v in vs) if v] for k, vs in found.items()}


def iso_date(value):
    """Return the YYYY-MM-DD part of an ISO date or datetime, or "" when it is not one."""
    match = ISO_DATE.fullmatch(value)
    try:
        return datetime.date.fromisoformat(match.group(1)).isoformat() if match else ""
    except ValueError:
        return ""


def note_date(fields):
    """Return (date, bad): the first ISO "updated" else "created" date, else "" and the raw value."""
    values = fields.get("updated", [])[:1] + fields.get("created", [])[:1]
    good = next((d for d in map(iso_date, values) if d), "")
    return good, "" if good else (values or [""])[0]


def scan(vault):
    """Yield (relative path, lowercase statuses, date, bad date) for every note."""
    for path in note_files(vault):
        fields = note_fields(path)
        yield (path.relative_to(vault).as_posix(), {v.lower() for v in fields.get("status", [])},
               *note_date(fields))


def overview(vault):
    """Return (found, lines): one "<status>: <count>" line per status in the vault."""
    counts = {}
    no_status = 0
    for _, statuses, _, _ in scan(vault):
        no_status += not statuses
        for value in statuses:
            counts[value] = counts.get(value, 0) + 1
    if not counts:
        return False, ["Nothing found."]
    order = sorted(counts, key=lambda v: (LIFECYCLE.index(v) if v in LIFECYCLE else len(LIFECYCLE), v))
    return True, [f"{v}: {counts[v]}" for v in order] + ([f"(no status): {no_status}"] if no_status else [])


def hint(want, known):
    """Return "did you mean: <status>" for a close vault status, or "" when none fits."""
    close = difflib.get_close_matches(want.lower(), sorted(known), n=1)
    return f"did you mean: {close[0]}" if close else ""


def lookup(vault, wanted, cap=BLOCK_CAP):
    """Return (found, lines): one block per wanted status, oldest first, or "Nothing found.".

    A block stops after cap notes with "- ... and <n> more"; cap None shows all.
    """
    hits = {i: [] for i in range(len(wanted))}
    known = set()
    for rel, statuses, date, bad in scan(vault):
        known |= statuses
        label = f" ({date})" if date else f" (bad date: {bad})" if bad else ""
        for i, want in enumerate(wanted):
            if want.lower() in statuses:
                hits[i].append((date == "", date, rel, label))
    hints = {i: hint(want, known) for i, want in enumerate(wanted)
             if not hits[i] and want.lower() not in LIFECYCLE}
    if not any(hits.values()):
        return False, ["Nothing found."] + [f"{wanted[i]}: {h}" for i, h in hints.items() if h]
    lines = []
    for i, want in enumerate(wanted):
        lines.append(f"{want}:")
        if not hits[i]:
            lines.append("- nothing found")
            if hints.get(i):
                lines.append(f"- {hints[i]}")
        notes = sorted(hits[i])
        lines.extend(f"- {rel}{label}" for _, _, rel, label in notes[:cap])
        if cap is not None and len(notes) > cap:
            lines.append(f"- ... and {len(notes) - cap} more")
    return True, lines


def run(argv):
    """Do the work. Returns the exit code."""
    if argv == ["-"]:
        sys.stdin.reconfigure(encoding="utf-8")
        argv = [sys.stdin.read()]
    try:
        parsed = parse_words(argv)
    except UsageError as err:
        print(f"SYSTEM ERROR: status.py: {err}", file=sys.stderr)
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if parsed is None:
        print(__doc__.strip())
        return 0
    words, show_all = parsed

    vault = require_vault()
    for word in words:
        if not STATUS_WORD.fullmatch(word):
            print(f"ERROR: invalid status '{word}': use words of letters, digits, _ or -, "
                  "then run /wiki-query:status <status>... again")
            return 0

    try:
        found, result = lookup(vault, words, None if show_all else BLOCK_CAP) if words else overview(vault)
    except OSError as err:
        print(f"SYSTEM ERROR: status.py: {err}", file=sys.stderr)
        return 1

    print(f"found: {'yes' if found else 'no'}")
    print("\n".join(result))
    return 0


def main():
    # Notes may hold any Unicode; always write UTF-8 with LF line ends.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
