# wiki-save

Keeps a useful answer from a Claude conversation before it gets lost in the chat history. It saves the answer as a new `draft` note in `01. Inbox`, with the frontmatter your vault `CLAUDE.md` asks for, so you can file it later with `wiki-ingest`. Save never changes another note and never overwrites a file; edit changes only the note you name and sends it back to `01. Inbox` as a `draft`.

## Skills

### `/wiki-save:save [title]`

Saves the last useful answer or insight of the conversation as a standalone note. Without a title, Claude picks a short one itself and never asks you to confirm it; if that name is taken, it silently tries another (at most 3 tries). When a title you gave matches an Inbox draft, Claude offers to append to it or to save under another title. Normal language works too: "save this to my vault".

- `/wiki-save:save` (Claude picks a title)
- `/wiki-save:save Dolphin sleep patterns`

### `/wiki-save:edit <note> <change>`

Changes one existing note the way you describe, sets its `status` to `draft` whatever it was, and moves it to `01. Inbox` from wherever it is (also `99. Archived`). A note directly in `01. Inbox` is edited in place. The filename never changes, so `[[Name]]` links keep working; notes that link the old location by path are listed. Claude edits a temp copy, never the note itself, and changes only what you asked. Runs only when you type `/wiki-save:edit`. The longest start of your text that names a note (filename, path, `[[link]]` or alias) is the note; the rest is the change.

- `/wiki-save:edit Docker Basics add a section on volumes`
- `/wiki-save:edit [[Seals]] fix the typo in the first paragraph`
- `/wiki-save:edit "20. Knowledge/Seals.md": shorten the intro`

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

### gather.py (save)

Runs right after `vault.py`, before Claude starts, and collects everything else the note needs. Read-only.

* Check the arguments
  * Any argument other than `--related <keyword>...`: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Check that the vault has a `01. Inbox` folder
  * Missing: print an `ERROR:` line that tells the user to run `/wiki-vault:overwrite`
* Collect the existing `topic` values of all notes, so Claude can reuse one
  * Skips dot folders and `90. Templates`
  * A note cannot be read: stop with a system error
* `--related <keyword>...`: list the notes whose filename, first `# ` heading or an `aliases` entry contains a keyword, so Claude can pick related notes without searching
  * Case-insensitive and Unicode-normalized; skips dot folders and `90. Templates`
  * One `related: <path> (<what matched>)` line per note, or `related: none`
* Pick a free temp file path for the draft (not in the vault, not created yet)
  * Windows short 8.3 temp folder (`USERNA~1`): print the long path, which the Write tool accepts
* Print today's date, the draft file path and the topics

### save.py (save)

Writes the note that Claude prepared in the draft file.

* Check the arguments: draft file, optional title, optional `--append` and `--allow-secrets`
  * Wrong number of arguments: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop, nothing saved
  * No `01. Inbox` folder: stop with a system error
* Check the draft file
  * Missing: stop with a usage error
* Scan the whole draft, code blocks included, for secrets: private keys, authorization or bearer headers, common API key prefixes, `password=` or `secret=` values and URLs with `user:password@`
  * Found: print `secret: line <n>: <kind>` per finding (never the value) and stop with a user error, nothing saved
  * `--allow-secrets`: skip the scan, only when the user says the content is safe
* Take the title from the argument, else from the first `# ` heading of the draft (so Claude never quotes it for the shell)
  * Neither: stop with a usage error
* Make a filename from the title
  * Characters not allowed in filenames: replace them with `-`
  * A trailing `.md`: drop it
  * Unicode-normalize it (NFC), remove control and invisible characters and leading dots
  * Too long: cut at a word boundary to at most 200 bytes, and so the full Windows path stays under 260 characters
  * Nothing usable left, or a Windows reserved name (`CON`, `NUL`, `COM1`, ...): stop with a user error
* Look for a note with the same filename anywhere in the vault (case-insensitive, Unicode-normalized)
  * Found while creating: list each match with its status, say whether it can be appended to, and stop
  * Creating: a note outside `99. Archived` with that name as an alias counts as a match too (never appendable), like the duplicate-name check of wiki-lint
* Split the draft into frontmatter and body
  * Opening `---` without a closing one: stop with a usage error
  * Body empty: stop with a usage error
* Create mode: check the frontmatter
  * A key twice, a date (`created`, `updated`, `modified`, `date`, `*_date`) not as `YYYY-MM-DD`, or a `related` entry that is not a quoted `"[[link]]"`: print `frontmatter: line <n>: <problem>` per problem
  * No `type`, `topic` or `status`, or a `type` that is not on the ``Allowed `type` values`` line of the vault `CLAUDE.md` (read like wiki-lint does; no such line: any type): same `frontmatter:` lines
  * Tags not in lowercase kebab-case: rewrite them and print `normalized: tags`
* Check for empty sections, with the rule of wiki-lint's empty-section check: a heading with only blank lines, comments or block ids before the next heading of the same or a higher level or the end; code blocks count as content
  * Found: print `section: line <n>: <heading> is empty` per heading
* Check every `[[link]]` outside code against the vault
  * Link to a missing note: a `suggest:` line naming the closest note filename or alias when one is close
* Create mode: no `status: draft` in the frontmatter is a problem too
* Any of these frontmatter, section, link or status problems: print all their lines in one run, then stop with a usage error, nothing saved, so one edit of the draft fixes them all
* Create mode: write `01. Inbox/<title>.md` with a `# <title>` heading
  * Written to a dot temp file first, then published with a hard link, which never overwrites a file and never leaves a half-written note
  * No hard links on the file system: exclusive create, and a partial file is removed on a write error
* Append mode: add the body under a `## <today>` heading
  * Target is not a single draft directly in `01. Inbox`: stop with a user error
  * The full new text goes to a temp file that replaces the note in one step, only when the note did not change since it was read (otherwise a system error, nothing written)
* Delete the draft file and print the saved path and whether the name was changed

### edit.py (edit)

Edits one note in two steps, so Claude only ever changes a temp copy. Imports its helpers (`key`, `note_files`, the secret scan, the link check, `publish_file` and `replace_if_unchanged`) from the save scripts of this plugin.

* Check the arguments: `prepare <text>` or `publish [--allow-secrets] <note> <draft-file> <sha>`
  * Anything else: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem, or no `01. Inbox` folder: print the `ERROR:` line and stop, nothing changed
* `prepare`: the longest start of the text (a leading quoted name or `[[link]]`, then up to 20 words, where a `:` also ends a word) that names a note is the note; the rest is the change request, printed last as `request: <rest>`
  * A note is named by path, `[[link]]` or filename (case-insensitive, Unicode-normalized); a filename or path always beats an alias, also a longer alias
  * Path leaves the vault or enters a dot folder: stop with a usage error
  * Skips dot folders and `90. Templates`
  * None: print one `suggest:` line (the closest name over all starts) and `request:`, stop with a user error
  * Several: print `match: <path> (status: <status>)` per note and `request:`, stop with a user error
* The note is not directly in `01. Inbox` and `01. Inbox` already holds a note with that filename: print `exists:` and stop with a user error
* `prepare`: copy the note byte for byte to a temp draft file outside the vault and print its path, the target and a sha of the note
* `publish`: check and write the edited draft
  * The note changed since `prepare` (sha differs): stop with a user error, nothing written
  * Secrets on new or changed lines of the draft (same scan as save.py; lines the note already had pass): print `secret:` lines and stop with a user error; `--allow-secrets` skips the scan
  * Opening `---` without a closing one (also checked on the note in `prepare`): stop with a usage error
  * The draft lost the frontmatter the note had, or has no body text: stop with a usage error, so an edit never empties a note
  * No frontmatter: add one with only `status: draft`; else set `status: draft` and an existing `updated:` to today (never added)
  * A `[[link]]` to a missing note that the original did not have: print `suggest:` lines and stop with a usage error; old dead links pass
  * Line endings and odd bytes are kept
  * Directly in `01. Inbox`: replace the note in one step, only when it did not change meanwhile
  * Elsewhere: publish `01. Inbox/<filename>` with a hard link (never overwrites; exclusive create without hard links), then remove the old file to complete the move, only when it did not change meanwhile (otherwise a system error, both files kept)
  * Delete the draft file and print one line for the user: `Edited and moved to draft: <target> (from <old path>, was <status>)` or `Edited in place: <target> (was <status>)`
  * Moved: print `path-link: <note>` for each note that links the old location by path (report only)

## Tests

`python3 -m unittest discover -s plugins/wiki-save/tests -t plugins/wiki-save`
