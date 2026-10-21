#!/usr/bin/env python3
"""usage: merge.py [--run <id>] <source note> <target name> <archive folder>

The mechanical steps of one approved merge, in one call. Before writing anything
it checks: the target exists and its filename is unique, the source is a draft
directly in "01. Inbox" (or already archived by an earlier run), the archive
folder exists and has no note with the source's name. Then, in this order:
  1. add the source's filename and title to the target's aliases (no duplicates)
  2. rewrite links to the source into links to the target (as relink.py)
  3. move the source to <archive folder> with status archived (as promote.py)
  4. set the target to status review, unless it is evergreen
Safe to rerun: steps already done are found and skipped. Never deletes.
The model merges the body content itself, after this call, from the archived source.
--run <id> (from select.py) records every change, or the refusal, in the run ledger.
The vault comes from vault.py (the configured vault path).

arguments:
  <source note>     merge source path from the vault root, e.g. "01. Inbox/ACE notes.md"
  <target name>     merge target filename without .md, e.g. "ACE"
  <archive folder>  archive folder from the vault root, e.g. "99. Archived"

output (stdout):
  evergreen-target: <path>   first, before any write: the target stays evergreen,
                             so the merged content is not reviewed; the model reports it
  changed: <path>            one line per note rewritten (relinks and the target's aliases)
  links: <n>                 links rewritten (0 on a rerun)
  skipped-ambiguous: <n>     bare links left alone, several notes have the source's filename
  archived: <path>           the source after the move
  target-status: <status>    the target's status now
  ERROR: <message>           vault problem (path missing, no CLAUDE.md), exit 0

exit codes:
  0  done (also on a rerun with nothing left to do), or an ERROR line
  1  system error (read, write or move failed)
  2  bad usage (wrong arguments)
  3  user error (target missing, ambiguous or in 01. Inbox, source not a draft in 01. Inbox,
     archive folder missing, name clash in it); nothing written

example: merge.py "01. Inbox/ACE notes.md" "ACE" "99. Archived"
"""

import json
import re
import sys
from pathlib import Path

import ledger
import promote
import relink
from promote import INBOX, DASHES, Fail, fm_status, read_text, set_status, split_lines
from vault import require_vault

SAFE = re.compile(r"[\w][\w .()&'-]*")
KEY = re.compile(r"^([A-Za-z_]+):[ \t]*(.*)$")
ITEM = re.compile(r"^([ \t]*)-[ \t]*(.*)$")


def bad(msg):
    return Fail(2, f"SYSTEM ERROR: merge.py: {msg}, see --help")


def user_error(msg):
    return Fail(3, f"USER ERROR: merge.py: {msg}")


def unquote(value):
    return re.sub(r"^[\"']|[\"']$", "", value.strip(" \t"))


def quote(value):
    return value if SAFE.fullmatch(value) else json.dumps(value, ensure_ascii=False)


def title_of(text):
    """The first # heading outside the frontmatter and code, empty when there is none."""
    in_fm = in_fence = False
    for number, line in enumerate(split_lines(text), 1):
        line = line.removesuffix("\r")
        if number == 1 and DASHES.match(line.removeprefix("﻿")):
            in_fm = True
        elif in_fm:
            in_fm = not DASHES.match(line)
        elif relink.FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and line.startswith("# "):
            return unquote(line[2:])
    return ""


def with_aliases(text, names):
    """Return text with names added to the frontmatter aliases as a YAML list, or None
    when nothing is added. A flow list [a, b] stays a flow list."""
    lines = split_lines(text)
    if not lines or not DASHES.match(lines[0].removesuffix("\r").removeprefix("﻿")):
        return None
    cr = "\r" if lines[0].endswith("\r") else ""
    end = next((i for i in range(1, len(lines)) if DASHES.match(lines[i].removesuffix("\r"))), None)
    if end is None:
        return None
    key_at = next((i for i in range(1, end) if lines[i].startswith("aliases:")), None)
    have, items_end, indent, flow = [], None, "  ", None
    if key_at is not None:
        value = KEY.match(lines[key_at].removesuffix("\r")).group(2).strip(" \t")
        if value.startswith("[") and value.endswith("]"):
            flow = value
            have = [unquote(v) for v in value[1:-1].split(",") if unquote(v)]
        elif value:
            have = [unquote(value)]
        items_end = key_at + 1
        while items_end < end and ITEM.match(lines[items_end].removesuffix("\r")):
            m = ITEM.match(lines[items_end].removesuffix("\r"))
            indent = m.group(1)
            have.append(unquote(m.group(2)))
            items_end += 1
    known = {h.casefold() for h in have}
    add = []
    for name in names:
        if name and name.casefold() not in known:
            known.add(name.casefold())
            add.append(name)
    if not add:
        return None
    if flow is not None and have:
        lines[key_at] = f"aliases: [{flow[1:-1].rstrip()}, {', '.join(quote(a) for a in add)}]{cr}"
    elif key_at is None:
        lines[end:end] = [f"aliases:{cr}"] + [f"{indent}- {quote(a)}{cr}" for a in add]
    elif items_end > key_at + 1:
        lines[items_end:items_end] = [f"{indent}- {quote(a)}{cr}" for a in add]
    else:  # aliases: [] or one plain value: becomes a YAML list
        lines[key_at:items_end] = [f"aliases:{cr}"] + [f"{indent}- {quote(a)}{cr}" for a in have + add]
    return "".join(line + "\n" for line in lines)


def parse_args(argv):
    if len(argv) != 3:
        raise bad("expected <source note> <target name> <archive folder>")
    source = promote.rel_path(argv[0])
    target = argv[1].removesuffix(".md").rsplit("/", 1)[-1]
    archive = promote.rel_path(argv[2]).removesuffix("/")
    if "/." in f"/{source}/{archive}/" or not archive or not target:
        raise bad("empty name, or a path that leaves the vault or enters a dot folder")
    if not re.fullmatch(re.escape(INBOX) + r"/[^/]+\.md", source):
        raise bad(f"source must be a note directly in {INBOX}")
    if any(c in target for c in "[]|#"):
        raise bad("target must not contain [ ] | #")
    return source, target, archive


def merge(vault, source, target, archive, run=None):
    name = source.rsplit("/", 1)[-1]
    old = name.removesuffix(".md")
    if old.casefold() == target.casefold():
        raise bad("source and target have the same name")
    archived = f"{archive}/{name}"

    # Every check first, so a refused merge writes nothing.
    notes = relink.list_notes(vault)
    hits = [n for n in notes if relink.stem(n).casefold() == target.casefold() and n not in (source, archived)]
    if not hits:
        raise user_error(f'no note named "{target}" in the vault, create or pick the merge target first')
    if len(hits) > 1:
        raise user_error(f'several notes are named "{target}": {", ".join(hits)}; rename one before merging')
    target_path = hits[0]
    if target_path.rsplit("/", 1)[0] == INBOX:
        raise user_error(f"target {target_path} is in {INBOX}, ingest it before merging into it")
    promote.check_portable(vault, archived)
    if (vault / source).is_file():
        status = fm_status(vault / source)
        if status != "draft":
            raise user_error(f"{source} has {promote.status_words(status)}, only a draft is merged")
        promote.check_move(vault, source, archive)
        source_now = source
    elif (vault / archived).is_file() and fm_status(vault / archived) in ("draft", "archived"):
        source_now = archived  # an earlier run already moved the source
    else:
        raise user_error(f"merge source not found: {source}")
    target_status = fm_status(vault / target_path)
    if target_status == "evergreen":
        print(f"evergreen-target: {target_path}")

    # 1. aliases
    changed = set()
    before = read_text(vault / target_path)
    text = with_aliases(before, [old, title_of(read_text(vault / source_now))])
    if text is not None:
        relink.write_note(vault / target_path, target_path, text, before)
        changed.add(target_path)
    # 2. links
    twins = sum(relink.stem(n).casefold() == old.casefold() for n in notes)
    relinker = relink.Relinker(old, source.removesuffix(".md"), target, ambiguous=twins > 1,
                               new_path=target_path)
    total = 0
    for rel in notes:
        before = read_text(vault / rel)
        if not relinker.might_link(before):
            continue
        body, count = relinker.rewrite(before, rel)
        if count:
            relink.write_note(vault / rel, rel, body, before)
            changed.add(archived if rel == source else rel)
            total += count
    for rel in sorted(changed):
        ledger.record(run, "changed", rel if rel != archived else source_now)
        print(f"changed: {rel}")
    print(f"links: {total}")
    if relinker.skipped:
        print(f"skipped-ambiguous: {relinker.skipped}")
    # 3. archive
    if source_now == source:
        promote.move(vault, source, archived)
    if fm_status(vault / archived) != "archived":
        set_status(vault, archived, "archived")
    ledger.record(run, "moved", source, archived)
    ledger.record(run, "status", archived, "archived")
    print(f"archived: {archived}")
    # 4. target status
    if target_status not in ("evergreen", "review"):
        set_status(vault, target_path, "review")
    ledger.record(run, "status", target_path, fm_status(vault / target_path))
    print(f"target-status: {fm_status(vault / target_path)}")


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    run = None
    try:
        run, argv = ledger.pop_run(argv, bad)
        source, target, archive = parse_args(argv)
        merge(require_vault(), source, target, archive, run)
    except (Fail, relink.Fail) as fail:
        message = str(fail).replace("promote.py:", "merge.py:").replace("relink.py:", "merge.py:")
        if fail.code == 3:
            ledger.record(run, "failed", promote.rel_path(argv[0]), message)
        print(message, file=sys.stderr)
        return fail.code
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(main(sys.argv[1:]))
