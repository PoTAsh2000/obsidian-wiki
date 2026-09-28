# wiki-lint

Keeps the vault healthy without you having to look for problems. It checks the notes against the rules in your vault `CLAUDE.md`, fixes the two safe things on its own (stray drafts and dead links) and reports everything else by impact. It never deletes a note and never changes `status`.

## Skills

### `/wiki-lint:lint [--files <path>...] [--dry-run]`

Checks the vault and explains the result: what lint changed, what is broken or risky, rule violations, housekeeping and placeholders. It moves `draft` notes outside `01. Inbox` into the Inbox and unlinks dead links (the link text stays). Use it now and then, or after a big change. `wiki-ingest` also runs it before and after filing notes. Normal language works too: "check my vault".

- `/wiki-lint:lint` (full vault check with orphans, duplicate names and old Inbox notes)
- `/wiki-lint:lint --files "01. Inbox/" "30. Knowledge/Tokens.md"` (only these notes or folders)
- `/wiki-lint:lint --dry-run` (show what lint would do, change nothing)

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

### lint.py (lint)

Lives at `skills/lint/scripts/lint.py`.

* Check the options: `--files <path>...` and `--dry-run`
  * Unknown option or `--files` without paths: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Read the allowed `type` and `status` values from the vault `CLAUDE.md`
  * Either list missing: stop with a user error
* Select the notes: the whole vault, or only the `--files` notes and folders
  * A `--files` path not found: stop with a user error
  * Skips hidden files, hidden folders and `Attachments`
* Move `draft` notes outside `01. Inbox` into the Inbox, filename unchanged
  * Inbox already has that name: report it instead of moving
* Check every wiki link and Markdown link outside code
  * Dead link: replace it with its text
  * Link that fits several notes: report it as ambiguous
  * Template placeholder like `[[{{title}}]]`: list it, leave it alone
* Check each note outside `10. Daily`, `90. Templates` and `99. Archived`
  * Missing or invalid frontmatter, empty sections: report them
  * `archived` status outside `99. Archived`: report it
  * Full vault only: report Inbox notes older than 7 days
* Full vault only: report duplicate names or aliases, and orphans without incoming links
* Write the moves and changed notes, keeping CRLF line endings
  * `--dry-run`: write nothing
  * Write fails: stop with a system error
* Print one JSON object: exit 0 when clean, exit 4 when it fixed or found something

## Tests

`python3 -m unittest discover -s plugins/wiki-lint/tests -t plugins/wiki-lint`
