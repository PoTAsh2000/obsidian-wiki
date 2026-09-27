#!/usr/bin/env python3
"""usage: search.py --vault <dir> [--limit <n>] <term>...

Rank the notes in an Obsidian vault by how well they match the terms. Read-only.
Case-insensitive substring match on filename, first "# " title, aliases, tags,
topic and body lines. Skips dot folders, Attachments, "90. Templates" and
the vault root CLAUDE.md.

arguments:
  --vault <dir>  vault root (required)
  --limit <n>    max notes to list, 1-200, default 20
  <term>...      one or more terms; quote a phrase as one term

output (sorted by score, then path):
  terms: <term>, ...
  matches: <notes with any hit>
  shown: <listed>
  - <path> | score: <n> | status: <status or none> | terms: <hit>/<given> | in: <fields>
  fields: name, title, alias, tag, topic, body:<line hits summed over terms>

exit codes:
  0  searched (matches: 0 means nothing found)
  1  system error (cannot read a note)
  2  bad usage (missing or invalid argument)
  3  user error (vault folder not found)

example: search.py --vault "$HOME/Vault" "EDI" "mapping" "edifact"
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import to_native  # noqa: E402

DEFAULT_LIMIT = 20
SKIP_ROOT_DIRS = {"Attachments", "90. Templates"}
META_KEYS = ("aliases", "tags", "topic", "status")
# (field shown in output, points per term), in output order
FIELDS = (("name", 10), ("title", 10), ("alias", 6), ("tag", 4), ("topic", 4))
BODY_CAP = 5

FM_FENCE = re.compile(r"^---[ \t]*$")
FM_KEY = re.compile(r"^([A-Za-z_]+):[ \t]*(.*)$")
FM_ITEM = re.compile(r"^[ \t]*-[ \t]*(.*)$")
CODE_FENCE = re.compile(r"^[ \t]*(```|~~~)")
LIMIT_RE = re.compile(r"^[1-9][0-9]{0,2}$")


class UsageError(Exception):
    """Bad arguments: exit 2."""


def parse_args(argv):
    """Return (vault, limit, terms), or None when help was printed."""
    vault, limit, terms = "", str(DEFAULT_LIMIT), []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            print(__doc__.strip())
            return None
        if arg in ("--vault", "--limit"):
            if i + 1 >= len(argv):
                raise UsageError("--vault needs a folder" if arg == "--vault" else "--limit needs a number")
            if arg == "--vault":
                vault = argv[i + 1]
            else:
                limit = argv[i + 1]
            i += 2
        elif arg == "--":
            terms += argv[i + 1:]
            break
        elif arg.startswith("-"):
            raise UsageError(f"unknown option: {arg}")
        else:
            terms.append(arg)
            i += 1
    if not vault:
        raise UsageError("no vault: pass --vault <dir>")
    if not LIMIT_RE.match(limit) or int(limit) > 200:
        raise UsageError(f"invalid --limit: {limit}")
    if not terms:
        raise UsageError("no search term given")
    for term in terms:
        if not term.strip():
            raise UsageError("empty search term")
        if "\n" in term or "\t" in term:
            raise UsageError("search term contains a newline or tab")
    return vault, int(limit), terms


def find_notes(root):
    """Yield (relative posix path, Path) of every searchable .md note, unsorted."""
    for path in root.rglob("*.md"):
        rel = path.relative_to(root)
        folders = rel.parts[:-1]
        if any(p.startswith(".") for p in folders):
            continue
        if folders and folders[0] in SKIP_ROOT_DIRS:
            continue
        # rglob ignores case on Windows, find -name did not
        if not path.name.endswith(".md") or rel.as_posix() == "CLAUDE.md" or not path.is_file():
            continue
        yield rel.as_posix(), path


def read_lines(path):
    """Lines of a note without line endings (CRLF or LF)."""
    text = path.read_bytes().decode("utf-8", errors="replace")
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def clean(value):
    """Trim blanks and one surrounding quote on each side, lowercase."""
    value = value.strip(" \t")
    value = re.sub(r"^[\"']", "", value)
    value = re.sub(r"[\"']$", "", value)
    return value.lower()


def parse_note(lines):
    """Return (meta, status, title, body lines) of a note, all lowercase."""
    meta = {key: [] for key in META_KEYS if key != "status"}
    status, title, titled, body = "none", "", False, []

    def add(key, value):
        nonlocal status
        value = clean(value)
        if not value:
            return
        if key == "status":
            status = value
        else:
            meta[key].append(value)

    start = 0
    if lines and FM_FENCE.match(lines[0]):
        # frontmatter runs to the next "---" line, or to the end of the file
        start = len(lines)
        list_key = ""
        for n, line in enumerate(lines[1:], start=1):
            if FM_FENCE.match(line):
                start = n + 1
                break
            key = FM_KEY.match(line)
            item = FM_ITEM.match(line)
            if key:
                list_key = ""
                name, value = key.groups()
                if name in META_KEYS:
                    if value == "":
                        list_key = name
                    elif value.startswith("[") and value.endswith("]") and len(value) >= 2:
                        for part in value[1:-1].split(","):
                            add(name, part)
                    else:
                        add(name, value)
            elif list_key and item:
                add(list_key, item.group(1))

    in_fence = False
    for line in lines[start:]:
        if CODE_FENCE.match(line):
            in_fence = not in_fence
        if not titled and not in_fence and line.startswith("# "):
            title, titled = line[2:].lower(), True
        body.append(line.lower())
    return meta, status, title, body


def score_note(path, lines, terms):
    """Return the output line and score of a note, or None when no term hits."""
    meta, status, title, body = parse_note(lines)
    name = Path(path).name
    name = (name[:-3] if name.endswith(".md") else name).lower()
    fields = {"name": [name], "title": [title] if title else [],
              "alias": meta["aliases"], "tag": meta["tags"], "topic": meta["topic"]}
    score = hits = body_hits = 0
    found = set()
    for term in terms:
        hit = False
        for field, points in FIELDS:
            if any(term in value for value in fields[field]):
                score += points
                found.add(field)
                hit = True
        lines_hit = sum(1 for line in body if term in line)
        if lines_hit:
            score += min(lines_hit, BODY_CAP)
            body_hits += lines_hit
            hit = True
        hits += hit
    if not hits:
        return None
    where = [field for field, _ in FIELDS if field in found]
    if body_hits:
        where.append(f"body:{body_hits}")
    line = (f"- {path} | score: {score} | status: {status} | "
            f"terms: {hits}/{len(terms)} | in: {','.join(where)}")
    return score, line


def main(argv):
    try:
        parsed = parse_args(argv)
    except UsageError as err:
        print(f"SYSTEM ERROR: search.py: {err}, see --help", file=sys.stderr)
        return 2
    if parsed is None:
        return 0
    vault, limit, terms = parsed

    root = Path(to_native(vault))
    if not root.is_dir():
        print(f"USER ERROR: search.py: vault folder not found: {vault}", file=sys.stderr)
        return 3

    print(f"terms: {', '.join(terms)}")
    lowered = [term.lower() for term in terms]
    ranked = []
    for path, file in find_notes(root):
        try:
            lines = read_lines(file)
        except OSError as err:
            print(f"SYSTEM ERROR: search.py: cannot read {path}: {err}", file=sys.stderr)
            return 1
        result = score_note(path, lines, lowered)
        if result:
            ranked.append((-result[0], path.encode("utf-8"), result[1]))
    ranked.sort()

    shown = min(len(ranked), limit)
    print(f"matches: {len(ranked)}")
    print(f"shown: {shown}")
    for _, _, line in ranked[:shown]:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
