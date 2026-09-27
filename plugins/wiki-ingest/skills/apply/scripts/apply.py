#!/usr/bin/env python3
"""apply.py: set frontmatter status review to evergreen in the configured vault.

Model-run, has side effects. Python 3 standard library only.

usage: apply.py [<note name> | <folder>/<note>.md]

Mark review notes in the vault as evergreen. The only edit is the frontmatter
line "status: review", which becomes "status: evergreen". No moves, no other
change. The vault comes from ~/.claude/obsidian-wiki/vault-path.

arguments:
  none or ""        every note in the vault with status review (dot folders skipped)
  <note name>       one note by filename without .md, case-insensitive, any folder
  <folder>/<n>.md   one note by its path from the vault root (to pick between matches)

output (stdout):
  evergreen: <path from vault root>   one line per changed note
  count: <n>                          number of changed notes (0 is a normal result)
  match: <path>                       exit 3 only, one line per note with that name

exit codes:
  0  done (count may be 0)
  1  system error (vault path missing, edit failed)
  2  bad usage (more than one argument)
  3  user error (no note with that name, several matches, status is not review)

examples: apply.py
          apply.py "Context Engineering"
          apply.py "30. Knowledge/Context Engineering.md"
"""

import os
import re
import sys
from pathlib import Path

# vault.py lives in the plugin scripts folder: plugins/wiki-ingest/scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import read_vault, VaultError  # noqa: E402

FENCE = re.compile(r"^---[ \t]*$")
# Undecodable bytes survive a read and write unchanged.
ENCODING = {"encoding": "utf-8", "errors": "surrogateescape", "newline": ""}


class Exit(Exception):
    """Stop with a stderr message and an exit code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def system_error(message):
    return Exit(1, f"SYSTEM ERROR: apply.py: {message}")


def user_error(message):
    return Exit(3, f"USER ERROR: apply.py: {message}")


def parse_argument(raw):
    """Return (mode, arg). Mode is all, path or name."""
    arg = raw.strip(" \t")
    if arg.startswith("./"):
        arg = arg[2:]
    if not arg:
        return "all", ""
    if "/" in arg:
        return "path", arg if arg.endswith(".md") else arg + ".md"
    return "name", arg[:-3] if arg.endswith(".md") else arg


def list_notes(vault):
    """Every .md file below the vault as a posix path, skipping dot folders."""
    notes = []
    for folder, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if not (d.startswith(".") and len(d) > 1)]
        for name in files:
            if name.endswith(".md"):
                notes.append((Path(folder) / name).relative_to(vault).as_posix())
    return sorted(notes)


def unquote(value):
    """Drop one pair of surrounding double or single quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_status(file):
    """Return (line number, value) of the first status line in the frontmatter.

    The frontmatter is the block between a first line "---" and the next "---".
    Line number 0 means no status. None means an empty file (not a note).
    """
    text = file.read_text(**ENCODING)
    if not text:
        return None
    lines = text.split("\n")
    if not FENCE.match(lines[0].removesuffix("\r")):
        return 0, ""
    for number, line in enumerate(lines[1:], start=2):
        line = line.removesuffix("\r")
        if FENCE.match(line):
            break
        if line.startswith("status:"):
            value = line[len("status:"):].lstrip(" \t").rstrip(" \t")
            return number, unquote(value)
    return 0, ""


def read_records(vault):
    """One (path, status line number, status value) per note, sorted by path."""
    records = []
    for path in list_notes(vault):
        status = read_status(vault / path)
        if status is not None:
            records.append((path, *status))
    return records


def select(records, mode, arg):
    """Notes for this mode: all review notes, or the notes matching a path or name."""
    wanted = arg.lower()
    if mode == "all":
        return [r for r in records if r[1] > 0 and r[2] == "review"]
    if mode == "path":
        return [r for r in records if r[0].lower() == wanted]
    return [r for r in records if Path(r[0]).name.removesuffix(".md").lower() == wanted]


def check_single(selected, arg):
    """For a name or path: exactly one note, with status review."""
    if not selected:
        raise user_error(f'no note named "{arg}" in the vault')
    if len(selected) > 1:
        for path, _, _ in selected:
            print(f"match: {path}")
        raise user_error(f'several notes named "{arg}", run again with one path from the match lines')
    path, number, value = selected[0]
    if number == 0:
        raise user_error(f"{path} has no status in its frontmatter, nothing changed")
    if value != "review":
        raise user_error(f"{path} has status {value}, not review, nothing changed")


def set_evergreen(file, number):
    """Replace line <number> with "status: evergreen", keeping its CRLF or LF ending."""
    lines = file.read_text(**ENCODING).split("\n")
    ending = "\r" if lines[number - 1].endswith("\r") else ""
    lines[number - 1] = "status: evergreen" + ending
    with file.open("w", **ENCODING) as out:
        out.write("\n".join(lines))


def run(argv):
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n", 2)[2].strip())
        return 0
    if len(argv) > 1:
        raise Exit(2, f"SYSTEM ERROR: apply.py: expected at most one argument, got {len(argv)}. "
                      "Quote a name with spaces. See --help")
    try:
        vault = read_vault()
    except VaultError as err:
        raise system_error(str(err))

    mode, arg = parse_argument(argv[0] if argv else "")
    selected = select(read_records(vault), mode, arg)
    if mode != "all":
        check_single(selected, arg)

    for path, number, _ in selected:
        try:
            set_evergreen(vault / path, number)
        except OSError as err:
            raise system_error(f"edit failed for {path}: {err}")
        print(f"evergreen: {path}")
    print(f"count: {len(selected)}")
    return 0


def main(argv):
    # Note paths can hold any character; the Windows console default codepage cannot.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    try:
        return run(argv)
    except Exit as stop:
        sys.stdout.flush()
        print(stop, file=sys.stderr)
        return stop.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
