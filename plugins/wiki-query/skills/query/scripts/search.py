#!/usr/bin/env python3
"""usage: search.py [--limit <n>] [--excerpts <n>] [--links <n>] <term>...

Rank the notes in the configured Obsidian vault by how well they match the terms. Read-only.
Case-insensitive match (Unicode NFC and casefold, so composed and decomposed
accents and sharp s match) on filename, first "# " title, aliases, tags, topic and
body lines. A whole word (plural -s/-es included) scores full points, a match
inside a word (edi in "credit") a fifth. Body hits are weighted by how rare
the term is across the notes (BM25 style, computed per run, nothing cached).
Each extra term that hits as a whole word in the same section as another adds
2 points (best section only, at most 6, below a filename or title hit).
Skips dot folders, Attachments, "90. Templates", the vault root CLAUDE.md and
notes that resolve outside the vault (symlinks, junctions). The vault comes
from vault.py (require_vault).

arguments:
  --limit <n>     max notes to list, 1-200, default 20
  --excerpts <n>  under each listed note, the n best matching body lines (1-20):
                  most rare terms as whole words, one per section first,
                  in line order, skipping code fences, each cut to 160 chars
  --links <n>     after the list, the links of the top n listed notes (1-20)
  <term>...       1-20 terms of up to 200 chars; quote a phrase as one term

output (sorted by score, then non-archived first, then path):
  ERROR: <message>  vault problem (path missing or no CLAUDE.md), exit 0
  terms: <term>, ...
  matches: <notes with any hit>
  shown: <listed>
  - <path> | score: <n.n> | status: <s> | terms: <hit>/<given> | in: <fields>[ | archived: yes]
    [ | created: <d>][ | updated: <d>][ | source: <s>] | link: [[...]]
  fields: name, title, alias, tag, topic, body:<line hits summed over terms>
  archived: yes  the note is under "99. Archived"
  created, updated (or modified), source (or url): frontmatter values as written,
    only when present (never file times), cut to 160 chars
  link: [[...]]  shortest wikilink that is unique in the vault, cite it as is
  with --excerpts, under each note (heading lines are not excerpts):
    <line number> | <section heading, or -> (<first>-<last>) | <line text>
    <first>-<last> is the section the line sits in: its heading up to the next
    heading of the same or higher level, or the end of the note
  when no note has a whole-word hit (matches: 0 included), after the list:
  suggest: <term> = <up to 10 close words from note names, titles, aliases,
           tags and topics>   (difflib, one line per term that has any)
  with --links, after the list:
  links:
  - <path>
      out: <target> = <path> (<status>)   or   out: <target> = unresolved
      in: <paths of notes linking to it, or none>
  out lists body [[links]] and frontmatter related entries; links resolve like
  Obsidian (case-insensitive filename or path suffix, shortest path wins);
  links to the note itself are left out

exit codes:
  0  searched (matches: 0 means nothing found)
  1  system error (cannot read a note)
  2  bad usage (missing or invalid argument)

example: search.py --excerpts 3 --links 5 "EDI" "mapping" "edifact"
"""

import difflib
import math
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault  # noqa: E402

DEFAULT_LIMIT = 20
SKIP_ROOT_DIRS = {"Attachments", "90. Templates"}
ARCHIVE_DIR = "99. Archived"
META_KEYS = ("aliases", "tags", "topic", "status", "related")
# frontmatter shown as is on each result line: (output name, keys, first present wins)
FRESH = (("created", ("created",)), ("updated", ("updated", "modified")),
         ("source", ("source", "url")))
FRESH_KEYS = {key for _, keys in FRESH for key in keys}
# (field shown in output, points per term), in output order
FIELDS = (("name", 10), ("title", 10), ("alias", 6), ("tag", 4), ("topic", 4))
# body points per term: BODY_WEIGHT * saturated hits * rarity, as in BM25
BODY_WEIGHT = 2
BM25_K1 = 1.2
PART_WEIGHT = 0.2  # a match inside a word, against 1 for a whole word
# points per extra distinct whole-word term in one section, and the cap (below name/title)
SECTION_BONUS = 2
SECTION_CAP = 6
MAX_TERMS = 20
MAX_TERM_LEN = 200
EXCERPT_WIDTH = 160
MAX_SUGGEST = 10
# number options and their maximum
OPTIONS = {"--limit": 200, "--excerpts": 20, "--links": 20}

FM_FENCE = re.compile(r"^---[ \t]*$")
FM_KEY = re.compile(r"^([A-Za-z_]+):[ \t]*(.*)$")
FM_ITEM = re.compile(r"^[ \t]*-[ \t]*(.*)$")
CODE_FENCE = re.compile(r"^[ \t]*(```|~~~)")
NUMBER_RE = re.compile(r"^[1-9][0-9]{0,2}$")
HEADING = re.compile(r"^#{1,6}[ \t]+(.*?)[ \t#]*$")
# target of [[target]], [[target|alias]], [[target#heading]], also inside ![[...]]
WIKILINK = re.compile(r"\[\[([^\[\]|#]*)[^\[\]]*\]\]")


class UsageError(Exception):
    """Bad arguments: exit 2."""


def parse_args(argv):
    """Return ({"limit", "excerpts", "links": number}, terms), or None when help was printed."""
    opts, terms = {"--limit": str(DEFAULT_LIMIT), "--excerpts": "", "--links": ""}, []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            print(__doc__.strip())
            return None
        if arg in OPTIONS:
            if i + 1 >= len(argv):
                raise UsageError(f"{arg} needs a number")
            value = argv[i + 1]
            if not NUMBER_RE.match(value) or int(value) > OPTIONS[arg]:
                raise UsageError(f"invalid {arg}: {value}")
            opts[arg] = value
            i += 2
        elif arg == "--":
            terms += argv[i + 1:]
            break
        elif arg.startswith("-"):
            raise UsageError(f"unknown option: {arg}")
        else:
            terms.append(arg)
            i += 1
    if not terms:
        raise UsageError("no search term given")
    if len(terms) > MAX_TERMS:
        raise UsageError(f"too many search terms: {len(terms)}, max {MAX_TERMS}")
    for term in terms:
        if not term.strip():
            raise UsageError("empty search term")
        if "\n" in term or "\t" in term:
            raise UsageError("search term contains a newline or tab")
        if len(term) > MAX_TERM_LEN:
            raise UsageError(f"search term longer than {MAX_TERM_LEN} characters")
    return {key[2:]: int(value or 0) for key, value in opts.items()}, terms


def find_notes(root):
    """Yield (relative posix path, Path, searchable) of every .md note outside dot folders.

    Not searchable: Attachments, "90. Templates" and the vault root CLAUDE.md.
    They still count as link targets and for unique link names, as in Obsidian.
    Left out: notes that resolve outside the vault (symlinked files or folders, junctions).
    """
    real_root = root.resolve()
    for path in root.rglob("*.md"):
        rel = path.relative_to(root)
        folders = rel.parts[:-1]
        if any(p.startswith(".") for p in folders):
            continue
        # rglob ignores case on Windows, find -name did not
        if not path.name.endswith(".md") or not path.is_file():
            continue
        try:
            path.resolve().relative_to(real_root)
        except ValueError:
            continue
        skipped = (folders and folders[0] in SKIP_ROOT_DIRS) or rel.as_posix() == "CLAUDE.md"
        yield rel.as_posix(), path, not skipped


def read_lines(path):
    """Lines of a note without line endings (CRLF or LF)."""
    text = path.read_bytes().decode("utf-8", errors="replace")
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def fold(text):
    """Text for matching only: canonical caseless form (NFC, casefold), output keeps the original."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", text).casefold())


def clean(value, lower=True):
    """Trim blanks and one surrounding quote on each side, fold unless told not to."""
    value = value.strip(" \t")
    value = re.sub(r"^[\"']", "", value)
    value = re.sub(r"[\"']$", "", value)
    return fold(value) if lower else value


def parse_note(lines):
    """Return (meta, status, title, body lines, body start index) of a note.

    All folded (see fold), except meta["related"] and meta["fresh"] (FRESH_KEYS -> first
    value), which keep their text for display.
    """
    meta = {key: [] for key in META_KEYS if key != "status"}
    meta["fresh"] = {}
    status, title, titled, body = "none", "", False, []

    def add(key, value):
        nonlocal status
        value = clean(value, key not in FRESH_KEYS and key != "related")
        if not value:
            return
        if key in FRESH_KEYS:
            meta["fresh"].setdefault(key, value)
        elif key == "status":
            status = value.lower()
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
                if name in FRESH_KEYS:
                    if value == "":
                        list_key = name
                    else:
                        add(name, value)
                elif name in META_KEYS:
                    if value == "":
                        list_key = name
                    elif name == "related" and "[[" in value:
                        add(name, value)
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
            title, titled = fold(line[2:]), True
        body.append(fold(line))
    return meta, status, title, body, start


def word_pattern(term):
    """Regex for term as a whole word, optionally plural; edges that are not word chars always fit."""
    start = r"(?<!\w)" if re.match(r"\w", term[0]) else ""
    end = r"(?:e?s)?(?!\w)" if re.match(r"\w", term[-1]) else ""
    return re.compile(start + re.escape(term) + end)


def weight(term, word, value):
    """1 for a whole-word match in value, PART_WEIGHT for a match inside a word, else 0."""
    if term not in value:
        return 0
    return 1 if word.search(value) else PART_WEIGHT


def rarity(terms, bodies):
    """BM25 idf per term over the searchable note bodies; rare terms weigh more."""
    total = len(bodies)
    idf = {}
    for term in terms:
        df = sum(1 for body in bodies if any(term in line for line in body))
        idf[term] = math.log(1 + (total - df + 0.5) / (df + 0.5))
    return idf


def score_note(path, meta, status, title, body, terms, idf, owner):
    """Return (score, output line, any whole-word hit) of a note, or None when no term hits.

    owner: the section of each body line (see line_sections), for the same-section bonus.
    """
    name = Path(path).name
    name = fold(name[:-3] if name.endswith(".md") else name)
    fields = {"name": [name], "title": [title] if title else [],
              "alias": meta["aliases"], "tag": meta["tags"], "topic": meta["topic"]}
    score = hits = body_hits = 0
    found, whole = set(), False
    together = {}  # section -> terms with a whole-word hit in it
    for term in terms:
        hit = False
        word = word_pattern(term)
        for field, points in FIELDS:
            best = max((weight(term, word, value) for value in fields[field]), default=0)
            if best:
                whole = whole or best == 1
                score += points * best
                found.add(field)
                hit = True
        weights = []
        for i, line in enumerate(body):
            w = weight(term, word, line)
            if w:
                weights.append(w)
                if w == 1:
                    together.setdefault(owner[i], set()).add(term)
        if weights:
            whole = whole or 1 in weights
            tf = sum(weights)
            score += BODY_WEIGHT * tf * (BM25_K1 + 1) / (tf + BM25_K1) * idf[term]
            body_hits += len(weights)
            hit = True
        hits += hit
    if not hits:
        return None
    meet = max((len(t) for t in together.values()), default=1)
    score = round(score + min(SECTION_BONUS * (meet - 1), SECTION_CAP), 1)
    where = [field for field, _ in FIELDS if field in found]
    if body_hits:
        where.append(f"body:{body_hits}")
    line = (f"- {path} | score: {score:g} | status: {status} | "
            f"terms: {hits}/{len(terms)} | in: {','.join(where)}")
    if is_archived(path):
        line += " | archived: yes"
    for label, keys in FRESH:
        value = next((meta["fresh"][k] for k in keys if k in meta["fresh"]), "")
        if value:
            cut = value if len(value) <= EXCERPT_WIDTH else value[:EXCERPT_WIDTH - 3] + "..."
            line += f" | {label}: {cut}"
    return score, line, whole


def suggest(terms, parsed):
    """Per term, up to MAX_SUGGEST close words from note names, titles, aliases, tags, topics."""
    vocab = set()
    for path, meta, _, title, *_ in parsed:
        for value in [fold(stem(Path(path).name)), title,
                      *meta["aliases"], *meta["tags"], *meta["topic"]]:
            vocab.add(value)
            vocab.update(re.findall(r"[\w-]+", value))
    vocab.discard("")
    for term in terms:
        close = [w for w in difflib.get_close_matches(term, sorted(vocab), MAX_SUGGEST + 1)
                 if w != term][:MAX_SUGGEST]
        if close:
            yield term, close


def is_archived(path):
    return path.startswith(ARCHIVE_DIR + "/")


def stem(path):
    """Vault path without .md."""
    return path[:-3] if path.lower().endswith(".md") else path


def unique_links(paths):
    """Map each path to its shortest unique wikilink: the filename, plus folders when shared."""
    keys = {path: stem(path).lower().split("/") for path in paths}
    links = {}
    for path, parts in keys.items():
        # Limit: O(notes^2) over shared names only in practice, index by name if vaults get huge
        others = [o for p, o in keys.items() if p != path and o[-1] == parts[-1]]
        k = 1
        while k < len(parts) and any(o[-k:] == parts[-k:] for o in others):
            k += 1
        links[path] = "[[" + "/".join(stem(path).split("/")[-k:]) + "]]"
    return links


def resolve(target, paths):
    """Vault path a link target points to, like Obsidian: case-insensitive, shortest path wins."""
    want = stem(target.strip().strip("/")).lower()
    hits = [p for p in paths if stem(p).lower() == want or stem(p).lower().endswith("/" + want)]
    return min(hits, key=lambda p: (p.count("/"), len(p), p), default=None)


def note_links(lines, related):
    """Link targets of a note in order, without duplicates: body [[links]], then related."""
    targets, in_fence = [], False
    for line in lines:
        if CODE_FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            targets += WIKILINK.findall(line)
    for value in related:
        found = WIKILINK.findall(value)
        targets += found if found else [value.strip("[]")]
    seen, result = set(), []
    for target in (t.strip() for t in targets):
        if target and target.lower() not in seen:
            seen.add(target.lower())
            result.append(target)
    return result


def headings(lines, start):
    """(line number, level, text) of every heading outside code fences, from body start."""
    found, in_fence = [], False
    for n, line in enumerate(lines[start:], start=start + 1):
        if CODE_FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and HEADING.match(line):
            found.append((n, len(line) - len(line.lstrip("#")), HEADING.match(line).group(1)))
    return found


def sections(lines, start):
    """(first line, last line, heading) of each section: a heading up to the next heading of
    the same or higher level, or the end of the note; text before the first heading is "-"."""
    heads = headings(lines, start)
    first = heads[0][0] - 1 if heads else len(lines)
    result = [(start + 1, first, "-")] if first > start else []
    for i, (n, level, text) in enumerate(heads):
        end = next((m - 1 for m, lv, _ in heads[i + 1:] if lv <= level), len(lines))
        result.append((n, end, text or "-"))
    return result


def line_sections(lines, start):
    """The section (first, last, heading) each body line sits in: the nearest heading above."""
    heads = {sec[0]: sec for sec in sections(lines, start)}
    owner, section = [], None
    for n in range(start + 1, len(lines) + 1):
        section = heads.get(n, section)
        owner.append(section)
    return owner


def excerpts(lines, start, terms, idf, count):
    """The count best (line number, "heading (first-last)", text) of body lines outside code
    fences with a term, in line order; the range is the section the line sits in.

    A line scores its terms' rarity, a match inside a word a fifth. The best line of each
    section goes first, best section first; leftover slots take the next best lines.
    """
    owner = line_sections(lines, start)
    words = [(term, word_pattern(term)) for term in terms]
    found, in_fence = [], False
    for n, line in enumerate(lines[start:], start=start + 1):
        if CODE_FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or HEADING.match(line):
            continue
        folded = fold(line)
        score = sum(weight(term, word, folded) * idf[term] for term, word in words)
        if score:
            found.append((-score, n, owner[n - start - 1], line.strip()))
    found.sort()
    picked, seen = [], set()
    for row in found:
        if row[2] not in seen:
            seen.add(row[2])
            picked.append(row)
    picked = picked[:count]
    picked += [row for row in found if row not in picked][:count - len(picked)]
    result = []
    for _, n, (first, last, heading), text in sorted(picked, key=lambda row: row[1]):
        if len(text) > EXCERPT_WIDTH:
            text = text[:EXCERPT_WIDTH - 3] + "..."
        result.append((n, f"{heading} ({first}-{last})", text))
    return result


def print_links(top, notes, searchable):
    """Print the outgoing and inbound links of the top notes. Return the exit code."""
    paths = sorted(notes)
    out = {}
    for path in searchable:
        lines, meta, _, start = notes[path]
        hits = ((t, resolve(t, paths)) for t in note_links(lines[start:], meta["related"]))
        out[path] = [(t, hit) for t, hit in hits if hit != path]
    print("links:")
    for path in top:
        print(f"- {path}")
        for target, hit in out[path]:
            if hit is None:
                print(f"    out: {target} = unresolved")
                continue
            if not isinstance(notes[hit], tuple):
                # a template or attachment note: read it only for its status
                try:
                    notes[hit] = (None, None, parse_note(read_lines(notes[hit]))[1], 0)
                except OSError as err:
                    print(f"SYSTEM ERROR: search.py: cannot read {hit}: {err}", file=sys.stderr)
                    return 1
            print(f"    out: {target} = {hit} ({notes[hit][2]})")
        inbound = sorted((p for p in searchable
                          if p != path and any(hit == path for _, hit in out[p])),
                         key=lambda p: p.encode("utf-8"))
        print(f"    in: {', '.join(inbound) if inbound else 'none'}")
    return 0


def main(argv):
    # UTF-8 and LF output on every OS: Windows pipes default to cp1252 and CRLF.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    try:
        parsed = parse_args(argv)
    except UsageError as err:
        print(f"SYSTEM ERROR: search.py: {err}, see --help", file=sys.stderr)
        return 2
    if parsed is None:
        return 0
    opts, terms = parsed
    root = require_vault()

    print(f"terms: {', '.join(terms)}")
    lowered = [fold(term) for term in terms]
    # notes: path -> (lines, meta, status, body start) once read, else its Path
    ranked, notes, searchable, parsed = [], {}, [], []
    for path, file, search in find_notes(root):
        notes[path] = file
        if not search:
            continue
        try:
            lines = read_lines(file)
        except OSError as err:
            print(f"SYSTEM ERROR: search.py: cannot read {path}: {err}", file=sys.stderr)
            return 1
        searchable.append(path)
        meta, status, title, body, start = parse_note(lines)
        notes[path] = (lines, meta, status, start)
        parsed.append((path, meta, status, title, body, line_sections(lines, start)))
    idf = rarity(lowered, [note[4] for note in parsed])
    whole = False
    for path, meta, status, title, body, owner in parsed:
        result = score_note(path, meta, status, title, body, lowered, idf, owner)
        if result:
            ranked.append((-result[0], is_archived(path), path.encode("utf-8"), path, result[1]))
            whole = whole or result[2]
    ranked.sort()

    links = unique_links(notes)
    shown = ranked[:opts["limit"]]
    print(f"matches: {len(ranked)}")
    print(f"shown: {len(shown)}")
    for *_, path, line in shown:
        print(f"{line} | link: {links[path]}")
        if opts["excerpts"]:
            lines, _, _, start = notes[path]
            for n, heading, text in excerpts(lines, start, lowered, idf, opts["excerpts"]):
                print(f"  {n} | {heading} | {text}")
    if not whole:
        for term, close in suggest(lowered, parsed):
            print(f"suggest: {term} = {', '.join(close)}")
    if opts["links"]:
        return print_links([row[3] for row in shown[:opts["links"]]], notes, searchable)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
