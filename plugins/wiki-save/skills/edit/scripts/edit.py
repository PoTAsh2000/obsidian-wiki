#!/usr/bin/env python3
"""edit.py: edit one existing note, set it to status draft and move it into 01. Inbox.

usage: edit.py prepare <note>
       edit.py publish [--allow-secrets] <note> <draft-file> <sha>

prepare finds the note and copies it byte for byte to a temp draft file outside the
vault, for the model to edit. publish checks the edited draft, sets status: draft,
sets an existing updated: key to today (never adds one) and writes the result to
"01. Inbox/<same filename>". A note directly in 01. Inbox is replaced in place; any
other note (also in 99. Archived) is moved there and its old file removed, which
completes the move. The filename never changes, so [[Name]] links keep working.
The vault comes from the shared scripts/vault.py.
Use it in wiki-save:edit.

arguments:
  <note>        a path from the vault root ending in .md, a [[link]] (|alias and #heading
                are ignored) or a plain note name; compared case-insensitive and NFC.
                The filename (or path) wins; only when nothing matches, an alias counts.
                Dot folders and 90. Templates are never searched.
  <draft-file>  the draft_file from prepare, edited. Deleted after a successful publish.
  <sha>         the sha from prepare: publish refuses when the note changed meanwhile
  --allow-secrets  skip the secret scan (only when the user says the content is safe)

checks on publish: the note still has the sha from prepare, no secrets in the draft
(same scan as save.py), frontmatter closed by --- (no frontmatter: one with only
status: draft is added), no [[link]] to a missing note that the original did not have,
no other note with that filename in 01. Inbox. Line endings and odd bytes are kept.

output (stdout):
  prepare: note: <path>, status: <status|none>, target: <path>, draft_file: <path>, sha: <hex>
  publish: edited: <path>, from: <old path>, status: draft (was <status|none>), then
           path-link: <note> per note that links the old location by path (report only)
  exit 3 on prepare: match: <path> (status: <status|none>) per match when several match,
           suggest: <note> -> <close name> when none matches,
           exists: <path> when 01. Inbox holds another note with that filename
  exit 3 for secrets: secret: line <n>: <kind> per finding (the value is never shown)
  exit 2 for new missing links: suggest: <missing> -> <closest note name>
  vault problem or no 01. Inbox (exit 0): a single "ERROR: <message>" line, nothing changed

exit codes:
  0  prepared or published, or an ERROR line
  1  system error (read or write failed, the note changed after the Inbox copy was written)
  2  bad usage (arguments, path leaves the vault, draft missing or invalid, new missing link)
  3  user error (note not found, several matches, name taken in 01. Inbox, note changed
     since prepare, the draft holds secrets)
  On every error the draft file is kept.

examples:
  edit.py prepare "Docker Basics"
  edit.py prepare "20. Knowledge/Docker Basics.md"
  edit.py publish "20. Knowledge/Docker Basics.md" /tmp/wiki-save-1.md 3f2a...
"""

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
from save import (WIKILINK, Fail, basename, find_secrets, missing_links, status_of,  # noqa: E402
                  suggestions, vault_files, write_full, write_temp)

INBOX = "01. Inbox"
DASHES = re.compile(r"^---[ \t]*$")
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")


def usage(msg):
    return Fail(2, f"SYSTEM ERROR: edit.py: {msg}, see --help")


def user_error(msg):
    return Fail(3, f"USER ERROR: edit.py: {msg}")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def split_lines(text):
    """Lines without their final \\n; a \\r before it stays in the line."""
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


# Copied from wiki-ingest promote.py (plugins are installed on their own, so no import).
def with_status(text, status):
    """Return text with the frontmatter status set (rewritten or added), or None without frontmatter."""
    out, in_fm, done = [], False, False
    for number, line in enumerate(split_lines(text), 1):
        cr = "\r" if line.endswith("\r") else ""
        bare = line.removesuffix("\r")
        if number == 1:
            if not DASHES.match(bare.removeprefix("\ufeff")):
                return None
            in_fm = True
        elif in_fm and DASHES.match(bare):
            if not done:
                out.append(f"status: {status}{cr}")  # no status line yet: add one before the closing ---
            in_fm, done = False, True
        elif in_fm and bare.startswith("status:"):
            out.append(f"status: {status}{cr}")
            done = True
            continue
        out.append(line)
    if not done:
        return None
    return "".join(line + "\n" for line in out)


def set_updated(text):
    """Set an existing frontmatter updated: key to today; never add one."""
    lines = text.split("\n")
    for i in range(1, len(lines)):
        bare = lines[i].removesuffix("\r")
        if DASHES.match(bare):
            break
        if bare.startswith("updated:"):
            cr = "\r" if lines[i].endswith("\r") else ""
            lines[i] = f"updated: {date.today().isoformat()}{cr}"
    return "\n".join(lines)


def frontmatter_end(text):
    """Index of the closing --- line, 0 without frontmatter, -1 when it is not closed."""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    if not DASHES.match(lines[0].removeprefix("﻿")):
        return 0
    return next((i for i in range(1, len(lines)) if DASHES.match(lines[i])), -1)


def as_draft(text, had_frontmatter):
    """The draft text with status: draft, or Fail 2 when the draft lost content."""
    end = frontmatter_end(text)
    if end < 0:
        raise usage("draft frontmatter has no closing --- line")
    if had_frontmatter and end == 0:
        raise usage("draft lost the frontmatter the note had; put it back")
    if not "\n".join(text.split("\n")[end + 1 if end else 0:]).strip():
        raise usage("draft has no body text; an edit never empties a note")
    if end == 0:
        bom = "﻿" if text.startswith("﻿") else ""
        eol = "\r\n" if "\r\n" in text else "\n"
        return f"{bom}---{eol}status: draft{eol}---{eol}{text.removeprefix(bom)}"
    new = with_status(text, "draft")
    if not text.endswith("\n"):
        new = new[:-1]  # with_status ends every line with \n; keep a missing final newline
    return set_updated(new)


def in_inbox(rel):
    return rel.startswith(INBOX + "/") and "/" not in rel[len(INBOX) + 1:]


def find_note(vault, raw):
    """The one note path (from the vault root) that raw names, else Fail 3 with lines."""
    name = raw.strip().replace("\\", "/")
    if name.startswith("[[") and name.endswith("]]"):
        name = re.split(r"[|#]", name[2:-2], maxsplit=1)[0]
    name = name.removeprefix("./")
    if not name or "/." in f"/{name}":
        raise usage("note name is empty, leaves the vault or enters a dot folder")
    want = key(name.removesuffix(".md"))
    notes = sorted(p.relative_to(vault).as_posix() for p in note_files(vault))
    hits = [r for r in notes if want in (key(r[:-3]), key(basename(r)[:-3]))]
    if not hits:
        hits = [r for r in notes if want in map(key, note_meta(vault / r)[1])]
    if not hits:
        for line in suggestions(vault, [name]):
            print(line)
        raise user_error(f"note not found: {raw}")
    if len(hits) > 1:
        print("\n".join(f"match: {r} (status: {status_of(vault / r) or 'none'})" for r in hits))
        raise user_error(f"several notes match {raw}, give the path")
    return hits[0]


def check_clash(vault, rel):
    """Fail 3 when the note moves and 01. Inbox already holds a file with its name."""
    if in_inbox(rel):
        return
    for entry in os.listdir(vault / INBOX):
        if key(entry) == key(basename(rel)):
            print(f"exists: {INBOX}/{entry}")
            raise user_error(f"{INBOX}/{entry} already exists, {rel} not moved")


def prepare(vault, raw):
    rel = find_note(vault, raw)
    check_clash(vault, rel)
    data = (vault / rel).read_bytes()
    if frontmatter_end(data.decode("utf-8", "replace")) < 0:
        raise usage(f"{rel} has a frontmatter without a closing --- line; fix the note first")
    draft = draft_path()
    with open(to_native(draft), "xb") as out:
        write_full(out, data)
    return [f"note: {rel}", f"status: {status_of(vault / rel) or 'none'}",
            f"target: {INBOX}/{basename(rel)}", f"draft_file: {draft}", f"sha: {sha(data)}"]


def publish_new(vault, target, data):
    """Create target in one step, never replacing a file (like save.py create_note)."""
    path = vault / target
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
        raise user_error(f"{target} was created meanwhile, nothing changed")
    except OSError as err:
        raise Fail(1, f"SYSTEM ERROR: edit.py: could not create {target}: {err}")


def replace_note(vault, rel, before, data):
    """Replace a note in one step, only when it still holds before."""
    path = vault / rel
    try:
        tmp = write_temp(path.parent, data)
        try:
            if path.read_bytes() != before:
                raise user_error(f"{rel} changed while editing, nothing written; prepare again")
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)  # allow-delete: own temp file left after a failed replace
    except OSError as err:
        raise Fail(1, f"SYSTEM ERROR: edit.py: could not write {rel}: {err}")


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
    rel = find_note(vault, raw)
    if not draft.is_file():
        raise usage(f"draft file not found: {draft.as_posix()}")
    before = (vault / rel).read_bytes()
    if sha(before) != expected:
        raise user_error(f"{rel} changed since prepare, nothing written; prepare again")
    text = draft.read_bytes().decode("utf-8", "surrogateescape")
    found = [] if allow_secrets else find_secrets(text.splitlines())
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
        replace_note(vault, rel, before, data)
    else:
        check_clash(vault, rel)
        publish_new(vault, target, data)
        if (vault / rel).read_bytes() != before:
            raise Fail(1, f"SYSTEM ERROR: edit.py: {rel} changed after {target} was written; "
                          "both files exist, nothing deleted")
        os.unlink(vault / rel)  # allow-delete: source note after its edited copy is published in 01. Inbox, completes a move
    draft.unlink()  # allow-delete: used-up draft input file, outside the vault
    out = [f"edited: {target}", f"from: {rel}", f"status: draft (was {old_status})"]
    return out + (path_links(vault, rel, target) if rel != target else [])


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
