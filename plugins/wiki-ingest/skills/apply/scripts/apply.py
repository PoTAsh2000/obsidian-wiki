#!/usr/bin/env python3
"""apply.py: set frontmatter status review to evergreen in the configured vault.

Model-run, has side effects. Python 3 standard library only.

usage: apply.py [--dry-run] [<note name> | <folder>/<note>.md]

Mark review notes in the vault as evergreen. The only edit is the frontmatter
line "status: review", which becomes "status: evergreen". No moves, no other
change. The vault comes from ~/.claude/obsidian-wiki/vault-path.

arguments:
  none or ""        every note in the vault with status review (dot folders skipped)
  <note name>       one note by filename without .md, case-insensitive, any folder
  <folder>/<n>.md   one note by its path from the vault root (to pick between matches)
  --dry-run         select and check as a real run, print what would change, write nothing
Several arguments are joined with single spaces into one name; a leading
"--dry-run" word in that joined text counts as the flag.

output (stdout): the final report for the user, a heading with one backticked
path per line ("Moved from review to evergreen:", or the line "No notes moved
from review to evergreen."), then "Changed during the run, left as review" and
"Still in 01. Inbox, left as review" sections when there are such notes. A full
run also lists, changing nothing, notes whose status only looks like review
("Review", "review # checked", "reviewed"), notes with more than one status
line and notes whose frontmatter has no closing "---".
On exit 3 stdout is the reply for the user instead: the reason as a sentence
with the path in backticks, or for several notes with that name one backticked
path per line and the question "Which one? Run /wiki-ingest:apply with its path."
  ERROR: <message>    vault problem (path missing, no CLAUDE.md), exit 0

Skipped: dot folders, dot files, symlinks and the vault root CLAUDE.md. Review
notes still in 01. Inbox are never changed: ingest has not filed them yet.

exit codes:
  0  done (the report may say no notes moved), or an ERROR line for a vault problem
  1  system error (edit failed; the report lists the notes that did change)
  3  user error (no note with that name, several matches, status is not exactly
     review, more than one status line, frontmatter not closed, the note is
     still in 01. Inbox, or it changed since it was read)

examples: apply.py
          apply.py --dry-run
          apply.py "--dry-run Context Engineering"
          apply.py "Context Engineering"
          apply.py "30. Knowledge/Context Engineering.md"
"""

import os
import re
import sys
import shutil
import tempfile
import time
from pathlib import Path

# vault.py lives in the plugin scripts folder: plugins/wiki-ingest/scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault  # noqa: E402

INBOX = "01. Inbox"
FENCE = re.compile(r"^---[ \t]*$")
# Undecodable bytes survive a read and write unchanged.
ENCODING = {"encoding": "utf-8", "errors": "surrogateescape", "newline": ""}


class Exit(Exception):
    """Stop with a stderr message, an exit code and optional reply text for stdout."""

    def __init__(self, code, message, text=""):
        super().__init__(message)
        self.code = code
        self.text = text


def system_error(message):
    return Exit(1, f"SYSTEM ERROR: apply.py: {message}")


def user_error(message, text=None):
    """Exit 3; stdout gets text, by default the message itself."""
    return Exit(3, f"USER ERROR: apply.py: {message}", message if text is None else text)


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
    """Every .md file below the vault as a posix path.

    Dot folders, dot files, symlinks and the root CLAUDE.md are skipped.
    """
    notes = []
    for folder, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            full = Path(folder) / name
            if name.startswith(".") or not name.endswith(".md") or full.is_symlink():
                continue
            rel = full.relative_to(vault).as_posix()
            if rel != "CLAUDE.md":
                notes.append(rel)
    return sorted(notes)


def read_text(file):
    """Note text with line endings kept (Path.read_text has no newline before 3.13)."""
    with file.open(**ENCODING) as handle:
        return handle.read()


def unquote(value):
    """Drop one pair of surrounding double or single quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_status(file):
    """Return (line number, value, problem) of the status line in the frontmatter.

    The frontmatter is the block between a first line "---" and the next "---".
    Line number 0 means no status. None means an empty file (not a note).
    Problem "unclosed": no second "---", so no frontmatter (line number 0).
    Problem "duplicate": several top-level status lines; value lists them all.
    """
    return parse_status(read_text(file))


def parse_status(text):
    """read_status for text already read."""
    if not text:
        return None
    lines = text.split("\n")
    if not FENCE.match(lines[0].removeprefix("\ufeff").removesuffix("\r")):
        return 0, "", ""
    found = []
    for number, line in enumerate(lines[1:], start=2):
        line = line.removesuffix("\r")
        if FENCE.match(line):
            if len(found) > 1:
                return found[0][0], ", ".join(v for _, v in found), "duplicate"
            return (*found[0], "") if found else (0, "", "")
        if line.startswith("status:"):
            found.append((number, unquote(line[len("status:"):].strip(" \t"))))
    return 0, "", "unclosed"


def near_review(value):
    """True for a value that only looks like review: other case, a " #" comment, or "reviewed".

    Only the exact value review is ever promoted; these are reported instead.
    """
    if value == "review":
        return False
    end = value.find(value[:1], 1) if value[:1] in ("'", '"') else -1
    value = value[1:end] if end > 0 else value.split(" #", 1)[0].rstrip(" \t")
    return value.lower().startswith("review")


def read_records(vault):
    """One (path, status line number, status value, problem) per note, sorted by path."""
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
        return [r for r in records if r[1] > 0 and r[2] == "review" and not r[3]]
    if mode == "path":
        return [r for r in records if r[0].lower() == wanted]
    return [r for r in records if Path(r[0]).name.removesuffix(".md").lower() == wanted]


def in_inbox(path):
    return path.lower().startswith(INBOX.lower() + "/")


def check_single(selected, arg):
    """For a name or path: exactly one note, with status review, outside the Inbox."""
    if not selected:
        raise user_error(f'No note named "{arg}" in the vault. Nothing changed.')
    if len(selected) > 1:
        raise user_error(f'several notes named "{arg}"', "\n".join(
            [f'Several notes are named "{arg}":', *(f"- `{r[0]}`" for r in selected),
             "Which one? Run /wiki-ingest:apply with its path."]))
    path, number, value, problem = selected[0]
    if problem == "unclosed":
        raise user_error(f"`{path}` frontmatter is not closed (no second ---). Nothing changed.")
    if problem == "duplicate":
        raise user_error(f"`{path}` has more than one status line ({value}), fix it by hand. Nothing changed.")
    if number == 0:
        raise user_error(f"`{path}` has no status in its frontmatter. Nothing changed.")
    if near_review(value):
        raise user_error(f'`{path}` has status "{value}", which is not exactly review '
                         f'(only lowercase review with no # comment counts). Nothing changed.')
    if value != "review":
        raise user_error(f"`{path}` has status {value}, not review. Nothing changed.")
    if in_inbox(path):
        raise user_error(f"`{path}` is still in {INBOX}, run /wiki-ingest:ingest first. Nothing changed.")


# Waits between tries of os.replace: Windows refuses it while another process
# (Obsidian, a sync client, antivirus) holds the note open for a moment.
RETRY_WAITS = (0.05, 0.1, 0.2, 0.3, 0.4)


def set_evergreen(file, number):
    """Replace line <number> with "status: evergreen", keeping its CRLF or LF ending.

    Returns False and writes nothing when that line is no longer the frontmatter
    status review (the note changed since it was read). Written to a temp file with
    the note's mode and moved over the note, so a failed write leaves it whole.
    """
    text = read_text(file)
    if parse_status(text) != (number, "review", ""):
        return False
    lines = text.split("\n")
    ending = "\r" if lines[number - 1].endswith("\r") else ""
    lines[number - 1] = "status: evergreen" + ending
    fd, tmp = tempfile.mkstemp(prefix=file.name + ".", dir=file.parent)
    try:
        with os.fdopen(fd, "w", **ENCODING) as out:
            out.write("\n".join(lines))
        shutil.copymode(file, tmp)  # mkstemp makes 0600
        for wait in (*RETRY_WAITS, None):
            try:
                os.replace(tmp, file)
                break
            except PermissionError:
                if wait is None:
                    raise
                time.sleep(wait)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)  # allow-delete: own temp file after a failed atomic write
        raise
    return True


def section(heading, paths):
    return [heading + ":", *(f"- `{p}`" for p in paths)] if paths else []


def unclear(records):
    """Report lines for notes a full run leaves alone because their status is not clear."""
    def block(heading, rows):
        return [heading + ":", *rows] if rows else []
    return [*block("Status looks like review but is not exact, left as is",
                   [f"- `{p}` (status: {v})" for p, n, v, x in records if n and not x and near_review(v)]),
            *block("Duplicate status, left as is (fix by hand)",
                   [f"- `{p}` (status: {v})" for p, _, v, x in records if x == "duplicate"]),
            *section("Unclosed frontmatter, left as is", [p for p, _, _, x in records if x == "unclosed"])]


def report(moved, changed, skipped, done="Moved from review to evergreen",
           none="No notes moved from review to evergreen.", extra=()):
    """Print the final report. Backticks stop Markdown reading "30." as a list number."""
    lines = section(done, moved) or [none]
    lines += section("Changed during the run, left as review (run again)", changed)
    lines += section(f"Still in {INBOX}, left as review (run /wiki-ingest:ingest first)", skipped)
    print("\n".join([*lines, *extra]))


def run(argv):
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n", 2)[2].strip())
        return 0
    # The skill passes all words as one argument, so "--dry-run Twin" arrives joined.
    words = " ".join(argv).strip(" \t")
    dry_run = words == "--dry-run" or words.startswith("--dry-run ")
    if dry_run:
        words = words[len("--dry-run"):]
    vault = require_vault()

    mode, arg = parse_argument(words)
    records = read_records(vault)
    selected = select(records, mode, arg)
    extra = unclear(records) if mode == "all" else []
    if mode != "all":
        check_single(selected, arg)
    skipped = [r[0] for r in selected if in_inbox(r[0])]
    selected = [r for r in selected if not in_inbox(r[0])]

    if dry_run:
        report([r[0] for r in selected], [], skipped, "Would move from review to evergreen (dry run)",
               "No notes would move from review to evergreen (dry run).", extra)
        return 0

    moved, changed = [], []
    for path, number, *_ in selected:
        try:
            done = set_evergreen(vault / path, number)
        except OSError as err:
            report(moved, changed, skipped, "Moved from review to evergreen before the error", extra=extra)
            raise system_error(f"edit failed for {path}: {err}")
        if not done:
            if mode != "all":
                raise user_error(f"`{path}` changed since it was read. Nothing changed.")
            changed.append(path)
            continue
        moved.append(path)
    report(moved, changed, skipped, extra=extra)
    return 0


def main(argv):
    # Note paths can hold any character; the Windows console default codepage cannot.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    try:
        return run(argv)
    except Exit as stop:
        if stop.text:
            print(stop.text)
        sys.stdout.flush()
        print(stop, file=sys.stderr)
        return stop.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
