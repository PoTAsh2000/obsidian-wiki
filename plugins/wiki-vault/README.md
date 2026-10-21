# wiki-vault

Tells every obsidian-wiki plugin where your Obsidian vault is. You set the vault folder once, and all other skills read it from `~/.claude/obsidian-wiki/vault-path`. It is the only plugin that writes that file, and it never touches the vault itself.

## Skills

### `/wiki-vault:add [vault path]`

Stores the vault path for the first time. Use it right after installing the marketplace. Without a path, Claude asks for it. When a path is already stored, it stops and points you to `/wiki-vault:overwrite`. When the folder does not exist yet, Claude asks whether to store it anyway.

- `/wiki-vault:add C:/Users/you/Obsidian/MyVault`
- `/wiki-vault:add` (Claude asks for the path)

### `/wiki-vault:overwrite [vault path]`

Replaces the stored vault path, for example after you moved or renamed the vault. It shows the old path next to the new one.

- `/wiki-vault:overwrite D:/Notes/Vault`

### `/wiki-vault:delete`

Removes the stored vault path. Use it when you stop using the plugins or want to start over with `/wiki-vault:add`. The vault stays as it is.

- `/wiki-vault:delete`

## Scripts

The scripts get the location of the vault path file only from `vault.py`, so none of them checks `HOME` itself. `add.py` and `overwrite.py` clean a typed path the same way through `vault.py`: `\` becomes `/`, trailing slashes go (a root like `/` or `C:/` stays), and the path must be absolute and on one line.

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

### status.py (add)

Runs before Claude starts, so the add skill knows whether a path is stored already. Read-only.

* Check the arguments
  * Any argument: stop with a usage error
* Read the stored vault path through `vault.py`
  * File cannot be read: stop with a system error
* Print `configured: <path>`, or `configured: none` when no path is stored

### add.py (add)

* Check the arguments: one vault path, optional `--force` before or after it
  * Unknown option or wrong number of paths: stop with a usage error
* Clean the path through `vault.py`
  * Empty, not absolute, or it holds a line break: stop with a user error
* Check that no path is stored yet
  * A path is stored: stop with `already configured: <path>`
  * File cannot be read: stop with a system error
* Check that the folder exists
  * Missing and no `--force`: stop with `folder not found: <path>`
* Write the path through a temp file, so a failed write leaves no half file
  * Write fails: stop with a system error
* Print `path: <saved path>`

### overwrite.py (overwrite)

* Check the arguments: one vault path, optional `--force` before or after it
  * Wrong arguments: stop with a usage error
* Clean the path through `vault.py`
  * Empty, not absolute, or it holds a line break: stop with a user error
  * Folder missing and no `--force`: stop with `folder not found: <path>`
* Read the old path, if any
  * File cannot be read: stop with a system error
* Write the new path through a temp file, so a failed write keeps the old file
  * Write fails: stop with a system error
* Print `path: <saved path>` and `old: <old path>` (or `none`)

### delete.py (delete)

* Check the arguments
  * `--dry-run` alone: run every check below, print `Would remove vault path: <path>` (or `No vault path configured.`) and keep every file
  * Any other argument: stop with a usage error
* Find the vault path file through `vault.py`
  * The file or its `obsidian-wiki` folder is a symlink, junction or other reparse point: stop with a system error and remove nothing
  * File missing: print `No vault path configured.`
* Claim the file by renaming it to a unique `vault-path.del.*` name, read the stored path from the claim, then remove the claim
  * A path written by add or overwrite in the meantime stays, and the output names only what was removed
  * On Windows, a rename or removal blocked by another process holding the file open is retried for about half a second
  * Not a regular file, or it cannot be read or removed: stop with a system error
* Print `Vault path removed: <path>` and `To restore it, run /wiki-vault:add <path>`, or `No vault path configured.` when the file was empty
  * Control characters in the path show as `\xNN` and a path over 300 characters is cut with `...`
* Remove leftover `vault-path.tmp.<digits>` plain files from an interrupted add or overwrite, and `vault-path.del.*` claims from an interrupted delete, when older than a minute
  * Nothing else in the folder is touched; a file that cannot be removed is skipped
  * Print `Cleaned up <n> leftover temp file(s).` as a second line, only when there were any
* Remove the `obsidian-wiki` folder when it is now empty (not with `--dry-run`); a folder that still holds anything stays

The output is the reply Claude gives the user word for word.

## Tests

`python3 -m unittest discover -s plugins/wiki-vault/tests -t plugins/wiki-vault`
