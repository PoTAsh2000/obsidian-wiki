#!/usr/bin/env python3
"""gather.py: read-only context for wiki-save:save. Injected before the model runs.

usage: gather.py

Print the context wiki-save:save needs, as key: value lines.
Read-only: changes nothing. Gets the vault from the shared scripts/vault.py. The vault
path and the vault CLAUDE.md come from the vault.py injection, not from here.
Used through !` injection at the start of wiki-save:save; run by hand to debug.

output:
  today: <YYYY-MM-DD>
  draft_file: <free temp path for the note draft, not created>
  topics: <existing topics, comma separated>
  ERROR: <message>    vault problem or no 01. Inbox folder: relay it to the user and stop

exit codes:
  0  context printed, or an ERROR line
  1  system error (cannot read a file)
  2  bad usage (arguments given)

example: gather.py
"""

import os
import re
import sys
import tempfile
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


def draft_path():
    """A free temp file path for the draft note. Not created here."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return (Path(tempfile.gettempdir()) / f"wiki-save-{stamp}-{os.getpid()}.md").as_posix()


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
    if argv:
        print("usage: gather.py (no arguments, see --help)", file=sys.stderr)
        return 2
    vault = require_vault()
    if not (vault / INBOX).is_dir():
        print("ERROR: " + NO_INBOX.format(inbox=INBOX, vault=vault.as_posix()))
        return 0
    try:
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
