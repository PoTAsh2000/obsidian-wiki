# wiki-ingest

Turns the drafts in your Inbox into filed, linked notes. Claude proposes a plan per draft (frontmatter, links, destination folder or merge), and only after your OK it moves the note out of `01. Inbox` and sets `status: review`. When you have reviewed the filed notes, one command approves them as `evergreen`.

Installing wiki-ingest also installs `wiki-lint`, which it runs before and after filing notes.

## Skills

### `/wiki-ingest:ingest [all | note name]`

Processes `draft` notes in `01. Inbox`. It first lints the whole vault, then shows one plan table with a row per change. You approve it, or approve with changes per row id ("id 3 skip"). Then it edits, moves or merges each note, lints the changed notes and ends with the notes that moved from `draft` to `review`. It never deletes a note. Normal language works too: "process my inbox".

- `/wiki-ingest:ingest` (lists the drafts and asks which one)
- `/wiki-ingest:ingest all` (the 10 oldest drafts per run)
- `/wiki-ingest:ingest Tokens`

### `/wiki-ingest:apply [note name]`

Marks reviewed notes as `evergreen`. Typing the command is your approval, so it only runs when you type it, never from normal language or another skill. It only changes the line `status: review`; no moves, no other edits.

- `/wiki-ingest:apply` (every `review` note in the vault)
- `/wiki-ingest:apply Context Engineering`
- `/wiki-ingest:apply "30. Knowledge/Twin.md"` (pick one of several notes with the same name)

## Vault

Every skill of this plugin first runs `vault.py`, which prints the configured vault path and the vault `CLAUDE.md`. Claude follows those rules for the rest of the skill. The scripts get the vault from `vault.py` as well, so none of them takes a vault option. A vault problem (no path configured, or no `CLAUDE.md` in the vault) is always one `ERROR: <message>` line: Claude relays it and stops.

## Scripts

### vault.py

Shared vault reader, the same file in every obsidian-wiki plugin at `plugins/<plugin>/scripts/vault.py`. Read-only. Every skill except wiki-vault runs it as its first step. The other scripts of the skills import it to get the vault, and the wiki-vault scripts use it to find, read and clean the stored path.

* Find the vault path file `~/.claude/obsidian-wiki/vault-path`
  * `HOME` is set: use it before the OS home folder
* Read the vault path from the first line
  * File missing or empty: print `ERROR:` with a hint to run `/wiki-vault:add`
  * Git Bash path like `/c/Users/...` on Windows: turn it into `C:/Users/...`
* Check that the vault has a `CLAUDE.md`
  * Missing: print `ERROR:` with a hint to run `/wiki-vault:overwrite`
* Print the vault path and the vault `CLAUDE.md`
  * `--path`: print only the vault path
  * `CLAUDE.md` cannot be read: stop with a system error

An `ERROR:` line always ends with exit 0, also in the scripts that import vault.py, so Claude relays the message and stops.

### select.py (ingest)

Lists the drafts to ingest and an index of all other notes, so Claude can plan without extra searches. Read-only.

* Check the arguments: nothing, `all` or a note name
  * More than one argument: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Read every note, skipping dot folders and the vault `CLAUDE.md`
  * Status, aliases and the first `# ` title outside code
  * A note cannot be read: stop with a system error
* Pick the candidates: `draft` notes directly in `01. Inbox`
  * Note name given: only that one; not an Inbox draft or not found: stop with a user error
  * `all`: at most the 10 oldest by `created` (or file date), then `candidates: <n>, selected: <k>`; the rest stay in the index for a next run
  * Another note has the same filename: add it as `same name:`
* Per candidate, facts for the plan
  * `frontmatter:` schema keys that are missing or empty, plus a `created` date from the file when it is missing and a `source` URL from the draft (a `Source:` or `URL:` line, else the first web link, outside code) when it is empty
  * `mention:` filenames, titles and aliases of other notes that appear as whole words in the draft text (outside frontmatter, code and links) but are not linked yet; archived notes and names under 3 characters are skipped
  * `mentioned-in:` up to 3 existing notes whose text names the draft (filename, title or alias, same rules as `mention:`) without linking it; the ledger records them for `linked` rows
  * `overlap:` up to 3 other notes that share at least 3 distinctive words with the draft (stopwords and words in over half the notes skipped), with a score, as merge hints; another selected draft is marked `draft`, and `draft, duplicate` (listed first) when its text after the frontmatter is the same apart from whitespace
* Print the candidates, then the other notes grouped by folder: a `folder:` line, then one `note:` line per note by filename
  * Index longer than about 20000 characters: stop the list and say how many notes are left out
* Print a new run id as the last line, `run: <id>`, for the run ledger (see `ledger.py`)
  * The ledger gets each listed candidate with a SHA-256 of its content, so `plan.py` can see a note changed later

### plan.py (ingest)

Checks the plan rows Claude proposes, prints the approval table and applies only the approved rows, so the table and the order of the writes are the same every run.

* Read the rows from stdin: `note | state | change | destination` per line, or a JSON list
  * No `select.py` run with this id: stop with a usage error
* Check every row before anything is shown; a refused row is a user error with one `row <id> (<note>): <reason>` line each, nothing stored
  * State `draft` (a candidate of this run), `orphan` (an existing note, by name or path) or `linked` (a `mentioned-in:` note of this run, `new links:` only)
  * Change: `new links:`, `merge with:`, `actions:` (`formatter`, `new type:`, `fill section:`, `fix link:`, `add alias:`, `set <key>:`, `add <tag|alias|related>:`) or `none`; never `status`
  * `new type:` only for a type missing from the allowed list, `set type:` only for an allowed one
  * Folder destination exists and is not `01. Inbox`; every row of a note has the same destination
  * Merge target exists once and is not in `01. Inbox`; no name clash in the archive folder
  * `select.py all` or a name: every selected draft has a row
* Rewrite destinations: a note with the same name in the folder gives `keep, name clash in <folder>`, an orphan always `keep, orphan stays in <folder>`, a linked row `keep, links only in <folder>`
* Number the rows, store the plan in the run ledger and print the `## Changes to ingest` table
* `--approve`: apply the user's corrections (`--skip <id>`, `--dest <id>=...` for all rows of that note, `--link <id>=[[Note]]`), check again and store the approved plan
  * Skipping a merge row keeps the note in `01. Inbox`
  * A note that changed since `select.py` read it (or since the plan for an orphan): stop with a user error, nothing approved
  * Print `skipped:` per skipped row and `apply: <path> | <destination>` per note, orphans first
* `--apply <note>`: refuse a note that changed since the plan, then run `frontmatter.py` with exactly the approved values (`--new-type` only for a `new type:` row, `--approved` for an orphan; `new links:` of a draft also go to `related`)
  * Print `edit: <path> | <change>` per row Claude does with Edit; without such rows finish the note right away
* `--finish <note>`: only after `--apply`; run `promote.py` for a folder, `merge.py` for a merge row (first target, archive folder from the row), or print `kept:`

### promote.py (ingest)

Moves one approved note and sets its status.

* Check the arguments: note, destination folder, `review` or `archived`
  * Wrong arguments, a path with `..` or a dot folder: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Destination is the note's own folder: only set the status (merge target)
  * Note in `01. Inbox`: refuse, a draft gets `review` only by moving out
  * Note is `evergreen`: refuse with a user error, never set it back to `review`
* Otherwise check the move
  * Destination Windows cannot store (reserved name like `CON`, a part ending in a dot or space, a character like `?`, path over 259 characters): stop with a user error
  * Note not a `draft` in `01. Inbox`, folder missing or name clash (ignoring case and Unicode form, as Obsidian does): stop with a user error, nothing moved
  * Note already moved by an earlier run: finish the status, or report `unchanged: already done`
* Move the note, filename unchanged, never replacing a file (hard link, or an exclusive create without hard links)
* Set the status line in the frontmatter, keeping line endings
  * The note changed since it was read (an autosave or a sync): stop with a user error, nothing written
  * No frontmatter: stop with a user error
  * Write fails: stop with a system error
* Print the path after the move and the status
* `--run <id>`: record the move and status, or the user error, in the run ledger

### relink.py (ingest)

Points links to a merged note at the merge target.

* Check the arguments: old note path, new note name
  * Empty, the same, or with `[ ] | #`: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
  * No note with the new name: stop with a user error
* Check whether other notes share the old filename
  * Yes: leave bare links like `[[Old]]` alone and count them as ambiguous
* Rewrite `[[Old...]]` links to `[[New...]]` in every note, outside code blocks, inline code and dot folders
  * Keep `#heading` and `|display` parts
  * A link without display text keeps the old name as display text, `[[Old]]` becomes `[[New|Old]]` (`\|` in a table row), so the text reads the same
  * Embeds `![[Old]]` and links in the frontmatter (such as `related:`) only change the target; their quotes stay
  * Path links only change when they point to the exact old path
* Rewrite Markdown links to the old note, `[text](01.%20Inbox/Old.md)`, also in `<...>`, relative and bare forms, to the target's path; external URLs stay
* Write each changed note through a temp file
  * The note changed since it was read (an autosave or a sync): stop with a user error, that note not written
  * Write fails: stop with a system error
* Print the changed notes, the number of links and the skipped ambiguous links
  * Several notes have the new name: print `ambiguous-target:`, the new bare links are ambiguous
* `--run <id>`: record each changed note in the run ledger

### merge.py (ingest)

Does the mechanical part of one approved merge in one call; Claude merges the body content afterwards.

* Check the arguments: source note in `01. Inbox`, target name, archive folder
  * Wrong arguments, the same name twice, or a path with `..` or a dot folder: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Check everything before writing, a refusal is a user error and writes nothing
  * Target missing, in `01. Inbox`, or several notes with its name
  * Source not a `draft` in `01. Inbox` (an earlier run that already archived it is fine)
  * Archive folder missing, a name clash in it or a name Windows cannot store (as `promote.py`)
  * Target `evergreen`: print `evergreen-target:` first, its status stays
* Add the source's filename and title to the target's `aliases`, no duplicates, as a YAML list (a flow list stays one)
* Rewrite links to the source into links to the target, as `relink.py`
* Move the source to the archive folder with `status: archived`, as `promote.py`
* Set the target to `review`
* Print the changed notes, the links count, skipped ambiguous links, the archived path and the target's status
  * A rerun skips the steps already done
* `--run <id>`: record every change, or the user error, in the run ledger

### frontmatter.py (ingest)

Writes the frontmatter of one note from the values Claude picked for the approved rows, the same way every time.

* Check the arguments: note path, then `key=value` (set, repeat for a list) or `key+=value` (add to a list)
  * Unknown key, `status`, a `created` that is no date, or a multi-line value: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Check the note: a `draft` directly in `01. Inbox`, or any note with `--approved` (an approved orphan or merge row)
  * Otherwise, note missing or no frontmatter: stop with a user error, nothing written
* Check `type` against the `Allowed `type` values` line of the vault `CLAUDE.md`
  * Not in it and no `--new-type` (an approved `new type:` row): stop with a user error
* Write one block: `type`, `topic`, `aliases`, `tags`, `created`, `related`, `source` in that order, then every other key as it was
  * `aliases`, `tags` and `related` as YAML lists without duplicates, `related` as quoted `"[[links]]"`, tags without `#`
  * `created` as `YYYY-MM-DD`; missing: the file date
  * `status` is never changed; CRLF, a BOM and odd bytes stay; written through a temp file, refused when the note changed since it was read
* Print `frontmatter:` or `unchanged:` with the path
* `--run <id>`: record the change in the run ledger

### ledger.py (ingest)

Reports on the run ledger, so Claude keeps no list of changed paths by hand. Read-only.

* `promote.py`, `relink.py`, `merge.py` and `frontmatter.py` append one line per change (moved, status set, changed, failed); `select.py` and `plan.py` add the candidates, the plan and the hashes to `wiki-ingest-<run id>.log` in the system temp dir, never in the vault
* Read the ledger of `--run <id>`; missing: nothing changed
* Print `file:` per changed note at its path now, moves remapped, plus extra paths Claude edited with Edit; these go to `wiki-lint:lint --files`
* Print `failed:` per refused move or merge with its `USER ERROR` text, unless the note moved later in the run
* Print the final list `Moved from draft to review:` with one backticked path per line, or `No notes moved from draft to review.`

### apply.py (apply)

* Check the arguments: nothing, a note name or a note path
  * More than one argument: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Read the first `status:` line of every note, skipping dot folders
* No argument: select every `review` note
* Name or path given: select that note
  * Not found, or its status is not `review`: stop with a user error, nothing changed
  * Several notes with that name: print them as `match:` lines and stop
* Change `status: review` into `status: evergreen`, keeping line endings
  * Write fails: stop with a system error
* Print each changed note and the count (0 is a normal result)

## Tests

`python3 -m unittest discover -s plugins/wiki-ingest/tests -t plugins/wiki-ingest`
