#!/usr/bin/env python3
"""usage: select.py [all | <note name>]

List the ingest candidates (status: draft, directly in "01. Inbox") and index
every other note, so the plan needs no extra searches. Read-only.
Run after the full wiki-lint:lint run, because lint moves stray drafts into the Inbox.
The vault comes from vault.py (the configured vault path).

arguments:
  (none)         every candidate, to pick one from
  all            the oldest candidates by created (or file) date, at most 10
                 (env INGEST_ALL_LIMIT); the others stay in the index as note: lines
  <note name>    one candidate by filename without .md, case-insensitive

output (stdout):
  candidate: <path> [| same name: <path>, ...]   a draft to ingest; same name = filename clash elsewhere
  frontmatter: <path> [| missing: <keys>] [| empty: <keys>] [| created: <YYYY-MM-DD> (file date)]
               [| source: <url> (from draft)]
                 schema keys the draft lacks; created is a suggestion from the file date, source
                 the URL on a Source: or URL: line of the body, else its first web link (outside code)
  mention: <path> | <text> -> <note path>, ...   a filename, title or alias of another note
                 found as a whole word in the draft body (outside frontmatter, code and
                 links) and not linked yet; the model judges whether to link it
  mentioned-in: <path> | <text> <- <note path>   up to 3 existing notes (not archived, not
                 a candidate) whose body names the draft's filename, title or alias by the
                 same rules without linking it; the plan may give them a linked row
  overlap: <path> | <note path> | <score> [| draft[, duplicate]]   up to 3 other notes (not
                 archived) sharing at least 3 distinctive words with the draft (outside
                 frontmatter, code and links; stopwords and words in over half the notes
                 skipped); score = shared / the draft's distinctive words, at least 0.30;
                 draft = another selected draft of this run, duplicate = the same text after
                 the frontmatter (whitespace ignored), listed first;
                 the model reads those notes to judge a merge or links
  candidates: <n>[, selected: <k>]   selected only when all leaves candidates for a next run
  ERROR: <message>   vault problem (path missing, no CLAUDE.md), exit 0
  folder: <folder>   a folder of the index ((vault root) for the root), its notes follow
  note: <name> [| status: <s>] [| aliases: <a>, ...] [| title: <t>]   every other note (dot
                 folders skipped) by filename without .md; its path is <folder>/<name>.md
  notes: <n>
  index: first <k> of <n> notes listed ...   only when the index passes about 20000
                 characters (env INGEST_INDEX_LIMIT); the rest is not listed
  run: <id>      last line: a new run id; pass it as --run <id> to plan.py and ledger.py
                 (and the other scripts), which keep the run ledger; the ledger gets every
                 listed candidate with a hash of its content, so apply can see a changed note,
                 and every mentioned-in note, the only non-orphans a linked row may edit

exit codes:
  0  listed (candidates: 0 is a normal result), or an ERROR line
  1  system error (a note cannot be read)
  2  bad usage (wrong arguments)
  3  user error (the named note does not exist, or is not a draft in 01. Inbox)

example: select.py "Tokens"
"""

import datetime
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault  # noqa: E402

import ledger  # noqa: E402

INBOX = "01. Inbox"
DEFAULT_LIMIT = 20000
FENCE = re.compile(r"^[ \t]*(```|~~~)")
DASHES = re.compile(r"^---[ \t]*$")
KEY = re.compile(r"^([A-Za-z_]+):[ \t]*(.*)$")
LIST_ITEM = re.compile(r"^[ \t]*-[ \t]*(.*)$")
SCHEMA = ("type", "topic", "aliases", "tags", "created", "related", "source")
CODE = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)")
# a [[wikilink]] (group 1 is its target) or a [markdown](link)
LINK = re.compile(r"!?\[\[([^\]|#\r\n]*)[^\]\r\n]*\]\]|\[[^\]\r\n]*\]\([^)\r\n]*\)")
MIN_NAME = 3  # shorter names match too many plain words
DEFAULT_ALL = 10
WORD = re.compile(r"[^\W\d_]{4,}")  # letters only, shorter words are mostly stopwords
STOP = frozenset("""about above after again also always among another because been before being
below between both cannot could does doing down during each even every from further have having
here into itself just like more most much must never only other over same should some such than
that their them then there these they this those through under until very want were what when
where which while will with within would your yours""".split())
URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
SOURCE_LINE = re.compile(r"^[\W_]*(?:source|url)\b[*_ \t]*:", re.IGNORECASE)
MIN_SHARED, MIN_SCORE, MAX_OVERLAP, MAX_MENTIONED = 3, 0.30, 3, 3


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
    return status, aliases, title


def frontmatter_and_body(text):
    """Return ({key: has a value}, body lines outside frontmatter and fenced code, created value,
    the text after the frontmatter with whitespace runs as one space)."""
    keys, body, last, created = {}, [], None, ""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    start = 0
    if lines and DASHES.match(lines[0].removeprefix("﻿")):
        for i in range(1, len(lines)):
            if DASHES.match(lines[i]):
                start = i + 1
                break
            key, item = KEY.match(lines[i]), LIST_ITEM.match(lines[i])
            if key:
                last = key.group(1)
                keys[last] = clean(key.group(2)) not in ("", "[]", "{}")
                if last == "created":
                    created = clean(key.group(2))
            elif item and last and clean(item.group(1)):
                keys[last] = True
    in_fence = False
    for line in lines[start:]:
        if FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            body.append(line)
    return keys, body, created, " ".join(" ".join(lines[start:]).split())


def file_date(path):
    st = path.stat()
    stamp = min(getattr(st, "st_birthtime", st.st_mtime), st.st_mtime)
    return datetime.date.fromtimestamp(stamp).isoformat()


def frontmatter_line(rec):
    keys = rec["keys"]
    missing = [k for k in SCHEMA if k not in keys]
    empty = [k for k in SCHEMA if keys.get(k) is False]
    parts = [f"frontmatter: {rec['path']}"]
    if missing:
        parts.append("missing: " + ", ".join(missing))
    if empty:
        parts.append("empty: " + ", ".join(empty))
    if not keys.get("created"):
        parts.append(f"created: {rec['date']} (file date)")
    if not keys.get("source"):
        url = source_url(rec["body"])
        if url:
            parts.append(f"source: {url} (from draft)")
    return [" | ".join(parts)] if len(parts) > 1 else []


def source_url(body):
    """The URL on a Source: or URL: line of the body, else its first web link; code skipped."""
    lines = [CODE.sub(" ", line) for line in body]
    for line in [l for l in lines if SOURCE_LINE.match(l)] + lines:
        m = URL.search(line)
        if m:
            return m.group(0).rstrip(".,;:!?*_")
    return ""


def name_index(records):
    """{casefolded name: set of paths} over filenames, titles and aliases; archived notes skipped."""
    names = {}
    for rec in records:
        if rec["status"] == "archived":
            continue
        for name in [stem(rec["path"]), rec["title"], *rec["aliases"]]:
            if len(name) >= MIN_NAME:
                names.setdefault(name.casefold(), set()).add(rec["path"])
    return names


def name_pattern(names):
    """One alternation of every name, longest first, as whole words."""
    # Limit: one big alternation, fine for a few thousand notes; a trie if vaults get huge
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def mention_lines(rec, names, pattern):
    """Names of other notes in the draft body that the draft does not link yet."""
    own = {n.casefold() for n in [stem(rec["path"]), rec["title"], *rec["aliases"]]}
    linked = set()
    for line in rec["body"]:
        for m in LINK.finditer(line):
            if m.group(1) is not None:
                linked |= names.get(m.group(1).strip().removesuffix(".md").rsplit("/", 1)[-1].casefold(), set())
    seen, out = set(), []
    for line in rec["body"]:
        masked = LINK.sub("\0", CODE.sub("\0", line))
        for m in pattern.finditer(masked):
            key = m.group(0).casefold()
            paths = names[key] - {rec["path"]} - linked - seen
            if key in own or not paths:
                continue
            seen |= paths
            out.append(f"mention: {rec['path']} | {m.group(0)} -> {', '.join(sorted(paths))}")
    return out


def words(body):
    """Distinctive word candidates of a body: letters only, outside code and links, no stopwords."""
    found = set()
    for line in body:
        for word in WORD.findall(LINK.sub(" ", CODE.sub(" ", line))):
            found.add(word.casefold())
    return found - STOP


def common_words(records):
    """Words in more than half of the notes (with at least 4 notes): too common to tell notes apart."""
    with_words = [r for r in records if "words" in r]
    if len(with_words) < 4:
        return set()
    counts = {}
    for rec in with_words:
        for word in rec["words"]:
            counts[word] = counts.get(word, 0) + 1
    return {w for w, n in counts.items() if n * 2 > len(with_words)}


def name_scan(rec, pattern):
    """({casefolded name: text as written} of note names in the body outside code and links,
    other than its own names; the casefolded stems it links to)."""
    theirs = {n.casefold() for n in [stem(rec["path"]), rec["title"], *rec["aliases"]]}
    found, targets = {}, set()
    for line in rec["body"]:
        targets |= {m.group(1).strip().removesuffix(".md").rsplit("/", 1)[-1].casefold()
                    for m in LINK.finditer(line) if m.group(1) is not None}
        for m in pattern.finditer(LINK.sub("\0", CODE.sub("\0", line))):
            if m.group(0).casefold() not in theirs:
                found.setdefault(m.group(0).casefold(), m.group(0))
    return found, targets


def mentioned_in_lines(rec, scans):
    """Existing notes whose body names the draft (filename, title or alias) without linking it;
    scans: (path, name_scan result) per existing note."""
    own = [n.casefold() for n in [stem(rec["path"]), rec["title"], *rec["aliases"]] if len(n) >= MIN_NAME]
    out = []
    for path, (found, targets) in scans:
        hit = next((found[n] for n in own if n in found), None)
        if hit and not targets & set(own):
            out.append((path, f"mentioned-in: {rec['path']} | {hit} <- {path}"))
            if len(out) == MAX_MENTIONED:
                break
    return out


def overlap_lines(rec, others, common):
    """Other notes that share the most distinctive words with the draft; others with a "norm" are
    drafts of this run, an identical one is a duplicate."""
    # Limit: plain word-set overlap, O(drafts x notes); stemming or tf-idf if hints miss too much
    mine = rec["words"] - common
    scored = []
    for other in others:
        shared = len(mine & other["words"])
        dup = "norm" in other and rec["norm"] != "" and other["norm"] == rec["norm"]
        if dup or (shared >= MIN_SHARED and shared / len(mine) >= MIN_SCORE):
            tag = (" | draft, duplicate" if dup else " | draft") if "norm" in other else ""
            scored.append((not dup, -(shared / len(mine) if mine else 1.0), other["path"], tag))
    return [f"overlap: {rec['path']} | {path} | {-score:.2f}{tag}"
            for _, score, path, tag in sorted(scored)[:MAX_OVERLAP]]


def read_records(vault):
    records = []
    for rel in list_notes(vault):
        try:
            text = (vault / rel).read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            raise sys_error(f"cannot read the notes in {vault.as_posix()}: {err}")
        status, aliases, title = parse_note(text)
        rec = {"path": rel, "status": status, "aliases": aliases, "title": title}
        if status != "archived":
            keys, body, created, norm = frontmatter_and_body(text)
            rec["words"], rec["body"] = words(body), body
            if is_candidate(rec):
                rec["keys"], rec["norm"] = keys, norm
                rec["created"] = created if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", created) else ""
                rec["date"] = file_date(vault / rel)
        records.append(rec)
    return records


def stem(path):
    return path.rsplit("/", 1)[-1].removesuffix(".md")


def folder_of(path):
    return path.rsplit("/", 1)[0] if "/" in path else "vault root"


def index_folder(path):
    return path.rsplit("/", 1)[0] if "/" in path else "(vault root)"


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
    line = f"note: {stem(rec['path'])}"
    if rec["status"]:
        line += f" | status: {rec['status']}"
    if rec["aliases"]:
        line += f" | aliases: {', '.join(rec['aliases'])}"
    if rec["title"] and rec["title"] != stem(rec["path"]):
        line += f" | title: {rec['title']}"
    return line


def build_output(records, arg, want, limit, all_limit):
    take_all = arg == "all"
    picked = [r for r in records if is_candidate(r) and (take_all or stem(r["path"]).lower() == want.lower())]
    if not take_all and not picked:
        raise user_error(not_found_message(records, want))
    total = len(picked)
    if take_all and total > all_limit:  # a bounded batch: the oldest drafts first
        oldest = sorted(picked, key=lambda r: (r["created"] or r["date"], r["path"]))[:all_limit]
        picked = [r for r in picked if r in oldest]
    names = name_index(records)
    pattern = name_pattern(names) if names else None
    existing = [r for r in records if "words" in r and not is_candidate(r)]
    common = common_words(records)
    # Limit: every note body scanned once with the vault-wide name pattern; fine for thousands of notes
    scans = [(r["path"], name_scan(r, pattern)) for r in existing] if pattern and picked else []
    out, mentioned = [], set()
    for rec in picked:
        out.append(candidate_line(rec, records))
        out += frontmatter_line(rec)
        if pattern:
            out += mention_lines(rec, names, pattern)
        for path, line in mentioned_in_lines(rec, scans):
            mentioned.add(path)
            out.append(line)
        out += overlap_lines(rec, existing + [r for r in picked if r is not rec], common)
    out.append(f"candidates: {total}" + (f", selected: {len(picked)}" if len(picked) < total else ""))
    picked_paths = {r["path"] for r in picked}
    others = sorted((r for r in records if r["path"] not in picked_paths),
                    key=lambda r: (index_folder(r["path"]), r["path"]))
    size, shown, folder = sum(len(line.encode("utf-8")) + 1 for line in out), 0, None
    for rec in others:
        if size > limit:  # the line that passes the limit is still printed
            break
        lines = [note_line(rec)]
        if index_folder(rec["path"]) != folder:
            folder = index_folder(rec["path"])
            lines.insert(0, f"folder: {folder}")
        out += lines
        shown += 1
        size += sum(len(line.encode("utf-8")) + 1 for line in lines)
    out.append(f"notes: {len(others)}")
    if shown < len(others):
        out.append(f"index: first {shown} of {len(others)} notes listed (output limit), search the vault for the rest")
    return out, picked, mentioned


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
        limits = []
        for var, default in (("INGEST_INDEX_LIMIT", DEFAULT_LIMIT), ("INGEST_ALL_LIMIT", DEFAULT_ALL)):
            value = os.environ.get(var, str(default))
            if not re.fullmatch(r"[0-9]+", value):
                raise bad(f"{var} must be a number")
            limits.append(int(value))
        out, picked, mentioned = build_output(records, arg, want, *limits)
        run = ledger.new_run_id()
        # plan.py checks the plan against these; apply refuses a note changed since this read
        ledger.record(run, "select", "pick" if not argv or not argv[0] else "all" if arg == "all" else "name")
        for rec in picked:
            try:
                ledger.record(run, "candidate", rec["path"], ledger.file_hash(vault / rec["path"]))
            except OSError as err:
                raise sys_error(f"cannot read {rec['path']}: {err}")
        for path in sorted(mentioned):
            ledger.record(run, "mentioned", path)
        print("\n".join(out))
        print(f"run: {run}")
    except Fail as fail:
        print(fail, file=sys.stderr)
        return fail.code
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(main(sys.argv[1:]))
