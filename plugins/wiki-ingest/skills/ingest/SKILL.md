---
name: ingest
description: Processes draft notes in the Obsidian vault Inbox (01. Inbox) after an approved plan - fixes frontmatter, adds links, picks a destination folder or merge, moves them out of the Inbox and sets status review. Use when the user asks to process, ingest or sort their inbox or a draft note in their vault.
argument-hint: "[all | note name]"
allowed-tools: Bash(bash "${CLAUDE_SKILL_DIR}/scripts/*)
---

# wiki-ingest:ingest

Arguments: `$ARGUMENTS`

What ingest may change: only notes with `status: draft` inside `01. Inbox` (edit them, move them out, set `status: review`), plus link rows and merges the user approved in the plan. Never delete a note, never set `evergreen`, never archive an orphan.

Scripts: deterministic work runs in the scripts below; you only do the judgment (plan, content edits, summary). Every script has `--help`. Exit codes for every script: 0 done; 1 or 2 is a system error or a wrong call (`SYSTEM ERROR:` on stderr): fix the call once with `--help`, and if it still fails report the error line and stop; 3 is a user error (`USER ERROR:` on stderr): do not retry, handle it as the step says.

## 1. Vault path and vault rules

!`bash "${CLAUDE_SKILL_DIR}/scripts/context.sh"`

- The output above starts with `ERROR:`: reply with the text after `ERROR: ` exactly as it is, and stop.
- Otherwise `vault:` is the vault path, and the text after `----- vault CLAUDE.md -----` is the vault `CLAUDE.md`. Read it now and follow it: folders, frontmatter schema, allowed `type` values, merge and archive rules, never delete, keep the filename when moving, English without em dashes. If it says to read another file first (for example `Home.md`), read that too.

Never ask for the vault path and never write it; only `wiki-vault` does that.

## 2. Lint the whole vault first

Invoke the skill `wiki-lint:lint` by name with no arguments (never call a lint script by path). This moves stray drafts into the Inbox before ingest selects notes. If lint stops with an error instead of a result (a usage, `SYSTEM ERROR:` or `USER ERROR:` line), show it and stop.

Show nothing of lint's result to the user at this point: no summary, no list of fixes or findings. Its data only feeds the plan. Keep from its result:

- `orphans`: candidates for orphan rows in the plan. Only this full run gives orphans; the `--files` run in step 6 does not.
- `findings` for the selected drafts (for example `frontmatter-missing`, `frontmatter-invalid`, `empty-section`, `ambiguous-link`): turn them into plan rows.
- `placeholderLinks`: never touch these links.
- `movedToInbox` and `removedDeadLinks`: keep them for the summary in step 7.

## 3. Select the notes

Run, with `all`, the note name from the arguments, or nothing when there is no argument:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/select.sh" --vault "<vault>" ["all" | "<note name>"]
```

It prints `candidate:` lines (drafts directly in `01. Inbox`), `candidates: <n>`, then one `note:` line per other note with its `status`, `aliases` and `title` (only when it differs from the filename). A `same name:` part on a candidate lists other notes with the same filename. An `index:` line means the vault is too big to list every note; search the vault for link targets beyond the list.

- **No argument:** list every candidate, one path from the vault root per line in backticks, and ask which one to process. Continue with the chosen note. `candidates: 0`: say there are no drafts in the Inbox and go to step 8.
- **`all`:** every candidate. `candidates: 0`: say so and go to step 8.
- **A note name:** the one candidate printed. Exit 3 means the note is not a `draft` in `01. Inbox` or does not exist: tell the user the error text (it names the status and folder) and stop.

## 4. Build the plan

For each selected note, read it and work out the rows below. Use the `note:` lines from step 3 as the index of existing notes (filenames, titles, aliases, status); search note bodies only when you need their content to judge relevance.

- **Frontmatter:** fix it to the schema in the vault `CLAUDE.md` (`type`, `topic`, `aliases`, `tags`, `created`, `related`, `source`). A `type` that is not in the allowed list gets its own `new type:` row, never used silently.
- **Structure:** tidy headings and layout; keep the content and meaning.
- **Links:** add `[[Note]]` links (shortest form) to existing notes from the index, and fill `related`.
- **Orphans:** for each note in lint's `orphans` list that is really related to this draft, add a separate plan row with a link from the draft to the orphan or from the orphan to the draft. Unrelated orphans stay as they are.
- **Destination:** the folder from the vault `CLAUDE.md` that fits (`20. Customers`, `30. Knowledge`, `40. Projects`, ...), or a merge into an existing note. If no folder fits the note content, the destination is `keep, <reason>`.
- **Name clash:** if the candidate's `same name:` list has a note in the destination folder, do not plan a move there; the destination becomes `keep, name clash in <folder>`.

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
- **destination:** a folder path, or `keep, <reason>`. Status is never a row, it follows from the destination: a folder means `status: review`, `keep` means the note stays `draft` in `01. Inbox` (its other approved rows are still applied). A merge source goes to the archive folder of the vault `CLAUDE.md` (`99. Archived` by default) with `status: archived`, through step 5 item 4 only. A name clash in the target folder gives `keep, name clash in <folder>`. An orphan always gets `keep, orphan stays in <folder>`.

Wait for one reply. It is either an OK, or an OK with changes per id (for example "id 3 skip", "id 6 to 40. Projects", "id 2 also [[X]]"). Apply those changes to the plan and go straight to step 5: do not show the table again and do not ask again. Approving the table is the explicit OK for each merge row, because the row names both the source (`note`) and the target (`merge with:`). A reply that does not approve means no change at all.

## 5. Apply, one note at a time

Finish each note completely before starting the next, without asking the user anything:

1. Edit the note with its approved rows. Never edit the `status` line yourself; the script sets it.
2. Folder destination only, and not a merge source (a merge source is archived in item 4; a `keep` note stays `draft` in `01. Inbox`, no call):

   ```bash
   bash "${CLAUDE_SKILL_DIR}/scripts/promote.sh" --vault "<vault>" "01. Inbox/<name>.md" "<folder>" review
   ```

   It moves the note with its filename unchanged and sets `status: review`, then prints `path:` (after the move) and `status:`. Exit 3 (for example a name clash found now): nothing moved and the note stays `draft` in `01. Inbox`; note the error for step 7 and continue.
3. Apply the approved orphan rows for this note.
4. For an approved merge, in this order (with several targets, links go to the first one):
   1. Add the source's content to the target and the source's title to the target's `aliases` (Edit).
   2. Change links to the source into links to the target, in every note: `bash "${CLAUDE_SKILL_DIR}/scripts/relink.sh" --vault "<vault>" "01. Inbox/<source name>.md" "<target name>"`. It prints one `changed:` line per rewritten note, and `skipped-ambiguous: <n>` when bare links were left alone because several notes share the source's filename; list those under "Still to consider" in step 7.
   3. Archive the source, never delete it: `bash "${CLAUDE_SKILL_DIR}/scripts/promote.sh" --vault "<vault>" "01. Inbox/<source name>.md" "<archive folder>" archived`.
   4. Set the target to review in place: `bash "${CLAUDE_SKILL_DIR}/scripts/promote.sh" --vault "<vault>" "<target path>" "<target folder>" review`.

   Exit 3 in any of these steps: stop this merge (do not run the next merge steps), leave the source where it is, and report the error text in step 7.

Keep a list of every changed note by its path after the move: `path:` lines, `changed:` lines and the orphans you edited. A `changed:` note that was moved later in this step is listed by its new `path:`.

## 6. Lint the changed notes

Invoke `wiki-lint:lint --files "<path 1>" "<path 2>" ...` with every note changed in step 5 (drafts, orphans that got a link, notes relinked, merge targets and archived sources), paths from the vault root after the move, each one quoted. Lint runs straight away and checks stray draft, frontmatter, outgoing dead links, ambiguous links and empty sections for those notes. Skip this step when nothing changed.

## 7. Summary of what is left

Short and scannable: a point list or a small table per group, no prose story. Skip empty groups.

- **Lint fixed:** `movedToInbox` (`from` to `to`) and `removedDeadLinks` (`path:line` and the original link) from both lint runs.
- **Still to consider:** step 6 `findings` as a table `category | note | detail`, plus skipped ids, drafts kept in the Inbox with their reason, and moves that failed with exit 3 (with the error text).

Ingest fixes nothing more itself; any further fix is a new ingest run.

## 8. Final list

Always end with the notes that went from `draft` to `review` (the `path:` of each successful `promote.sh ... review` call for a draft), one path from the vault root per line in backticks. The backticks stop Markdown from reading a folder number like `30.` as a numbered list:

```
Moved from draft to review:
- `30. Knowledge/Context Engineering.md`
- `20. Customers/RBH.md`
```

When nothing changed: `No notes moved from draft to review.`
