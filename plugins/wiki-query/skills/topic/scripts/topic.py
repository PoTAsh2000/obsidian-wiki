#!/usr/bin/env python3
"""topic.py: list vault notes by frontmatter topic. Read-only.

usage: topic.py [--inject] <topic>...

List notes in the configured Obsidian vault whose frontmatter topic matches,
one block per topic (case-insensitive, exact value). Read-only.
The vault path comes from ~/.claude/obsidian-wiki/vault-path (set by wiki-vault),
read through plugins/wiki-query/scripts/vault.py.
Use it from the topic skill; run it again with the topics the user gives.

Scope: every .md note except dot folders and the root folders Attachments
and "90. Templates".

arguments:
  <topic>...  one or more topics, space separated
  --inject    for !`...` injection: report user errors as "ERROR: <text>" on
              stdout with exit 0, so the skill does not abort
  -h, --help  show this help

output:
  "<topic>:" blocks with "- <note path>" lines, or "Nothing found.".
  A topic without notes gets "- nothing found" when another topic has notes.
  No topics: "ERROR: no topic given" (soft fail, exit 0).

exit codes:
  0  done (also when nothing is found)
  1  system error (cannot read the vault)
  2  bad usage (unknown option)
  3  user error (vault path missing, vault folder or its CLAUDE.md missing)

examples: topic.py EDI      topic.py ai tooling      topic.py --inject EDI
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import read_vault, VaultError  # noqa: E402

SKIP_ROOT_DIRS = {"Attachments", "90. Templates"}
FENCE = re.compile(r"^---[ \t]*$")
KEY_LINE = re.compile(r"^([A-Za-z_]+):[ \t]*(.*)$")
LIST_ITEM = re.compile(r"^[ \t]*-[ \t]*(.*)$")
USAGE = "usage: topic.py [--inject] <topic>... | --help"


class UsageError(Exception):
    """Bad call: exit 2."""


def parse_args(argv):
    """Return (inject, topics). Options come before the topics."""
    inject = False
    args = list(argv)
    while args and args[0].startswith("-"):
        opt = args.pop(0)
        if opt in ("-h", "--help"):
            return None, None
        if opt != "--inject":
            raise UsageError(f"unknown option: {opt}")
        inject = True
    return inject, args


def notes(vault):
    """Yield (relative posix path, file) for every note in scope."""
    for path in vault.rglob("*.md"):
        rel = path.relative_to(vault)
        folders = rel.parts[:-1]
        if any(part.startswith(".") and part != "." for part in folders):
            continue
        if folders and folders[0] in SKIP_ROOT_DIRS:
            continue
        if path.is_file():
            yield rel.as_posix(), path


def clean(value):
    """Trim whitespace, then one leading and one trailing quote."""
    value = value.strip(" \t")
    value = re.sub(r"^[\"']", "", value)
    return re.sub(r"[\"']$", "", value)


def split_value(value):
    """An inline list "[a, b]" gives its items, anything else gives itself."""
    if value.startswith("[") and value.endswith("]"):
        return value[1:-1].split(",")
    return [value]


def topics_of(text):
    """Return the frontmatter topic values of a note, cleaned, empty ones dropped."""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    if not lines or not FENCE.match(lines[0]):
        return []
    found = []
    in_list = False  # inside a "topic:" block list
    for line in lines[1:]:
        if FENCE.match(line):
            break
        key = KEY_LINE.match(line)
        if key:
            in_list = key.group(1) == "topic" and key.group(2) == ""
            if key.group(1) == "topic" and not in_list:
                found += split_value(key.group(2))
        elif in_list:
            item = LIST_ITEM.match(line)
            if item:
                found.append(item.group(1))
    return [v for v in map(clean, found) if v]


def lookup(vault, wanted):
    """Return one sorted list of note paths per wanted topic, in the same order."""
    keys = [w.lower() for w in wanted]
    hits = [set() for _ in wanted]
    for rel, path in notes(vault):
        text = path.read_text(encoding="utf-8", errors="replace")
        for topic in topics_of(text):
            for i, key in enumerate(keys):
                if topic.lower() == key:
                    hits[i].add(rel)
    return [sorted(h) for h in hits]


def report(wanted, hits):
    """Format the lookup result as printed lines."""
    if not any(hits):
        return ["Nothing found."]
    lines = []
    for topic, paths in zip(wanted, hits):
        lines.append(f"{topic}:")
        lines += [f"- {p}" for p in paths] or ["- nothing found"]
    return lines


def main(argv):
    try:
        inject, wanted = parse_args(argv)
    except UsageError as err:
        print(f"SYSTEM ERROR: topic.py: {err}. {USAGE}", file=sys.stderr)
        return 2
    if inject is None:
        print(__doc__.strip())
        return 0
    try:
        vault = read_vault()
    except VaultError as err:
        if inject:
            print(f"ERROR: {err}")
            return 0
        print(f"USER ERROR: {err}", file=sys.stderr)
        return 3
    except OSError as err:
        print(f"SYSTEM ERROR: topic.py: cannot read the vault path: {err}", file=sys.stderr)
        return 1
    if not wanted:
        print("ERROR: no topic given")
        return 0
    try:
        hits = lookup(vault, wanted)
    except OSError as err:
        print(f"SYSTEM ERROR: topic.py: lookup failed: {err}", file=sys.stderr)
        return 1
    print("\n".join(report(wanted, hits)))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # note paths may hold non-ASCII on Windows
    sys.exit(main(sys.argv[1:]))
