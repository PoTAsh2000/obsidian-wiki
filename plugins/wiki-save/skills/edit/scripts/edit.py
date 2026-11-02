#!/usr/bin/env python3
"""edit.py: edit one existing note, set it to status draft and move it into 01. Inbox.

usage: edit.py prepare <note and change request>
       edit.py publish [--allow-secrets] <note> <draft-file> <sha>

prepare finds the note and copies it byte for byte to a temp draft file outside the
vault, for the model to edit. Its one argument is the whole user text: the longest
leading part that names a note is the note, the rest is printed as the change request.
publish checks the edited draft, sets status: draft, sets an existing updated: key to
today (never adds one) and writes the result to "01. Inbox/<same filename>". A note
directly in 01. Inbox is replaced in place; any other note (also in 99. Archived) is
moved there and its old file removed, which completes the move. The filename never
changes, so [[Name]] links keep working.
The vault comes from the shared scripts/vault.py.
Use it in wiki-save:edit.

arguments:
  <note>        prepare: the user text. A leading quoted name or [[link]] is the note;
                otherwise (or when that names no note) the longest run of leading words
                (at most 20) that names a note; a ":" ends a word too, and an unmatched
                leading quote is also tried without it. publish: the note path printed
                by prepare.
                A note is named by a path from the vault root (.md optional), a [[link]]
                (|alias and #heading ignored) or a filename; compared case-insensitive
                and NFC. A filename or path always wins; only when none matches, an alias
                counts. Dot folders and 90. Templates are never searched.
  <draft-file>  the draft_file from prepare, edited. Deleted after a successful publish.
  <sha>         the sha from prepare: publish refuses when the note changed meanwhile
  --allow-secrets  skip the secret scan (only when the user says the content is safe)

checks on publish: the note still has the sha from prepare, no secrets on new or changed
lines of the draft (same scan as save.py), frontmatter closed by --- (no frontmatter: one
with only status: draft is added), the draft keeps the frontmatter the note had and has
body text, no [[link]] to a missing note that the original did not have, no other note
with that filename in 01. Inbox. Line endings and odd bytes are kept.

output (stdout):
  prepare: note: <path>, status: <status|none>, target: <path>, draft_file: <path>,
           sha: <hex>, then request: <rest of the user text> as the LAST line (it may
           span several lines, it is empty when the text only names the note)
  publish: Edited and moved to draft: <target> (from <old path>, was <status|none>)
           or Edited in place: <target> (was <status|none>), then
           path-link: <note> per note that links the old location by path (report only)
  exit 3 on prepare: match: <path> (status: <status|none>) per match when several match,
           suggest: <name> -> <close note name> when none matches (the best over all
           leading parts), each followed by request: <rest>;
           exists: <path> when 01. Inbox holds another note with that filename
  exit 3 for secrets: secret: line <n>: <kind> per finding (the value is never shown)
  exit 2 for new missing links: suggest: <missing> -> <closest note name>
  vault problem or no 01. Inbox (exit 0): a single "ERROR: <message>" line, nothing changed

exit codes:
  0  prepared or published, or an ERROR line
  1  system error (read or write failed, the note changed after the Inbox copy was written)
  2  bad usage (arguments, path leaves the vault, frontmatter not closed, draft missing or
     invalid, new missing link)
  3  user error (note not found, several matches, name taken in 01. Inbox, note changed
     since prepare, the draft holds secrets)
  On every error the draft file is kept.

examples:
  edit.py prepare "Docker Basics add a section on volumes"
  edit.py prepare "20. Knowledge/Docker Basics.md"
  edit.py publish "20. Knowledge/Docker Basics.md" /tmp/wiki-save-1.md 3f2a...
"""

import difflib
import hashlib
import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote

# The shared vault reader lives in the plugin's scripts folder; helpers come from save.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "save" / "scripts"))
from vault import require_vault, to_native  # noqa: E402
from gather import NO_INBOX, draft_path, key, note_files, note_meta  # noqa: E402
from save import (FENCE, SUGGEST_CUTOFF, WIKILINK, Fail, basename, find_secrets,  # noqa: E402
                  missing_links, publish_file, replace_if_unchanged, status_of, suggestions,
                  vault_files, write_full)

INBOX = "01. Inbox"
BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
MAX_WORDS = 20  # ponytail: names over 20 words never match, raise if needed


def usage(msg):
    return Fail(2, f"SYSTEM ERROR: edit.py: {msg}, see --help")


def user_error(msg):
    return Fail(3, f"USER ERROR: edit.py: {msg}")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def frontmatter_end(text):
    """Index of the closing --- line, 0 without frontmatter, -1 when it is not closed."""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    if not FENCE.match(lines[0].removeprefix(BOM)):
        return 0
    return next((i for i in range(1, len(lines)) if FENCE.match(lines[i])), -1)


def as_draft(text, had_frontmatter):
    """The draft text with status: draft and updated: today, or Fail 2 when it lost content."""
    end = frontmatter_end(text)
    if end < 0:
        raise usage("draft frontmatter has no closing --- line")
    if had_frontmatter and end == 0:
        raise usage("draft lost the frontmatter the note had; put it back")
    if not "\n".join(text.split("\n")[end + 1 if end else 0:]).strip():
        raise usage("draft has no body text; an edit never empties a note")
    if end == 0:
        bom = BOM if text.startswith(BOM) else ""
        eol = "\r\n" if "\r\n" in text else "\n"
        return f"{bom}---{eol}status: draft{eol}---{eol}{text.removeprefix(bom)}"
    lines = text.split("\n")  # a \r stays at the end of its line
    out, has_status = [], False
    for line in lines[1:end]:
        cr = "\r" if line.endswith("\r") else ""
        if line.startswith("status:"):
            line, has_status = f"status: draft{cr}", True
        elif line.startswith("updated:"):
            line = f"updated: {date.today().isoformat()}{cr}"
        out.append(line)
    if not has_status:
        out.append("status: draft" + ("\r" if lines[end].endswith("\r") else ""))
    return "\n".join(lines[:1] + out + lines[end:])


def in_inbox(rel):
    return rel.startswith(INBOX + "/") and "/" not in rel[len(INBOX) + 1:]


def name_key(name):
    """Compare form of a note name, path or [[link]]; None when empty or outside the vault."""
    name = name.strip().replace("\\", "/")
    if name.startswith("[[") and name.endswith("]]"):
        name = re.split(r"[|#]", name[2:-2], maxsplit=1)[0]
    name = name.strip().removeprefix("./")
    if not name or "/." in f"/{name}":
        return None
    return key(name.removesuffix(".md"))


def candidates(raw, split):
    """(name, rest) pairs to try: a quoted name or [[link]] first, then leading words,
    longest first. A ":" ends a word too, since a filename never holds one."""
    text = raw.strip()
    if not split:
        return [(text, "")]
    out, texts = [], [text]
    if text[:1] in ('"', "'"):
        close = text.find(text[0], 1)
        if close > 0:
            out.append((text[1:close], text[close + 1:]))
        else:
            texts.append(text[1:])  # an unmatched quote may be a typo, or part of the name
    if text.startswith("[["):
        end = text.find("]]")
        if end >= 0:
            out.append((text[:end + 2], text[end + 2:]))
    for t in texts:
        ends = [m.end() for m in re.finditer(r"[^\s:]+", t)][:MAX_WORDS]
        out += [(t[:e], t[e:]) for e in reversed(ends)]
    return out


def find_note(vault, raw, split=False):
    """(note path from the vault root, change request) for raw, else Fail with lines."""
    cands = []
    for name, rest in candidates(raw, split):
        k = name_key(name)
        if k:
            cands.append((k, name, rest.strip().lstrip(":").strip()))
    if not cands:
        raise usage("note name is empty, leaves the vault or enters a dot folder")
    notes = sorted(p.relative_to(vault).as_posix() for p in note_files(vault))
    by_name, by_alias = {}, {}
    for rel in notes:
        for k in {key(rel[:-3]), key(basename(rel)[:-3])}:
            by_name.setdefault(k, []).append(rel)

    def first_hit(index):
        return next(((index[k], rest) for k, _, rest in cands if k in index), None)

    found = first_hit(by_name)
    if not found:
        for rel in notes:
            for alias in set(map(key, note_meta(vault / rel)[1])):
                by_alias.setdefault(alias, []).append(rel)
        found = first_hit(by_alias)
    if not found:
        names = {key(basename(r)[:-3]): basename(r)[:-3] for r in notes}
        for alias, rels in by_alias.items():
            names.setdefault(alias, basename(rels[0])[:-3])
        best = None
        for k, name, rest in cands:
            close = difflib.get_close_matches(k, names, n=1, cutoff=SUGGEST_CUTOFF)
            if not close:
                continue
            ratio = difflib.SequenceMatcher(None, k, close[0]).ratio()
            if best is None or ratio > best[0]:
                best = (ratio, name, names[close[0]], rest)
        if best:
            print(f"suggest: {best[1]} -> {best[2]}")
            if split:
                print(f"request: {best[3]}")
        raise user_error(f"note not found: {raw.strip()}")
    hits, rest = found
    if len(hits) > 1:
        print("\n".join(f"match: {r} (status: {status_of(vault / r) or 'none'})" for r in hits))
        if split:
            print(f"request: {rest}")
        raise user_error("several notes match, give the path")
    return hits[0], rest


def check_clash(vault, rel):
    """Fail 3 when the note moves and 01. Inbox already holds a file with its name."""
    if in_inbox(rel):
        return
    for entry in os.listdir(vault / INBOX):
        if key(entry) == key(basename(rel)):
            print(f"exists: {INBOX}/{entry}")
            raise user_error(f"{INBOX}/{entry} already exists, {rel} not moved")


def prepare(vault, raw):
    rel, request = find_note(vault, raw, split=True)
    check_clash(vault, rel)
    data = (vault / rel).read_bytes()
    if frontmatter_end(data.decode("utf-8", "replace")) < 0:
        raise usage(f"{rel} has a frontmatter without a closing --- line; fix the note first")
    draft = draft_path()
    with open(to_native(draft), "xb") as out:
        write_full(out, data)
    return [f"note: {rel}", f"status: {status_of(vault / rel) or 'none'}",
            f"target: {INBOX}/{basename(rel)}", f"draft_file: {draft}", f"sha: {sha(data)}",
            f"request: {request}"]


def path_links(vault, old, skip):
    """Notes that link old (a path from the vault root) by path, as [[path]] or ](path)."""
    want = key(old.removesuffix(".md"))
    found = []
    for path in sorted(note_files(vault)):
        rel = path.relative_to(vault).as_posix()
        if rel == skip:
            continue
        text = path.read_bytes().decode("utf-8", "replace")
        targets = [re.split(r"[|#]", t, maxsplit=1)[0] for t in WIKILINK.findall(text)]
        targets += [unquote(t.split("#", 1)[0]) for t in MD_LINK.findall(text)]
        if any(key(t.strip().removesuffix(".md")) == want for t in targets):
            found.append(f"path-link: {rel}")
    return found


def publish(vault, raw, draft, expected, allow_secrets):
    rel = find_note(vault, raw)[0]
    if not draft.is_file():
        raise usage(f"draft file not found: {draft.as_posix()}")
    before = (vault / rel).read_bytes()
    if sha(before) != expected:
        raise user_error(f"{rel} changed since prepare, nothing written; prepare again")
    text = draft.read_bytes().decode("utf-8", "surrogateescape")
    old = set(before.decode("utf-8", "surrogateescape").splitlines())
    # Only new or changed lines count, so an example the note already had never blocks an edit.
    found = [] if allow_secrets else find_secrets(
        ["" if line in old else line for line in text.splitlines()])
    if found:
        print("\n".join(found))
        raise user_error("the draft looks like it holds secrets, nothing written")
    new = as_draft(text, frontmatter_end(before.decode("utf-8", "replace")) > 0)

    files, own = vault_files(vault), basename(rel)
    old_missing = missing_links(before.decode("utf-8", "replace"), files, own)
    added = [m for m in missing_links(new, files, own) if m not in old_missing]
    if added:
        for line in suggestions(vault, added):
            print(line)
        raise usage("links to notes that do not exist: " + ", ".join(f"[[{m}]]" for m in added))

    old_status = status_of(vault / rel) or "none"
    data = new.encode("utf-8", "surrogateescape")
    target = f"{INBOX}/{own}"
    if in_inbox(rel):
        if not replace_if_unchanged(vault / rel, before, data):
            raise user_error(f"{rel} changed while editing, nothing written; prepare again")
    else:
        check_clash(vault, rel)
        try:
            publish_file(vault / target, data)
        except FileExistsError:
            raise user_error(f"{target} was created meanwhile, nothing changed")
        if (vault / rel).read_bytes() != before:
            raise Fail(1, f"SYSTEM ERROR: edit.py: {rel} changed after {target} was written; "
                          "both files exist, nothing deleted")
        os.unlink(vault / rel)  # allow-delete: source note after its edited copy is published in 01. Inbox, completes a move
    draft.unlink()  # allow-delete: used-up draft input file, outside the vault
    if rel == target:
        return [f"Edited in place: {target} (was {old_status})"]
    return ([f"Edited and moved to draft: {target} (from {rel}, was {old_status})"]
            + path_links(vault, rel, target))


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    allow = argv[1:2] == ["--allow-secrets"]
    args = argv[2:] if allow else argv[1:]
    if not ((argv[:1] == ["prepare"] and not allow and len(args) == 1)
            or (argv[:1] == ["publish"] and len(args) == 3)):
        print("usage: edit.py prepare <note> | edit.py publish [--allow-secrets] "
              "<note> <draft-file> <sha> (see --help)", file=sys.stderr)
        return 2
    vault = require_vault()
    if not (vault / INBOX).is_dir():
        print("ERROR: " + NO_INBOX.format(inbox=INBOX, vault=vault.as_posix()))
        return 0
    try:
        if argv[0] == "prepare":
            lines = prepare(vault, args[0])
        else:
            lines = publish(vault, args[0], Path(to_native(args[1])), args[2], allow)
    except Fail as err:
        print(err, file=sys.stderr)
        return err.code
    except OSError as err:
        print(f"SYSTEM ERROR: edit.py: {err}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
