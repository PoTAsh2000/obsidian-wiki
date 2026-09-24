---
name: ingest
description: Processes draft notes in the Obsidian vault Inbox (01. Inbox) after an approved plan - fixes frontmatter, adds links, picks a destination folder or merge, moves them out of the Inbox and sets status review. Use when the user asks to process, ingest or sort their inbox or a draft note in their vault.
argument-hint: "[all | note name]"
---

# wiki-ingest:ingest

Arguments: `$ARGUMENTS`

What ingest may change: only notes with `status: draft` inside `01. Inbox` (edit them, move them out, set `status: review`), plus link rows and merges the user approved in the plan. Never delete a note, never set `evergreen`, never archive an orphan.

## 1. Vault path

Resolve the vault folder in this order, and stop at the first one that is set:

1. The plugin option set at install: `${user_config.vault_path}`. It counts as set only when it shows a real path here, not an empty value or the literal placeholder.
2. `OBSIDIAN_VAULT` in the `env` object of `~/.claude/settings.json` (read the file).
3. Neither is set: ask the user once for the vault path. Show the exact change (`"env": { "OBSIDIAN_VAULT": "<path>" }` added to `~/.claude/settings.json`, keeping everything else) and write it only after their OK. Without an OK, use the path for this run only.

The path is valid when it contains `CLAUDE.md`. If not, say so and ask again.

## 2. Read the vault rules

Read `CLAUDE.md` in the vault root and follow it: folders, frontmatter schema, allowed `type` values, merge rules, never delete, keep the filename when moving, English without em dashes.

## 3. Lint the whole vault first

Invoke the skill `wiki-lint:lint` by name with no arguments (never call a lint script by path). This moves stray drafts into the Inbox before ingest selects notes. If lint reports a usage error (exit code 2), show it and stop.

Show nothing of lint's result to the user at this point: no summary, no list of fixes or findings. Its data only feeds the plan. Keep from its result:

- `orphans`: candidates for orphan rows in the plan. Only this full run gives orphans; the `--files` run in step 7 does not.
- `findings` for the selected drafts (for example `frontmatter-missing`, `frontmatter-invalid`, `empty-section`, `ambiguous-link`): turn them into plan rows.
- `placeholderLinks`: never touch these links.
- `movedToInbox` and `removedDeadLinks`: keep them for the summary in step 8.

## 4. Select the notes

A note is a candidate only when it is inside `01. Inbox` (not in a subfolder) and its frontmatter has `status: draft`. Notes with another status or no `status` are skipped.

- **No argument:** list every candidate, one path from the vault root per line, and ask which one to process. Continue with the chosen note. No candidates: say so and go to step 9.
- **`all`:** every candidate.
- **A note name:** the candidate whose filename (without `.md`) matches, case-insensitive. If the note exists but is not a `draft` in `01. Inbox`, stop and say which status and folder it has. Not found at all: say so and stop.

## 5. Build the plan

For each selected note, read it and work out:

- **Frontmatter:** fix it to the schema in the vault `CLAUDE.md` (`type`, `topic`, `aliases`, `tags`, `created`, `related`, `source`). A `type` that is not in the allowed list gets its own `new type:` row, never used silently.
- **Structure:** tidy headings and layout; keep the content and meaning.
- **Links:** add `[[Note]]` links (shortest form) to existing notes found by searching filenames, titles and aliases, and fill `related`.
- **Orphans:** for each note in lint's `orphans` list that is really related to this draft, add a separate plan row with a link from the draft to the orphan or from the orphan to the draft. Unrelated orphans stay as they are.
- **Destination:** the folder from the vault `CLAUDE.md` that fits (`20. Customers`, `30. Knowledge`, `40. Projects`, ...), or a merge into an existing note. If no folder fits the note content, the destination is `keep, <reason>`.
- **Name clash:** if a note with the same filename already exists in the destination, do not plan a move there; the destination becomes `keep, name clash in <folder>`.

Show only this, with no text before it and at most one line after it asking for approval:

## Changes to ingest

| id | note | state | change | destination |
|---|---|---|---|---|
| 1 | Tokens | draft | actions: formatter | 30. Knowledge |
| 2 | Tokens | draft | new links: [[Context Window]], [[LLM]] | 30. Knowledge |
| 3 | Tokens | draft | actions: new type: concept | 30. Knowledge |
| 4 | Context Window | orphan | new links: [[Tokens]] | keep, orphan stays in 30. Knowledge |
| 5 | ACE notes | draft | merge with: ACE | 99. Archived |
| 6 | Idea | draft | actions: formatter | keep, no relevant target found based on note content |

Table rules:

- **id:** an incrementing number per row, so the user can say "id 3: do this instead".
- **note:** the filename without `.md` and without folder.
- **state:** `draft` or `orphan`, nothing else. List an orphan only when ingest really changes it; orphans that stay orphan are not in the table.
- **change:** exactly one change per row. A note with several changes gets several rows, with note and destination repeated. Allowed changes:
  - `new links:` the `[[Note]]` links to add, comma separated.
  - `merge with:` one or more target notes, comma separated.
  - `actions:` one of `formatter` (frontmatter to the schema and tidy structure), `new type: <value>` (a `type` not in the allowed list), `fill section: <heading>` (an empty section), `fix link: [[X]]` (an ambiguous link rewritten to path form), `add alias: <name>`, or any other frontmatter property change such as `set topic: <value>`, `add tag: <tag>` or `set source: <value>`. Never `status`.
  - `none` when a draft has nothing to change; it still gets one row.
- **destination:** a folder path, or `keep, <reason>`. Status is never a row, it follows from the destination: a folder means `status: review`, `keep` means the note stays `draft` in `01. Inbox` (its other approved rows are still applied). A merge source goes to `99. Archived`. A name clash in the target folder gives `keep, name clash in <folder>`. An orphan always gets `keep, orphan stays in <folder>`.

Wait for one reply. It is either an OK, or an OK with changes per id (for example "id 3 skip", "id 6 to 40. Projects", "id 2 also [[X]]"). Apply those changes to the plan and go straight to step 6: do not show the table again and do not ask again. Approving the table is the explicit OK for each merge row, because the row names both the source (`note`) and the target (`merge with:`). A reply that does not approve means no change at all.

## 6. Apply, one note at a time

Finish each note completely before starting the next, without asking the user anything:

1. Edit the note with its approved rows. Set `status: review` only when it has a folder destination; a `keep` note stays `draft`.
2. Move it with its filename unchanged: `mv -n "<vault>/01. Inbox/<name>.md" "<vault>/<folder>/<name>.md"`. If the target exists, do not move: set the note back to `status: draft`, leave it in `01. Inbox` and note it for step 8.
3. Apply the approved orphan rows for this note.
4. For an approved merge: add the source's content to the target, add the source's title to the target's `aliases`, change links to the source into links to the target, set the source to `status: archived` and move it to `99. Archived` with its filename unchanged. The target gets `status: review`; the source is never deleted.

Keep a list of every changed note by its path after the move.

## 7. Lint the changed notes

Invoke `wiki-lint:lint --files "<path 1>" "<path 2>" ...` with every note changed in step 6 (drafts, orphans that got a link, merge targets and archived sources), paths from the vault root after the move, each one quoted. Lint runs straight away and checks stray draft, frontmatter, outgoing dead links, ambiguous links and empty sections for those notes. Skip this step when nothing changed.

## 8. Summary of what is left

Short and scannable: a point list or a small table per group, no prose story. Skip empty groups.

- **Lint fixed:** `movedToInbox` (`from` to `to`) and `removedDeadLinks` (`path:line` and the original link) from both lint runs.
- **Still to consider:** step 7 `findings` as a table `category | note | detail`, plus skipped ids, drafts kept in the Inbox with their reason, and moves that failed on a name clash.

Ingest fixes nothing more itself; any further fix is a new ingest run.

## 9. Final list

Always end with the notes that went from `draft` to `review`, one path from the vault root per line, using the path after the move:

```
Moved from draft to review:
- 30. Knowledge/Context Engineering.md
- 20. Customers/RBH.md
```

When nothing changed: `No notes moved from draft to review.`
