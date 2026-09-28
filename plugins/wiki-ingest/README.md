# wiki-ingest

Turns the drafts in your Inbox into filed, linked notes. Claude proposes a plan per draft (frontmatter, links, destination folder or merge), and only after your OK it moves the note out of `01. Inbox` and sets `status: review`. When you have reviewed the filed notes, one command approves them as `evergreen`.

Installing wiki-ingest also installs `wiki-lint`, which it runs before and after filing notes.

## Skills

### `/wiki-ingest:ingest [all | note name]`

Processes `draft` notes in `01. Inbox`. It first lints the whole vault, then shows one plan table with a row per change. You approve it, or approve with changes per row id ("id 3 skip"). Then it edits, moves or merges each note, lints the changed notes and ends with the notes that moved from `draft` to `review`. It never deletes a note. Normal language works too: "process my inbox".

- `/wiki-ingest:ingest` (lists the drafts and asks which one)
- `/wiki-ingest:ingest all`
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
  * Another note has the same filename: add it as `same name:`
* Print the candidates, then one line per other note
  * Index longer than about 20000 characters: stop the list and say how many notes are left out

### promote.py (ingest)

Moves one approved note and sets its status.

* Check the arguments: note, destination folder, `review` or `archived`
  * Wrong arguments, a path with `..` or a dot folder: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Destination is the note's own folder: only set the status (merge target)
  * Note in `01. Inbox`: refuse, a draft gets `review` only by moving out
* Otherwise check the move
  * Note not a `draft` in `01. Inbox`, folder missing or name clash: stop with a user error, nothing moved
  * Note already moved by an earlier run: finish the status, or report `unchanged: already done`
* Move the note, filename unchanged
* Set the status line in the frontmatter, keeping line endings
  * No frontmatter: stop with a user error
  * Write fails: stop with a system error
* Print the path after the move and the status

### relink.py (ingest)

Points links to a merged note at the merge target.

* Check the arguments: old note path, new note name
  * Empty, the same, or with `[ ] | #`: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
  * No note with the new name: stop with a user error
* Check whether other notes share the old filename
  * Yes: leave bare links like `[[Old]]` alone and count them as ambiguous
* Rewrite `[[Old...]]` links to `[[New...]]` in every note, outside code blocks and dot folders
  * Keep `#heading` and `|display` parts
  * Path links only change when they point to the exact old path
* Write each changed note through a temp file
  * Write fails: stop with a system error
* Print the changed notes, the number of links and the skipped ambiguous links

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
