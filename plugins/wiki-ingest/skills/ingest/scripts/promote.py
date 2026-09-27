#!/usr/bin/env python3
"""usage: promote.py <note> <folder> <review|archived>

Move a draft from "01. Inbox" to <folder> with its filename unchanged, and set
the frontmatter status. Run only for rows the user approved. Never deletes.
When <folder> is the note's own folder, only the status is set (merge target).
Safe to rerun: a moved note whose status is still draft gets its status set;
a note already at <folder>/<name> with <status> is reported as already done.
The vault comes from vault.py (the configured vault path).

arguments:
  <note>         note path from the vault root, e.g. "01. Inbox/Tokens.md"
  <folder>       destination folder from the vault root, e.g. "30. Knowledge"
  <status>       review (filed draft or merge target), archived (merge source)

output (stdout):
  path: <path after the move>
  status: <status now in the frontmatter>
  unchanged: already done      only on a rerun that finds the work done
  ERROR: <message>             vault problem (path missing, no CLAUDE.md), exit 0

exit codes:
  0  moved or status set (or already done), or an ERROR line
  1  system error (read, write or move failed)
  2  bad usage (wrong arguments)
  3  user error (note missing, not a draft in 01. Inbox, folder missing, name clash)

example: promote.py "01. Inbox/Tokens.md" "30. Knowledge" review
"""

import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault  # noqa: E402

INBOX = "01. Inbox"
STATUSES = ("review", "archived")
DASHES = re.compile(r"^---[ \t]*$")


class Fail(Exception):
    """An error line for stderr plus the exit code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def sys_error(msg):
    return Fail(1, f"SYSTEM ERROR: promote.py: {msg}")


def bad(msg):
    return Fail(2, f"SYSTEM ERROR: promote.py: {msg}, see --help")


def user_error(msg):
    return Fail(3, f"USER ERROR: promote.py: {msg}")


def read_text(path):
    """Read a note as is: newline="" keeps CRLF, surrogateescape keeps odd bytes."""
    try:
        return path.open(encoding="utf-8", errors="surrogateescape", newline="").read()
    except OSError as err:
        raise sys_error(f"cannot read {path.name}: {err}")


def split_lines(text):
    """Lines without their final \\n; a \\r before it stays in the line."""
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def fm_status(path):
    """The frontmatter status value, empty when there is none."""
    for number, line in enumerate(split_lines(read_text(path)), 1):
        line = line.removesuffix("\r")
        if number == 1:
            if not DASHES.match(line.removeprefix("\ufeff")):
                return ""
            continue
        if DASHES.match(line):
            return ""
        if line.startswith("status:"):
            value = re.sub(r"^status:[ \t]*", "", line)
            value = re.sub(r"[ \t\"']+$", "", value)
            return re.sub(r"^[\"']", "", value)
    return ""


def with_status(text, status):
    """Return text with the frontmatter status set (rewritten or added), or None without frontmatter."""
    out, in_fm, done = [], False, False
    for number, line in enumerate(split_lines(text), 1):
        cr = "\r" if line.endswith("\r") else ""
        bare = line.removesuffix("\r")
        if number == 1:
            if not DASHES.match(bare.removeprefix("\ufeff")):
                return None
            in_fm = True
        elif in_fm and DASHES.match(bare):
            if not done:
                out.append(f"status: {status}{cr}")  # no status line yet: add one before the closing ---
            in_fm, done = False, True
        elif in_fm and bare.startswith("status:"):
            out.append(f"status: {status}{cr}")
            done = True
            continue
        out.append(line)
    if not done:
        return None
    return "".join(line + "\n" for line in out)


def set_status(vault, rel, status):
    """Rewrite the status line of a note through a temp file next to it."""
    path = vault / rel
    text = with_status(read_text(path), status)
    if text is None:
        raise user_error(f"{rel} has no frontmatter, add one before promoting")
    try:
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError as err:
        raise sys_error(f"cannot write {rel}: {err}")


def report(vault, rel):
    print(f"path: {rel}")
    print(f"status: {fm_status(vault / rel)}")


def status_words(status):
    return f"status {status}" if status else "no status"


def clean_path(raw):
    raw = raw.replace("\\", "/")
    return raw[2:] if raw.startswith("./") else raw


def parse_args(argv):
    """Return (note, folder, status) with paths in vault-root form."""
    if len(argv) != 3:
        raise bad("expected <note> <folder> <status>")
    note, folder, status = argv
    if status not in STATUSES:
        raise bad(f"status must be review or archived, got '{status}'")
    note = clean_path(note)
    folder = clean_path(folder).removesuffix("/")
    # Any part starting with a dot: ".." leaves the vault, ".x" is a dot folder.
    if "/." in f"/{note}/{folder}/":
        raise bad("path leaves the vault or enters a dot folder")
    if not folder or not note.endswith(".md"):
        raise bad("note must be a .md path and folder must not be empty")
    return note, folder, status


def promote(vault, note, folder, status):
    name = note.rsplit("/", 1)[-1]
    src_dir = note.rsplit("/", 1)[0] if "/" in note else "."
    dest = f"{folder}/{name}"

    # In place: only the status changes (merge target).
    if src_dir == folder:
        if not (vault / note).is_file():
            raise user_error(f"note not found: {note}")
        if folder == INBOX:
            raise user_error(f"{note} stays in {INBOX}, a draft gets review only by moving out")
        set_status(vault, note, status)
        report(vault, note)
        return

    if not (vault / note).is_file():
        if src_dir != INBOX or not (vault / dest).is_file():
            raise user_error(f"note not found: {note}")
        current = fm_status(vault / dest)
        if current == status:
            report(vault, dest)
            print("unchanged: already done")
            return
        # Resume: an earlier run moved the draft but did not set the status.
        if current != "draft":
            raise user_error(f"note not found: {note}, and {dest} has {status_words(current)}")
        set_status(vault, dest, status)
        report(vault, dest)
        return

    if src_dir != INBOX:
        raise user_error(f"{note} is not in {INBOX}, ingest only moves Inbox drafts")
    current = fm_status(vault / note)
    if current != "draft":
        raise user_error(f"{note} has {status_words(current)}, ingest only moves drafts")
    if not (vault / folder).is_dir():
        raise user_error(f"destination folder not found: {folder}")
    clash = user_error(f"name clash: {dest} already exists, {note} stays in {INBOX}")
    if (vault / dest).exists():
        raise clash
    try:
        (vault / note).rename(vault / dest)
    except FileExistsError:
        raise clash
    except OSError as err:
        raise sys_error(f"cannot move {note} to {dest}: {err}")
    set_status(vault, dest, status)
    report(vault, dest)


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    try:
        note, folder, status = parse_args(argv)
        promote(require_vault(), note, folder, status)
    except Fail as fail:
        print(fail, file=sys.stderr)
        return fail.code
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(main(sys.argv[1:]))
