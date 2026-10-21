# wiki-vault

Tells every obsidian-wiki plugin where your Obsidian vault is. You set the vault folder once, and all other skills read it from `~/.claude/obsidian-wiki/vault-path`. It is the only plugin that writes that file, and it never touches the vault itself.

## Skills

### `/wiki-vault:add [vault path]`

Stores the vault path for the first time. Use it right after installing the marketplace. Without a path, Claude asks for it. When a path is already stored, it stops and points you to `/wiki-vault:overwrite`. When the folder does not exist yet, Claude asks whether to store it anyway.

- `/wiki-vault:add C:/Users/you/Obsidian/MyVault`
- `/wiki-vault:add` (Claude asks for the path)

### `/wiki-vault:overwrite [vault path]`

Replaces the stored vault path, for example after you moved or renamed the vault. It shows the old path next to the new one, leaves the file alone when the new path is the same folder (also through a symlink or junction), and warns when the new folder has no `CLAUDE.md` or no `.obsidian` folder. When you typed a subfolder of a vault, or the folder just above one vault, it names the vault folder to use instead.

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
* Remove one pair of surrounding quotes (`"..."` or `'...'`), as Explorer "Copy as path" adds them
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
  * One pair of surrounding quotes (`"..."` or `'...'`) goes, as Explorer "Copy as path" adds them
  * A leading `~` becomes the home folder
  * Empty, not absolute, or it holds a line break: stop with a user error
  * On Windows store it as `C:/...`, also when typed as `/c/...`, `/mnt/c/...` (WSL) or `c:/...`
  * `.` and `..` segments collapse lexically, without following symlinks
  * Path is a file, not a folder: stop with `not a folder: <path>`, also with `--force`
  * Folder missing and no `--force`: stop with `folder not found: <path>`
    * The parent holds exactly one folder whose name nearly matches (case, a typo, a space or dash; `difflib`, cutoff 0.8): the ask names it and `on-yes: <that path>` follows, so a yes reruns with it and "anyway" reruns with `--force`
    * The parent folder is missing too: the ask says so (wrong drive letter, unmounted share), since a forced save points every skill at nothing
  * Path is `~/.claude` or inside it: stop with a user error, also with `--force`
  * Path is a drive root (`/`, `C:/`, a bare UNC share) or the home folder: stop with a user error, also with `--force`
  * Every user error also prints `ask: <question>` for the user; folder not found adds `on-no: <reply>`, and a yes reruns with `--force`
* Read the old path, if any
  * File cannot be read: stop with a system error
* Same folder as the old path: write nothing, reply `Vault unchanged: <old path>`
  * Same means equal after the Git Bash form `/c/...` becomes `C:/...`; on Windows also ignoring case and Unicode normalization
  * Same also means both exist and are one directory (same device and inode), for example through a symlink or junction; inode 0 (FAT, exFAT, some network shares) proves nothing and is skipped
* Otherwise write the new path through a temp file, so a failed write keeps the old file
  * Write fails: stop with a system error
  * Reply `Vault configured: <path>`, plus ` (was: <old path>)` when there was one
* Typed path is itself a symlink or junction: add `Note: <path> points to <target>.` to the reply
* Path is a `//wsl$/...` or `//wsl.localhost/...` share: add a warning that Git Bash tools may be slow or fail there
* Folder has no `CLAUDE.md`: add a warning to the reply, the path stays saved
  * A parent folder has a `CLAUDE.md` or `.obsidian` folder: add a hint naming the closest one as the vault root
* Folder exists without `.obsidian` and no such parent: add a warning to the reply, the path stays saved
  * Exactly one direct child folder has a `CLAUDE.md` or `.obsidian` folder: name that child as the vault instead of the warning
* Print `path: <saved path>`, `old: <old path>` (or `none`) and `reply: <reply>`

### delete.py (delete)

* Check the arguments
  * Any argument: stop with a usage error
* Find the vault path file through `vault.py`
  * File missing: print `removed: none` and stop
* Read the stored path and remove the file
  * Not a regular file, or it cannot be read or removed: stop with a system error
* Print `removed: <path>`, or `removed: none` when the file was empty

## Tests

`python3 -m unittest discover -s plugins/wiki-vault/tests -t plugins/wiki-vault`
