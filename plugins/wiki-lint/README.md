# wiki-lint

Keeps the vault healthy without you having to look for problems. It checks the notes against the rules in your vault `CLAUDE.md`, fixes the two safe things on its own (stray drafts and dead links) and reports everything else by impact. It never deletes a note and never changes `status`.

## Skills

### `/wiki-lint:lint [--files <path>...] [--dry-run] [--all] [--as-of YYYY-MM-DD]`

Checks the vault and shows the script-built report: what lint changed, what is broken or risky, rule violations, housekeeping and placeholders. It moves `draft` notes outside `01. Inbox` into the Inbox and unlinks dead links (the link text stays). Use it now and then, or after a big change. `wiki-ingest` also runs it before and after filing notes. Normal language works too: "check my vault".

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

* Check the options: `--files <path>...`, `--dry-run`, `--as-of YYYY-MM-DD` (day for the inbox-age cutoff, default today), `--format json|text` and `--all`
  * Unknown option, `--files` without paths, a bad `--as-of` date or `--format` value: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Read the allowed `type` and `status` values from the vault `CLAUDE.md`
  * Either list missing: stop with a user error
  * Optional `## Lint ignore` section: `- Links:` and `- Paths:` lines with backticked glob patterns, case-insensitive
* Select the notes: the whole vault, or only the `--files` notes and folders
  * A `--files` path not found: stop with a user error
  * Skips hidden files, hidden folders and the attachment folder (`attachmentFolderPath` in `.obsidian/app.json`, default `Attachments`)
  * Skips files that match a `Lint ignore` path or an Obsidian `userIgnoreFilters` entry, which still count as link targets
  * `.obsidian/app.json` missing or not valid JSON: the defaults, no error
* Move `draft` notes outside `01. Inbox` into the Inbox, filename unchanged
  * Inbox already has that name: report it instead of moving
* Check every wiki link and Markdown link outside code
  * Names match as Obsidian matches them: Unicode NFC and casefold, so an NFD file name from macOS or `ß` against `ss` still resolves
  * A link without extension also finds a `.canvas` or `.base` file
  * Dead link: replace it with its text
  * Dead link close to exactly one note name or alias (difflib ratio 0.9 or more, for example `[[Contex Engineering]]` next to `Context Engineering.md`): keep it and report `likely-typo` with the suggested link; with several close names it is unlinked as usual
  * Dead link to a file that is not a note (image, PDF, any extension other than `.md`, `.canvas` or `.base`): keep it and report `missing-attachment` with the file name, so restoring the file fixes the embed
  * Dead link whose target (with or without `.md`) matches a `Lint ignore` link: keep it, list it in `allowlistedLinks`
  * Heading or block after `#` missing in the target note: report it, keep the link
  * Link that fits several notes: report it as ambiguous, with the shortest unique link form for each note (lint does not rewrite it)
  * Link from outside `99. Archived` to an archived note: report `archived-link`, with the replacement link when exactly one active note has the archived name as alias (lint does not rewrite it)
  * Template placeholder like `[[{{title}}]]`: list it, leave it alone
* Check every scanned note for bytes that are not UTF-8 (first such line) or a UTF-16 byte order mark: report `invalid-encoding`
* Check each note outside `10. Daily`, `90. Templates` and `99. Archived`
  * Missing or invalid frontmatter, empty sections: report them; `created` must be a real date, not after `--as-of`
  * Note whose body has only blank lines, headings, HTML comments or block ids: report `empty-note` on line 1
  * A byte order mark before the frontmatter, a frontmatter block that is not closed and a duplicate key each get their own detail; with a byte order mark the other frontmatter checks still run
  * `archived` status outside `99. Archived`: report it
  * Full vault only: report Inbox notes older than 7 days
* Full vault only: report duplicate names or aliases, and orphans without incoming links
* Full vault only: report files in the attachment folder that nothing links to or embeds (`unused-attachment`, with the size); a `.canvas`, `.base` or ignored note that names the file counts as a use, and `Lint ignore` paths are skipped. Lint never deletes them
* Full vault only: report file and folder names that break on Windows, in a sync or in a link (`unsafe-name`): reserved names like `CON`, characters Windows forbids, a trailing dot or space, `# ^ [ ] |`, control characters, names that are not NFC and names in one folder that differ only in case
* Write the moves and changed notes, keeping CRLF line endings
  * Each write goes to a temp file first, then replaces the note
  * Note changed since the scan: leave it alone and report `skipped-changed`
  * `--dry-run`: write nothing
  * Write fails: stop with a system error
* Print one JSON object, valid even for odd bytes or control characters in a name or link
  * `summary`: notes and links scanned, and the category counts per impact group in report order
  * `findings` sorted by impact group, then path and line
  * `--format text`: the same report as plain text, a scan line and one block per non-empty impact group, one `path:line  category  detail` line per item (moves as `from -> to`), at most 25 per category and then a `... N more <category>` line; `--all` lifts the cap, the counts are always exact
  * Exit 0 when clean, exit 4 when it fixed or found something; exit 2 usage error, 3 user error, 1 system error

## Tests

`python3 -m unittest discover -s plugins/wiki-lint/tests -t plugins/wiki-lint`
