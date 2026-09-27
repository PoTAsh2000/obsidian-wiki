#!/usr/bin/env python3
"""usage: tag.py ['<tag> <tag>...']

List notes in the configured Obsidian vault by frontmatter tag, one block per tag.
Read-only. Reads the vault path with vault.py, prints the vault CLAUDE.md, then
the lookup result. Injected by the tag skill.

arguments:
  tags  one quoted string (or several arguments) with tags separated by spaces,
        case-insensitive, a leading # is ignored. Allowed: letters, digits, _ - /
        and other characters except spaces, quotes, brackets and shell symbols.

output (stdout, key: value):
  ERROR: <message>          soft fail, relay the message as-is
  vault: <dir>              always first when the vault is usable
  need: tags                no tag given, ask the user for tags and rerun
  --- vault CLAUDE.md ---   then the vault CLAUDE.md, up to the found: line
  found: yes|no             then the result: begin ... result: end block

exit codes:
  0  done (also for "Nothing found.", ERROR: and need: lines)
  1  system error (a file cannot be read)
  There is no usage error: every argument except -h/--help is read as tags.

example: tag.py 'ai #tooling'
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import MARKER, VaultError, read_vault  # noqa: E402

# Characters a tag may not contain: whitespace, quotes, brackets and shell symbols.
BAD_TAG = re.compile(r"""[\[\]\s#,;|&<>(){}"'`$*?\\]""")
# Folders at the vault root that are never searched. Dot folders are skipped everywhere.
SKIPPED_ROOT_FOLDERS = {"Attachments", "90. Templates"}
FRONTMATTER_FENCE = re.compile(r"^---[ \t]*$")
KEY_LINE = re.compile(r"^([A-Za-z_]+):[ \t]*(.*)$")
LIST_ITEM = re.compile(r"^[ \t]*-[ \t]*(.*)$")


class TagError(Exception):
    """Soft failure: an invalid tag, relayed to the user as is."""


def parse_tags(args):
    """Split every argument on whitespace, drop one leading #, reject bad characters."""
    tags = []
    for arg in args:
        for tag in arg.split():
            tag = tag[1:] if tag.startswith("#") else tag
            if not tag:
                continue
            if BAD_TAG.search(tag):
                raise TagError(f"Invalid tag '{tag}'. Use letters, digits, _ - or /, separated by spaces.")
            tags.append(tag)
    return tags


def note_files(folder, at_root=True):
    """Yield every .md file below folder, skipping dot folders and, at the root, SKIPPED_ROOT_FOLDERS."""
    for path in sorted(folder.iterdir()):
        if path.name.startswith("."):
            continue
        if path.is_dir():
            if not (at_root and path.name in SKIPPED_ROOT_FOLDERS):
                yield from note_files(path, at_root=False)
        elif path.suffix == ".md" and path.is_file():
            yield path


def clean(value):
    """Trim spaces and tabs, then one quote at each end."""
    value = value.strip(" \t")
    if value[:1] in ('"', "'"):
        value = value[1:]
    if value[-1:] in ('"', "'"):
        value = value[:-1]
    return value


def split_list(value):
    """Values of 'key: value': an inline list like [a, "b"] or a single value."""
    parts = value[1:-1].split(",") if re.fullmatch(r"\[.*\]", value) else [value]
    return [v for v in map(clean, parts) if v]


def frontmatter_tags(text):
    """Tags from the frontmatter: inline 'tags: [a, b]', 'tags: a' or a '- a' list below 'tags:'."""
    lines = text.split("\n")
    if not FRONTMATTER_FENCE.match(lines[0]):
        return []
    tags = []
    in_tag_list = False
    for line in lines[1:]:
        if FRONTMATTER_FENCE.match(line):
            break
        key = KEY_LINE.match(line)
        if key:
            in_tag_list = key.group(1) == "tags" and key.group(2) == ""
            if key.group(1) == "tags" and key.group(2):
                tags += split_list(key.group(2))
        elif in_tag_list:
            item = LIST_ITEM.match(line)
            if item and clean(item.group(1)):
                tags.append(clean(item.group(1)))
    return tags


def find_tagged(vault, tags):
    """Map each tag (by position) to the sorted vault-relative paths of notes carrying it."""
    wanted = [t.lower() for t in tags]
    hits = [set() for _ in tags]
    for note in note_files(vault):
        text = note.read_text(encoding="utf-8", errors="replace")
        note_tags = {t.lower() for t in frontmatter_tags(text)}
        for i, tag in enumerate(wanted):
            if tag in note_tags:
                hits[i].add(note.relative_to(vault).as_posix())
    return [sorted(paths) for paths in hits]


def result_lines(tags, hits):
    """One block per tag, or the single line 'Nothing found.' when no tag matched."""
    if not any(hits):
        return ["Nothing found."]
    lines = []
    for tag, paths in zip(tags, hits):
        lines.append(f"{tag}:")
        lines += [f"- {p}" for p in paths] or ["- nothing found"]
    return lines


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    try:
        vault = read_vault()
        tags = parse_tags(argv)
    except (VaultError, TagError) as err:
        print(f"ERROR: {err}")
        return 0
    if not tags:
        print(f"vault: {vault.as_posix()}")
        print("need: tags")
        return 0
    try:
        rules = (vault / "CLAUDE.md").read_text(encoding="utf-8-sig")
        hits = find_tagged(vault, tags)
    except OSError as err:
        print(f"SYSTEM ERROR: tag.py: cannot read the vault: {err}", file=sys.stderr)
        return 1
    print(f"vault: {vault.as_posix()}")
    print(MARKER)
    print(rules.rstrip("\n"))
    print(f"found: {'yes' if any(hits) else 'no'}")
    print("result: begin")
    print("\n".join(result_lines(tags, hits)))
    print("result: end")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
