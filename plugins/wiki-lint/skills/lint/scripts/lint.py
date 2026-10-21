#!/usr/bin/env python3
"""usage: lint.py [--dry-run] [--as-of YYYY-MM-DD] [--format json|text] [--all] [--files <path>...]

Check the configured Obsidian vault (read through vault.py) against its
CLAUDE.md and print one JSON object (or the plain-text report).
Fixes two things without asking: moves draft notes outside "01. Inbox" into
the Inbox and unlinks dead links. A dead link that is close to exactly one
note name or alias is kept and reported as likely-typo; a dead link to a
non-note file (image, PDF, ...) is kept and reported as missing-attachment.
Everything else is only reported, including notes that are not valid UTF-8,
links into "99. Archived" and unused attachments.
Writes are atomic (temp file, fsync, replace); a note that changed since the
scan is left alone and reported as skipped-changed.

options:
  --dry-run          same JSON, no file changed
  --as-of YYYY-MM-DD date for the 7-day inbox-age cutoff (default today)
  --format text      plain-text report instead of JSON: a scan line, then one
                     block per non-empty impact group, one item per line,
                     at most 25 per category plus a "... N more" line
  --all              text report without the 25-line cap
  --files <path>...  only these notes or folders, paths from the vault root;
                     skips orphans, duplicate and unsafe names, unused
                     attachments and inbox age
  -h, --help         this help

exit codes:
  0  clean, nothing fixed or found
  1  system error (write failed, internal error)
  2  bad usage (unknown option, --files without paths)
  3  user error (--files path not found, CLAUDE.md without the type and
     status lists)
  4  fixes or findings (normal result, read the JSON)

A vault problem (no vault path, no CLAUDE.md) prints "ERROR: <message>" on
stdout and exits 0, the same as every other obsidian-wiki script.

An optional "## Lint ignore" section in the vault CLAUDE.md holds backticked
glob patterns, matched without regard to case:
  - Links: `Future *`, `[[Planned Topic]]`   dead links lint keeps; they are
                                             listed in allowlistedLinks
  - Paths: `Clippings/**`                    files lint does not scan; links
                                             to them still resolve

The vault's .obsidian/app.json is read too, if it is valid JSON: its
attachmentFolderPath folder holds no notes (default Attachments), and its
userIgnoreFilters path prefixes are skipped like Lint ignore paths.

example: lint.py --files "30. Knowledge/Tokens.md" "01. Inbox/"
"""

import difflib
import fnmatch
import glob
import json
import os
import re
import sys
import tempfile
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault  # noqa: E402

USAGE = "usage: lint.py [--dry-run] [--as-of YYYY-MM-DD] [--format json|text] [--all] [--files <path>...]"
INBOX = "01. Inbox"
ARCHIVE = "99. Archived"
EXEMPT_TOPS = ("10. Daily", "90. Templates", ARCHIVE)  # no note checks, only dead links

KEY_RE = re.compile(r"[A-Za-z0-9_-]+:")
LIST_ITEM_RE = re.compile(r"[ \t]*-[ \t]*")
FENCE_RE = re.compile(r" {0,3}(```+|~~~+)")
HEADING_RE = re.compile(r"#{1,6}(?:[ \t]|$)")
BLOCK_ID_RE = re.compile(r"[ \t]*\^[A-Za-z0-9-]+[ \t]*")
BLOCK_END_RE = re.compile(r"(?:^|[ \t])\^([A-Za-z0-9-]+)[ \t]*$")
# Obsidian resolves an extensionless wiki link to a note, a Canvas or a Base.
SUFFIXES = ("", ".md", ".canvas", ".base")
NO_FRAGMENT_CHECK = (".pdf", ".canvas", ".base")  # #page=, views: fragments lint cannot check
LINK_RE = re.compile(r"!?\[\[[^\]]*\]\]|!?\[[^\]]*\]\((?:<[^>]*>|[^)]*)\)")
SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
TAG_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
# A file extension other than a note's: a dead link to it is a lost attachment, kept.
ATTACHMENT_RE = re.compile(r"\.(?!(?:md|canvas|base)$)[a-z][a-z0-9]{0,4}$", re.I)
TEXT_CAP = 25  # text report lines per category; --all lifts it
TYPO_CUTOFF = 0.9  # difflib ratio: [[Contex Engineering]] vs Context Engineering is 0.97

# Impact groups in report order; findings are sorted by group, then path and line.
GROUPS = (
    ("changed", ("movedToInbox", "removedDeadLinks")),
    ("broken-or-risky", ("ambiguous-link", "likely-typo", "missing-attachment", "invalid-encoding",
                         "duplicate-name", "unsafe-name",
                         "status-location", "broken-fragment", "skipped-changed")),
    ("rule-violations", ("frontmatter-missing", "frontmatter-invalid", "empty-note", "empty-section")),
    ("housekeeping", ("inbox-age", "archived-link", "unused-attachment", "orphans")),
    ("info", ("placeholderLinks", "allowlistedLinks")),
)
RANK = {cat: i for i, (_, cats) in enumerate(GROUPS) for cat in cats}
SURROGATE_RE = re.compile("[\ud800-\udfff]")
CONTROL_RE = re.compile("[\x00-\x1f\x7f]")
BOM = "\ufeff"
WIN_RESERVED = {"con", "prn", "aux", "nul"} | {f"{d}{i}" for d in ("com", "lpt") for i in range(1, 10)}
WIN_FORBIDDEN = '<>:"\\|?*'
LINK_FORBIDDEN = "#^[]|"

# Scan events for the empty-section check: a heading is a (level, line, text) tuple.
CONTENT = "content"
BLANK = "blank"  # blank line, block id or HTML comment: does not count as content


class LintExit(Exception):
    """Stop with an exit code and a stderr line."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def system_error(msg):
    return LintExit(1, f"SYSTEM ERROR: lint.py: {msg}")


def usage_error(msg):
    return LintExit(2, f"SYSTEM ERROR: lint.py: {msg}. {USAGE}")


def user_error(msg):
    return LintExit(3, f"USER ERROR: lint.py: {msg}")


# ---------- small helpers ----------

def top(p):
    """First folder of a vault path, "" for a note in the root."""
    return p.split("/", 1)[0] if "/" in p else ""


def base(p):
    return p.rsplit("/", 1)[-1]


def parent(p):
    return p.rsplit("/", 1)[0] if "/" in p else ""


def exempt(p):
    return top(p) in EXEMPT_TOPS


def trim(s):
    return s.strip(" \t")


def strip_cr(s):
    return s[:-1] if s.endswith("\r") else s


def unquote(s):
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def safe(v):
    """v with the lone surrogates (undecodable bytes) of each string shown as \\uXXXX text."""
    if isinstance(v, str):
        return SURROGATE_RE.sub(lambda m: f"\\u{ord(m.group()):04x}", v)
    if isinstance(v, dict):
        return {k: safe(x) for k, x in v.items()}
    return v


def plain(v):
    """One text-report field: odd bytes as \\uXXXX, control characters as \\xNN, never a line break."""
    return CONTROL_RE.sub(lambda m: f"\\x{ord(m.group()):02x}", safe(str(v)))


def js(v):
    """Strictly valid one-line JSON: json.dumps escapes control characters."""
    return json.dumps(safe(v), ensure_ascii=False)


def fold(s):
    """Name as Obsidian compares it: NFC (macOS sync gives NFD file names), then casefold (sharp s is ss)."""
    return unicodedata.normalize("NFC", s).casefold()


def matches(name, patterns):
    """Case-insensitive glob match of name against any of the (fold()) patterns."""
    name = fold(name)
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def url_decode(s):
    """Decode %XX byte escapes, leave anything else as is."""
    if "%" not in s:
        return s
    raw = s.encode("utf-8", "surrogateescape")
    decoded = re.sub(rb"%([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw)
    return decoded.decode("utf-8", "surrogateescape")


def normalize(p):
    """Resolve "." and ".." segments; ".." never climbs above the vault root."""
    out = []
    for part in p.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if out:
                out.pop()
            continue
        out.append(part)
    return "/".join(out)


def backtick_run(s, i):
    """Number of backticks starting at s[i]."""
    j = i
    while j < len(s) and s[j] == "`":
        j += 1
    return j - i


def mask_code(s):
    """Replace inline code spans with spaces, so links inside them are never seen."""
    if "`" not in s:
        return s
    out, i, n = [], 0, len(s)
    while i < n:
        if s[i] != "`":
            out.append(s[i])
            i += 1
            continue
        run = backtick_run(s, i)
        # Look for a closing run of exactly the same length.
        j, end = i + run, -1
        while j < n:
            if s[j] != "`":
                j += 1
                continue
            m = backtick_run(s, j)
            if m == run:
                end = j
                break
            j += m
        if end >= 0:
            out.append(" " * (end + run - i))
            i = end + run
        else:
            out.append(s[i:i + run])
            i += run
    return "".join(out)


def heading_key(s):
    """Heading text as Obsidian matches it: no closing #'s, single spaces, any case."""
    s = re.sub(r"[ \t]+#+[ \t]*$", "", " " + s)
    return fold(" ".join(s.split()))


def add_unique(d, key, value):
    """Append value to the list d[key] unless it is already there."""
    lst = d.setdefault(key, [])
    if value not in lst:
        lst.append(value)


def joined(paths):
    return ", ".join(sorted(paths))


def read_text(path):
    """File text without newline translation; odd bytes survive a write back."""
    return path.read_bytes().decode("utf-8", "surrogateescape")


# ---------- arguments and vault rules ----------

def parse_args(argv):
    """Return (dry_run, as_of, files_mode, files, text, all), or raise LintExit."""
    dry, as_of, files_mode, files, text, every = False, date.today(), False, [], False, False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            sys.stdout.write(__doc__)
            raise LintExit(0, "")
        if arg == "--dry-run":
            dry = True
            i += 1
        elif arg == "--all":
            every = True
            i += 1
        elif arg == "--as-of":
            try:
                as_of = date.fromisoformat(argv[i + 1])
            except (IndexError, ValueError):
                raise usage_error("--as-of needs a YYYY-MM-DD date")
            i += 2
        elif arg == "--format":
            if i + 1 >= len(argv) or argv[i + 1] not in ("json", "text"):
                raise usage_error("--format needs json or text")
            text = argv[i + 1] == "text"
            i += 2
        elif arg == "--files":
            files_mode = True
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                files.append(argv[i])
                i += 1
        else:
            raise usage_error(f"unknown argument: {arg}")
    if files_mode and not files:
        raise usage_error("--files needs at least one path")
    return dry, as_of, files_mode, files, text, every


def read_rules(text):
    """Allowed type and status values, then the Lint ignore link and path patterns."""
    types = []
    for line in text.split("\n"):
        if "Allowed `type` values" in line:
            rest = line.split(":", 1)[1] if ":" in line else line
            types = " ".join(re.findall(r"`([^`]*)`", rest)).split()
            break
    statuses, links, paths, section = [], [], [], None
    for line in text.split("\n"):
        if re.match(r"#+ ", line):
            section = ("status" if re.match(r"#+ Status lifecycle", line)
                       else "ignore" if re.match(r"#+ Lint ignore", line) else None)
        elif section == "status":
            m = re.match(r"- `([^`]*)`", line)
            if m:
                statuses.extend(m.group(1).split())
        elif section == "ignore":
            m = re.match(r"- (links|paths):", line, re.I)
            if m:
                pats = [fold(p.strip()) for p in re.findall(r"`([^`]*)`", line) if p.strip()]
                if m.group(1).lower() == "paths":
                    paths.extend(pats)
                else:  # `[[Planned Topic]]` means the target Planned Topic
                    links.extend(re.sub(r"^!?\[\[(.*)\]\]$", r"\1", p) for p in pats)
    if not types:
        raise user_error("no 'Allowed `type` values' line in CLAUDE.md")
    if not statuses:
        raise user_error("no '- `status`' items under 'Status lifecycle' in CLAUDE.md")
    return set(types), set(statuses), links, paths


def list_files(vault):
    """{vault path: modified date} for every file, hidden files and folders left out."""
    found = {}
    for root, dirs, names in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in names:
            full = Path(root) / name
            if name.startswith(".") or full.is_symlink() or not full.is_file():
                continue
            day = datetime.fromtimestamp(full.stat().st_mtime).date().isoformat()
            found[full.relative_to(vault).as_posix()] = day
    return dict(sorted(found.items()))


def selection(vault, files):
    """--files paths as vault paths; a folder ends with "/"."""
    sel = []
    for f in files:
        if f.startswith("./"):
            f = f[2:]
        if f.endswith("/"):
            f = f[:-1]
        if f and (vault / f).is_dir():
            sel.append(f + "/")
        elif f and (vault / f).is_file():
            sel.append(f)
        else:
            raise user_error(f"not found in vault: {f}")
    return sel


def obsidian_settings(vault):
    """(attachment folder as fold() text or None, ignore globs) from .obsidian/app.json, read-only.

    No file or no valid JSON: the "Attachments" folder and no ignores. An attachment folder of
    "/" (vault root) or "./..." (next to the note) excludes no folder. userIgnoreFilters entries
    are path prefixes, as in Obsidian.
    """
    try:
        cfg = json.loads((vault / ".obsidian" / "app.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    folder = cfg.get("attachmentFolderPath", "Attachments")
    folder = folder.strip("/") if isinstance(folder, str) and not folder.startswith("./") else ""
    filters = cfg.get("userIgnoreFilters")
    # Limit: /regex/ entries are skipped, add re.search support when a vault uses them
    ignored = [fold(glob.escape(f)) + "*" for f in (filters if isinstance(filters, list) else [])
               if isinstance(f, str) and f and not (len(f) > 2 and f[0] == f[-1] == "/")]
    return (fold(folder) if folder else None), ignored


def name_problems(name):
    """Reasons a file or folder name breaks on Windows, in a sync or in an Obsidian link."""
    out = []
    if name.split(".", 1)[0].rstrip(" ").lower() in WIN_RESERVED:
        out.append("Windows-reserved name")
    bad = sorted({ch for ch in name if ch in WIN_FORBIDDEN})
    if bad:
        out.append("character " + " ".join(bad) + " that Windows forbids")
    if name.endswith((".", " ")):
        out.append("ends with a dot or space")
    bad = sorted({ch for ch in name if ch in LINK_FORBIDDEN})
    if bad:
        out.append("character " + " ".join(bad) + " that Obsidian links cannot carry")
    if CONTROL_RE.search(name):
        out.append("control character")
    if unicodedata.normalize("NFC", name) != name:
        out.append("not Unicode NFC")
    return out


def unsafe_names(paths):
    """[(path, detail)] for each file or folder in paths whose name is unsafe or differs only
    in case from another name in the same folder. A folder is reported once, by its own path."""
    every = set()
    for p in paths:
        parts = p.split("/")
        every.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    by_fold = {}
    for p in every:
        by_fold.setdefault((fold(parent(p)), fold(base(p))), []).append(p)
    out = []
    for p in sorted(every):
        reasons = name_problems(base(p))
        others = [base(o) for o in by_fold[(fold(parent(p)), fold(base(p)))] if o != p]
        if others:
            reasons.append("differs only in case from " + ", ".join(sorted(others)))
        if reasons:
            out.append((p, "; ".join(reasons)))
    return out


# ---------- notes ----------

class Note:
    """One Markdown note: its lines (with any CR kept) and its frontmatter."""

    def __init__(self, path, raw):
        self.raw = raw            # bytes as scanned, to detect a change before writing
        text = raw.decode("utf-8", "surrogateescape")
        self.path = path          # path in the vault before any move
        self.final = path         # path after a move to the Inbox
        self.changed = False
        self.trailing_newline = text.endswith("\n")
        if self.trailing_newline:
            text = text[:-1]
        self.lines = text.split("\n") if text else []
        self.fm_end = 0           # line number of the closing ---, 0 without frontmatter
        self.values = {}          # scalar frontmatter values
        self.key_lines = {}       # key -> line number
        self.items = {}           # list values (tags, aliases, [..] lists) -> [(value, line)]
        self.bom = bool(self.lines) and self.lines[0].startswith(BOM)
        self.unclosed = False     # opening --- without a closing ---
        self.duplicates = []      # (key, first line, repeated line)
        self.parse_frontmatter()
        self.status = self.values.get("status", "").lower()
        self.headings, self.blocks = set(), set()
        for _, c, code in self.body():
            if code:
                continue
            m = HEADING_RE.match(c)
            if m:
                self.headings.add(heading_key(c[m.end():]))
            m = BLOCK_END_RE.search(c)
            if m:
                self.blocks.add(m.group(1).lower())

    def body(self):
        """(line number, line without CR, inside a code fence) for each body line."""
        fence = None
        for k in range(self.fm_end + 1, len(self.lines) + 1):
            c = strip_cr(self.line(k))
            m = FENCE_RE.match(c)
            if m:
                mark = m.group(0).lstrip(" ")
                if fence is None:
                    fence = (mark[0], len(mark))
                elif mark[0] == fence[0] and len(mark) >= fence[1] and trim(c[m.end():]) == "":
                    fence = None
                yield k, c, True
            else:
                yield k, c, fence is not None

    def line(self, k):
        return self.lines[k - 1]

    def parse_frontmatter(self):
        if not self.lines or strip_cr(self.lines[0]).lstrip(BOM) != "---":
            return
        for k in range(2, len(self.lines) + 1):
            if strip_cr(self.line(k)) == "---":
                self.fm_end = k
                break
        self.unclosed = not self.fm_end
        key = ""
        for k in range(2, self.fm_end):
            c = strip_cr(self.line(k))
            m = KEY_RE.match(c)
            if m:
                key = c[:m.end() - 1].lower()
                v = trim(c[m.end():])
                if key in self.key_lines:  # the last value still wins
                    self.duplicates.append((key, self.key_lines[key], k))
                self.key_lines[key] = k
                if re.fullmatch(r"\[.*\]", v):
                    for part in v[1:-1].split(","):
                        self.add_item(key, part, k)
                elif v:
                    v = unquote(re.sub(r"[ \t]+#.*$", "", v, count=1))
                    if key in ("tags", "aliases"):
                        self.add_item(key, v, k)
                    else:
                        self.values[key] = v
            elif key:
                m = LIST_ITEM_RE.match(c)
                if m:
                    self.add_item(key, c[m.end():], k)

    def add_item(self, key, value, k):
        value = unquote(trim(value))
        if value:
            self.items.setdefault(key, []).append((value, k))

    def text(self):
        return "\n".join(self.lines) + ("\n" if self.trailing_newline and self.lines else "")


# ---------- the lint run ----------

class Lint:
    def __init__(self, vault, files_mode, sel, rules, as_of):
        self.vault = vault
        self.files_mode = files_mode
        self.sel = sel
        self.types, self.statuses, self.keep_links, skip_paths = rules
        self.attachments, ignored = obsidian_settings(vault)
        self.skip_paths = skip_paths + ignored
        self.as_of = as_of
        self.cutoff = (as_of - timedelta(days=7)).isoformat()
        self.dates = list_files(vault)
        self.notes = [Note(p, (vault / p).read_bytes()) for p in self.dates if self.is_note(p)]
        # Lint ignore paths and files Obsidian excludes: still link targets (with aliases
        # and headings), never scanned.
        self.scanned = [n for n in self.notes if not matches(n.path, self.skip_paths)]
        self.final = {p: p for p in self.dates}
        self.moves = []           # (from, to)
        self.dead = {}            # sort key -> JSON
        self.placeholders = {}
        self.allowlisted = {}
        self.links = 0            # link tokens checked
        self.findings = {}
        self.orphans = {}
        self.incoming = {}
        self.seq = 0
        self.found = False        # any fix or finding

    def is_note(self, p):
        in_attachments = self.attachments is not None and fold(p).startswith(self.attachments + "/")
        return p.lower().endswith(".md") and not in_attachments and p != "CLAUDE.md"

    def selected(self, p):
        if not self.files_mode:
            return True
        return any(p == s or (s.endswith("/") and p.startswith(s)) for s in self.sel)

    def finding(self, category, path, line, detail):
        self.found = True
        self.findings[(RANK[category], path, line, category, detail)] = {
            "category": category, "path": path, "line": line, "detail": detail}

    def run(self):
        self.move_stray_drafts()
        self.build_index()
        self.checked = [n for n in self.scanned if self.selected(n.path)]
        for note in self.checked:
            self.check_note(note)
        if not self.files_mode:
            self.check_duplicates()
            self.check_orphans()
            self.check_attachments()
            kept = [p for p in self.final.values() if not matches(p, self.skip_paths)]
            for path, detail in unsafe_names(kept):
                self.finding("unsafe-name", path, 1, detail)

    # 1. Stray drafts into the Inbox.
    def move_stray_drafts(self):
        taken = {fold(p) for p in self.dates}
        for note in self.scanned:
            if note.status != "draft" or top(note.path) == INBOX or not self.selected(note.path):
                continue
            to = f"{INBOX}/{base(note.path)}"
            if fold(to) in taken:
                self.finding("status-location", note.path, note.key_lines.get("status", 0),
                             f"draft outside {INBOX}, not moved: {to} already exists")
                continue
            taken.add(fold(to))
            note.final = self.final[note.path] = to
            self.moves.append((note.path, to))
            self.found = True

    # Link index on final paths: exact path, file name and alias.
    def build_index(self):
        self.exists, self.by_base, self.alias_owners = {}, {}, {}
        self.note_at = {note.final: note for note in self.notes}
        for fp in self.final.values():
            self.exists[fold(fp)] = fp
            add_unique(self.by_base, fold(base(fp)), fp)
        self.names = {}           # fold(name or alias) -> name as written, for likely-typo
        for note in self.notes:
            name = re.sub(r"\.md$", "", base(note.final), flags=re.I)
            self.names.setdefault(fold(name), name)
            for alias, _ in note.items.get("aliases", []):
                add_unique(self.alias_owners, fold(alias), note.final)
                self.names.setdefault(fold(alias), alias)

    def resolve(self, target, from_dir, markdown):
        """Return ("self"|"ok"|"amb"|"dead", [final paths])."""
        target = target.split("#", 1)[0]
        if not target:
            return "self", []
        lt = fold(target)
        # Markdown links are relative to the note first.
        if markdown and from_dir:
            r = fold(normalize(f"{from_dir}/{target}"))
            for s in SUFFIXES:
                if r + s in self.exists:
                    return "ok", [self.exists[r + s]]
        lt = lt.lstrip("/")
        for s in SUFFIXES:
            if lt + s in self.exists:
                return "ok", [self.exists[lt + s]]
        # Then by file name, where the link may give the end of the path.
        # A note wins over a Canvas, a Canvas over a Base, as in Obsidian.
        b = base(lt)
        hits = []
        for s in SUFFIXES:
            for cand in self.by_base.get(b + s, []):
                c = fold(cand)
                if (c == lt + s or c.endswith("/" + lt + s)) and cand not in hits:
                    hits.append(cand)
            if hits and s:
                break
        if not hits and "/" not in lt:
            hits = list(self.alias_owners.get(lt, []))
        if not hits:
            return "dead", []
        return ("amb" if len(hits) > 1 else "ok"), hits

    def unique_link(self, path):
        """Shortest path suffix (no .md) that resolves to exactly this file; lint never writes it."""
        parts = re.sub(r"\.md$", "", path, flags=re.I).split("/")
        for n in range(1, len(parts)):
            suffix = "/".join(parts[-n:])
            if self.resolve(suffix, "", False) == ("ok", [path]):
                return suffix
        return "/".join(parts)

    def check_fragment(self, note, k, tok, target, hit):
        """Report a #heading or #^block that the resolved target does not have."""
        parts = [p for p in target.split("#")[1:] if trim(p)]
        if not parts or hit.lower().endswith(NO_FRAGMENT_CHECK):
            return
        frag = parts[-1]  # [[Note#H1#H2]] points at the last heading
        dest = self.note_at.get(hit)
        if dest is None:
            self.finding("broken-fragment", note.final, k, f"{tok} fragment on non-note target")
        elif frag.startswith("^"):
            if trim(frag[1:]).lower() not in dest.blocks:
                self.finding("broken-fragment", note.final, k, f"{tok} block not found")
        elif heading_key(frag) not in dest.headings:
            self.finding("broken-fragment", note.final, k, f"{tok} heading not found")

    def placeholder(self, fp, k, tok):
        self.seq += 1
        self.placeholders[(fp, k, self.seq)] = {"path": fp, "line": k, "link": tok}

    def kept(self, target):
        """True when a dead link target matches a Lint ignore link pattern, with or without .md."""
        t = target.split("#", 1)[0].strip()
        return matches(t, self.keep_links) or matches(t[:-3] if t.lower().endswith(".md") else t + ".md",
                                                       self.keep_links)

    def typo_of(self, target):
        """The one note name or alias close to a dead link target, else None."""
        t = re.sub(r"\.md$", "", base(target.split("#", 1)[0].strip()), flags=re.I)
        close = difflib.get_close_matches(fold(t), self.names, n=2, cutoff=TYPO_CUTOFF)
        return self.names[close[0]] if len(close) == 1 else None

    def archived_link(self, fp, k, tok, hit):
        """Report a link into the archive; suggest the one active note that has its name as alias."""
        name = re.sub(r"\.md$", "", base(hit), flags=re.I)
        owners = [p for p in self.alias_owners.get(fold(name), []) if top(p) != ARCHIVE]
        tail = f"; use [[{self.unique_link(owners[0])}]]" if len(owners) == 1 else ""
        self.finding("archived-link", fp, k, f"{tok} points to {hit}{tail}")

    def handle_link(self, note, k, tok):
        """Check one link token; return its replacement (the token unless it is dead)."""
        self.links += 1
        fp = note.final
        body = tok[1:] if tok.startswith("!") else tok
        if body.startswith("[["):
            inner = body[2:-2]
            if "{{" in inner:
                self.placeholder(fp, k, tok)
                return tok
            if "|" in inner:
                target, shown = inner.split("|", 1)
                if target.endswith("\\"):  # escaped pipe inside a table
                    target = target[:-1]
            else:
                target = shown = inner
            res, hits = self.resolve(target, "", False)
        else:
            i = body.index("](")
            text, dest = body[1:i], body[i + 2:-1]
            if dest.startswith("<"):
                dest = dest[1:-1]
            else:
                dest = dest.split(" ", 1)[0]
            if not dest or dest.startswith("#") or SCHEME_RE.match(dest):
                return tok
            if "{{" in dest:
                self.placeholder(fp, k, tok)
                return tok
            dest = url_decode(dest)
            shown = text or dest
            res, hits = self.resolve(dest, parent(fp), True)
        if res == "self":  # [[#Heading]] in the same note
            self.check_fragment(note, k, tok, target, fp)
            return tok
        if res == "ok":
            self.check_fragment(note, k, tok, target if body.startswith("[[") else dest, hits[0])
            if top(hits[0]) == ARCHIVE and top(fp) != ARCHIVE:
                self.archived_link(fp, k, tok, hits[0])
        if res == "amb":
            unique = ", ".join(f"[[{self.unique_link(h)}]]" for h in sorted(hits))
            self.finding("ambiguous-link", fp, k, f"{tok} matches {joined(hits)}; unique: {unique}")
        if res in ("ok", "amb"):
            for h in hits:
                if h != fp:
                    self.incoming[h] = self.incoming.get(h, 0) + 1
            return tok
        self.seq += 1
        target = target if body.startswith("[[") else dest
        if self.kept(target):
            self.allowlisted[(fp, k, self.seq)] = {"path": fp, "line": k, "link": tok}
            return tok
        name = base(target.split("#", 1)[0].strip())
        if ATTACHMENT_RE.search(name):
            self.finding("missing-attachment", fp, k, f"{tok} file {name} not found")
            return tok
        typo = self.typo_of(target)
        if typo:
            self.finding("likely-typo", fp, k, f"{tok} did you mean [[{typo}]]")
            return tok
        self.dead[(fp, k, self.seq)] = {"path": fp, "line": k, "deadLink": tok}
        self.found = True
        return shown

    def scan_line(self, note, k):
        """Check every link on line k outside inline code; unlink dead ones."""
        raw = note.line(k)
        if "[" not in raw:
            return
        masked = mask_code(raw)
        out, pos = [], 0
        m = LINK_RE.search(masked, pos)
        while m:
            out.append(raw[pos:m.start()])
            out.append(self.handle_link(note, k, raw[m.start():m.end()]))
            pos = m.end()
            m = LINK_RE.search(masked, pos)
        out.append(raw[pos:])
        new = "".join(out)
        if new != raw:
            note.lines[k - 1] = new
            note.changed = True

    def scan_body(self, note, check_sections):
        """Links in frontmatter and body (outside code), then the empty-section check."""
        for k in range(2, note.fm_end):
            self.scan_line(note, k)
        events, in_comment = [], False
        for k, c, code in note.body():
            if code:
                events.append(CONTENT)
                continue
            self.scan_line(note, k)
            kind, in_comment = self.line_kind(c, k, in_comment)
            events.append(kind)
        if check_sections:
            if CONTENT not in events:
                self.finding("empty-note", note.final, 1, "no body text")
            self.empty_sections(note, events)

    @staticmethod
    def line_kind(c, k, in_comment):
        """Return (event, still inside a multi-line HTML comment)."""
        if in_comment:
            return BLANK, "-->" not in c
        if HEADING_RE.match(c):
            return (len(re.match(r"#+", c).group(0)), k, trim(c)), False
        if trim(c) == "" or BLOCK_ID_RE.fullmatch(c):
            return BLANK, False
        if re.match(r"[ \t]*<!--", c):
            e = c.find("-->")
            if e < 0:
                return BLANK, True
            if trim(c[e + 3:]) == "":
                return BLANK, False
        return CONTENT, False

    def empty_sections(self, note, events):
        """A heading is empty when only blanks follow before the next same or higher heading."""
        for i, ev in enumerate(events):
            if not isinstance(ev, tuple):
                continue
            level, k, text = ev
            j = i + 1
            while j < len(events) and events[j] == BLANK:
                j += 1
            if j == len(events) or (isinstance(events[j], tuple) and events[j][0] <= level):
                self.finding("empty-section", note.final, k, text)

    # 2. Dead links (all folders) and the per-note checks.
    def check_note(self, note):
        fp = note.final
        checks = not exempt(fp)
        if note.raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            self.finding("invalid-encoding", fp, 1, "UTF-16 byte order mark, Obsidian needs UTF-8")
        else:
            bad = next((k for k, c in enumerate(note.lines, 1) if SURROGATE_RE.search(c)), 0)
            if bad:
                self.finding("invalid-encoding", fp, bad, "bytes that are not UTF-8 (cp1252 or Latin-1?)")
        self.scan_body(note, checks)
        if note.status == "archived" and top(fp) != ARCHIVE:
            self.finding("status-location", fp, note.key_lines.get("status", 0),
                         f"status archived outside {ARCHIVE}")
        if not checks:
            return
        if note.unclosed:
            self.finding("frontmatter-invalid", fp, 1, "frontmatter not closed")
            return
        if not note.fm_end:
            self.finding("frontmatter-missing", fp, 1, "no frontmatter")
            return
        if note.bom:
            self.finding("frontmatter-invalid", fp, 1, "starts with a byte order mark")
        for key, first, k in note.duplicates:
            self.finding("frontmatter-invalid", fp, k, f"duplicate key {key} at lines {first} and {k}")
        self.check_frontmatter(note)
        if not self.files_mode and top(fp) == INBOX:
            self.check_inbox_age(note)

    def check_frontmatter(self, note):
        fp, values, lines = note.final, note.values, note.key_lines
        for key in ("type", "status", "created"):
            if not values.get(key) and not note.items.get(key):
                self.finding("frontmatter-missing", fp, 1, f"no {key}")
        v = values.get("type", "")
        if v and v not in self.types:
            self.finding("frontmatter-invalid", fp, lines["type"], f"type '{v}' is not in the vault CLAUDE.md list")
        v = values.get("status", "")
        if v and v not in self.statuses:
            self.finding("frontmatter-invalid", fp, lines["status"], f"status '{v}' is not in the vault CLAUDE.md list")
        v = values.get("created", "")
        problem = v and self.created(note)[1]
        if problem:
            self.finding("frontmatter-invalid", fp, lines["created"], f"created '{v}' {problem}")
        for tag, k in note.items.get("tags", []):
            if not TAG_RE.fullmatch(tag):
                self.finding("frontmatter-invalid", fp, k, f"tag '{tag}' is not lowercase kebab-case")

    def created(self, note):
        """(created as text, None) when it is a real date not after --as-of, else (None, problem)."""
        v = note.values.get("created", "")
        if not DATE_RE.fullmatch(v):
            return None, "is not YYYY-MM-DD"
        try:
            day = date.fromisoformat(v)
        except ValueError:
            return None, "is not a real date"
        return (None, f"is after {self.as_of}") if day > self.as_of else (v, None)

    def check_inbox_age(self, note):
        """Inbox notes older than 7 days, by a valid created date or else by file date."""
        v = self.created(note)[0]
        if v:
            if v < self.cutoff:
                self.finding("inbox-age", note.final, note.key_lines["created"], f"created {v}, older than 7 days")
        elif self.dates[note.path] < self.cutoff:
            self.finding("inbox-age", note.final, 1, f"file date {self.dates[note.path]}, older than 7 days")

    # 3. Whole-vault checks (full mode only).
    def check_duplicates(self):
        # Archived notes are left out: a merge adds their name as an alias by design.
        named, name_of = {}, {}
        for note in self.scanned:
            if top(note.final) != ARCHIVE:
                nm = re.sub(r"\.md$", "", fold(base(note.final)))
                add_unique(named, nm, note.final)
                name_of[note.final] = nm
        for note in self.scanned:
            fp = note.final
            if fp not in name_of:
                continue
            nm = name_of[fp]
            others = [p for p in named[nm] if p != fp]
            if others:
                self.finding("duplicate-name", fp, 1, f"same name as {joined(others)}")
            for alias, k in note.items.get("aliases", []):
                la = fold(alias)
                if la == nm:
                    continue
                if la in named:
                    self.finding("duplicate-name", fp, k, f"alias '{alias}' equals the name of {joined(named[la])}")
                others = [p for p in self.alias_owners.get(la, []) if p != fp and p in name_of]
                if others:
                    self.finding("duplicate-name", fp, k, f"alias '{alias}' is also an alias of {joined(others)}")

    def check_orphans(self):
        for note in self.scanned:
            fp = note.final
            if not exempt(fp) and base(fp) != "Home.md" and not self.incoming.get(fp):
                self.orphans[fp] = fp

    def check_attachments(self):
        """Attachment-folder files no scanned link reaches; a .canvas, .base or unscanned note that
        names the file counts as a use, so a skipped reference never reports a file as unused."""
        if self.attachments is None:
            return
        scanned = {n.path for n in self.scanned}
        # Limit: plain name search in those files, parse canvas/base links if it hides real leftovers
        other = "\n".join(fold(read_text(self.vault / p)) for p in self.dates
                          if p.lower().endswith((".canvas", ".base")) or (self.is_note(p) and p not in scanned))
        for p in self.dates:
            if (fold(p).startswith(self.attachments + "/") and not self.incoming.get(p)
                    and not matches(p, self.skip_paths) and fold(base(p)) not in other):
                size = (self.vault / p).stat().st_size
                self.finding("unused-attachment", p, 1, f"{size} bytes, no note, canvas or base links to it")

    # ---------- output and writes ----------

    def json(self):
        def block(name, items, tail):
            if not items:
                return f'  "{name}": []{tail}\n'
            return f'  "{name}": [\n    ' + ",\n    ".join(items) + f"\n  ]{tail}\n"

        moved = [js({"from": a, "to": b}) for a, b in self.moves]
        by_key = lambda d: [js(d[key]) for key in sorted(d)]  # noqa: E731
        return ("{\n" + self.summary() + block("movedToInbox", moved, ",")
                + block("removedDeadLinks", by_key(self.dead), ",")
                + block("placeholderLinks", by_key(self.placeholders), ",")
                + block("allowlistedLinks", by_key(self.allowlisted), ",")
                + block("orphans", by_key(self.orphans), ",")
                + block("findings", by_key(self.findings), "") + "}\n")

    def counts(self):
        """Item count per category."""
        counts = {"movedToInbox": len(self.moves), "removedDeadLinks": len(self.dead),
                  "placeholderLinks": len(self.placeholders), "allowlistedLinks": len(self.allowlisted),
                  "orphans": len(self.orphans)}
        for key in self.findings:
            counts[key[3]] = counts.get(key[3], 0) + 1
        return counts

    def summary(self):
        """Scan counts, then per impact group (in report order) the counts of each category."""
        counts = self.counts()
        lines = [f'    "notesScanned": {len(self.checked)}', f'    "linksScanned": {self.links}']
        for group, cats in GROUPS:
            lines.append(f"    {js(group)}: " + js({c: counts[c] for c in cats if counts.get(c)}))
        return '  "summary": {\n' + ",\n".join(lines) + "\n  },\n"

    def text(self, dry, every=False):
        """The impact report as plain text: the same items and order as the JSON."""
        rows = {"movedToInbox": [f"{plain(a)} -> {plain(b)}  movedToInbox" for a, b in self.moves],
                "orphans": [f"{plain(p)}  orphans" for _, p in sorted(self.orphans.items())]}
        for cat, d, field in (("removedDeadLinks", self.dead, "deadLink"),
                              ("placeholderLinks", self.placeholders, "link"),
                              ("allowlistedLinks", self.allowlisted, "link")):
            rows[cat] = [f"{plain(d[k]['path'])}:{d[k]['line']}  {cat}  {plain(d[k][field])}" for k in sorted(d)]
        for k in sorted(self.findings):
            f = self.findings[k]
            rows.setdefault(f["category"], []).append(
                f"{plain(f['path'])}:{f['line']}  {f['category']}  {plain(f['detail'])}")
        out = [f"lint: {len(self.checked)} notes, {self.links} links scanned"
               + (" (dry run, nothing changed)" if dry else "")]
        for group, cats in GROUPS:
            items = [row for c in cats for row in rows.get(c, [])]
            if items:
                out += ["", f"{group} ({len(items)}):"]
                for c in cats:
                    r = rows.get(c, [])
                    cap = len(r) if every else TEXT_CAP
                    out += r[:cap] + ([f"... {len(r) - cap} more {c}"] if len(r) > cap else [])
        return "\n".join(out) + "\n"

    def unchanged(self, note, path):
        """True when the file still has the bytes lint scanned."""
        try:
            return (self.vault / path).read_bytes() == note.raw
        except OSError:
            return False

    def skip_changed(self, note, path):
        """Leave a note that changed since the scan (autosave, sync) alone, and say so."""
        note.changed = False
        self.dead = {key: v for key, v in self.dead.items() if key[0] != note.final}
        self.finding("skipped-changed", path, 1, "changed since the scan, lint left it alone")

    def write(self):
        """Apply the moves, then write every note whose links changed."""
        for note in self.notes:
            src, dst = note.path, note.final
            if src == dst:
                continue
            if (self.vault / dst).exists():
                raise system_error(f"refusing to overwrite {dst}")
            if not self.unchanged(note, src):
                self.moves.remove((src, dst))
                self.skip_changed(note, src)
                continue
            try:
                (self.vault / src).rename(self.vault / dst)
            except OSError:
                raise system_error(f"move failed: {src}")
        for note in self.notes:
            if not note.changed:
                continue
            if not self.unchanged(note, note.final):
                self.skip_changed(note, note.final)
                continue
            try:
                atomic_write(self.vault / note.final, note.text().encode("utf-8", "surrogateescape"))
            except OSError:
                raise system_error(f"write failed: {note.final}")


def atomic_write(path, data):
    """Temp file in the same folder, fsync, then replace: never a half-written note."""
    if not os.access(path, os.W_OK):  # os.replace would bypass a read-only note on POSIX
        raise PermissionError(f"read-only: {path}")
    # Hidden name, so a leftover is never linted as a note.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)  # allow-delete: temp file of a failed atomic write
        except OSError:
            pass
        raise


def lint(argv):
    """Run the whole check and return the exit code."""
    dry, as_of, files_mode, files, text, every = parse_args(argv)
    vault = require_vault()
    rules = read_rules(read_text(vault / "CLAUDE.md"))
    sel = selection(vault, files)
    run = Lint(vault, files_mode, sel, rules, as_of)
    run.run()
    if not dry:
        run.write()
    sys.stdout.buffer.write((run.text(dry, every) if text else run.json()).encode("utf-8"))
    sys.stdout.flush()
    return 4 if run.found else 0


def main(argv):
    # UTF-8 and LF output on every OS: Windows pipes default to cp1252 and CRLF.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    try:
        return lint(argv)
    except LintExit as stop:
        if str(stop):
            print(stop, file=sys.stderr)
        return stop.code
    except Exception as err:  # noqa: BLE001
        print(f"SYSTEM ERROR: lint.py: internal error ({type(err).__name__}: {err})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
