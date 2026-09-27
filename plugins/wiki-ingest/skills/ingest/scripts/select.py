#!/usr/bin/env python3
"""usage: select.py [all | <note name>]

List the ingest candidates (status: draft, directly in "01. Inbox") and index
every other note, so the plan needs no extra searches. Read-only.
Run after the full wiki-lint:lint run, because lint moves stray drafts into the Inbox.
The vault comes from vault.py (the configured vault path).

arguments:
  (none) | all   every candidate
  <note name>    one candidate by filename without .md, case-insensitive

output (stdout):
  candidate: <path> [| same name: <path>, ...]   a draft to ingest; same name = filename clash elsewhere
  candidates: <n>
  ERROR: <message>   vault problem (path missing, no CLAUDE.md), exit 0
  note: <path> [| status: <s>] [| aliases: <a>, ...] [| title: <t>]   every other note (dot folders skipped)
  notes: <n>
  index: first <k> of <n> notes listed ...   only when the index passes about 20000
                 characters (env INGEST_INDEX_LIMIT); the rest is not listed

exit codes:
  0  listed (candidates: 0 is a normal result), or an ERROR line
  1  system error (a note cannot be read)
  2  bad usage (wrong arguments)
  3  user error (the named note does not exist, or is not a draft in 01. Inbox)

example: select.py "Tokens"
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault  # noqa: E402

INBOX = "01. Inbox"
DEFAULT_LIMIT = 20000
FENCE = re.compile(r"^[ \t]*(```|~~~)")
DASHES = re.compile(r"^---[ \t]*$")
KEY = re.compile(r"^([A-Za-z_]+):[ \t]*(.*)$")
LIST_ITEM = re.compile(r"^[ \t]*-[ \t]*(.*)$")


class Fail(Exception):
    """An error line for stderr plus the exit code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def sys_error(msg):
    return Fail(1, f"SYSTEM ERROR: select.py: {msg}")


def bad(msg):
    return Fail(2, f"SYSTEM ERROR: select.py: {msg}, see --help")


def user_error(msg):
    return Fail(3, f"USER ERROR: select.py: {msg}")


def clean(value):
    """Trim blanks, then one quote at each end."""
    value = value.strip(" \t")
    value = re.sub(r"^[\"']", "", value)
    return re.sub(r"[\"']$", "", value)


def list_notes(vault):
    """Every .md path from the vault root, dot files and folders skipped, the root CLAUDE.md too."""
    found = []
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            full = Path(root) / name
            if name.startswith(".") or not name.endswith(".md") or full.is_symlink():
                continue
            rel = full.relative_to(vault).as_posix()
            if rel != "CLAUDE.md":
                found.append(rel)
    return sorted(found)


def parse_note(text):
    """Return (status, aliases, title) from the frontmatter and the first # heading."""
    status, aliases, title = "", [], ""
    in_fm = in_aliases = in_fence = False

    def add_alias(value):
        value = clean(value)
        if value:
            aliases.append(value)

    for number, line in enumerate(text.split("\n"), 1):
        line = line.removesuffix("\r")
        if number == 1:
            line = line.removeprefix("\ufeff")
            if DASHES.match(line):
                in_fm = True
                continue
        if in_fm:
            if DASHES.match(line):
                in_fm = False
                continue
            key = KEY.match(line)
            item = LIST_ITEM.match(line)
            if key:
                in_aliases = False
                name, value = key.groups()
                if name == "status":
                    status = clean(value)
                elif name == "aliases":
                    if value == "":
                        in_aliases = True  # a YAML list follows on the next lines
                    elif value.startswith("[") and value.endswith("]"):
                        for part in value[1:-1].split(","):
                            add_alias(part)
                    else:
                        add_alias(value)
            elif in_aliases and item:
                add_alias(item.group(1))
            continue
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("# "):
            title = clean(line[2:])
            break
    return status, ", ".join(aliases), title


def read_records(vault):
    records = []
    for rel in list_notes(vault):
        try:
            text = (vault / rel).read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            raise sys_error(f"cannot read the notes in {vault.as_posix()}: {err}")
        status, aliases, title = parse_note(text)
        records.append({"path": rel, "status": status, "aliases": aliases, "title": title})
    return records


def stem(path):
    return path.rsplit("/", 1)[-1].removesuffix(".md")


def folder_of(path):
    return path.rsplit("/", 1)[0] if "/" in path else "vault root"


def is_candidate(rec):
    return re.fullmatch(r"01\. Inbox/[^/]+", rec["path"]) is not None and rec["status"] == "draft"


def not_found_message(records, want):
    """Explain why no candidate matches the name: wrong status or folder, or no such note."""
    hits = [r for r in records if stem(r["path"]).lower() == want.lower()]
    if not hits:
        return f'no note named "{want}" in the vault'
    parts = []
    for r in hits:
        status = f"status {r['status']}" if r["status"] else "no status"
        parts.append(f"{r['path']} has {status} in {folder_of(r['path'])}")
    return "; ".join(parts) + f", only a draft directly in {INBOX} can be ingested"


def candidate_line(rec, records):
    line = f"candidate: {rec['path']}"
    same = [r["path"] for r in records if r is not rec and stem(r["path"]).lower() == stem(rec["path"]).lower()]
    if same:
        line += " | same name: " + ", ".join(same)
    return line


def note_line(rec):
    line = f"note: {rec['path']}"
    if rec["status"]:
        line += f" | status: {rec['status']}"
    if rec["aliases"]:
        line += f" | aliases: {rec['aliases']}"
    if rec["title"] and rec["title"] != stem(rec["path"]):
        line += f" | title: {rec['title']}"
    return line


def build_output(records, arg, want, limit):
    take_all = arg == "all"
    picked = [r for r in records if is_candidate(r) and (take_all or stem(r["path"]).lower() == want.lower())]
    if not take_all and not picked:
        raise user_error(not_found_message(records, want))
    out = [candidate_line(r, records) for r in picked]
    out.append(f"candidates: {len(picked)}")
    picked_paths = {r["path"] for r in picked}
    others = [r for r in records if r["path"] not in picked_paths]
    size = shown = 0
    for rec in others:
        if size > limit:  # the line that passes the limit is still printed
            break
        line = note_line(rec)
        out.append(line)
        shown += 1
        size += len(line.encode("utf-8")) + 1
    out.append(f"notes: {len(others)}")
    if shown < len(others):
        out.append(f"index: first {shown} of {len(others)} notes listed (output limit), search the vault for the rest")
    return out


def parse_args(argv):
    """Return "all" or the note name."""
    if len(argv) > 1:
        raise bad("too many arguments, quote a note name with spaces")
    return argv[0] if argv and argv[0] else "all"


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    try:
        arg = parse_args(argv)
        vault = require_vault()
        records = read_records(vault)
        want = arg.removesuffix(".md").rsplit("/", 1)[-1]
        limit = os.environ.get("INGEST_INDEX_LIMIT", str(DEFAULT_LIMIT))
        if not re.fullmatch(r"[0-9]+", limit):
            raise bad("INGEST_INDEX_LIMIT must be a number")
        print("\n".join(build_output(records, arg, want, int(limit))))
    except Fail as fail:
        print(fail, file=sys.stderr)
        return fail.code
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(main(sys.argv[1:]))
