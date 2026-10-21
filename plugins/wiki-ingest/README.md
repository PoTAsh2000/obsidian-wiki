# wiki-ingest

Turns the drafts in your Inbox into filed, linked notes. Claude proposes a plan per draft (frontmatter, links, destination folder or merge), and only after your OK it moves the note out of `01. Inbox` and sets `status: review`. When you have reviewed the filed notes, one command approves them as `evergreen`.

Installing wiki-ingest also installs `wiki-lint`, which it runs before and after filing notes.

## Skills

### `/wiki-ingest:ingest [all | note name]`

Processes `draft` notes in `01. Inbox`. It first lints the whole vault, then shows one plan table with a row per change. You approve it, or approve with changes per row id ("id 3 skip"). Then it edits, moves or merges each note, lints the changed notes and ends with the notes that moved from `draft` to `review`. It never deletes a note. Normal language works too: "process my inbox".

- `/wiki-ingest:ingest` (lists the drafts and asks which one)
- `/wiki-ingest:ingest all`
- `/wiki-ingest:ingest Tokens`

### `/wiki-ingest:apply [--dry-run] [note name]`

Marks reviewed notes as `evergreen`. Typing the command is your approval, so it only runs when you type it, never from normal language or another skill. It only changes the line `status: review`; no moves, no other edits. A `review` note still in `01. Inbox` is left alone and listed, so you can run ingest first.

- `/wiki-ingest:apply` (every `review` note in the vault)
- `/wiki-ingest:apply Context Engineering`
- `/wiki-ingest:apply "30. Knowledge/Twin.md"` (pick one of several notes with the same name)
- `/wiki-ingest:apply --dry-run` or `/wiki-ingest:apply --dry-run Twin` (preview what would change, write nothing)

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

### apply.py (apply)

* Check the arguments: nothing, a note name or a note path, optionally after `--dry-run`
  * More than one argument: join them with single spaces into one name; a leading `--dry-run` word counts as the flag
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Read the `status:` line in the frontmatter of every note (a UTF-8 BOM is allowed), skipping dot folders, dot files, symlinks and the vault `CLAUDE.md`
  * No closing `---`: the note has no frontmatter, so a `status:` line in its body never counts
  * More than one top-level `status:` line: never written
* No argument: select every `review` note
  * Still in `01. Inbox`: leave it as `review` and list it, so the user runs ingest first
  * List, without changing them, notes whose status only looks like review (other case, a ` #` comment, `reviewed`), notes with a duplicate status and notes with unclosed frontmatter
* Name or path given: select that note
  * Not found, its status is not exactly `review`, more than one status line, frontmatter not closed, or still in `01. Inbox`: print the reason as a sentence for the user and stop with a user error, nothing changed
  * Several notes with that name: print their backticked paths and the question which one, and stop with a user error
* `--dry-run`: print the report of what would change and stop, nothing written
* Read the note again and check that the status line is still `status: review` in the frontmatter
  * Changed since the first read: leave the note alone, list it and go on (one note given: stop with a user error)
* Change `status: review` into `status: evergreen`, keeping line endings and the file mode, through a temp file so a failed write leaves the note whole
  * Note locked for a moment (Windows): try the replace again, up to 6 tries in about 1 second
  * Write fails: print the report of the notes that did change, then stop with a system error
* Print the final report: the changed notes as backticked paths (or `No notes moved from review to evergreen.`), then the notes changed during the run, the notes still in `01. Inbox` and the notes with an unclear status

## Tests

`python3 -m unittest discover -s plugins/wiki-ingest/tests -t plugins/wiki-ingest`
