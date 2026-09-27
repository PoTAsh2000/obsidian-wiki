#!/usr/bin/env python3
"""usage: lint.py --vault <dir> [--dry-run] [--files <path>...]

Check an Obsidian vault against its CLAUDE.md and print one JSON object.
Fixes two things without asking: moves draft notes outside "01. Inbox" into
the Inbox and unlinks dead links. Everything else is only reported.

options:
  --vault <dir>      vault root, must contain CLAUDE.md (required)
  --dry-run          same JSON, no file changed
  --files <path>...  only these notes or folders, paths from the vault root;
                     skips orphans, duplicate names and inbox age
  -h, --help         this help

exit codes:
  0  clean, nothing fixed or found
  1  system error (write failed, internal error)
  2  bad usage (unknown option, no --vault, --files without paths)
  3  user error (vault or --files path not found, CLAUDE.md missing or
     without the type and status lists)
  4  fixes or findings (normal result, read the JSON)

example: lint.py --vault "C:/Vault" --files "30. Knowledge/Tokens.md" "01. Inbox/"
"""

import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vault import to_native  # noqa: E402

USAGE = "usage: lint.py --vault <dir> [--dry-run] [--files <path>...]"
INBOX = "01. Inbox"
ARCHIVE = "99. Archived"
EXEMPT_TOPS = ("10. Daily", "90. Templates", ARCHIVE)  # no note checks, only dead links

KEY_RE = re.compile(r"[A-Za-z0-9_-]+:")
LIST_ITEM_RE = re.compile(r"[ \t]*-[ \t]*")
FENCE_RE = re.compile(r" {0,3}(```+|~~~+)")
HEADING_RE = re.compile(r"#{1,6}(?:[ \t]|$)")
BLOCK_ID_RE = re.compile(r"[ \t]*\^[A-Za-z0-9-]+[ \t]*")
LINK_RE = re.compile(r"!?\[\[[^\]]*\]\]|!?\[[^\]]*\]\((?:<[^>]*>|[^)]*)\)")
SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
TAG_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

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


def js(s):
    """JSON string with the same escapes as before: backslash, quote, tab, CR, LF."""
    for a, b in (("\\", "\\\\"), ('"', '\\"'), ("\t", "\\t"), ("\r", "\\r"), ("\n", "\\n")):
        s = s.replace(a, b)
    return f'"{s}"'


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
    """Return (vault, dry_run, files_mode, files), or raise LintExit."""
    vault, dry, files_mode, files = "", False, False, []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            sys.stdout.write(__doc__)
            raise LintExit(0, "")
        if arg == "--vault":
            if i + 1 >= len(argv):
                raise usage_error("--vault needs a path")
            vault = argv[i + 1]
            i += 2
        elif arg == "--dry-run":
            dry = True
            i += 1
        elif arg == "--files":
            files_mode = True
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                files.append(argv[i])
                i += 1
        else:
            raise usage_error(f"unknown argument: {arg}")
    if not vault:
        raise usage_error("no vault path, pass --vault")
    if files_mode and not files:
        raise usage_error("--files needs at least one path")
    return vault, dry, files_mode, files


def read_rules(text):
    """Allowed type and status values from the vault CLAUDE.md."""
    types = []
    for line in text.split("\n"):
        if "Allowed `type` values" in line:
            rest = line.split(":", 1)[1] if ":" in line else line
            types = " ".join(re.findall(r"`([^`]*)`", rest)).split()
            break
    statuses, in_section = [], False
    for line in text.split("\n"):
        if re.match(r"#+ ", line):
            in_section = bool(re.match(r"#+ Status lifecycle", line))
        elif in_section:
            m = re.match(r"- `([^`]*)`", line)
            if m:
                statuses.extend(m.group(1).split())
    if not types:
        raise user_error("no 'Allowed `type` values' line in CLAUDE.md")
    if not statuses:
        raise user_error("no '- `status`' items under 'Status lifecycle' in CLAUDE.md")
    return set(types), set(statuses)


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


# ---------- notes ----------

class Note:
    """One Markdown note: its lines (with any CR kept) and its frontmatter."""

    def __init__(self, path, text):
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
        self.parse_frontmatter()
        self.status = self.values.get("status", "").lower()

    def line(self, k):
        return self.lines[k - 1]

    def parse_frontmatter(self):
        if not self.lines or strip_cr(self.lines[0]) != "---":
            return
        for k in range(2, len(self.lines) + 1):
            if strip_cr(self.line(k)) == "---":
                self.fm_end = k
                break
        key = ""
        for k in range(2, self.fm_end):
            c = strip_cr(self.line(k))
            m = KEY_RE.match(c)
            if m:
                key = c[:m.end() - 1].lower()
                v = trim(c[m.end():])
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
    def __init__(self, vault, files_mode, sel, types, statuses):
        self.vault = vault
        self.files_mode = files_mode
        self.sel = sel
        self.types = types
        self.statuses = statuses
        self.cutoff = (date.today() - timedelta(days=7)).isoformat()
        self.dates = list_files(vault)
        self.notes = [Note(p, read_text(vault / p)) for p in self.dates if self.is_note(p)]
        self.final = {p: p for p in self.dates}
        self.moves = []           # (from, to)
        self.dead = {}            # sort key -> JSON
        self.placeholders = {}
        self.findings = {}
        self.orphans = {}
        self.incoming = {}
        self.seq = 0
        self.found = False        # any fix or finding

    @staticmethod
    def is_note(p):
        return p.lower().endswith(".md") and top(p).lower() != "attachments" and p != "CLAUDE.md"

    def selected(self, p):
        if not self.files_mode:
            return True
        return any(p == s or (s.endswith("/") and p.startswith(s)) for s in self.sel)

    def finding(self, category, path, line, detail):
        self.found = True
        self.findings[(path, line, category, detail)] = (
            f'{{"category": {js(category)}, "path": {js(path)}, "line": {line}, "detail": {js(detail)}}}')

    def run(self):
        self.move_stray_drafts()
        self.build_index()
        for note in self.notes:
            if self.selected(note.path):
                self.check_note(note)
        if not self.files_mode:
            self.check_duplicates()
            self.check_orphans()

    # 1. Stray drafts into the Inbox.
    def move_stray_drafts(self):
        taken = {p.lower() for p in self.dates}
        for note in self.notes:
            if note.status != "draft" or top(note.path) == INBOX or not self.selected(note.path):
                continue
            to = f"{INBOX}/{base(note.path)}"
            if to.lower() in taken:
                self.finding("status-location", note.path, note.key_lines.get("status", 0),
                             f"draft outside {INBOX}, not moved: {to} already exists")
                continue
            taken.add(to.lower())
            note.final = self.final[note.path] = to
            self.moves.append((note.path, to))
            self.found = True

    # Link index on final paths: exact path, file name and alias.
    def build_index(self):
        self.exists, self.by_base, self.alias_owners = {}, {}, {}
        for fp in self.final.values():
            self.exists[fp.lower()] = fp
            add_unique(self.by_base, base(fp).lower(), fp)
        for note in self.notes:
            for alias, _ in note.items.get("aliases", []):
                add_unique(self.alias_owners, alias.lower(), note.final)

    def resolve(self, target, from_dir, markdown):
        """Return ("self"|"ok"|"amb"|"dead", [final paths])."""
        target = target.split("#", 1)[0]
        if not target:
            return "self", []
        lt = target.lower()
        # Markdown links are relative to the note first.
        if markdown and from_dir:
            r = normalize(f"{from_dir}/{target}").lower()
            for key in (r, r + ".md"):
                if key in self.exists:
                    return "ok", [self.exists[key]]
        lt = lt.lstrip("/")
        for key in (lt, lt + ".md"):
            if key in self.exists:
                return "ok", [self.exists[key]]
        # Then by file name, where the link may give the end of the path.
        b = base(lt)
        hits = []
        for cand in self.by_base.get(b, []) + self.by_base.get(b + ".md", []):
            c = cand.lower()
            if c in (lt, lt + ".md") or c.endswith("/" + lt) or c.endswith("/" + lt + ".md"):
                if cand not in hits:
                    hits.append(cand)
        if not hits and "/" not in lt:
            hits = list(self.alias_owners.get(lt, []))
        if not hits:
            return "dead", []
        return ("amb" if len(hits) > 1 else "ok"), hits

    def placeholder(self, fp, k, tok):
        self.seq += 1
        self.placeholders[(fp, k, self.seq)] = f'{{"path": {js(fp)}, "line": {k}, "link": {js(tok)}}}'

    def handle_link(self, note, k, tok):
        """Check one link token; return its replacement (the token unless it is dead)."""
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
        if res == "self":
            return tok
        if res == "amb":
            self.finding("ambiguous-link", fp, k, f"{tok} matches {joined(hits)}")
        if res in ("ok", "amb"):
            for h in hits:
                if h != fp:
                    self.incoming[h] = self.incoming.get(h, 0) + 1
            return tok
        self.seq += 1
        self.dead[(fp, k, self.seq)] = f'{{"path": {js(fp)}, "line": {k}, "deadLink": {js(tok)}}}'
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
        events, fence, in_comment = [], None, False
        for k in range(note.fm_end + 1, len(note.lines) + 1):
            c = strip_cr(note.line(k))
            m = FENCE_RE.match(c)
            if m:
                mark = m.group(0).lstrip(" ")
                if fence is None:
                    fence = (mark[0], len(mark))
                elif mark[0] == fence[0] and len(mark) >= fence[1] and trim(c[m.end():]) == "":
                    fence = None
                events.append(CONTENT)
                continue
            if fence is not None:
                events.append(CONTENT)
                continue
            self.scan_line(note, k)
            kind, in_comment = self.line_kind(c, k, in_comment)
            events.append(kind)
        if check_sections:
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
        self.scan_body(note, checks)
        if note.status == "archived" and top(fp) != ARCHIVE:
            self.finding("status-location", fp, note.key_lines.get("status", 0),
                         f"status archived outside {ARCHIVE}")
        if not checks:
            return
        if not note.fm_end:
            self.finding("frontmatter-missing", fp, 1, "no frontmatter")
            return
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
        if v and not DATE_RE.fullmatch(v):
            self.finding("frontmatter-invalid", fp, lines["created"], f"created '{v}' is not YYYY-MM-DD")
        for tag, k in note.items.get("tags", []):
            if not TAG_RE.fullmatch(tag):
                self.finding("frontmatter-invalid", fp, k, f"tag '{tag}' is not lowercase kebab-case")

    def check_inbox_age(self, note):
        """Inbox notes older than 7 days, by created date or else by file date."""
        v = note.values.get("created", "")
        if DATE_RE.fullmatch(v):
            if v < self.cutoff:
                self.finding("inbox-age", note.final, note.key_lines["created"], f"created {v}, older than 7 days")
        elif self.dates[note.path] < self.cutoff:
            self.finding("inbox-age", note.final, 1, f"file date {self.dates[note.path]}, older than 7 days")

    # 3. Whole-vault checks (full mode only).
    def check_duplicates(self):
        # Archived notes are left out: a merge adds their name as an alias by design.
        named, name_of = {}, {}
        for note in self.notes:
            if top(note.final) != ARCHIVE:
                nm = re.sub(r"\.md$", "", base(note.final).lower())
                add_unique(named, nm, note.final)
                name_of[note.final] = nm
        for note in self.notes:
            fp = note.final
            if fp not in name_of:
                continue
            nm = name_of[fp]
            others = [p for p in named[nm] if p != fp]
            if others:
                self.finding("duplicate-name", fp, 1, f"same name as {joined(others)}")
            for alias, k in note.items.get("aliases", []):
                la = alias.lower()
                if la == nm:
                    continue
                if la in named:
                    self.finding("duplicate-name", fp, k, f"alias '{alias}' equals the name of {joined(named[la])}")
                others = [p for p in self.alias_owners.get(la, []) if p != fp and p in name_of]
                if others:
                    self.finding("duplicate-name", fp, k, f"alias '{alias}' is also an alias of {joined(others)}")

    def check_orphans(self):
        for note in self.notes:
            fp = note.final
            if not exempt(fp) and base(fp) != "Home.md" and not self.incoming.get(fp):
                self.orphans[fp] = js(fp)

    # ---------- output and writes ----------

    def json(self):
        def block(name, items, tail):
            if not items:
                return f'  "{name}": []{tail}\n'
            return f'  "{name}": [\n    ' + ",\n    ".join(items) + f"\n  ]{tail}\n"

        moved = [f'{{"from": {js(a)}, "to": {js(b)}}}' for a, b in self.moves]
        by_key = lambda d: [d[key] for key in sorted(d)]  # noqa: E731
        return ("{\n" + block("movedToInbox", moved, ",")
                + block("removedDeadLinks", by_key(self.dead), ",")
                + block("placeholderLinks", by_key(self.placeholders), ",")
                + block("orphans", by_key(self.orphans), ",")
                + block("findings", by_key(self.findings), "") + "}\n")

    def write(self):
        """Apply the moves, then write every note whose links changed."""
        for src, dst in self.moves:
            if (self.vault / dst).exists():
                raise system_error(f"refusing to overwrite {dst}")
            try:
                (self.vault / src).rename(self.vault / dst)
            except OSError:
                raise system_error(f"move failed: {src}")
        for note in self.notes:
            if not note.changed:
                continue
            try:
                (self.vault / note.final).write_bytes(note.text().encode("utf-8", "surrogateescape"))
            except OSError:
                raise system_error(f"write failed: {note.final}")


def lint(argv):
    """Run the whole check and return the exit code."""
    vault_arg, dry, files_mode, files = parse_args(argv)
    vault = Path(to_native(vault_arg))
    if not vault.is_dir():
        raise user_error(f"vault not found: {vault_arg}")
    if not (vault / "CLAUDE.md").is_file():
        raise user_error(f"no CLAUDE.md in vault root: {vault_arg}")
    types, statuses = read_rules(read_text(vault / "CLAUDE.md"))
    sel = selection(vault, files)
    run = Lint(vault, files_mode, sel, types, statuses)
    run.run()
    if not dry:
        run.write()
    sys.stdout.buffer.write(run.json().encode("utf-8", "surrogateescape"))
    sys.stdout.flush()
    return 4 if run.found else 0


def main(argv):
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
