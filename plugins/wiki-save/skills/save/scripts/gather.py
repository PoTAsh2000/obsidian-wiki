#!/usr/bin/env python3
"""gather.py: read-only context for wiki-save:save. Injected before the model runs.

usage: gather.py
       gather.py --related <keyword>...

Print the context wiki-save:save needs, as key: value lines.
With --related: list notes whose filename, first "# " heading or an aliases entry
contains one of the keywords (case-insensitive), to pick related notes from.
Read-only: changes nothing. Gets the vault from the shared scripts/vault.py. The vault
path and the vault CLAUDE.md come from the vault.py injection, not from here.
Used through !` injection at the start of wiki-save:save; run by hand to debug.

output:
  today: <YYYY-MM-DD>
  draft_file: <free temp path for the note draft, not created>
  topics: <existing topics, comma separated>
  ERROR: <message>    vault problem or no 01. Inbox folder: relay it to the user and stop
--related output, one line per match, or "related: none":
  related: <path from vault root> (<filename|heading|alias, comma separated>)

exit codes:
  0  context printed, or an ERROR line
  1  system error (cannot read a file)
  2  bad usage (other arguments, --related without keywords)

examples:
  gather.py
  gather.py --related docker container
"""

import os
import re
import sys
import tempfile
import unicodedata
from datetime import date, datetime
from pathlib import Path

# The shared vault reader lives in the plugin's scripts folder.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault  # noqa: E402

INBOX = "01. Inbox"
TEMPLATES = "90. Templates"
NO_INBOX = ("The configured vault folder has no {inbox} folder: {vault}. "
            "Use /wiki-vault:overwrite <vault path> to fix the vault path.")
FENCE = re.compile(r"^---[ \t]*$")
LIST_ITEM = re.compile(r"^[ \t]*-[ \t]+(.*)$")


def key(text):
    """Compare form of a name: NFC-normalized and casefolded."""
    return unicodedata.normalize("NFC", text).casefold()


def draft_path():
    """A free temp file path for the draft note. Not created here. resolve() turns a
    Windows 8.3 temp dir (C:/Users/USERNA~1/...) into the long path the Write tool accepts."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = Path(tempfile.gettempdir()).resolve()
    return (folder / f"wiki-save-{stamp}-{os.getpid()}.md").as_posix()


def note_files(vault):
    """Every .md file in the vault, skipping dot folders and the templates folder."""
    for root, dirs, files in os.walk(vault):
        top = Path(root) == vault
        dirs[:] = [d for d in dirs
                   if not (d.startswith(".") and len(d) > 1) and not (top and d == TEMPLATES)]
        for name in files:
            if name.endswith(".md"):
                yield Path(root) / name


def frontmatter_topics(path):
    """Values of every topic: line inside the frontmatter of one note."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or not FENCE.match(lines[0]):
        return []
    topics = []
    for line in lines[1:]:
        if FENCE.match(line):
            break
        if line.startswith("topic:"):
            value = line[len("topic:"):].lstrip(" \t")
            # Drop one leading quote and one trailing quote (plus spaces after it).
            value = re.sub(r"""^["']|["'][ \t]*$""", "", value).rstrip(" \t")
            if value:
                topics.append(value)
    return topics


def unquote(value):
    return value.strip().strip("\"'").strip()


def note_meta(path):
    """(first "# " heading or "", aliases list) of one note."""
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    aliases, start = [], 0
    if lines and FENCE.match(lines[0]):
        in_list = False
        for start in range(1, len(lines)):
            line = lines[start]
            if FENCE.match(line):
                break
            item = LIST_ITEM.match(line)
            if in_list and item:
                aliases.append(unquote(item.group(1)))
                continue
            in_list = False
            if line.startswith("aliases:"):
                value = line[len("aliases:"):].strip()
                if value:
                    aliases += [unquote(v) for v in value.strip("[]").split(",")]
                else:
                    in_list = True
        start += 1
    heading = next((line[2:].strip() for line in lines[start:] if line.startswith("# ")), "")
    return heading, [a for a in aliases if a]


def related(vault, keywords):
    """Output lines for notes whose filename, heading or an alias contains a keyword."""
    words = [key(w) for w in keywords if w.strip()]
    out = []
    for path in sorted(note_files(vault)):
        heading, aliases = note_meta(path)
        fields = [("filename", [path.stem]), ("heading", [heading]), ("alias", aliases)]
        hits = [label for label, values in fields
                if any(w in key(v) for v in values for w in words)]
        if hits:
            out.append(f"related: {path.relative_to(vault).as_posix()} ({', '.join(hits)})")
    return out or ["related: none"]


def all_topics(vault):
    """Distinct topics, case-insensitive, sorted case-insensitive."""
    seen = {}
    for path in note_files(vault):
        for topic in frontmatter_topics(path):
            seen.setdefault(topic.upper(), topic)
    return [seen[key] for key in sorted(seen)]


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # topics may hold non-ASCII text
    if argv in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    mode = argv[:1] == ["--related"]
    if (argv and not mode) or argv == ["--related"]:
        print("usage: gather.py [--related <keyword>...] (see --help)", file=sys.stderr)
        return 2
    vault = require_vault()
    if not (vault / INBOX).is_dir():
        print("ERROR: " + NO_INBOX.format(inbox=INBOX, vault=vault.as_posix()))
        return 0
    try:
        if mode:
            print("\n".join(related(vault, argv[1:])))
            return 0
        topics = all_topics(vault)
    except OSError as err:
        print(f"SYSTEM ERROR: gather.py: cannot read the vault {vault.as_posix()}: {err}",
              file=sys.stderr)
        return 1
    print(f"today: {date.today().isoformat()}")
    print(f"draft_file: {draft_path()}")
    print(f"topics: {', '.join(topics)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
