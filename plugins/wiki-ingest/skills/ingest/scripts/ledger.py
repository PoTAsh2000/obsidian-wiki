#!/usr/bin/env python3
"""usage: ledger.py --run <id> [<path> ...]

Report on the run ledger of one ingest run. select.py prints the run id; promote.py,
relink.py, merge.py and frontmatter.py get it as --run <id> and append one line per
change to the ledger, a file in the system temp dir (never in the vault). This report
remaps moves, so a note relinked and moved later is listed by its new path. Read-only.
A missing ledger means nothing changed.

arguments:
  --run <id>     the run id from select.py
  <path> ...     notes edited without a script (orphans, drafts kept in 01. Inbox),
                 path from the vault root; listed as file: as given

output (stdout):
  file: <path>                  every changed note at its path now, for wiki-lint:lint --files
  failed: <note> | <error>      a move or merge refused with a user error (left out when
                                the note was moved in another call of the run)
  Moved from draft to review:   then "- `<path>`" per draft moved out of 01. Inbox to review,
                                ready for the final list; or the line
  No notes moved from draft to review.

exit codes:
  0  printed
  1  system error (the ledger cannot be read)
  2  bad usage (no or a wrong --run id)

example: ledger.py --run 20261020-101500-1a2b "40. Projects/Orphan.md"
"""

import hashlib
import re
import secrets
import sys
import tempfile
import time
from pathlib import Path

INBOX = "01. Inbox"
RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def new_run_id():
    return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def ledger_path(run):
    return Path(tempfile.gettempdir()) / f"wiki-ingest-{run}.log"


def pop_run(argv, bad):
    """Return (run id or None, argv without --run <id>); bad(msg) builds the usage error."""
    if "--run" not in argv:
        return None, argv
    at = argv.index("--run")
    if at + 1 >= len(argv) or not RUN_ID.fullmatch(argv[at + 1]):
        raise bad("--run needs the run id from select.py")
    return argv[at + 1], argv[:at] + argv[at + 2:]


def file_hash(path):
    """SHA-256 of the file bytes, to see later whether a note changed."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(run):
    """The ledger rows of a run as lists of fields; [] when there is no ledger. OSError passes."""
    path = ledger_path(run)
    text = path.read_text(encoding="utf-8", errors="surrogateescape") if path.exists() else ""
    return [line.split("\t") for line in text.splitlines() if line]


def record(run, kind, *fields):
    """Append one row: moved <from> <to> | status <path> <value> | changed <path> | failed <note> <error>;
    for plan.py also select <mode> | candidate <path> <hash> | plan <json> | hash <path> <hash> | applied <path>."""
    if run is None:
        return
    line = "\t".join(re.sub(r"[\t\r\n]", " ", str(f)) for f in (kind, *fields))
    try:
        with ledger_path(run).open("a", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
            f.write(line + "\n")
    except OSError as err:
        print(f"SYSTEM ERROR: ledger: cannot write {ledger_path(run)}: {err}", file=sys.stderr)
        raise SystemExit(1)


def report(rows, extra):
    """Return the report lines for ledger rows (lists of fields) plus extra edited paths."""
    changed, status, from_inbox, failed, moved = [], {}, [], [], set()

    def remap(src, dst):
        for paths in (changed, from_inbox):
            paths[:] = [dst if p == src else p for p in paths]
        if src in status:
            status[dst] = status.pop(src)
        moved.add(src)

    for kind, *f in rows:
        if kind == "moved" and len(f) == 2:
            remap(*f)
            changed.append(f[1])
            if f[0].startswith(INBOX + "/"):
                from_inbox.append(f[1])
        elif kind == "status" and len(f) == 2:
            status[f[0]] = f[1]
            changed.append(f[0])
        elif kind == "changed" and len(f) == 1:
            changed.append(f[0])
        elif kind == "failed" and len(f) == 2:
            failed.append(f)
    out = [f"file: {p}" for p in dict.fromkeys(changed + extra)]
    out += [f"failed: {note} | {err}" for note, err in failed if note not in moved]  # moved in another call
    review = [p for p in dict.fromkeys(from_inbox) if status.get(p) == "review"]
    if review:
        out += ["Moved from draft to review:"] + [f"- `{p}`" for p in review]
    else:
        out.append("No notes moved from draft to review.")
    return out


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0

    def bad(msg):
        return ValueError(f"SYSTEM ERROR: ledger.py: {msg}, see --help")

    try:
        run, extra = pop_run(argv, bad)
        if run is None:
            raise bad("--run <id> is required")
    except ValueError as err:
        print(err, file=sys.stderr)
        return 2
    try:
        rows = read_rows(run)
    except OSError as err:
        print(f"SYSTEM ERROR: ledger.py: cannot read {ledger_path(run)}: {err}", file=sys.stderr)
        return 1
    extra = [p.replace("\\", "/").removeprefix("./") for p in extra]
    print("\n".join(report(rows, extra)))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n", errors="surrogateescape")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(main(sys.argv[1:]))
