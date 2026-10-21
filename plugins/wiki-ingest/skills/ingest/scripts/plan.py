#!/usr/bin/env python3
"""usage: plan.py --run <id>                       < rows      check the rows, print the table
       plan.py --run <id> --approve [--skip <id>] [--dest <id>=<destination>] [--link <id>=<[[Note]]>]
       plan.py --run <id> --apply <note>          frontmatter of one note, then its body to-do
       plan.py --run <id> --finish <note>         move, merge or keep one note

The ingest plan of one run, kept in the run ledger (outside the vault). The model only
proposes the rows; this script checks them, prints the table, takes the user's
corrections and applies the approved rows, so nothing unapproved is ever written.
The vault comes from vault.py (the configured vault path); <id> is the run id of select.py.

rows (stdin), one per line "note | state | change | destination", or a JSON list of
[note, state, change, destination] lists or {"note", "state", "change", "destination"} objects:
  note          filename without .md (a path from the vault root for an orphan twin)
  state         draft (a candidate of select.py), orphan (an existing note) or linked (a
                mentioned-in note of select.py, new links: only)
  change        exactly one of:
                  new links: [[A]], [[B]]       links to add (body, and related for a draft)
                  merge with: <target>[, ...]   the first target is merged into
                  actions: formatter            frontmatter to the schema, tidy structure
                  actions: new type: <type>     only for a type missing from the allowed list
                  actions: fill section: <heading> | fix link: [[X]] | add alias: <name>
                  actions: set <key>: <value>   type, topic, created, source, ... (never status)
                  actions: add <key>: <value>   tag, alias or related
                  none                          a draft with nothing to change
  destination   a folder from the vault root, or "keep, <reason>"; orphan rows always get
                "keep, orphan stays in <folder>", linked rows "keep, links only in <folder>"; a folder with a note of the same name
                becomes "keep, name clash in <folder>"; a merge source names the archive folder

checks: state, change kind, never status, a new type only when not allowed (a set type
only when allowed), the folder exists and is not 01. Inbox, every row of a note has the
same destination, a merge target exists once and is not in 01. Inbox, no name clash in
the archive folder, and (select.py all or a name) every selected draft has a row.

output (stdout):
  propose     the "## Changes to ingest" Markdown table with numbered ids, to show as is
  --approve   approved: <n> rows; skipped: <id> | <note> | <change> per skipped row;
              apply: <path> | <destination> per note, in the order to process them
  --apply     the frontmatter.py line (frontmatter: or unchanged:) when a row changes the
              frontmatter; edit: <path> | <change> per row the model does with Edit, then
              finish with --finish; without edit: lines it finishes the note itself
  --finish    the promote.py or merge.py output, or kept: <path> | <reason>
  ERROR: <message>   vault problem (path missing, no CLAUDE.md), exit 0

exit codes:
  0  done, or an ERROR line
  1  system error (read or write failed)
  2  bad usage (wrong arguments, no select.py run with this id, no plan yet)
  3  user error: rows refused (one "row <id> (<note>): <reason>" line each on stderr,
     nothing stored), an unknown id in a correction, a note changed since select.py
     read it or the plan was shown (re-read it and build a new plan), or a refused
     move or merge (from promote.py or merge.py)

example: plan.py --run 20261020-101500-1a2b --approve --skip 3 --dest "6=40. Projects"
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import require_vault  # noqa: E402

import frontmatter  # noqa: E402
import ledger  # noqa: E402
import merge  # noqa: E402
import promote  # noqa: E402
import relink  # noqa: E402
from promote import INBOX, Fail, rel_path, portable_key  # noqa: E402

ADD_KEYS = {"tag": "tags", "tags": "tags", "alias": "aliases", "aliases": "aliases", "related": "related"}
LINKS = re.compile(r"\[\[[^\]\r\n]+\]\](?:[ \t]*,[ \t]*\[\[[^\]\r\n]+\]\])*")
TARGET = re.compile(r"\[\[([^\]|#\r\n]+)[^\]\r\n]*\]\]")
BODY = ("formatter", "links", "body")  # kinds the model finishes with Edit
EXISTING = ("orphan", "linked")  # rows on a note that stays where it is


def bad(msg):
    return Fail(2, f"SYSTEM ERROR: plan.py: {msg}, see --help")


def user_error(msg):
    return Fail(3, f"USER ERROR: plan.py: {msg}")


def stem(path):
    return path.rsplit("/", 1)[-1].removesuffix(".md")


def folder_of(path):
    return path.rsplit("/", 1)[0] if "/" in path else "vault root"


def parse_change(text, allowed=None):
    """Return (kind, data) of one change, or raise ValueError with the reason.
    allowed: the allowed types to check against; None for an approved row (no type checks)."""
    if text == "none":
        return "none", None
    head, sep, rest = text.partition(":")
    rest = rest.strip(" \t")
    if not sep or not rest:
        raise ValueError("change must be new links:, merge with:, actions: or none")
    if head == "new links":
        if not LINKS.fullmatch(rest):
            raise ValueError("new links: takes [[Note]] links, comma separated")
        return "links", TARGET.findall(rest)
    if head == "merge with":
        return "merge", [n.strip(" \t[]").removesuffix(".md") for n in rest.split(",") if n.strip(" \t[]")]
    if head != "actions":
        raise ValueError("change must be new links:, merge with:, actions: or none")
    if rest == "formatter":
        return "formatter", None
    action, sep, value = rest.partition(":")
    action, value = action.strip(" \t"), value.strip(" \t")
    if not sep or not value:
        raise ValueError(f"unknown action '{rest}'")
    if action in ("fill section", "fix link"):
        return "body", None
    if action == "new type":
        if allowed is not None and value.casefold() in allowed:
            raise ValueError(f"type '{value}' is allowed already, use actions: set type: {value}")
        return "newtype", value
    if action == "add alias":
        return "add", ("aliases", value)
    verb, _, key = action.partition(" ")
    if key == "status":
        raise ValueError("ingest never sets status in a row, it follows from the destination")
    if verb == "set" and key in frontmatter.SCHEMA:
        if key == "type" and allowed is not None and value.casefold() not in allowed:
            raise ValueError(f"type '{value}' is not allowed, propose actions: new type: {value} as its own row")
        if key == "created" and not frontmatter.iso_date(value):
            raise ValueError(f"created must be a date YYYY-MM-DD, got '{value}'")
        return "set", (key, value)
    if verb == "add" and key in ADD_KEYS:
        return "add", (ADD_KEYS[key], value)
    raise ValueError(f"unknown action '{rest}', see --help")


def read_rows(text):
    """Rows from stdin as [note, state, change, destination] lists."""
    text = text.strip()
    if text.startswith("["):
        try:
            items = json.loads(text)
        except ValueError as err:
            raise bad(f"rows are no valid JSON: {err}")
        out = []
        for item in items:
            if isinstance(item, dict):
                item = [item.get(k, "") for k in ("note", "state", "change", "destination")]
            if not isinstance(item, list) or len(item) != 4:
                raise bad("each JSON row needs note, state, change and destination")
            out.append([str(v).strip() for v in item])
        return out
    out = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if not line.strip():
            continue
        if len(parts) == 5 and parts[0].isdigit():
            parts = parts[1:]  # a table row with its id
        if len(parts) < 4:
            raise bad(f"row '{line.strip()}' needs note | state | change | destination")
        out.append([parts[0], parts[1], "|".join(parts[2:-1]).strip(), parts[-1]])
    return out


def context(vault, run):
    """The facts the checks need: notes by name, the select.py candidates, allowed types."""
    try:
        rows = ledger.read_rows(run)
    except OSError as err:
        raise Fail(1, f"SYSTEM ERROR: plan.py: cannot read the run ledger: {err}")
    modes = [r[1] for r in rows if r[0] == "select" and len(r) == 2]
    if not modes:
        raise bad(f"no select.py run with id {run}, run select.py first")
    by_stem = {}
    for rel in relink.list_notes(vault):
        by_stem.setdefault(stem(rel).casefold(), []).append(rel)
    plans = [json.loads(r[1]) for r in rows if r[0] == "plan" and len(r) == 2]
    expected = {r[1]: r[2] for r in rows if r[0] == "candidate" and len(r) == 3}
    candidates = set(expected)
    if plans:
        expected.update(plans[-1].get("hashes", {}))
    for r in rows:
        if r[0] == "hash" and len(r) == 3:
            expected[r[1]] = r[2]
    return {"mode": modes[-1], "candidates": candidates, "by_stem": by_stem, "rows": rows,
            "allowed": frontmatter.allowed_types(vault), "plan": plans[-1] if plans else None,
            "expected": expected, "mentioned": {r[1] for r in rows if r[0] == "mentioned" and len(r) == 2},
            "changed": {r[1] for r in rows if r[0] == "changed" and len(r) == 2}}


def folder_problem(vault, folder):
    if "/." in f"/{folder}/":
        return "the destination leaves the vault or is a dot folder"
    if folder == INBOX or folder.startswith(INBOX + "/"):
        return f"the destination must not be {INBOX}, use keep, <reason> to leave the note there"
    if not (vault / folder).is_dir():
        return f"destination folder not found: {folder}"
    return ""


def clash(vault, folder, path):
    """A note with the same name in folder, ignoring case and Unicode form as promote.py does."""
    key = portable_key(path.rsplit("/", 1)[-1])
    return any(portable_key(e.name) == key for e in (vault / folder).iterdir())


def validate(vault, ctx, rows, cover=True):
    """Check and normalize rows (dicts with id, note, state, change, dest); return (rows, problems)."""
    problems, by_path, named = [], {}, set()

    def problem(row, reason):
        problems.append(f"row {row['id']} ({row['note']}): {reason}")

    candidates = {portable_key(c): c for c in ctx["candidates"]}
    for row in rows:
        name = row["note"].removesuffix(".md")
        row["change"] = re.sub(r"[ \t]+", " ", row["change"]).strip()
        row["dest"] = row["dest"].strip()
        draft = candidates.get(portable_key(f"{INBOX}/{name.rsplit('/', 1)[-1]}.md"))
        if row["state"] == "draft" and draft:
            named.add(draft)  # named in a row, even a refused one
        try:
            row["kind"], row["data"] = parse_change(row["change"], ctx["allowed"])
        except ValueError as err:
            problem(row, str(err))
            continue
        if row["state"] == "draft":
            path = draft
            if path is None:
                problem(row, "not a draft select.py selected in this run")
                continue
        elif row["state"] in EXISTING:
            hits = ([name + ".md"] if "/" in name and (vault / f"{name}.md").is_file()
                    else ctx["by_stem"].get(name.casefold(), []))
            if len(hits) != 1:
                problem(row, f"several notes are named {name}, give the path: {', '.join(hits)}" if hits
                        else f"no note named {name} in the vault")
                continue
            path = hits[0]
            if row["state"] == "linked":
                if path not in ctx["mentioned"] or row["kind"] != "links":
                    problem(row, "a linked row only adds new links: to a mentioned-in note of select.py")
                    continue
                row["dest"] = f"keep, links only in {folder_of(path)}"
            elif row["kind"] in ("merge", "none", "newtype"):
                problem(row, "an orphan row only adds links or changes a property")
                continue
            else:
                row["dest"] = f"keep, orphan stays in {folder_of(path)}"
        else:
            problem(row, f"state must be draft, orphan or linked, got '{row['state']}'")
            continue
        row["path"], row["note"] = path, stem(path)
        if row["dest"].startswith("keep"):
            reason = row["dest"][4:].lstrip(" ,")
            if not reason:
                problem(row, "keep needs a reason: keep, <reason>")
                continue
            row["dest"] = f"keep, {reason}"
        else:
            row["dest"] = rel_path(row["dest"]).strip("/")
            reason = folder_problem(vault, row["dest"])
            if reason:
                problem(row, reason)
                continue
        if row["kind"] == "merge":
            for target in row["data"]:
                hits = [h for h in ctx["by_stem"].get(target.casefold(), []) if h != path]
                if len(hits) != 1:
                    problem(row, f"several notes are named {target}: {', '.join(hits)}" if hits
                            else f"merge target not found: {target}")
                elif hits[0].startswith(INBOX + "/"):
                    problem(row, f"merge target {hits[0]} is in {INBOX}, ingest it first")
        by_path.setdefault(path, []).append(row)

    for path, group in by_path.items():
        if group[0]["state"] in EXISTING:
            continue
        dests = {r["dest"] for r in group}
        merges = [r for r in group if r["kind"] == "merge"]
        first = group[0]
        if len(dests) > 1:
            problem(first, "all rows of a note need the same destination, got " + "; ".join(sorted(dests)))
        elif len(merges) > 1:
            problem(first, "one merge row per note, list several targets in it")
        elif merges and first["dest"].startswith("keep"):
            problem(merges[0], "a merge row needs the archive folder as destination")
        elif merges and clash(vault, first["dest"], path):
            problem(merges[0], f"name clash: {first['dest']} has a note named {stem(path)}")
        elif not first["dest"].startswith("keep") and not merges and clash(vault, first["dest"], path):
            folder = first["dest"]
            for r in group:
                r["dest"] = f"keep, name clash in {folder}"
    if cover and ctx["mode"] != "pick":
        for path in sorted(ctx["candidates"] - named):
            problems.append(f"draft {stem(path)} has no row, give it at least: {stem(path)} | draft | none | keep, <reason>")
    return rows, problems


def cell(text):
    return str(text).replace("|", "\\|")


def table(rows):
    out = ["## Changes to ingest", "", "| id | note | state | change | destination |", "|---|---|---|---|---|"]
    out += [f"| {r['id']} | {cell(r['note'])} | {r['state']} | {cell(r['change'])} | {cell(r['dest'])} |"
            for r in rows]
    return out


def store(run, rows, approved, hashes):
    keep = ("id", "note", "path", "state", "change", "dest")
    ledger.record(run, "plan", json.dumps({"approved": approved, "hashes": hashes,
                                           "rows": [{k: r[k] for k in keep} for r in rows]}, ensure_ascii=False))


def checked(vault, ctx, rows, cover=True):
    _, problems = validate(vault, ctx, rows, cover)
    if problems:
        raise Fail(3, "USER ERROR: plan.py: rows refused, fix them and run again\n" + "\n".join(problems))
    return rows


def propose(vault, run, ctx, text):
    rows = [{"id": i, "note": n, "state": s, "change": c, "dest": d}
            for i, (n, s, c, d) in enumerate(read_rows(text), 1)]
    if not rows:
        raise bad("no rows on stdin")
    rows = checked(vault, ctx, rows)
    hashes = {}
    for r in rows:
        if r["state"] in EXISTING:
            hashes[r["path"]] = ledger.file_hash(vault / r["path"])
    store(run, rows, False, hashes)
    print("\n".join(table(rows)))


def unchanged_since_read(vault, ctx, path):
    """Refuse a note that changed after select.py read it or the plan was shown."""
    if not (vault / path).is_file():
        raise user_error(f"{path} is gone since the plan was shown, nothing written")
    # Limit: a note a script of this run rewrote (a merge relink) is trusted as is;
    # per-write hashes in the ledger if that ever hides a user edit
    if ledger.file_hash(vault / path) != ctx["expected"].get(path) and path not in ctx["changed"]:
        raise user_error(f"{path} changed since the plan was shown (edited in Obsidian or synced), "
                         "nothing written; re-read it and build a new plan")


def approve(vault, run, ctx, skips, dests, links):
    plan = ctx["plan"]
    if plan is None:
        raise bad("no plan for this run yet, propose the rows first")
    rows = plan["rows"]
    ids = {r["id"]: r for r in rows}
    for i in [*skips, *dests, *links]:
        if i not in ids:
            raise user_error(f"there is no id {i} in the plan")
    for i, dest in dests.items():
        for r in rows:
            if r["path"] == ids[i]["path"]:
                r["dest"] = dest
    for i, link in links.items():
        link = link if link.startswith("[[") else f"[[{link}]]"
        row = ids[i]
        if row["change"].startswith("new links:"):
            row["change"] += f", {link}"
        else:
            rows.append({**row, "id": max(ids) + 1, "change": f"new links: {link}"})
            ids[max(ids) + 1] = rows[-1]
    skipped = [ids[i] for i in sorted(skips)]
    for s in skipped:
        if s["change"].startswith("merge with:"):
            for r in rows:
                if r["path"] == s["path"]:
                    r["dest"] = "keep, merge skipped"
    # the stored path stands in for the name, so an orphan twin resolves again; skipped drafts
    # may have no row left
    rows = checked(vault, ctx, [dict(r, note=r["path"]) for r in rows if r["id"] not in skips], cover=False)
    for path in dict.fromkeys(r["path"] for r in rows):
        unchanged_since_read(vault, ctx, path)
    store(run, rows, True, plan.get("hashes", {}))
    print(f"approved: {len(rows)} rows")
    for s in skipped:
        print(f"skipped: {s['id']} | {s['note']} | {s['change']}")
    order = [r for r in rows if r["state"] in EXISTING] + [r for r in rows if r["state"] == "draft"]
    for path in dict.fromkeys(r["path"] for r in order):
        print(f"apply: {path} | {next(r['dest'] for r in rows if r['path'] == path)}")


def note_rows(ctx, note):
    plan = ctx["plan"]
    if plan is None or not plan["approved"]:
        raise bad("no approved plan for this run, run --approve first")
    want = rel_path(note).removesuffix(".md").casefold()
    rows = [r for r in plan["rows"] if want in (r["path"].removesuffix(".md").casefold(), r["note"].casefold())]
    if not rows:
        raise user_error(f"{note} has no approved row in this run")
    return rows


def apply(vault, run, ctx, note):
    rows = note_rows(ctx, note)
    path, orphan = rows[0]["path"], rows[0]["state"] in EXISTING
    unchanged_since_read(vault, ctx, path)
    flags, args = ["--approved"] if orphan else [], []
    for r in rows:
        kind, data = parse_change(r["change"])
        if kind == "set":
            args.append(f"{data[0]}={data[1]}")
        elif kind == "add":
            args.append(f"{data[0]}+={data[1]}")
        elif kind == "links" and not orphan:  # an orphan only gets the body link, its frontmatter stays
            args += [f"related+={t.strip()}" for t in data]
        elif kind == "newtype":
            flags.append("--new-type")
            args.append(f"type={data}")
    if args or any(r["change"] == "actions: formatter" for r in rows):
        code = frontmatter.main(["--run", run, *flags, path, *args])
        if code:
            return code
    ledger.record(run, "hash", path, ledger.file_hash(vault / path))
    ledger.record(run, "applied", path)
    edits = [r for r in rows if parse_change(r["change"])[0] in BODY]
    for r in edits:
        print(f"edit: {path} | {r['change']}")
    if edits:
        ledger.record(run, "changed", path)  # the model edits it next
        return 0
    return finish(run, rows)


def finish(run, rows):
    path, dest = rows[0]["path"], rows[0]["dest"]
    merges = [r for r in rows if r["change"].startswith("merge with:")]
    if merges:
        target = parse_change(merges[0]["change"])[1][0]
        return merge.main(["--run", run, path, target, dest])
    if dest.startswith("keep"):
        print(f"kept: {path} | {dest.removeprefix('keep, ')}")
        return 0
    return promote.main(["--run", run, path, dest, "review"])


def parse_args(argv):
    """Return (mode, note, skips, dests, links)."""
    mode, note, skips, dests, links = "propose", None, set(), {}, {}
    i = 0
    while i < len(argv):
        flag = argv[i]
        if flag == "--approve":
            mode = "approve"
            i += 1
            continue
        if flag not in ("--apply", "--finish", "--skip", "--dest", "--link") or i + 1 >= len(argv):
            raise bad(f"unexpected argument '{flag}'")
        value = argv[i + 1]
        i += 2
        if flag in ("--apply", "--finish"):
            mode, note = flag[2:], value
            continue
        if flag == "--skip":
            if not value.isdigit():
                raise bad("--skip takes an id")
            skips.add(int(value))
            continue
        m = re.fullmatch(r"([0-9]+)=(.+)", value, re.S)
        if not m or "\n" in value:
            raise bad(f"{flag} takes <id>=<value>")
        (dests if flag == "--dest" else links)[int(m.group(1))] = m.group(2).strip()
    if (skips or dests or links) and mode != "approve":
        raise bad("--skip, --dest and --link only go with --approve")
    return mode, note, skips, dests, links


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    try:
        run, argv = ledger.pop_run(argv, bad)
        if run is None:
            raise bad("--run <id> is required")
        mode, note, skips, dests, links = parse_args(argv)
        vault = require_vault()
        ctx = context(vault, run)
        if mode == "propose":
            propose(vault, run, ctx, sys.stdin.read())
        elif mode == "approve":
            approve(vault, run, ctx, skips, dests, links)
        elif mode == "apply":
            return apply(vault, run, ctx, note)
        else:
            rows = note_rows(ctx, note)
            if ["applied", rows[0]["path"]] not in ctx["rows"]:
                raise user_error(f"run --apply {rows[0]['path']} first")
            return finish(run, rows)
    except (Fail, relink.Fail) as fail:
        print(fail, file=sys.stderr)
        return fail.code
    except OSError as err:
        print(f"SYSTEM ERROR: plan.py: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(main(sys.argv[1:]))
