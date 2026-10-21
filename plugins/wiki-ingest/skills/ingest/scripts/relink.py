#!/usr/bin/env python3
"""usage: relink.py [--run <id>] <old note> <new name>

Rewrite links to <old note> in every note to [[new name]], for an approved merge.
Keeps #heading and |display parts, matches case-insensitively. A link without display
text keeps the old name as display text ([[Old]] becomes [[New|Old]], \\| in a table row),
so the prose reads the same; embeds ![[Old]] and links in the frontmatter only change
the target. Markdown links [text](01.%20Inbox/Old.md) (also <...>, relative and bare
forms) get the target's path. A bare link matches by filename; a path link only when
the path is <old note>. Skips fenced code blocks, inline `code` spans and dot folders.
Never deletes. --run <id> (from select.py) records each changed note in the run ledger.
The vault comes from vault.py (the configured vault path).

arguments:
  <old note>     merge source path from the vault root, e.g. "01. Inbox/ACE notes.md"
  <new name>     merge target filename without .md, must exist in the vault

output (stdout):
  changed: <path>    one line per note that was rewritten
  links: <n>         number of links rewritten (0 on a second run)
  skipped-ambiguous: <n>   bare links left alone because several notes have
                           the old filename; the model reports them
  ambiguous-target: <n>    <n> notes have the new filename, so the rewritten
                           bare [[new name]] links are ambiguous; the model reports it
  ERROR: <message>   vault problem (path missing, no CLAUDE.md), exit 0

exit codes:
  0  done (also when nothing had to change), or an ERROR line
  1  system error (read or write failed)
  2  bad usage (wrong arguments)
  3  user error (no note named <new name> in the vault, or a note changed while it was
     being written; that note is not written)

example: relink.py "01. Inbox/ACE notes.md" "ACE"
"""

import os
import posixpath
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote

import ledger

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault  # noqa: E402

FENCE = re.compile(r"^[ \t]*(```|~~~)")
DASHES = re.compile(r"^---[ \t]*$")
# an inline code span: a backtick run, then text, then the same run (CommonMark, one line)
CODE = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)")
# ![[target#heading|display]]: 1 embed mark, 2 target, 3 #heading, 4 |display (\| in a table)
LINK = re.compile(r"(!?)\[\[([^\]|#\r\n]*?)(#[^\]|\r\n]*?)?(\\?\|[^\]\r\n]*)?\]\]")
# [text](destination "title"): 1 up to the (, 2 destination, 3 the rest up to the )
MD_LINK = re.compile(r"(!?\[[^\]\r\n]*\]\()(<[^>\r\n]*>|[^)\s]+)([^)\r\n]*\))")
SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")


class Fail(Exception):
    """An error line for stderr plus the exit code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def sys_error(msg):
    return Fail(1, f"SYSTEM ERROR: relink.py: {msg}")


def bad(msg):
    return Fail(2, f"SYSTEM ERROR: relink.py: {msg}, see --help")


def user_error(msg):
    return Fail(3, f"USER ERROR: relink.py: {msg}")


def list_notes(vault):
    """Every .md path from the vault root, dot files and folders skipped, sorted."""
    found = []
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            full = Path(root) / name
            if not name.startswith(".") and name.endswith(".md") and not full.is_symlink():
                found.append(full.relative_to(vault).as_posix())
    return sorted(found)


def stem(path):
    return path.rsplit("/", 1)[-1].removesuffix(".md")


class Relinker:
    """Rewrites the links of one merge; counts rewritten and skipped links."""

    def __init__(self, old, old_path, new, ambiguous, new_path=None):
        self.old = old.lower()
        self.old_path = old_path.lower()
        self.new = new
        self.new_path = (new_path or new).removesuffix(".md")
        self.ambiguous = ambiguous
        self.skipped = 0

    def might_link(self, text):
        """Quick skip: False when no link to the old note is possible in text."""
        low = text.lower()
        return self.old in low or quote(self.old).lower() in low

    def target_matches(self, target):
        t = target.strip(" \t").removesuffix(".md").removeprefix("/").lower()
        if "/" in t:
            return t == self.old_path
        if t != self.old:
            return False
        if self.ambiguous:
            self.skipped += 1  # a bare link could mean any of the same-name notes
            return False
        return True

    def md_destination(self, dest, folder):
        """The new destination of a Markdown link to the old note, or None."""
        angle = dest.startswith("<")
        raw = dest[1:-1] if angle else dest
        if SCHEME.match(raw):
            return None  # an external URL
        raw_path, hash_, frag = raw.partition("#")
        path = unquote(raw_path)
        if not path:
            return None
        md = ".md" if path.lower().endswith(".md") else ""
        if "/" not in path:
            if not self.target_matches(path):
                return None
            new = self.new
        elif posixpath.normpath(path.lstrip("/")).lower().removesuffix(".md") == self.old_path:
            new = self.new_path
        elif posixpath.normpath(posixpath.join(folder, path)).lower().removesuffix(".md") == self.old_path:
            new = posixpath.relpath(self.new_path, folder or ".")
        else:
            return None
        new += md
        return f"<{new}{hash_}{frag}>" if angle else quote(new) + hash_ + frag

    def rewrite(self, text, rel=""):
        """Return (new text, number of links rewritten). rel is the note's own path, for
        relative Markdown links. Fenced code blocks stay as they are."""
        count = 0
        in_fence = in_fm = False
        folder = rel.rsplit("/", 1)[0] if "/" in rel else ""

        def wikilink(m, table):
            nonlocal count
            bang, target, heading, display = m.group(1), m.group(2), m.group(3) or "", m.group(4)
            if not self.target_matches(target):
                return m.group(0)
            count += 1
            if not display and not bang and not in_fm:
                # keep the visible text: [[Old]] reads "Old", so [[New|Old]] does too
                display = ("\\|" if table else "|") + target.strip(" \t").removesuffix(".md")
            return f"{bang}[[{self.new}{heading}{display or ''}]]"

        def mdlink(m):
            nonlocal count
            dest = self.md_destination(m.group(2), folder)
            if dest is None:
                return m.group(0)
            count += 1
            return m.group(1) + dest + m.group(3)

        def links(chunk, table):
            return MD_LINK.sub(mdlink, LINK.sub(lambda m: wikilink(m, table), chunk))

        lines = text.split("\n")
        if lines[-1] == "":
            lines.pop()
        out = []
        for number, line in enumerate(lines):
            bare = line.removesuffix("\r")
            if number == 0 and DASHES.match(bare.removeprefix("﻿")):
                in_fm = True
            elif in_fm and DASHES.match(bare):
                in_fm = False
            elif in_fm:
                line = links(line, False)  # frontmatter: quoting and form stay, only the target changes
            elif FENCE.match(line):
                in_fence = not in_fence
            elif not in_fence:
                table = line.lstrip(" \t").startswith("|")
                parts, pos = [], 0
                for code in CODE.finditer(line):
                    parts += [links(line[pos:code.start()], table), code.group(0)]
                    pos = code.end()
                line = "".join(parts) + links(line[pos:], table)
            out.append(line)
        return "".join(line + "\n" for line in out), count


def read_text(path, rel):
    try:
        return path.open(encoding="utf-8", errors="surrogateescape", newline="").read()
    except OSError as err:
        raise sys_error(f"cannot rewrite {rel}: {err}")


def changed_meanwhile(rel):
    return user_error(f"{rel} changed while ingest was writing it (Obsidian or a sync tool), "
                      "this note was not written; re-read it and run the step again")


def write_note(path, rel, text, before):
    """Write through a temp file next to the note, so a failed write leaves the note intact.
    before is the text the change started from: when the note differs from it just before
    the replace (an autosave or a sync in between), nothing is written (user error)."""
    try:
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
            f.write(text)
        if read_text(path, rel) != before:
            os.unlink(tmp)  # allow-delete: own temp file, the note changed meanwhile
            raise changed_meanwhile(rel)
        os.replace(tmp, path)
    except OSError as err:
        raise sys_error(f"cannot write {rel}: {err}")


def parse_args(argv):
    """Return (old name, old path without .md, new name)."""
    if len(argv) != 2:
        raise bad("expected <old note> <new name>")
    old_path = argv[0].replace("\\", "/")
    old_path = (old_path[2:] if old_path.startswith("./") else old_path).removesuffix(".md")
    old = old_path.rsplit("/", 1)[-1]
    new = argv[1].removesuffix(".md").rsplit("/", 1)[-1]
    if not old or not new:
        raise bad("names must not be empty")
    if any(c in old + new for c in "[]|#"):
        raise bad("names must not contain [ ] | #")
    if old.lower() == new.lower():
        raise bad("old and new name are the same")
    return old, old_path, new


def relink(vault, old, old_path, new, run=None):
    notes = list_notes(vault)
    targets = [n for n in notes if stem(n).lower() == new.lower()]
    if not targets:
        raise user_error(f'no note named "{new}" in the vault, create or pick the merge target first')
    twins = sum(stem(n).lower() == old.lower() for n in notes)
    relinker = Relinker(old, old_path, new, ambiguous=twins > 1, new_path=targets[0])
    total = 0
    for rel in notes:
        path = vault / rel
        text = read_text(path, rel)
        if not relinker.might_link(text):
            continue
        new_text, count = relinker.rewrite(text, rel)
        if count:
            write_note(path, rel, new_text, text)
            ledger.record(run, "changed", rel)
            print(f"changed: {rel}")
            total += count
    print(f"links: {total}")
    if relinker.skipped:
        print(f"skipped-ambiguous: {relinker.skipped}")
    if len(targets) > 1 and total:
        print(f"ambiguous-target: {len(targets)}")


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    try:
        run, argv = ledger.pop_run(argv, bad)
        old, old_path, new = parse_args(argv)
        relink(require_vault(), old, old_path, new, run)
    except Fail as fail:
        print(fail, file=sys.stderr)
        return fail.code
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(main(sys.argv[1:]))
