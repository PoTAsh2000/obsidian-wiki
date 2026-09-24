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

Invoke the skill `wiki-lint:lint` by name with no arguments (never call a lint script by path). This moves stray drafts into the Inbox before ingest selects notes. If lint reports a usage error (exit code 2), show it and stop. Keep from its result:

- `orphans`: candidates for link rows in the plan. Only this full run gives orphans; the `--files` run in step 7 does not.
- `findings` for the selected drafts (for example `frontmatter-missing`, `frontmatter-invalid`, `empty-section`): take them into the plan.
- `placeholderLinks`: never touch these links.
- `movedToInbox` and `removedDeadLinks`: mention them briefly to the user, as lint's own fixes.

## 4. Select the notes

A note is a candidate only when it is inside `01. Inbox` (not in a subfolder) and its frontmatter has `status: draft`. Notes with another status or no `status` are skipped.

- **No argument:** list every candidate, one path from the vault root per line, and ask which one to process. Continue with the chosen note. No candidates: say so and go to step 9.
- **`all`:** every candidate.
- **A note name:** the candidate whose filename (without `.md`) matches, case-insensitive. If the note exists but is not a `draft` in `01. Inbox`, stop and say which status and folder it has. Not found at all: say so and stop.

## 5. Build the plan

For each selected note, read it and work out:

- **Frontmatter:** fix it to the schema in the vault `CLAUDE.md` (`type`, `topic`, `aliases`, `tags`, `created`, `related`, `source`). The final `status` is `review`. A `type` that is not in the allowed list is proposed to the user as a new value, never used silently.
- **Structure:** tidy headings and layout; keep the content and meaning.
- **Links:** add `[[Note]]` links (shortest form) to existing notes found by searching filenames, titles and aliases, and fill `related`.
- **Orphans:** for each note in lint's `orphans` list that is really related to this draft, add a separate plan row with a link from the draft to the orphan or from the orphan to the draft. Unrelated orphans stay as they are.
- **Destination:** the folder from the vault `CLAUDE.md` that fits (`20. Customers`, `30. Knowledge`, `40. Projects`, ...), or a merge into an existing note. If the destination is unclear, the note stays in `01. Inbox` as `draft`; say why.
- **Name clash:** if a note with the same filename already exists in the destination, do not plan a move there; mark the row and ask the user.

Show one plan table and stop:

| # | Note | Action | Changes | Destination |
|---|---|---|---|---|
| 1 | 01. Inbox/Tokens.md | move | frontmatter, 3 links, status review | 30. Knowledge/Tokens.md |
| 2 | 30. Knowledge/Context Window.md | link (orphan) | add `[[Tokens]]` under Related | stays |
| 3 | 01. Inbox/ACE notes.md | merge | into `30. Knowledge/ACE.md` | 99. Archived/ACE notes.md |
| 4 | 01. Inbox/Idea.md | keep | none, destination unclear: ... | stays in Inbox as draft |

Wait for the user's OK. Apply only the rows they approved; they may approve some rows and not others. A merge row needs an explicit OK that names both the source and the target note, per the vault `CLAUDE.md`. Anything not in the approved rows needs a new plan.

## 6. Apply, one note at a time

Finish each note completely before starting the next:

1. Edit the note: frontmatter, structure, links, `status: review`.
2. Move it with its filename unchanged: `mv -n "<vault>/01. Inbox/<name>.md" "<vault>/<folder>/<name>.md"`. If the target exists, do not move; stop and ask.
3. Apply the approved orphan link rows for this note.
4. For an approved merge: add the source's content to the target, add the source's title to the target's `aliases`, change links to the source into links to the target, set the source to `status: archived` and move it to `99. Archived` with its filename unchanged. The target gets `status: review`; the source is never deleted.

Keep a list of every changed note by its path after the move.

## 7. Lint the changed notes

Invoke `wiki-lint:lint --files "<path 1>" "<path 2>" ...` with every note changed in step 6 (drafts, orphans that got a link, merge targets and archived sources), paths from the vault root after the move, each one quoted. Lint runs straight away and checks stray draft, frontmatter, outgoing dead links, ambiguous links and empty sections for those notes. Skip this step when nothing changed.

## 8. Report lint's result

Tell the user what lint fixed (`movedToInbox`, `removedDeadLinks`) and what it found (`findings`), by impact. Ingest fixes nothing more itself; any further fix is a new plan the user approves.

## 9. Final list

Always end with the notes that went from `draft` to `review`, one path from the vault root per line, using the path after the move:

```
Moved from draft to review:
- 30. Knowledge/Context Engineering.md
- 20. Customers/RBH.md
```

When nothing changed: `No notes moved from draft to review.`
