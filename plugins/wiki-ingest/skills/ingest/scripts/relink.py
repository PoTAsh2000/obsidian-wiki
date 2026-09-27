#!/usr/bin/env python3
"""usage: relink.py --vault <dir> <old note> <new name>

Rewrite links to <old note> in every note to [[new name]], for an approved merge.
Keeps #heading and |display parts, matches case-insensitively. A bare link [[Old]]
matches by filename; a path link [[01. Inbox/Old]] only when the path is <old note>.
Skips fenced code blocks and dot folders. Never deletes.

arguments:
  --vault <dir>  vault root (required)
  <old note>     merge source path from the vault root, e.g. "01. Inbox/ACE notes.md"
  <new name>     merge target filename without .md, must exist in the vault

output (stdout):
  changed: <path>    one line per note that was rewritten
  links: <n>         number of links rewritten (0 on a second run)
  skipped-ambiguous: <n>   bare links left alone because several notes have
                           the old filename; the model reports them

exit codes:
  0  done (also when nothing had to change)
  1  system error (read or write failed)
  2  bad usage (wrong arguments, vault folder not found)
  3  user error (no note named <new name> in the vault)

example: relink.py --vault "C:/Vault" "01. Inbox/ACE notes.md" "ACE"
"""

import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import to_native  # noqa: E402

FENCE = re.compile(r"^[ \t]*(```|~~~)")
# [[target followed by the character that ends the target: ] or | or #
LINK = re.compile(r"\[\[([^\]|#\r\n]*)([\]|#])")


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

    def __init__(self, old, old_path, new, ambiguous):
        self.old = old.lower()
        self.old_path = old_path.lower()
        self.new = new
        self.ambiguous = ambiguous
        self.skipped = 0

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

    def rewrite(self, text):
        """Return (new text, number of links rewritten). Fenced code blocks stay as they are."""
        count = 0
        in_fence = False

        def replace(m):
            nonlocal count
            if not self.target_matches(m.group(1)):
                return m.group(0)
            count += 1
            return f"[[{self.new}{m.group(2)}"

        lines = text.split("\n")
        if lines[-1] == "":
            lines.pop()
        out = []
        for line in lines:
            if FENCE.match(line):
                in_fence = not in_fence
            elif not in_fence:
                line = LINK.sub(replace, line)
            out.append(line)
        return "".join(line + "\n" for line in out), count


def read_text(path, rel):
    try:
        return path.read_text(encoding="utf-8", errors="surrogateescape", newline="")
    except OSError as err:
        raise sys_error(f"cannot rewrite {rel}: {err}")


def write_text(path, rel, text):
    """Write through a temp file next to the note, so a failed write leaves the note intact."""
    try:
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError as err:
        raise sys_error(f"cannot write {rel}: {err}")


def parse_args(argv):
    if len(argv) != 4 or argv[0] != "--vault":
        raise bad("expected --vault <dir> <old note> <new name>")
    old_path = argv[2].replace("\\", "/")
    old_path = (old_path[2:] if old_path.startswith("./") else old_path).removesuffix(".md")
    old = old_path.rsplit("/", 1)[-1]
    new = argv[3].removesuffix(".md").rsplit("/", 1)[-1]
    if not old or not new:
        raise bad("names must not be empty")
    if any(c in old + new for c in "[]|#"):
        raise bad("names must not contain [ ] | #")
    if old.lower() == new.lower():
        raise bad("old and new name are the same")
    vault = Path(to_native(argv[1]))
    if not vault.is_dir():
        raise bad(f"vault folder not found: {argv[1]}")
    return vault, old, old_path, new


def relink(vault, old, old_path, new):
    notes = list_notes(vault)
    if not any(stem(n).lower() == new.lower() for n in notes):
        raise user_error(f'no note named "{new}" in the vault, create or pick the merge target first')
    twins = sum(stem(n).lower() == old.lower() for n in notes)
    relinker = Relinker(old, old_path, new, ambiguous=twins > 1)
    total = 0
    for rel in notes:
        path = vault / rel
        text = read_text(path, rel)
        if old.lower() not in text.lower():
            continue  # quick skip: no link to the old note is possible
        new_text, count = relinker.rewrite(text)
        if count:
            write_text(path, rel, new_text)
            print(f"changed: {rel}")
            total += count
    print(f"links: {total}")
    if relinker.skipped:
        print(f"skipped-ambiguous: {relinker.skipped}")


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    try:
        relink(*parse_args(argv))
    except Fail as fail:
        print(fail, file=sys.stderr)
        return fail.code
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(main(sys.argv[1:]))
