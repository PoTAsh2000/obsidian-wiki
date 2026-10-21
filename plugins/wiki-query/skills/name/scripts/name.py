#!/usr/bin/env python3
"""usage: name.py [--limit <n>] [--] <text>...

List notes in the vault configured by wiki-vault whose filename or title
contains <text>, falling back to aliases. Read-only. The title is the
frontmatter title or the first '# ' heading; aliases come from the
frontmatter key alias or aliases (keys in any case); YAML quotes are
undone as Obsidian does (quotes, '' and escapes). Text and names are
compared after Unicode NFC, casefold, dropping accents and apostrophes and
treating other ASCII punctuation (except + and #) and runs of whitespace as
one space. Titles are compared and shown as plain text: links give their
display text; emphasis, code marks and closing #'s of a heading go. A text in
[[ ]] or ending in .md, .canvas or .base counts as a link or path: only the
note name is searched (no folder, extension, |display or #heading).
When nothing matches as one piece,
a text of several words also matches a filename or title holding every word
in any order.
Only the head of each note is read (up to the first heading, at most 64 KiB);
a leading UTF-8 byte order mark is ignored.
Linked folders are skipped, and so are file links that leave the vault.
Dot folders, Attachments, 90. Templates and the Excluded files of
.obsidian/app.json (userIgnoreFilters: path prefixes, /regex/ on the path)
are not searched, but still count for shared names.

arguments:
  <text>       the text to look for; several words are joined with one space
  --limit <n>  max notes to list, 1-200, default 20
  --           end of options, use before a text that starts with a dash

output (relay as printed; best first: exact name, starts with, contains, then path;
any-order hits are listed only when no filename, title or alias matches):
  - <link> <path> (filename[, <status>][, shared name])         filename match
  - <link> <path> (title: <title>[, <status>][, shared name])   title match
  No filename or title matches "<text>". Found through aliases:
  - <link> <path> (alias: <alias>[, <status>][, shared name])   alias fallback
  <n> more not shown                   the list was cut at --limit
  Nothing found.                       no match (still exit 0)
  Nothing found. Close names:          no match, but up to 5 notes have a name
  - <link> <path> (filename|title: ...|alias: ...)  spelled alike (difflib ratio
                                       at least 0.8), most alike first
  ERROR: <message>                     vault problem (path missing, no CLAUDE.md)

  <link> is the wikilink Obsidian resolves: [[Stem]], or [[folder/Stem]] marked
  "shared name" when another .md, .canvas or .base file has the same name.
  An alias hit links as [[Stem|<alias>]], with | [ ] removed from the alias.
  Vault text is printed without control or bidi characters; titles, aliases
  and status are cut at 120.

exit codes:
  0  lookup done (matches or "Nothing found."), or an ERROR line for a vault problem
  1  system error (a note cannot be read, or vault.py is missing)
  2  bad usage (no text given, invalid --limit)

example: name.py --limit 5 -- context engineering
"""

import json
import os
import re
import stat
import sys
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from itertools import chain
from pathlib import Path

# vault.py lives in the plugin scripts folder, three levels up from this file.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault  # noqa: E402

USAGE = "usage: name.py [--limit <n>] [--] <text>..."
DEFAULT_LIMIT, MAX_LIMIT = 20, 200
HEAD_CAP = 64 * 1024  # characters read per note at most
TEXT_CAP = 120  # longest title, alias or status printed
CLOSE_CUTOFF, CLOSE_MAX = 0.8, 5  # typo suggestions on the no-match path
# Folders at the vault root that are not searched (their notes still count for
# shared names, as in Obsidian). Dot folders are skipped everywhere.
SKIPPED_ROOT_DIRS = {"Attachments", "90. Templates"}
FRONTMATTER_FENCE = re.compile(r"^---[ \t]*$")
FRONTMATTER_KEY = re.compile(r"^([A-Za-z_]+):[ \t]*(.*)$")
LIST_ITEM = re.compile(r"^[ \t]*-[ \t]*(.*)$")
# One item of an inline list: a quoted string (may hold commas) or text up to a comma.
INLINE_ITEM = re.compile(r"""[ \t]*("(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^,]*)[ \t]*(?:,|$)""")
CODE_FENCE = re.compile(r"^[ \t]*(```|~~~)")
NUMBER = re.compile(r"^[1-9][0-9]{0,2}$")
ALIAS_KEYS = {"alias", "aliases"}
LINK_UNSAFE = dict.fromkeys(map(ord, "|[]"))  # would break [[Stem|alias]]
LINK_SUFFIXES = (".md", ".canvas", ".base")  # what [[Name]] resolves to in Obsidian
LINE_BREAKS = re.compile("[\t\n\r\v\f\x85  ]")
# Bidi marks, embeddings, overrides and isolates: they can hide or reorder text.
BIDI = dict.fromkeys(map(ord, "؜‎‏‪‫‬‭‮"
                              "⁦⁧⁨⁩"))


class ReadError(Exception):
    """A note cannot be read: system error, exit 1."""


class UsageError(Exception):
    """Bad arguments: exit 2."""


def is_link(entry):
    """Symlink, or a Windows junction (any reparse point)."""
    if entry.is_symlink():
        return True
    attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def note_paths(vault):
    """Yield (path relative to the vault with / separators, searchable) for every file
    a [[Name]] link can resolve to: *.md notes, plus *.canvas and *.base files that
    only count for shared names.

    Linked folders are never entered (no escapes, no loops); a linked file counts
    only when its real path is inside the vault.
    """
    real_vault = Path(os.path.realpath(vault))
    stack = [(vault, True)]
    while stack:
        folder, searchable = stack.pop()
        at_root = folder == vault
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                link = is_link(entry)
                if entry.is_dir():
                    if not link:
                        stack.append((Path(entry.path), searchable
                                      and not (at_root and entry.name in SKIPPED_ROOT_DIRS)))
                elif entry.name.endswith(LINK_SUFFIXES) and entry.is_file():
                    if link and not Path(os.path.realpath(entry.path)).is_relative_to(real_vault):
                        continue
                    yield Path(entry.path).relative_to(vault).as_posix(), searchable


def ignore_filters(vault):
    """Excluded files from .obsidian/app.json as a test on a note path; none on a
    missing or invalid file. /x/ is a regex searched in the path, else a path prefix."""
    try:
        filters = json.loads((vault / ".obsidian" / "app.json").read_text(encoding="utf-8-sig"))
        filters = filters.get("userIgnoreFilters") or []
    except (OSError, ValueError, AttributeError):
        return lambda path: False
    prefixes, regexes = [], []
    for item in filters if isinstance(filters, list) else []:
        if not isinstance(item, str) or not item:
            continue
        if len(item) > 1 and item.startswith("/") and item.endswith("/"):
            try:
                regexes.append(re.compile(item[1:-1]))
            except re.error:
                pass
        else:
            prefixes.append(item)
    prefixes = tuple(prefixes)
    return lambda path: path.startswith(prefixes) or any(r.search(path) for r in regexes)


# Apostrophes go (Obsidian's -> obsidians); other ASCII punctuation is a space, but
# + and # stay so C++ and C# differ.
SEPARATORS = str.maketrans({**dict.fromkeys(map(ord, "!\"$%&()*,-./:;<=>?@[\\]^_`{|}~"), " "),
                            **dict.fromkeys(map(ord, "'‘’"))})
WIKILINK = re.compile(r"\[\[([^\]|]*)(?:\|([^\]]*))?\]\]")
MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
MARKUP = re.compile(r"\*+|`+|~~|==|__")
CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")


def plain(title):
    """A title as Obsidian shows it: [[a|b]] -> b, [[a]] -> a, [t](url) -> t, and no
    emphasis, highlight or code marks."""
    title = WIKILINK.sub(lambda m: m.group(1) if m.group(2) is None else m.group(2), title)
    return MARKUP.sub("", MD_LINK.sub(r"\1", title)).strip(" \t")


def note_name(text):
    """The note name in a search text that is a wikilink or a file path:
    [[folder/Name#heading|shown]] or folder/Name.md give Name; other text is kept."""
    name = text.strip(" \t")
    is_link = name.startswith("[[") and name.endswith("]]")
    if is_link:
        name = re.split(r"[|#]", name[2:-2])[0]
    if name.lower().endswith(LINK_SUFFIXES):
        name, is_link = name.rsplit(".", 1)[0], True
    if is_link:  # Limit: folder dropped, not used to prefer notes in that folder
        name = re.split(r"[/\\]", name)[-1].strip(" \t")
    return name or text


def same_name(value):
    """Key for names Obsidian treats as one: NFC (macOS/iCloud save names decomposed),
    casefold, one space per run of whitespace."""
    folded = unicodedata.normalize("NFC", unicodedata.normalize("NFC", value).casefold())
    return " ".join(folded.split())


def norm(value):
    """Match key: same_name without accents and apostrophes; other ASCII punctuation
    but + and # counts as a space."""
    bare = "".join(c for c in unicodedata.normalize("NFD", same_name(value))
                   if unicodedata.category(c) != "Mn")
    return " ".join(unicodedata.normalize("NFC", bare).translate(SEPARATORS).split())


def unquote(value):
    """A YAML scalar as Obsidian reads it: trimmed, and quotes dropped only when the
    same quote opens and closes it; '' inside single quotes is one ', escapes inside
    double quotes are decoded (raw text kept when they do not decode)."""
    value = value.strip(" \t")
    if len(value) < 2 or value[0] != value[-1] or value[0] not in "'\"":
        return value
    if value[0] == "'":
        return value[1:-1].replace("''", "'")
    try:  # Limit: JSON escapes only, a YAML-only escape such as \x41 keeps the raw text
        return json.loads(value, strict=False)
    except ValueError:
        return value[1:-1]


def safe(value, cap=None):
    """Vault text made safe to print on one line: tabs and line breaks become a space,
    other control and bidi characters go, and with cap the text is cut."""
    value = LINE_BREAKS.sub(" ", value).translate(BIDI)
    value = "".join(c for c in value if unicodedata.category(c) != "Cc")
    return value[:cap - 3] + "..." if cap and len(value) > cap else value


def split_list(value):
    """A frontmatter value as a list: [a, "b, c"] gives two items, anything else one."""
    if value.startswith("[") and value.endswith("]"):
        return INLINE_ITEM.findall(value[1:-1])
    return [value]


def head_lines(handle):
    """Lines of an open note without "\\n", stopping after HEAD_CAP characters."""
    read = 0
    for line in handle:
        read += len(line)
        if read > HEAD_CAP:
            return
        yield line[:-1] if line.endswith("\n") else line


def read_note(lines):
    """Return (titles, aliases, status) from note lines without "\\n".

    Titles are the frontmatter title and the first '# ' heading outside code;
    reading stops at that heading.
    """
    lines = (line[:-1] if line.endswith("\r") else line for line in lines)
    aliases, titles, status = [], [], ""
    first = next(lines, None)
    body = lines
    if first is not None and FRONTMATTER_FENCE.match(first):
        in_list = False
        for line in lines:  # frontmatter that never closes covers the whole note
            if FRONTMATTER_FENCE.match(line):
                break
            key = FRONTMATTER_KEY.match(line)
            if key:
                name, value = key.group(1).lower(), key.group(2)
                in_list = name in ALIAS_KEYS and value == ""
                if name == "title":
                    titles.append(plain(unquote(value)))
                elif name == "status":
                    status = unquote(value)
                elif name in ALIAS_KEYS:
                    aliases += split_list(value)
            elif in_list:
                item = LIST_ITEM.match(line)
                if item:
                    aliases.append(item.group(1))
    elif first is not None:
        body = chain([first], lines)
    in_code = False
    for line in body:
        if CODE_FENCE.match(line):
            in_code = not in_code
        elif not in_code and line.startswith("# "):
            titles.append(plain(CLOSING_HASHES.sub("", line[2:])))
            break
    unique = {}
    for alias in map(unquote, aliases):
        if alias:
            unique.setdefault(same_name(alias), alias)
    return [t for t in titles if t], list(unique.values()), status


def rank(query, value, words=()):
    """0 exact, 1 starts with, 2 contains, 3 holds all words in any order, None no match."""
    key = norm(value)
    if key == query:
        return 0
    if key.startswith(query):
        return 1
    if query in key:
        return 2
    return 3 if words and all(w in key for w in words) else None


def best(query, candidates, words=()):
    """(rank, label) of the best matching (label, value); the earliest wins a tie. None: no match."""
    found = [(r, i, label) for i, (label, value) in enumerate(candidates)
             if (r := rank(query, value, words)) is not None]
    return min(found)[::2] if found else None


def close_names(query, near):
    """Lines for the notes whose filename, title or alias is spelled like the query,
    most alike first; [] when none reaches CLOSE_CUTOFF."""
    scored = []
    for path, target, extra, names in near:
        score, kind, value = max(((SequenceMatcher(None, query, norm(v)).ratio(), k, v)
                                 for k, v in names), key=lambda x: x[0])  # filename wins a tie
        if score < CLOSE_CUTOFF:
            continue
        link, label = f"[[{target}]]", kind
        if kind != "filename":
            label = f"{kind}: {safe(value, TEXT_CAP)}"
        if kind == "alias":
            shown = safe(value, TEXT_CAP).translate(LINK_UNSAFE).strip()
            link = f"[[{target}|{shown}]]" if shown else link
        scored.append((-score, path, f"- {safe(link)} {safe(path)} ({label}{extra})"))
    if not scored:
        return []
    return ["Nothing found. Close names:"] + [line for *_, line in sorted(scored)[:CLOSE_MAX]]


def lookup(vault, text, limit):
    """Return the output lines for a search text."""
    query = norm(note_name(text))
    if not query:  # only punctuation: would match every note
        return ["Nothing found."]
    words = query.split() if " " in query else ()
    notes = list(note_paths(vault))
    stems = Counter(same_name(Path(path).stem) for path, _ in notes)
    ignored = ignore_filters(vault)
    hits, alias_hits, loose_hits, near = [], [], [], []
    for path, searchable in notes:
        if not (searchable and path.endswith(".md")) or ignored(path):
            continue
        try:
            with open(vault / path, encoding="utf-8-sig", errors="replace", newline="") as handle:
                titles, aliases, status = read_note(head_lines(handle))
        except OSError as err:
            raise ReadError(f"cannot read {path}: {err}")
        stem = Path(path).stem
        shared = stems[same_name(stem)] > 1
        target = path[:-3] if shared else stem
        link = f"[[{target}]]"
        extra = (f", {safe(status, TEXT_CAP)}" if status else "") + (", shared name" if shared else "")
        match = best(query, [("filename", stem)]
                     + [(f"title: {safe(t, TEXT_CAP)}", t) for t in titles], words)
        found = hits
        if not match or match[0] == 3:
            alias_match = best(query, [(a, a) for a in aliases])
            if alias_match:
                alias = safe(alias_match[1], TEXT_CAP)
                shown = alias.translate(LINK_UNSAFE).strip()
                link = f"[[{target}|{shown}]]" if shown else link
                match, found = (alias_match[0], f"alias: {alias}"), alias_hits
            else:
                found = loose_hits
        if match:
            found.append((match[0], path, f"- {safe(link)} {safe(path)} ({match[1]}{extra})"))
        else:
            near.append((path, target, extra, [("filename", stem)] + [("title", t) for t in titles]
                         + [("alias", a) for a in aliases]))
    head = []
    if not hits and alias_hits:
        head = [f'No filename or title matches "{safe(text, TEXT_CAP)}". Found through aliases:']
        hits = alias_hits
    hits = hits or loose_hits
    if not hits:
        return close_names(query, near) or ["Nothing found."]
    hits.sort()
    lines = head + [line for _, _, line in hits[:limit]]
    if len(hits) > limit:
        lines.append(f"{len(hits) - limit} more not shown")
    return lines


def parse_args(argv):
    """Return (limit, text) or raise UsageError."""
    limit = DEFAULT_LIMIT
    while argv[:1] == ["--limit"]:
        if len(argv) < 2:
            raise UsageError("--limit needs a number")
        if not NUMBER.match(argv[1]) or int(argv[1]) > MAX_LIMIT:
            raise UsageError(f"invalid --limit: {argv[1]}, use 1 to {MAX_LIMIT}")
        limit, argv = int(argv[1]), argv[2:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not argv:
        raise UsageError("no text given")
    text = " ".join(argv)
    if not text.strip():
        raise UsageError("text is empty")
    return limit, text


def fail(prefix, message, code):
    print(f"{prefix}: {message}", file=sys.stderr)
    return code


def main(argv):
    # UTF-8 and LF on every OS: note paths may hold any character.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    try:
        limit, text = parse_args(argv)
    except UsageError as err:
        return fail("SYSTEM ERROR", f"name.py: {err}. {USAGE}", 2)
    vault = require_vault()
    try:
        print("\n".join(lookup(vault, text, limit)))
    except ReadError as err:
        return fail("SYSTEM ERROR", f"name.py: {err}", 1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
