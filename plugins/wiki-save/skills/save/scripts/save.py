#!/usr/bin/env python3
"""save.py: write a draft note into <vault>/01. Inbox, never overwriting anything.

usage: save.py [--append] [--allow-secrets] [<title>] <draft-file>

Create "<vault>/01. Inbox/<title>.md" from <draft-file>, or with --append add the
draft body to an existing draft note of that name in 01. Inbox.
The vault comes from the shared scripts/vault.py.
The draft file holds frontmatter, a "# <title>" line and the body. Without <title> the
title comes from that first "# " heading, so it never goes through shell quoting.
The script writes the heading from the (cleaned) title.
Use it in wiki-save:save after the model wrote the draft file (path from gather.py).

arguments:
  <title>      optional, wins over the heading; \\ / : * ? " < > | # ^ [ ] become "-"
               (a trailing .md is dropped); NFC-normalized; control and invisible
               format characters and leading dots are removed; cut at a word
               boundary to at most 200 UTF-8 bytes and a Windows path under 260
               characters; Windows reserved names such as CON, NUL, COM1 or LPT1
               are refused
  <draft-file>  frontmatter (with status: draft), a "# <title>" line, then the body.
                --append uses only the body. Deleted after a successful save.
  --allow-secrets  skip the secret scan (only when the user says the content is safe)

checks: no secrets in the draft (private keys, authorization or bearer headers, API key
prefixes, password=/secret= values, user:password@ URLs; code included), no note with
that filename anywhere in the vault and, on create, no note outside 99. Archived with that
name as an alias (case-insensitive, NFC), frontmatter closed by --- with status: draft,
type, topic and status present, type from the 'Allowed `type` values' line of the vault
CLAUDE.md (when it has one), no duplicate key, dates (created, updated, modified, date, *_date)
as YYYY-MM-DD, related entries as quoted "[[link]]", every [[link]] outside code points
to an existing file or to the note itself, no empty section (a heading with only blank
lines, comments or block ids before the next heading of the same or higher level or the
end; code blocks count as content, like wiki-lint). Tags are made lowercase kebab-case.
The note goes to a dot temp file first and is published in one step (a hard link, so an
existing name is never overwritten; append replaces the note only if it did not change).

output (stdout): saved|appended: <path from vault root>, renamed: yes|no, then
normalized: tags when tags were rewritten
on exit 3 for secrets: secret: line <n>: <kind> per finding (the value is never shown)
on exit 3: exists: <path> and status: <status|none> per match (a filename or an alias),
then appendable: yes|no (yes only for a single filename match that is a draft directly in
01. Inbox)
on exit 2 for missing links: suggest: <missing> -> <closest note name>, one per link with
a close note filename or alias (left out when nothing is close)
on exit 2 for frontmatter: frontmatter: line <n>: <problem>, one per problem
on exit 2 for empty sections: section: line <n>: <heading> is empty, one per heading
all exit 2 draft problems (frontmatter, empty sections, missing links, status) are
reported together in one run, with one "SYSTEM ERROR:" stderr line per group
vault problem (exit 0): a single "ERROR: <message>" line, nothing saved

exit codes:
  0  saved or appended, or an ERROR line
  1  system error (01. Inbox missing, write failed)
  2  bad usage (arguments, draft file missing or invalid, empty section, no title, link to a
     missing note)
  3  user error (a note or an alias with that name exists, --append target is not an Inbox draft,
     the draft holds secrets)

examples:
  save.py /tmp/wiki-save-1.md
  save.py --append /tmp/wiki-save-1.md
  save.py "ACE vs SOP" /tmp/wiki-save-1.md
"""

import difflib
import os
import re
import sys
import tempfile
import unicodedata
from datetime import date
from pathlib import Path

# The shared vault reader lives in the plugin's scripts folder.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault, to_native  # noqa: E402
from gather import key, note_files, note_meta  # noqa: E402

INBOX = "01. Inbox"
ARCHIVE = "99. Archived"
REQUIRED = ("type", "topic", "status")
FENCE = re.compile(r"^---[ \t]*$")
BLANK = re.compile(r"^[ \t]*$")
CODE_FENCE = re.compile(r"^[ \t]*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")
WIKILINK = re.compile(r"\[\[([^\]]*)\]\]")
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)
DRAFT_STATUS = re.compile(r"""^status:\s*["']?draft["']?\s*$""")
MAX_BYTES = 200   # well under the 255-byte filename limit
MAX_PATH = 259    # Windows MAX_PATH (260) minus the terminating NUL
SUGGEST_CUTOFF = 0.8
FM_KEY = re.compile(r"^([A-Za-z0-9_][\w .-]*?)\s*:(?:\s(.*))?$")
FM_ITEM = re.compile(r"^(\s*-\s*)(.*)$")
DATE_KEY = re.compile(r"^(created|updated|modified|date)$|[_-]date$", re.IGNORECASE)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEADING = re.compile(r"^(#{1,6})(?:[ \t]|$)")
OPEN_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
BLOCK_ID = re.compile(r"^[ \t]*\^[A-Za-z0-9-]+[ \t]*$")
ALLOWED_TYPES = re.compile(r"Allowed `type` values[^:]*:(.*)")
QUOTED_LINK = re.compile(r"""^(["'])\[\[[^\[\]]+\]\]\1$""")
# (kind, pattern) checked on every draft line, code included. Values are never printed.
SECRETS = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY")),
    ("authorization header", re.compile(
        r"(?i)\bauthorization\s*[:=]\s*[\"']?(?:basic|bearer|token)\s+[\w.~+/=-]{8,}")),
    ("bearer token", re.compile(r"(?i)\bbearer\s+[\w.~+/-]{20,}")),
    ("api key", re.compile(
        r"\b(?:sk-(?:ant-|proj-)?[\w-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_\w{20,}"
        r"|glpat-[\w-]{20,}|xox[abprs]-[\w-]{10,}|AKIA[0-9A-Z]{16}|AIza[\w-]{35})")),
    # "=" with any literal value; ":" only with a quoted value or one holding a digit, so
    # prose like "secret: keep it short" passes. Placeholders and code calls are skipped.
    ("password or secret", re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|client[_-]?secret|api[_-]?key)[\"']?\s*"
        r"(?:=\s*[\"']?|:\s*(?:[\"']|(?=\S*\d)))"
        r"(?![<$*{%])[^\s\"',;<>(){}\[\]]{3,}(?![\w(\[]|\.\w)")),
    ("url with password", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@")),
]


class Fail(Exception):
    """Stop with an exit code and a message for stderr."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def utf16_len(text):
    """Length as Windows counts path characters."""
    return len(text.encode("utf-16-le")) // 2


def safe_name(title, max_chars=MAX_PATH):
    """NFC-normalize, drop control and format characters, replace forbidden filename
    characters, collapse spaces, trim leading spaces and dots, trailing spaces and dots and a
    trailing ".md", then cut at a word boundary to MAX_BYTES and max_chars (UTF-16 units).
    "" when nothing is left or the name is reserved on Windows."""
    name = unicodedata.normalize("NFC", title)
    name = "".join(c for c in name if unicodedata.category(c) not in ("Cc", "Cf"))
    name = re.sub(r'[\[\]\\/:*?"<>|#^]', "-", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .")
    if name.lower().endswith(".md"):
        name = name[:-3].rstrip(" .")
    cut = name
    while cut and (len(cut.encode("utf-8")) > MAX_BYTES or utf16_len(cut) > max_chars):
        cut = cut[:-1]
    if cut != name:
        if name[len(cut)] != " " and " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        name = cut.rstrip(" .")
    return "" if RESERVED.match(name) else name


def vault_files(vault):
    """Every file in the vault except dot folders, as posix paths from the vault root."""
    found = []
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if not (d.startswith(".") and len(d) > 1)]
        for name in files:
            found.append((Path(root) / name).relative_to(vault).as_posix())
    return sorted(found)


def basename(path):
    return path.rsplit("/", 1)[-1]


def read_lines(path):
    """Lines of a text file without line endings."""
    return path.read_text(encoding="utf-8-sig", errors="replace").splitlines()


def status_of(path):
    """The frontmatter status of a note without quotes and spaces, or "" when none."""
    lines = read_lines(path)
    if not lines or not FENCE.match(lines[0]):
        return ""
    for line in lines[1:]:
        if FENCE.match(line):
            break
        if line.startswith("status:"):
            return re.sub(r"""["' \t]""", "", line[len("status:"):])
    return ""


def find_secrets(lines):
    """"secret: line <n>: <kind>" per line and kind that looks like a credential."""
    return [f"secret: line {n}: {kind}" for n, line in enumerate(lines, 1)
            for kind, pattern in SECRETS if pattern.search(line)]


def kebab(tag):
    """A tag in lowercase kebab-case, without quotes or a leading #."""
    tag = tag.strip().strip("\"'").lstrip("#").lower()
    return re.sub(r"-{2,}", "-", re.sub(r"[\s_]+", "-", tag)).strip("-")


def is_date(value):
    try:
        return bool(ISO_DATE.match(value)) and bool(date.fromisoformat(value))
    except ValueError:
        return False


def check_frontmatter(fm):
    """Check frontmatter lines (with fences; index 0 is draft line 1).
    Returns (lines with tags normalized, "frontmatter: ..." problem lines, tags changed)."""
    fm, problems, seen, changed, i = list(fm), [], {}, False, 1
    while i < len(fm) - 1:
        match = FM_KEY.match(fm[i])
        if not match:
            i += 1
            continue
        name, value, start = match.group(1), (match.group(2) or "").strip(), i
        items = []  # (prefix, value) of a block list under the key
        while i + 1 < len(fm) - 1 and FM_ITEM.match(fm[i + 1]):
            i += 1
            items.append(FM_ITEM.match(fm[i]).groups())
        i += 1
        n = start + 1
        if name in seen:
            problems.append(f"frontmatter: line {n}: duplicate key {name} "
                            f"(first on line {seen[name]})")
            continue
        seen[name] = n
        inline = value.startswith("[") and value.endswith("]") and not value.startswith("[[")
        entries = ([v.strip() for v in value[1:-1].split(",") if v.strip()] if inline
                   else [v.strip() for _, v in items] or ([value] if value else []))
        if DATE_KEY.search(name) and value and not is_date(value.strip("\"'")):
            problems.append(f"frontmatter: line {n}: {name} is not YYYY-MM-DD: {value}")
        elif name == "related":
            problems += [f'frontmatter: line {n}: related entry is not a quoted "[[link]]": {e}'
                         for e in entries if not QUOTED_LINK.match(e)]
        elif name == "tags":
            tags = [t for t in map(kebab, entries) if t]
            old = fm[start:i]
            if inline:
                new = [f"tags: [{', '.join(tags)}]"]
            elif items:
                new = [fm[start].rstrip()] + [p + kebab(v) for p, v in items if kebab(v)]
            else:
                new = [f"tags: {tags[0]}" if tags else "tags:"]
            if [line.rstrip() for line in old] != new:
                fm[start:i] = new
                changed = True
                i += len(new) - len(old)
    return fm, problems, changed


def allowed_types(vault):
    """Type values from the 'Allowed `type` values' line of the vault CLAUDE.md, read the
    way wiki-lint reads it, or None when the file or the line is missing."""
    try:
        text = (vault / "CLAUDE.md").read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    match = ALLOWED_TYPES.search(text)
    return (set(re.findall(r"`([^`]*)`", match.group(1))) or None) if match else None


def required_problems(fm, types):
    """"frontmatter: ..." lines for a missing REQUIRED key or a type not in types.
    fm holds the fences; index 0 is draft line 1."""
    values = {}  # key -> (line, value without quotes, present)
    for n, line in enumerate(fm[1:-1], 2):
        match = FM_KEY.match(line)
        if match and match.group(1) not in values:
            value = (match.group(2) or "").strip().strip("\"'").strip()
            items = n < len(fm) - 1 and bool(FM_ITEM.match(fm[n]))
            values[match.group(1)] = (n, value, bool(value) or items)
    out = [f"frontmatter: line 1: no {name}" for name in REQUIRED
           if not values.get(name, (0, "", False))[2]]
    n, value, _ = values.get("type", (0, "", False))
    if types and value and value not in types:
        out.append(f"frontmatter: line {n}: type {value} is not in the vault CLAUDE.md list: "
                   + ", ".join(sorted(types)))
    return out


def empty_sections(lines, first):
    """"section: line <n>: <heading> is empty" for each heading in lines[first:] followed
    only by blank, comment or block id lines up to the next heading of the same or a higher
    level or the end. Same rule as wiki-lint's empty-section check."""
    events, fence, comment = [], "", False  # ("h", level, n, text), ("i",) or ("c",)
    for n, line in enumerate(lines[first:], first + 1):
        match = OPEN_FENCE.match(line)
        if match:
            mark = match.group(1)
            if not fence:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence) and not line[match.end():].strip():
                fence = ""
            events.append(("c",))
            continue
        heading = HEADING.match(line)
        if fence:
            kind = ("c",)
        elif comment:
            kind, comment = ("i",), "-->" not in line
        elif heading:
            kind = ("h", len(heading.group(1)), n, line.strip())
        elif not line.strip() or BLOCK_ID.match(line):
            kind = ("i",)
        elif line.lstrip(" \t").startswith("<!--"):
            end = line.find("-->")
            comment = end < 0
            kind = ("i",) if comment or not line[end + 3:].strip() else ("c",)
        else:
            kind = ("c",)
        events.append(kind)
    out = []
    for i, event in enumerate(events):
        if event[0] != "h":
            continue
        after = next((e for e in events[i + 1:] if e[0] != "i"), None)
        if after is None or (after[0] == "h" and after[1] <= event[1]):
            out.append(f"section: line {event[2]}: {event[3]} is empty")
    return out


def alias_owners(vault, name):
    """Notes outside 99. Archived with name as an alias, as paths from the vault root."""
    owners = []
    for path in note_files(vault):
        rel = path.relative_to(vault).as_posix()
        if rel.startswith(ARCHIVE + "/"):
            continue
        try:
            aliases = note_meta(path)[1]
        except OSError:
            continue
        if key(name) in map(key, aliases):
            owners.append(rel)
    return sorted(owners)


def split_draft(lines):
    """Return (frontmatter with fences, leading "# " heading text or "", body without it)."""
    fm, rest = [], lines
    if lines and FENCE.match(lines[0]):
        end = next((i for i in range(1, len(lines)) if FENCE.match(lines[i])), None)
        if end is None:
            raise Fail(2, "SYSTEM ERROR: save.py: frontmatter has no closing --- line")
        fm, rest = lines[:end + 1], lines[end + 1:]
    while rest and BLANK.match(rest[0]):
        rest = rest[1:]
    heading = ""
    if rest and rest[0].startswith("# "):
        heading, rest = rest[0][2:].strip(), rest[1:]
        if rest and BLANK.match(rest[0]):
            rest = rest[1:]
    return "\n".join(fm).rstrip("\n"), heading, "\n".join(rest).rstrip("\n")


def link_targets(text):
    """Sorted distinct [[link]] targets outside code, without |alias or #heading."""
    targets, in_fence = set(), False
    for line in text.split("\n"):
        if CODE_FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for link in WIKILINK.findall(INLINE_CODE.sub("", line)):
            targets.add(re.split(r"[|#]", link, maxsplit=1)[0])
    return sorted(targets)


def missing_links(text, files, own_file):
    """Link targets that match no file basename (with or without .md) and not this note."""
    have = {key(basename(f)) for f in files} | {key(own_file)}
    missing = []
    for target in link_targets(text):
        name = key(basename(target))
        if name and name not in have and name + ".md" not in have:
            missing.append(target)
    return missing


def suggestions(vault, missing):
    """"suggest: <missing> -> <note>" lines from a fuzzy match on note names and aliases."""
    names = {}
    for path in note_files(vault):
        names.setdefault(key(path.stem), path.stem)
        try:
            aliases = note_meta(path)[1]
        except OSError:
            continue
        for alias in aliases:
            names.setdefault(key(alias), path.stem)
    out = []
    for target in missing:
        close = difflib.get_close_matches(key(basename(target)), names, n=1,
                                          cutoff=SUGGEST_CUTOFF)
        if close:
            out.append(f"suggest: {target} -> {names[close[0]]}")
    return out


def write_full(out, data):
    out.write(data)
    out.flush()
    os.fsync(out.fileno())


def write_temp(folder, data):
    """Path of a new fsynced temp file in folder holding data. The leading dot and .tmp
    keep Obsidian from indexing it."""
    fd, tmp = tempfile.mkstemp(prefix=".wiki-save-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as out:
            write_full(out, data)
    except BaseException:
        os.unlink(tmp)  # allow-delete: own temp file after a failed write
        raise
    return tmp


def create_note(vault, name, fm, body):
    """Publish a new note in one step: a complete temp file hard-linked to the name, which
    fails when the name exists. Without hard links: exclusive create, partial file removed."""
    target = f"{INBOX}/{name}.md"
    path, data = vault / target, f"{fm}\n# {name}\n\n{body}\n".encode("utf-8")
    try:
        tmp = write_temp(path.parent, data)
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise
        except OSError:  # no hard links on this file system
            with open(path, "xb") as out:
                try:
                    write_full(out, data)
                except BaseException:
                    out.close()
                    path.unlink()  # allow-delete: partial note this run just created
                    raise
        finally:
            os.unlink(tmp)  # allow-delete: own temp file, already hard-linked or unused
    except FileExistsError:
        raise Fail(3, f'USER ERROR: save.py: a note named "{name}" was created meanwhile: '
                      f"{target}")
    except OSError:
        raise Fail(1, f"SYSTEM ERROR: save.py: could not create {target}")
    return target


def append_note(vault, existing, body):
    """Add the body under a "## <today>" heading, keeping the note's line endings. The full
    new text replaces the note in one step, and only when the note did not change meanwhile."""
    path = vault / existing
    try:
        data = path.read_bytes()
        eol = "\r\n" if b"\r\n" in data else "\n"  # keep CRLF notes CRLF
        text = "" if not data or data.endswith(b"\n") else "\n"
        text += f"\n## {date.today().isoformat()}\n\n{body}\n"
        tmp = write_temp(path.parent, data + text.replace("\n", eol).encode("utf-8"))
        try:
            if path.read_bytes() != data:
                raise Fail(1, f"SYSTEM ERROR: save.py: {existing} changed while appending, "
                              "nothing written; rerun")
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)  # allow-delete: own temp file left after a failed replace
    except OSError:
        raise Fail(1, f"SYSTEM ERROR: save.py: could not append to {existing}")


def save(mode, vault, title, draft, allow_secrets=False):
    """Run all checks, then create or append. Returns the stdout lines."""
    if not (vault / INBOX).is_dir():
        raise Fail(1, f"SYSTEM ERROR: save.py: no {INBOX} folder in vault: {vault.as_posix()}")
    if not draft.is_file():
        raise Fail(2, f"SYSTEM ERROR: save.py: draft file not found: {draft.as_posix()}")
    lines = read_lines(draft)
    found = [] if allow_secrets else find_secrets(lines)
    if found:
        print("\n".join(found))
        raise Fail(3, "USER ERROR: save.py: the draft looks like it holds secrets, nothing saved")
    fm, heading, body = split_draft(lines)
    body_start = fm.count("\n") + 1 if fm else 0  # draft lines before the body
    title = title or heading
    if not title:
        raise Fail(2, 'SYSTEM ERROR: save.py: no title: give one or start the draft body '
                      f'with "# <title>": {draft.as_posix()}')

    budget = MAX_PATH - utf16_len(str(vault / INBOX)) - len("/.md")
    name = safe_name(title, budget)
    if not name:
        raise Fail(3, f"USER ERROR: save.py: title is not a usable filename: {title}")
    renamed = "no" if name == title else "yes"
    own_file = f"{name}.md"

    files = vault_files(vault)
    existing = [f for f in files if key(basename(f)) == key(own_file)]
    # Appendable only when the single match is a draft directly in 01. Inbox.
    appendable = (len(existing) == 1 and existing[0].startswith(INBOX + "/")
                  and "/" not in existing[0][len(INBOX) + 1:]
                  and status_of(vault / existing[0]) == "draft")

    taken = existing
    if mode == "create":
        taken = existing + [p for p in alias_owners(vault, name) if p not in existing]
    if mode == "create" and taken:
        appendable = appendable and taken == existing
        out = []
        for path in taken:
            out += [f"exists: {path}", f"status: {status_of(vault / path) or 'none'}"]
        print("\n".join(out + [f"appendable: {'yes' if appendable else 'no'}"]))
        raise Fail(3, f'USER ERROR: save.py: a note or an alias named "{name}" already '
                      "exists: " + ", ".join(taken))

    if not body:
        raise Fail(2, f"SYSTEM ERROR: save.py: draft file has no body text: {draft.as_posix()}")

    # Collect every exit-2 problem so one Edit can fix them all.
    out, errors, normalized = [], [], []
    if mode == "create" and fm:
        fm_lines, problems, changed = check_frontmatter(fm.split("\n"))
        problems += required_problems(fm.split("\n"), allowed_types(vault))
        if problems:
            out += problems
            errors.append("draft frontmatter is invalid")
        else:
            fm = "\n".join(fm_lines)
            normalized = ["normalized: tags"] if changed else []

    empty = empty_sections(lines, body_start)
    if empty:
        out += empty
        errors.append("draft has empty sections: fill or remove them")

    # Append drops the draft frontmatter, so only the body counts there.
    checked = f"{fm}\n{body}" if mode == "create" else body
    missing = missing_links(checked, files, own_file)
    if missing:
        out += suggestions(vault, missing)
        errors.append("links to notes that do not exist: "
                      + ", ".join(f"[[{m}]]" for m in missing))

    if mode == "create" and not any(DRAFT_STATUS.match(line) for line in fm.split("\n")):
        errors.append("draft file needs frontmatter with status: draft")
    if errors:
        if out:
            print("\n".join(out))
        raise Fail(2, "\n".join(f"SYSTEM ERROR: save.py: {e}" for e in errors))

    if mode == "create":
        target = create_note(vault, name, fm, body)
        draft.unlink()  # allow-delete: used-up draft input file, outside the vault
        return [f"saved: {target}", f"renamed: {renamed}"] + normalized

    if not appendable:
        found = f" (found: {', '.join(existing)})" if existing else ""
        raise Fail(3, f'USER ERROR: save.py: no single draft note "{name}" in {INBOX} '
                      f"to append to{found}")
    append_note(vault, existing[0], body)
    draft.unlink()  # allow-delete: used-up draft input file, outside the vault
    return [f"appended: {existing[0]}", f"renamed: {renamed}"]


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    mode, allow_secrets = "create", False
    while argv[:1] in (["--append"], ["--allow-secrets"]):
        mode = "append" if argv[0] == "--append" else mode
        allow_secrets = allow_secrets or argv[0] == "--allow-secrets"
        argv = argv[1:]
    if len(argv) not in (1, 2):
        print("usage: save.py [--append] [--allow-secrets] [<title>] <draft-file> "
              "(see --help)", file=sys.stderr)
        return 2
    vault = require_vault()
    try:
        title = argv[0] if len(argv) == 2 else ""
        lines = save(mode, vault, title, Path(to_native(argv[-1])), allow_secrets)
    except Fail as err:
        print(err, file=sys.stderr)
        return err.code
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
