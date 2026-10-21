#!/usr/bin/env python3
"""usage: frontmatter.py [--run <id>] [--new-type] [--approved] <note> [key=value | key+=value ...]

Write the frontmatter of one note as one canonical block, for the approved
"actions: formatter", "set ..." and "add ..." rows. The model picks the values;
this script writes them the same way every time:
  - schema keys first, in this order: type, topic, aliases, tags, created, related,
    source; every other key (status too) after them, as it was
  - aliases, tags and related as YAML lists without duplicates (case-insensitive),
    related as quoted "[[links]]", tags without a leading #
  - created as an ISO date YYYY-MM-DD; when the note has none and none is passed,
    the file date
  - status is never changed; CRLF, a BOM and odd bytes are kept
Works on a draft directly in "01. Inbox"; any other note only with --approved (a
note named in an approved orphan or merge row). Writes through a temp file next to
the note. --run <id> (from select.py) records the change in the run ledger.

arguments:
  <note>           note path from the vault root, e.g. "01. Inbox/Tokens.md"
  key=value        set a key; for a list key, repeat it for several values, the
                   given values replace the list; key= clears it
  key+=value       add one value to a list key (aliases, tags, related)
  --new-type       allow a type that is not in the vault's "Allowed `type` values"
                   line, only for an approved "new type:" row
  --approved       the note is not an Inbox draft but named in an approved row

output (stdout):
  frontmatter: <path>   the block was written
  unchanged: <path>     the block was already canonical with these values
  ERROR: <message>      vault problem (path missing, no CLAUDE.md), exit 0

exit codes:
  0  written or unchanged, or an ERROR line
  1  system error (read or write failed)
  2  bad usage (wrong arguments, unknown key, status, a created that is no date)
  3  user error (note missing or without frontmatter, not an Inbox draft without
     --approved, a type not in the allowed list without --new-type)

example: frontmatter.py --run 20261020-101500-1a2b "01. Inbox/Tokens.md" type=concept "tags+=ai" "related+=LLM"
"""

import datetime
import json
import re
import sys
from pathlib import Path

import ledger
import relink
from promote import DASHES, INBOX, Fail, rel_path, fm_status, read_text, split_lines
from vault import require_vault

SCHEMA = ("type", "topic", "aliases", "tags", "created", "related", "source")
LISTS = ("aliases", "tags", "related")
KEY = re.compile(r"^([A-Za-z_][\w-]*):[ \t]*(.*)$")
ITEM = re.compile(r"^[ \t]*-[ \t]*(.*)$")
WIKILINK = re.compile(r"\[\[[^\]\r\n]+\]\]")
DATE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
SAFE = re.compile(r"[\w][\w .()&'/-]*")


def bad(msg):
    return Fail(2, f"SYSTEM ERROR: frontmatter.py: {msg}, see --help")


def user_error(msg):
    return Fail(3, f"USER ERROR: frontmatter.py: {msg}")


def unquote(value):
    return re.sub(r"^[\"']|[\"']$", "", value.strip(" \t"))


def quote(value):
    return value if SAFE.fullmatch(value) and not value.endswith(" ") else json.dumps(value, ensure_ascii=False)


def parse_args(argv):
    """Return (note, {key: values to set}, {key: values to add}, new_type, approved)."""
    flags = {"--new-type", "--approved"}
    new_type, approved = "--new-type" in argv, "--approved" in argv
    rest = [a for a in argv if a not in flags]
    if not rest:
        raise bad("expected <note> [key=value ...]")
    note = rel_path(rest[0])
    if "/." in f"/{note}/" or not note.endswith(".md"):
        raise bad("note must be a .md path inside the vault, not in a dot folder")
    sets, adds = {}, {}
    for arg in rest[1:]:
        m = re.fullmatch(r"([a-z]+)(\+?=)(.*)", arg, re.S)
        if not m:
            raise bad(f"'{arg}' is not key=value or key+=value")
        key, op, value = m.group(1), m.group(2), m.group(3).strip(" \t")
        if key == "status":
            raise bad("status is never set here, promote.py and merge.py set it")
        if key not in SCHEMA:
            raise bad(f"unknown key '{key}', known: {', '.join(SCHEMA)}")
        if "\n" in value or "\r" in value:
            raise bad(f"{key}: value must be one line")
        if op == "+=" and key not in LISTS:
            raise bad(f"{key} is not a list, use {key}=value")
        if key == "created" and value and not iso_date(value):
            raise bad(f"created must be a date YYYY-MM-DD, got '{value}'")
        target = adds if op == "+=" else sets
        target.setdefault(key, [])
        if value:
            target[key].append(value)
    return note, sets, adds, new_type, approved


def iso_date(value):
    m = DATE.match(value.strip(" \t\"'"))
    if not m:
        return ""
    try:
        return datetime.date(*map(int, m.groups())).isoformat()
    except ValueError:
        return ""


def allowed_types(vault):
    """The values of the vault CLAUDE.md line "Allowed `type` values: `a`, `b`", as wiki-lint reads it."""
    for line in read_text(vault / "CLAUDE.md").split("\n"):
        if "Allowed `type` values" in line:
            rest = line.split(":", 1)[1] if ":" in line else line
            return {t.casefold() for t in " ".join(re.findall(r"`([^`]*)`", rest)).split()}
    return set()


def split_block(lines):
    """Return (end index of the closing ---, [(key or None, [lines])]) of the frontmatter."""
    end = next((i for i in range(1, len(lines)) if DASHES.match(lines[i].removesuffix("\r"))), None)
    if end is None:
        return None, []
    entries = []
    for line in lines[1:end]:
        m = KEY.match(line.removesuffix("\r"))
        if m or not entries:
            entries.append((m.group(1) if m else None, [line]))
        else:
            entries[-1][1].append(line)  # an indented value, a list item or a blank line
    return end, entries


def values_of(key, entry_lines):
    """The values of one entry as a list of strings."""
    text = "\n".join(line.removesuffix("\r") for line in entry_lines)
    if key == "related":
        return WIKILINK.findall(text)
    first = KEY.match(entry_lines[0].removesuffix("\r")).group(2).strip(" \t")
    out = []
    if first.startswith("[") and first.endswith("]"):
        out += [unquote(v) for v in first[1:-1].split(",")]
    elif first and not first.startswith(("|", ">")):
        out.append(unquote(first))
    for line in entry_lines[1:]:
        m = ITEM.match(line.removesuffix("\r"))
        if m:
            out.append(unquote(m.group(1)))
    return [v for v in out if v]


def normal(key, value):
    value = value.strip(" \t")
    if key == "tags":
        return value.lstrip("#").strip(" \t")
    if key == "related":
        inner = unquote(value)
        return inner if inner.startswith("[[") else f"[[{inner.removesuffix('.md')}]]"
    if key == "created":
        return iso_date(value) or value
    return unquote(value)


def dedupe(values):
    seen, out = set(), []
    for v in values:
        if v and v.casefold() not in seen:
            seen.add(v.casefold())
            out.append(v)
    return out


def canonical(text, sets, adds, file_date):
    """Return the note text with its frontmatter block rewritten, or None without frontmatter."""
    lines = split_lines(text)
    if not lines or not DASHES.match(lines[0].removesuffix("\r").removeprefix("﻿")):
        return None
    end, entries = split_block(lines)
    if end is None:
        return None
    cr = "\r" if lines[0].endswith("\r") else ""
    have, other = {}, []
    for key, entry_lines in entries:
        if key in SCHEMA:
            have.setdefault(key, []).extend(values_of(key, entry_lines))
        else:
            other.extend(entry_lines)
    block = [lines[0]]
    for key in SCHEMA:
        values = sets[key] if key in sets else have.get(key, [])
        values = dedupe([normal(key, v) for v in values + adds.get(key, [])])
        if key == "created" and not values:
            values = [file_date]
        if key in LISTS:
            if not values:
                block.append(f"{key}: []{cr}")
            else:
                block.append(f"{key}:{cr}")
                block += [f"  - {json.dumps(v, ensure_ascii=False) if key == 'related' else quote(v)}{cr}"
                          for v in values]
        else:
            block.append(f"{key}: {quote(values[0])}{cr}" if values else f"{key}:{cr}")
    block += [line if line.endswith("\r") or not cr else line + cr for line in other]
    return "".join(line + "\n" for line in block + lines[end:])


def file_date(path):
    st = path.stat()
    stamp = min(getattr(st, "st_birthtime", st.st_mtime), st.st_mtime)
    return datetime.date.fromtimestamp(stamp).isoformat()


def write(vault, note, sets, adds, new_type, approved, run=None):
    path = vault / note
    if not path.is_file():
        raise user_error(f"note not found: {note}")
    in_inbox = re.fullmatch(re.escape(INBOX) + r"/[^/]+", note) is not None
    if not approved and not (in_inbox and fm_status(path) == "draft"):
        raise user_error(f"{note} is not a draft directly in {INBOX}; "
                         "pass --approved only for a note named in an approved orphan or merge row")
    for t in sets.get("type", []):
        if not new_type and t.casefold() not in allowed_types(vault):
            raise user_error(f"type '{t}' is not in the vault's allowed types; "
                             "plan a 'new type:' row and pass --new-type once it is approved")
    text = read_text(path)
    new = canonical(text, sets, adds, file_date(path))
    if new is None:
        raise user_error(f"{note} has no frontmatter, add one with --- lines first")
    if new == text:
        print(f"unchanged: {note}")
        return
    relink.write_note(path, note, new, text)
    ledger.record(run, "changed", note)
    print(f"frontmatter: {note}")


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    try:
        run, argv = ledger.pop_run(argv, bad)
        note, sets, adds, new_type, approved = parse_args(argv)
        write(require_vault(), note, sets, adds, new_type, approved, run)
    except (Fail, relink.Fail) as fail:
        print(str(fail).replace("promote.py:", "frontmatter.py:").replace("relink.py:", "frontmatter.py:"),
              file=sys.stderr)
        return fail.code
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(main(sys.argv[1:]))
