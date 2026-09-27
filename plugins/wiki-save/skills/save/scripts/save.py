#!/usr/bin/env python3
"""save.py: write a draft note into <vault>/01. Inbox, never overwriting anything.

usage: save.py [--append] <vault> <title> <draft-file>

Create "<vault>/01. Inbox/<title>.md" from <draft-file>, or with --append add the
draft body to an existing draft note of that name in 01. Inbox.
The script adds the "# <title>" heading; the draft file holds frontmatter and body.
Use it in wiki-save:save after the model wrote the draft file (path from gather.py).

arguments:
  <vault>       vault root, as printed by gather.py
  <title>       note title; \\ / : * ? " < > | # ^ [ ] become "-"
  <draft-file>  frontmatter (with status: draft) plus body, no "# Title" needed.
                --append uses only the body. Deleted after a successful save.

checks: no note with that filename anywhere in the vault (case-insensitive),
frontmatter present with status: draft, every [[link]] outside code points to an
existing file or to the note itself.

output (stdout): saved|appended: <path from vault root>, renamed: yes|no
on exit 3: exists: <path> and status: <status|none> per match, then appendable: yes|no
(yes only for a single match that is a draft directly in 01. Inbox)

exit codes:
  0  saved or appended
  1  system error (vault folder or 01. Inbox missing, write failed)
  2  bad usage (arguments, draft file missing or invalid, link to a missing note)
  3  user error (a note with that name exists, --append target is not an Inbox draft)

examples:
  save.py "C:/Vault" "ACE vs SOP" /tmp/wiki-save-1.md
  save.py --append "C:/Vault" "ACE vs SOP" /tmp/wiki-save-1.md
"""

import os
import re
import sys
from datetime import date
from pathlib import Path

# The shared vault reader lives in the plugin's scripts folder; only to_native is used.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import to_native  # noqa: E402

INBOX = "01. Inbox"
FENCE = re.compile(r"^---[ \t]*$")
BLANK = re.compile(r"^[ \t]*$")
CODE_FENCE = re.compile(r"^[ \t]*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")
WIKILINK = re.compile(r"\[\[([^\]]*)\]\]")
DRAFT_STATUS = re.compile(r"""^status:\s*["']?draft["']?\s*$""")


class Fail(Exception):
    """Stop with an exit code and a message for stderr."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def safe_name(title):
    """Replace forbidden filename characters, collapse spaces, trim spaces and trailing dots."""
    name = re.sub(r"[\r\n]", "", title)
    name = re.sub(r'[\[\]\\/:*?"<>|#^]', "-", name)
    name = re.sub(r"\s+", " ", name)
    return name.removeprefix(" ").rstrip(" .")


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


def split_draft(lines):
    """Return (frontmatter with fences, body without a leading "# " heading), both as text."""
    fm, rest = [], lines
    if lines and FENCE.match(lines[0]):
        end = next((i for i in range(1, len(lines)) if FENCE.match(lines[i])), len(lines) - 1)
        fm, rest = lines[:end + 1], lines[end + 1:]
    while rest and BLANK.match(rest[0]):
        rest = rest[1:]
    if rest and rest[0].startswith("# "):
        rest = rest[1:]
        if rest and BLANK.match(rest[0]):
            rest = rest[1:]
    return "\n".join(fm).rstrip("\n"), "\n".join(rest).rstrip("\n")


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
    have = {basename(f).lower() for f in files} | {own_file.lower()}
    missing = []
    for target in link_targets(text):
        key = basename(target).lower()
        if key and key not in have and key + ".md" not in have:
            missing.append(target)
    return missing


def create_note(vault, name, fm, body):
    """Write a new note; never overwrite an existing file."""
    target = f"{INBOX}/{name}.md"
    try:
        with open(vault / target, "x", encoding="utf-8", newline="") as out:
            out.write(f"{fm}\n# {name}\n\n{body}\n")
    except OSError:
        raise Fail(1, f"SYSTEM ERROR: save.py: could not create {target}")
    return target


def append_note(vault, existing, body):
    """Add the body under a "## <today>" heading, keeping the note's line endings."""
    path = vault / existing
    try:
        data = path.read_bytes()
        eol = "\r\n" if b"\r\n" in data else "\n"  # keep CRLF notes CRLF
        text = "" if not data or data.endswith(b"\n") else "\n"
        text += f"\n## {date.today().isoformat()}\n\n{body}\n"
        with open(path, "a", encoding="utf-8", newline="") as out:
            out.write(text.replace("\n", eol))
    except OSError:
        raise Fail(1, f"SYSTEM ERROR: save.py: could not append to {existing}")


def save(mode, vault, title, draft):
    """Run all checks, then create or append. Returns the stdout lines."""
    if not (vault / INBOX).is_dir():
        raise Fail(1, f"SYSTEM ERROR: save.py: no {INBOX} folder in vault: {vault.as_posix()}")
    if not draft.is_file():
        raise Fail(2, f"SYSTEM ERROR: save.py: draft file not found: {draft.as_posix()}")

    name = safe_name(title)
    if not name:
        raise Fail(3, f"USER ERROR: save.py: title has no usable characters: {title}")
    renamed = "no" if name == title else "yes"
    own_file = f"{name}.md"

    files = vault_files(vault)
    existing = [f for f in files if basename(f).lower() == own_file.lower()]
    # Appendable only when the single match is a draft directly in 01. Inbox.
    appendable = (len(existing) == 1 and existing[0].startswith(INBOX + "/")
                  and "/" not in existing[0][len(INBOX) + 1:]
                  and status_of(vault / existing[0]) == "draft")

    if mode == "create" and existing:
        out = []
        for path in existing:
            out += [f"exists: {path}", f"status: {status_of(vault / path) or 'none'}"]
        print("\n".join(out + [f"appendable: {'yes' if appendable else 'no'}"]))
        raise Fail(3, f'USER ERROR: save.py: a note named "{name}" already exists: '
                      + ", ".join(existing))

    fm, body = split_draft(read_lines(draft))
    if not body:
        raise Fail(2, f"SYSTEM ERROR: save.py: draft file has no body text: {draft.as_posix()}")

    # Append drops the draft frontmatter, so only the body counts there.
    checked = f"{fm}\n{body}" if mode == "create" else body
    missing = missing_links(checked, files, own_file)
    if missing:
        raise Fail(2, "SYSTEM ERROR: save.py: links to notes that do not exist: "
                      + ", ".join(f"[[{m}]]" for m in missing))

    if mode == "create":
        if not any(DRAFT_STATUS.match(line) for line in fm.split("\n")):
            raise Fail(2, "SYSTEM ERROR: save.py: draft file needs frontmatter with status: draft")
        target = create_note(vault, name, fm, body)
        draft.unlink()
        return [f"saved: {target}", f"renamed: {renamed}"]

    if not appendable:
        found = f" (found: {', '.join(existing)})" if existing else ""
        raise Fail(3, f'USER ERROR: save.py: no single draft note "{name}" in {INBOX} '
                      f"to append to{found}")
    append_note(vault, existing[0], body)
    draft.unlink()
    return [f"appended: {existing[0]}", f"renamed: {renamed}"]


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    mode = "create"
    if argv[:1] == ["--append"]:
        mode, argv = "append", argv[1:]
    if len(argv) != 3:
        print("usage: save.py [--append] <vault> <title> <draft-file> (see --help)",
              file=sys.stderr)
        return 2
    vault = Path(to_native(argv[0]))
    try:
        lines = save(mode, vault, argv[1], Path(to_native(argv[2])))
    except Fail as err:
        print(err, file=sys.stderr)
        return err.code
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
