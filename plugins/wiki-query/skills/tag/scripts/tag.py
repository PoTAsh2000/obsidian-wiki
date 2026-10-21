#!/usr/bin/env python3
"""usage: tag.py ['<tag> <tag>...']
       tag.py - <<'TAGS_END'   (tags on stdin, the form SKILL.md uses)

List notes in the configured Obsidian vault by frontmatter tag, one block per tag.
Read-only. Gets the vault with require_vault() from vault.py and prints only the
lookup result. Injected by the tag skill, after vault.py (which prints the vault
CLAUDE.md).

arguments:
  tags  one quoted string (or several arguments) with tags separated by spaces,
        case-insensitive, a leading # is ignored, repeats are dropped. Allowed
        like Obsidian: letters (Unicode too), digits, _ - and /, not only digits.
        Digit-only frontmatter values ('2026') are not tags and never match.
        A parent tag also finds its nested child tags: 'proj' finds 'proj/edi'.
        Tags joined with + ('ai+tooling') give one block of the notes that have
        all of them, nested matching per tag.
  --inline  a word among the tags (any place, any case): also read inline tags
        in the note body ('#tooling'), skipping fenced and inline code, headings,
        URLs and wikilinks. Default: frontmatter only.
  -     read the tags from stdin instead, so user text never passes through
        shell quoting (SKILL.md feeds it through a quoted heredoc)

output (stdout, key: value):
  ERROR: <message>          vault problem or invalid tag, relay the message as-is
  need: tags                no tag given, then a tags: begin ... tags: end block
                            with the vault's tags and note counts ('- ai (3)'),
                            most used first, at most 50 lines; nested tags are
                            indented under their parent ('  - proj/edi (1)'), whose
                            count covers the notes with it or any child
  found: yes|no             then the result: begin ... result: end block
                            note line: '- <path> (<status>)', or
                            '- <path> (<status>, tag <child>)' for a nested match,
                            '(<status>, inline...)' when it matched through a tag
                            that is only in the body (--inline);
                            at most 100 note lines per block, then '- ... N more';
                            a tag without notes may get a 'did you mean' line

exit codes:
  0  done (also for "Nothing found.", ERROR: and need: lines)
  1  system error (a vault folder cannot be listed); unreadable notes are skipped
  There is no usage error: every argument except -h/--help is read as tags (or --inline).

example: tag.py 'ai #tooling ai+tooling'
"""

import difflib
import io
import itertools
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault  # noqa: E402

# A tag as Obsidian allows it: letters (Unicode too), digits, _ - and /, but not only digits.
VALID_TAG = re.compile(r"[\w/-]+")
DIGITS_ONLY = re.compile(r"\d+")
# Folders at the vault root that are never searched. Dot folders are skipped everywhere.
SKIPPED_ROOT_FOLDERS = {"Attachments", "90. Templates"}
FRONTMATTER_FENCE = re.compile(r"^---[ \t]*$")
KEY_LINE = re.compile(r"^([A-Za-z_]+):[ \t]*(.*)$")
LIST_ITEM = re.compile(r"^[ \t]*-[ \t]*(.*)$")
TRAILING_COMMENT = re.compile(r"[ \t]+#.*$")
# Frontmatter keys Obsidian reads as tags.
TAG_KEYS = {"tags", "tag"}
# Most lines in the tag inventory printed after 'need: tags'.
MAX_INVENTORY = 50
# Most note lines per result block; the rest is one '- ... N more' line.
MAX_RESULT = 100
# Inline body tags: '#tag' at the line start or after whitespace, outside code, headings, URLs and wikilinks.
INLINE_FLAG = "--inline"
CODE_FENCE = re.compile(r"^[ \t]*(```|~~~)")
HEADING = re.compile(r"^[ \t]*#{1,6}([ \t]|$)")
NOT_TAGS = re.compile(r"`[^`]*`|\[\[[^\]]*\]\]|\S+://\S*")
INLINE_TAG = re.compile(r"(?<!\S)#([\w/-]+)")


class TagError(Exception):
    """Soft failure: an invalid tag, relayed to the user as is."""


def parse_tags(args):
    """Split every argument on whitespace into terms, a term on '+' into tags that must all match.

    Drops one leading # per tag, rejects invalid tags and drops repeats (casefold). Returns terms
    like 'ai' or 'ai+tooling'.
    """
    terms = {}
    for arg in args:
        for word in arg.split():
            parts = {}
            for tag in word.split("+"):
                tag = tag[1:] if tag.startswith("#") else tag
                if not tag:
                    continue
                if not VALID_TAG.fullmatch(tag) or DIGITS_ONLY.fullmatch(tag):
                    raise TagError(f"Invalid tag '{tag}'. Use letters, digits, _ - or / (not only digits), "
                                   "separated by spaces.")
                parts.setdefault(tag.casefold(), tag)
            if parts:
                terms.setdefault(frozenset(parts), "+".join(parts.values()))
    return list(terms.values())


def tag_match(tag, note_tags):
    """None if the note lacks tag, else the nested child tags it matched through ([] for the tag itself)."""
    if tag in note_tags:
        return []
    children = sorted(t for t in note_tags if t.startswith(tag + "/"))
    return children or None


def note_files(folder, at_root=True):
    """Yield every .md file below folder, skipping dot folders and, at the root, SKIPPED_ROOT_FOLDERS."""
    for path in sorted(folder.iterdir()):
        if path.name.startswith("."):
            continue
        if path.is_dir():
            if not (at_root and path.name in SKIPPED_ROOT_FOLDERS):
                yield from note_files(path, at_root=False)
        elif path.suffix.lower() == ".md" and path.is_file():
            yield path


def clean(value):
    """Trim spaces and tabs, then one quote at each end, then one leading #."""
    value = value.strip(" \t")
    if value[:1] in ('"', "'"):
        value = value[1:]
    if value[-1:] in ('"', "'"):
        value = value[:-1]
    return value[1:] if value.startswith("#") else value


def split_list(value):
    """Values of 'key: value': an inline list [a, "b"], a scalar 'a, b' or 'a', minus a trailing # comment."""
    value = TRAILING_COMMENT.sub("", value)
    if re.fullmatch(r"\[.*\]", value):
        value = value[1:-1]
    return [v for v in map(clean, value.split(",")) if v]


def frontmatter_tags(text):
    """Tags from the frontmatter 'tags:' or 'tag:' key."""
    return read_frontmatter(text)[0]


def read_frontmatter(text):
    """(tags, status) from the frontmatter: 'tags:' or 'tag:' inline values or a '- a' list, and 'status:'.

    text is a string or a file opened with utf-8-sig and universal newlines. Lines are read only up
    to the closing fence, only the first one without frontmatter. A leading BOM is dropped and CRLF
    or CR line endings count as LF. No status gives 'no status'.
    """
    lines = io.StringIO(text.lstrip("﻿"), newline=None) if isinstance(text, str) else text
    status = "no status"
    if not FRONTMATTER_FENCE.match(next(lines, "").rstrip("\n")):
        return [], status
    tags = []
    in_tag_list = False
    for line in lines:
        line = line.rstrip("\n")
        if FRONTMATTER_FENCE.match(line):
            break
        key = KEY_LINE.match(line)
        if key:
            is_tag_key = key.group(1) in TAG_KEYS
            in_tag_list = is_tag_key and key.group(2) == ""
            if is_tag_key and key.group(2):
                tags += split_list(key.group(2))
            if key.group(1) == "status":
                status = clean(TRAILING_COMMENT.sub("", key.group(2))) or status
        elif in_tag_list:
            item = LIST_ITEM.match(line)
            if item:
                tags += split_list(item.group(1))
    return tags, status


def inline_tags(lines):
    """'#tag' words in body lines, skipping fenced code blocks, headings, inline code, URLs and wikilinks."""
    tags = []
    fence = None
    for line in lines:
        mark = CODE_FENCE.match(line)
        if mark:
            fence = None if fence == mark.group(1) else fence or mark.group(1)
        elif not fence and not HEADING.match(line):
            tags += INLINE_TAG.findall(NOT_TAGS.sub(" ", line))
    return tags


def read_notes(vault, inline=False):
    """(vault-relative path, tags, status) for every note, sorted by path; digit-only tags left out.

    tags maps each casefolded tag to True when only the body has it (inline=True), else False.
    A note that cannot be opened or read is skipped; only a folder that cannot be listed raises OSError.
    """
    notes = []
    for note in note_files(vault):
        try:
            with open(note, encoding="utf-8-sig", errors="replace", newline=None) as f:
                first = f.readline()
                tags, status = read_frontmatter(itertools.chain([first], f))
                body = []
                if inline:
                    body = inline_tags(line.rstrip("\n") for line in (
                        f if FRONTMATTER_FENCE.match(first.rstrip("\n")) else itertools.chain([first], f)))
        except OSError:
            continue
        found = {t.casefold(): False for t in tags if not DIGITS_ONLY.fullmatch(t)}
        for t in body:
            if not DIGITS_ONLY.fullmatch(t):
                found.setdefault(t.casefold(), True)
        notes.append((note.relative_to(vault).as_posix(), found, status))
    return notes


def find_tagged(notes, tags):
    """Per term, its note lines: notes with every tag of the term, each itself or a nested child 'tag/...'.

    A note is marked 'inline' when a tag it matched through is only in its body.
    """
    hits = []
    for term in tags:
        parts = term.casefold().split("+")
        lines = []
        for path, note_tags, status in notes:
            matches = [tag_match(part, note_tags) for part in parts]
            if None in matches:
                continue
            children = list(dict.fromkeys(c for m in matches for c in m))
            inline = any(note_tags[t] for part, m in zip(parts, matches) for t in m or [part])
            details = [status] + ["inline"] * inline + [f"tag {', '.join(children)}"] * bool(children)
            lines.append(f"- {path} ({', '.join(details)})")
        hits.append(lines)
    return hits


def tag_counts(notes):
    """Counter of notes per casefolded tag."""
    return Counter(t for _, note_tags, _ in notes for t in note_tags)


def branch_counts(notes):
    """Counter of notes per tag and per parent of a nested tag, each note counted once per branch.

    Empty or digit-only parents ('2026' of '2026/q1') are left out, as a lookup cannot use them.
    """
    counts = Counter()
    for _, note_tags, _ in notes:
        branches = set()
        for tag in note_tags:
            parts = tag.split("/")
            branches.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
        counts.update(b for b in branches if b and not DIGITS_ONLY.fullmatch(b))
    return counts


def inventory(counts):
    """'- tag (n)' lines, children indented under their parent, each level most used first then by
    name, capped at MAX_INVENTORY lines."""
    children = {}
    for tag in counts:
        parent = tag.rpartition("/")[0]
        children.setdefault(parent if parent in counts else None, []).append(tag)
    lines = []

    def walk(parent, depth):
        for tag in sorted(children.get(parent, []), key=lambda t: (-counts[t], t)):
            lines.append(f"{'  ' * depth}- {tag} ({counts[tag]})")
            walk(tag, depth + 1)
    walk(None, 0)
    if len(lines) > MAX_INVENTORY:
        return lines[:MAX_INVENTORY] + [f"- ... {len(lines) - MAX_INVENTORY} more"]
    return lines


def suggestions(tag, counts):
    """Vault tags close to a tag without notes: a nested tag ending in '/tag', or a near spelling."""
    tag = tag.casefold()
    nested = sorted(t for t in counts if t.endswith("/" + tag))
    close = difflib.get_close_matches(tag, list(counts), n=3, cutoff=0.75)
    return list(dict.fromkeys(nested + close))


def result_lines(tags, hits, counts):
    """One block per term (at most MAX_RESULT note lines, then '- ... N more'), or 'Nothing found.'
    when no term matched, then 'did you mean' lines."""
    lines = []
    if any(hits):
        for tag, found in zip(tags, hits):
            lines.append(f"{tag}:")
            lines += found[:MAX_RESULT] or ["- nothing found"]
            if len(found) > MAX_RESULT:
                lines.append(f"- ... {len(found) - MAX_RESULT} more")
    else:
        lines.append("Nothing found.")
    for term, found in zip(tags, hits):
        for tag in [] if found else term.split("+"):
            if tag_match(tag.casefold(), counts) is not None:
                continue  # this tag has notes; the term failed on another part
            close = suggestions(tag, counts)
            if close:
                lines.append(f"did you mean {tag}: " + ", ".join(f"{t} ({counts[t]})" for t in close))
    return lines


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if argv == ["-"]:
        sys.stdin.reconfigure(encoding="utf-8")
        argv = [sys.stdin.read()]
    vault = require_vault()
    words = " ".join(argv).split()
    inline = INLINE_FLAG in (w.casefold() for w in words)
    try:
        tags = parse_tags(w for w in words if w.casefold() != INLINE_FLAG)
    except TagError as err:
        print(f"ERROR: {err}")
        return 0
    try:
        notes = read_notes(vault, inline)
    except OSError as err:
        print(f"SYSTEM ERROR: tag.py: cannot read the vault: {err}", file=sys.stderr)
        return 1
    counts = tag_counts(notes)
    if not tags:
        print("need: tags")
        print("tags: begin")
        print("\n".join(inventory(branch_counts(notes)) or ["- no tags in the vault"]))
        print("tags: end")
        return 0
    hits = find_tagged(notes, tags)
    print(f"found: {'yes' if any(hits) else 'no'}")
    print("result: begin")
    print("\n".join(result_lines(tags, hits, counts)))
    print("result: end")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
