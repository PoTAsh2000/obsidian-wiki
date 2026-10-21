#!/usr/bin/env python3
"""topic.py: list vault notes by frontmatter topic. Read-only.

usage: topic.py <topic>...   or   topic.py < topics.txt

List notes in the configured Obsidian vault whose frontmatter topic matches,
one block per topic (exact value, case-insensitive with Unicode case folding
and NFC normalization: "Straße" matches "STRASSE", composed and decomposed
accents match). Read-only.
The vault path comes from ~/.claude/obsidian-wiki/vault-path (set by wiki-vault),
read through plugins/wiki-query/scripts/vault.py.
Use it from the topic skill; run it again with the topics the user gives.

Scope: every .md note except dot folders, the root folders Attachments
and "90. Templates", and the vault CLAUDE.md. A note whose frontmatter has
no closing "---" or "..." has no topics. A leading BOM is ignored. Quoted
values follow YAML ('' and \" escapes); a comma inside a quoted inline list
item does not split it. An unquoted " #" starts a comment. A topic
written as a link ([[EDI]], [[30. Knowledge/EDI|EDI]]) is the alias, or
else the last path part without .md. Folder links (symlinks, junctions) are not
followed.

arguments:
  <topic>...  one or more topics. An argument with a comma is split on commas
              and each part trimmed ("Context Engineering, EDI"); otherwise it
              is split on whitespace ("ai tooling" is two topics).
              Without arguments each stdin line is one argument: the skill
              sends the user's text on stdin, so the shell never parses it
  -h, --help  show this help

output:
  "<topic>:" blocks with "- <note path>" lines (sorted case-insensitively),
  or "Nothing found.".
  A note with a frontmatter status gets it appended: "- <note path> (draft)".
  A topic without notes gets "- nothing found" when another topic has notes.
  When a topic has no notes, a last result line "did you mean: <topic>
  (<notes>), ..." names up to three known topics per such topic that
  contain it, are contained in it (3+ characters), or are close in
  spelling (difflib).
  No topics: "ERROR: no topic given" (soft fail, exit 0), then
  "known topics: <topic> (<notes>), ..." when the vault has any: sorted and
  deduplicated case-insensitively, each in its most common spelling.
  Notes or subfolders that cannot be read are skipped and named in one last
  line: "skipped: <n> unreadable note(s): <path>, ...".
  Vault problem (path missing, no CLAUDE.md): "ERROR: <message>" (exit 0).

exit codes:
  0  done (also when nothing is found)
  1  system error (cannot read the vault folder)
  2  bad usage (unknown option)

examples: topic.py EDI      topic.py ai tooling      topic.py "Supply Chain, EDI"
"""

import difflib
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault  # noqa: E402

SKIP_ROOT_DIRS = {"Attachments", "90. Templates"}
FENCE = re.compile(r"^---[ \t]*$")
CLOSE = re.compile(r"^(---|\.\.\.)[ \t]*$")
KEY_LINE = re.compile(r"^([A-Za-z_]+):[ \t]*(.*)$")
LIST_ITEM = re.compile(r"^[ \t]*-[ \t]*(.*)$")
WIKILINK = re.compile(r"\[\[([^\[\]]+)\]\]")
USAGE = "usage: topic.py <topic>... | --help"
JUNCTION = 0xA0000003  # IO_REPARSE_TAG_MOUNT_POINT: os.walk on 3.10 follows junctions


class UsageError(Exception):
    """Bad call: exit 2."""


def parse_args(argv):
    """Return the topics, or None for --help. Options come before the topics.

    An argument with a comma is split on commas and each part trimmed, any
    other on whitespace.
    """
    args = [word for arg in argv
            for word in ([p.strip() for p in arg.split(",")] if "," in arg else arg.split())
            if word]
    while args and args[0].startswith("-"):
        opt = args.pop(0)
        if opt in ("-h", "--help"):
            return None
        raise UsageError(f"unknown option: {opt}")
    return args


def is_link(path):
    """True for a symlink or a Windows junction (OneDrive placeholders are neither)."""
    try:
        return path.is_symlink() or getattr(os.lstat(path), "st_reparse_tag", 0) == JUNCTION
    except OSError:
        return False


def notes(vault, skipped):
    """Yield (relative posix path, file) for every note in scope.

    An unreadable subfolder is added to skipped; an unreadable vault root raises OSError.
    """
    def failed(err):
        if Path(err.filename) == vault:
            raise err
        skipped.append(Path(err.filename).relative_to(vault).as_posix() + "/")

    for top, dirs, files in os.walk(vault, onerror=failed):
        here = Path(top)
        root = here == vault
        dirs[:] = sorted(d for d in dirs if not d.startswith(".")
                         and not (root and d in SKIP_ROOT_DIRS) and not is_link(here / d))
        for name in files:
            if not name.endswith(".md") or (root and name == "CLAUDE.md"):  # vault rules file
                continue
            path = here / name
            yield path.relative_to(vault).as_posix(), path


def key(text):
    """Match key: NFC, then casefold, so case and accent encoding never differ."""
    return unicodedata.normalize("NFC", text).casefold()


def path_key(path):
    """Sort key for note paths that is the same on every platform."""
    return path.casefold(), path


def clean(value):
    """Trim whitespace and unquote a YAML scalar, NFC normalized.

    'it''s' and "a \"b\"" lose their quotes and escapes; a stray quote at
    either end is just dropped.
    """
    value = value.strip(" \t")
    if len(value) > 1 and value[0] == value[-1] == "'":
        value = value[1:-1].replace("''", "'")
    elif len(value) > 1 and value[0] == value[-1] == '"':
        try:  # Limit: JSON escapes only, YAML-only ones like \x41 keep the raw text
            value = json.loads(value)
        except ValueError:
            value = value[1:-1]
    else:
        value = re.sub(r"[\"']$", "", re.sub(r"^[\"']", "", value))
    link = WIKILINK.fullmatch(value.strip())
    if link:  # [[path/Note|alias]] names the alias, [[path/Note.md]] the note
        target = link.group(1)
        value = (target.split("|")[-1] if "|" in target
                 else target.rsplit("/", 1)[-1].removesuffix(".md")).strip()
    return unicodedata.normalize("NFC", value)


def uncomment(value):
    """Drop a YAML comment: a # at the start or after whitespace, outside quotes ("C#" stays)."""
    quote, esc = "", False
    for i, ch in enumerate(value):
        if esc:
            esc = False
        elif quote:
            esc = quote == '"' and ch == "\\"
            if ch == quote:
                quote = ""
        elif ch in "\"'" and (i == 0 or value[i - 1] in " \t[," or ch == "'" == value[i - 1]):
            quote = ch  # opening quote, or the second quote of '' in a single-quoted value
        elif ch == "#" and (i == 0 or value[i - 1] in " \t"):
            return value[:i].rstrip(" \t")
    return value


def split_value(value):
    """An inline list "[a, b]" gives its raw items, anything else gives itself.

    A comma inside a quoted item does not split it.
    """
    if not (value.startswith("[") and value.endswith("]")) or WIKILINK.fullmatch(value):
        return [value]
    items, cur, quote, esc = [], "", "", False
    for ch in value[1:-1]:
        if esc:
            esc = False
        elif quote:
            esc = quote == '"' and ch == "\\"
            if ch == quote:
                quote = ""
        elif ch in "\"'" and (not cur.strip() or ch == "'" and cur.endswith("'")):
            quote = ch  # opening quote, or the second quote of '' in a single-quoted item
        elif ch == ",":
            items.append(cur)
            cur = ""
            continue
        cur += ch
    return items + [cur]


def frontmatter(text):
    """Return (topics, status) of a note: topics cleaned, empty ones dropped.

    Frontmatter without a closing "---" or "..." gives ([], ""), as in
    Obsidian. A leading BOM is ignored.
    """
    lines = [line.removesuffix("\r") for line in text.removeprefix("﻿").split("\n")]
    if not lines or not FENCE.match(lines[0]):
        return [], ""
    found = []
    status = ""
    in_list = False  # inside a "topic:" block list
    for line in lines[1:]:
        if CLOSE.match(line):
            return [v for v in map(clean, found) if v], status
        key = KEY_LINE.match(line)
        if key:
            value = uncomment(key.group(2))
            in_list = key.group(1) == "topic" and value == ""
            if key.group(1) == "topic" and not in_list:
                found += split_value(value)
            elif key.group(1) == "status":
                status = clean(value)
        elif in_list:
            item = LIST_ITEM.match(line)
            if item:
                found.append(uncomment(item.group(1)))
    return [], ""


def scan(vault, skipped):
    """Yield (relative path, topics, status) for every readable note in scope.

    A note that cannot be read is added to skipped instead.
    """
    for rel, path in notes(vault, skipped):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped.append(rel)
            continue
        yield (rel, *frontmatter(text))


def lookup(rows, wanted):
    """Return one sorted list of (note path, status) per wanted topic, in the same order.

    rows is the list from scan().
    """
    keys = [key(w) for w in wanted]
    hits = [set() for _ in wanted]
    for rel, topics, status in rows:
        for topic in map(key, topics):
            for i, want in enumerate(keys):
                if topic == want:
                    hits[i].add((rel, status))
    return [sorted(h, key=lambda hit: path_key(hit[0])) for h in hits]


def vocabulary(rows):
    """Return [(spelling, note count)] of every topic in rows (from scan()), sorted case-insensitively.

    Spellings that differ only in case count as one topic, shown in the
    spelling most notes use (ties: the first in code point order). Values are
    NFC already (clean), so accent encodings never split a topic.
    """
    spellings = {}  # key() -> Counter of spellings, one count per note
    for _, topics, _ in rows:
        for topic in {key(t): t for t in topics}.values():  # once per note
            spellings.setdefault(key(topic), Counter())[topic] += 1
    counts = {key: sum(c.values()) for key, c in spellings.items()}
    return [(min(spellings[k], key=lambda s: (-spellings[k][s], s)), counts[k])
            for k in sorted(spellings)]


def suggest(want, known):
    """Up to three of known [(topic, notes)] close to want: substring matches first, then by ratio.

    A substring match needs 3+ characters, so "'" or "a" does not match everything.
    """
    w = key(want)
    scored = []
    for topic, n in known:
        k = key(topic)
        part = min(len(w), len(k)) >= 3 and (w in k or k in w)
        ratio = difflib.SequenceMatcher(None, w, k).ratio()
        if part or ratio >= 0.6:
            scored.append((not part, -ratio, topic, n))
    return [(t, n) for *_, t, n in sorted(scored)[:3]]


def fmt(known):
    return ", ".join(f"{t} ({n})" for t, n in known)


def report(wanted, hits, known):
    """Format the lookup result as printed lines; known is vocabulary() for suggestions."""
    lines = []
    if any(hits):
        for topic, paths in zip(wanted, hits):
            lines.append(f"{topic}:")
            lines += [f"- {p} ({st})" if st else f"- {p}" for p, st in paths] or ["- nothing found"]
    else:
        lines.append("Nothing found.")
    close = []
    for topic, paths in zip(wanted, hits):
        if not paths:
            close += [s for s in suggest(topic, known) if s not in close]
    return lines + (["did you mean: " + fmt(close)] if close else [])


def skipped_lines(skipped):
    """One line naming what could not be read, or no line."""
    if not skipped:
        return []
    noun = "note" if len(skipped) == 1 else "notes"
    return [f"skipped: {len(skipped)} unreadable {noun}: " + ", ".join(sorted(skipped, key=path_key))]


def stdin_args():
    """Each stdin line is one argument; none when stdin is a terminal."""
    if sys.stdin is None or sys.stdin.isatty():
        return []
    return sys.stdin.buffer.read().decode("utf-8", errors="replace").removeprefix("﻿").splitlines()


def main(argv):
    if not argv:
        argv = stdin_args()
    try:
        wanted = parse_args(argv)
    except UsageError as err:
        print(f"SYSTEM ERROR: topic.py: {err}. {USAGE}", file=sys.stderr)
        return 2
    if wanted is None:
        print(__doc__.strip())
        return 0
    vault = require_vault()
    skipped = []
    try:
        rows = list(scan(vault, skipped))  # read the vault once
        if wanted:
            lines = report(wanted, lookup(rows, wanted), vocabulary(rows))
        else:
            lines = ["ERROR: no topic given"]
            known = vocabulary(rows)
            if known:
                lines.append("known topics: " + fmt(known))
    except OSError as err:
        print(f"SYSTEM ERROR: topic.py: lookup failed: {err}", file=sys.stderr)
        return 1
    print("\n".join(lines + skipped_lines(skipped)))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # note paths may hold non-ASCII on Windows
    sys.exit(main(sys.argv[1:]))
