#!/usr/bin/env python3
"""usage: cite.py <link>...

Check the wikilinks an answer cites against the configured Obsidian vault. Read-only.
Each argument is one or more [[Note]], [[Note#Heading]] or [[Note|alias]] links, or a
bare target. Links resolve like search.py: case-insensitive filename or path suffix,
shortest path wins; headings are compared case-insensitively, ^block ids by line end.

output, only for links that are not ok (nothing when all are ok):
  ERROR: <message>                    vault problem, exit 0
  unresolved: [[...]] -> [[fix]]      no note has that name; fix is the closest name, if any
  ambiguous: [[...]] -> [[a]] or [[b]]  several notes share that name; pick the one meant
  heading: [[...]] -> [[fix]]         the note has no such heading; fix is the closest
                                      heading, or "no such heading in <path>"

exit codes:
  0  all links ok
  1  findings printed
  2  bad usage (no link given)
  3  system error (cannot read a note)

example: cite.py "[[Context Engineering#Rules]]" "[[Tokens]]"
"""

import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from search import find_notes, headings, parse_note, read_lines, stem, unique_links  # noqa: E402
from vault import require_vault  # noqa: E402  (search.py put it on the path)

LINK = re.compile(r"\[\[([^\[\]]*)\]\]")


def norm(text):
    return " ".join(text.split()).lower()


def check(target, notes, links, cache):
    """Return the finding line for one link target, or None when it is ok."""
    name, *anchors = target.split("|")[0].split("#")
    shown = f"[[{target}]]"
    want = stem(name.strip().strip("/")).lower()
    hits = [p for p in notes if stem(p).lower() == want or stem(p).lower().endswith("/" + want)]
    suffix = "".join("#" + a for a in anchors)
    if not hits:
        names = {stem(p).split("/")[-1].lower(): p for p in notes}
        close = difflib.get_close_matches(want.split("/")[-1], sorted(names), 1)
        fix = f" -> {links[names[close[0]]][:-2]}{suffix}]]" if close else ""
        return f"unresolved: {shown}{fix}"
    if len(hits) > 1:
        return f"ambiguous: {shown} -> " + " or ".join(
            f"{links[p][:-2]}{suffix}]]" for p in sorted(hits))
    path = hits[0]
    if path not in cache:
        lines = read_lines(notes[path])
        cache[path] = (lines, [text for _, _, text in headings(lines, parse_note(lines)[4])])
    lines, heads = cache[path]
    known = {norm(h): h for h in heads}
    for anchor in (a.strip() for a in anchors):
        if anchor.startswith("^"):
            if not any(line.rstrip().endswith(anchor) for line in lines):
                return f"heading: {shown} -> no such block {anchor} in {path}"
        elif norm(anchor) not in known:
            close = difflib.get_close_matches(norm(anchor), sorted(known), 1)
            fix = f"{links[path][:-2]}#{known[close[0]]}]]" if close else \
                f"no such heading in {path}"
            return f"heading: {shown} -> {fix}"
    return None


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    targets = [t.strip() for arg in argv for t in (LINK.findall(arg) or [arg]) if t.strip()]
    if not targets:
        print("SYSTEM ERROR: cite.py: no link given, see --help", file=sys.stderr)
        return 2
    root = require_vault()
    notes = {path: file for path, file, _ in find_notes(root)}
    links, cache, found = unique_links(notes), {}, 0
    for target in dict.fromkeys(targets):
        try:
            line = check(target, notes, links, cache)
        except OSError as err:
            print(f"SYSTEM ERROR: cite.py: cannot read a note: {err}", file=sys.stderr)
            return 3
        if line:
            print(line)
            found = 1
    return found


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
