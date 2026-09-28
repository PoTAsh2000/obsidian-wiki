# wiki-save

Keeps a useful answer from a Claude conversation before it gets lost in the chat history. It saves the answer as a new `draft` note in `01. Inbox`, with the frontmatter your vault `CLAUDE.md` asks for, so you can file it later with `wiki-ingest`. It never changes another note and never overwrites a file.

## Skills

### `/wiki-save:save [title]`

Saves the last useful answer or insight of the conversation as a standalone note. Without a title, Claude proposes one and asks you to confirm it. When an Inbox draft with the same name exists, Claude offers to append to it or to save under another title. Normal language works too: "save this to my vault".

- `/wiki-save:save` (Claude proposes a title)
- `/wiki-save:save Dolphin sleep patterns`

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
  * Any argument: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Check that the vault has a `01. Inbox` folder
  * Missing: print an `ERROR:` line that tells the user to run `/wiki-vault:overwrite`
* Collect the existing `topic` values of all notes, so Claude can reuse one
  * Skips dot folders and `90. Templates`
  * A note cannot be read: stop with a system error
* Pick a free temp file path for the draft (not in the vault, not created yet)
* Print today's date, the draft file path and the topics

### save.py (save)

Writes the note that Claude prepared in the draft file.

* Check the arguments: title, draft file, optional `--append`
  * Wrong number of arguments: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop, nothing saved
  * No `01. Inbox` folder: stop with a system error
* Check the draft file
  * Missing: stop with a usage error
* Make a filename from the title
  * Characters not allowed in filenames: replace them with `-`
  * Nothing usable left: stop with a user error
* Look for a note with the same filename anywhere in the vault
  * Found while creating: list each match with its status, say whether it can be appended to, and stop
* Split the draft into frontmatter and body
  * Body empty: stop with a usage error
* Check every `[[link]]` outside code against the vault
  * Link to a missing note: stop with a usage error
* Create mode: write `01. Inbox/<title>.md` with a `# <title>` heading
  * No `status: draft` in the frontmatter: stop with a usage error
* Append mode: add the body under a `## <today>` heading
  * Target is not a single draft directly in `01. Inbox`: stop with a user error
* Delete the draft file and print the saved path and whether the name was changed

## Tests

`python3 -m unittest discover -s plugins/wiki-save/tests -t plugins/wiki-save`
