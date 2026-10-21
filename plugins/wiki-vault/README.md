# wiki-vault

Tells every obsidian-wiki plugin where your Obsidian vault is. You set the vault folder once, and all other skills read it from `~/.claude/obsidian-wiki/vault-path`. It is the only plugin that writes that file, and it never touches the vault itself.

## Skills

### `/wiki-vault:add [vault path]`

Stores the vault path for the first time. Use it right after installing the marketplace. Without a path, Claude offers the vault you started Claude Code in and the vaults Obsidian itself knows (from its `obsidian.json`, marking the ones with a `CLAUDE.md`) or asks for the path. When a path is already stored, it stops and points you to `/wiki-vault:overwrite`, and says so when that folder is gone or has no `CLAUDE.md`. A folder inside a vault's `.obsidian`, `.trash` or `.git`, a folder whose parent does not exist, and a path with a character or name Windows cannot have in a folder are refused. When only the last folder does not exist yet, Claude asks whether to store it anyway. When it is a subfolder of a vault, Claude offers the vault root instead, and when it only holds one vault one level down, Claude offers that one. A folder that is not writable is stored with a warning. A folder inside `~/.claude` or the plugin, and a file, are always refused. A path that starts with `~` means your home folder. When the folder is a symlink or junction, Claude tells you where it really points, and a network share path gets a note that it may be slow or fail offline. On Windows a WSL `/mnt/...` path is refused; use the Windows form like `C:/Users/...`. A folder without `.obsidian` or `CLAUDE.md` is stored with a warning.

- `/wiki-vault:add C:/Users/you/Obsidian/MyVault`
- `/wiki-vault:add ~/Obsidian/MyVault`
- `/wiki-vault:add` (Claude offers known vaults or asks for the path)

### `/wiki-vault:overwrite [vault path]`

Replaces the stored vault path, for example after you moved or renamed the vault. It shows the old path next to the new one, leaves the file alone when the new path is the same folder (also through a symlink or junction), and warns when the new folder has no `CLAUDE.md` or no `.obsidian` folder. When you typed a subfolder of a vault, or the folder just above one vault, it names the vault folder to use instead.

- `/wiki-vault:overwrite D:/Notes/Vault`

### `/wiki-vault:delete`

Removes the stored vault path. Use it when you stop using the plugins or want to start over with `/wiki-vault:add`. The vault stays as it is.

- `/wiki-vault:delete`

## Scripts

The scripts get the location of the vault path file only from `vault.py`, so none of them checks `HOME` itself. `add.py` and `overwrite.py` clean a typed path the same way through `vault.py`: `\` becomes `/`, trailing slashes go (a root like `/` or `C:/` stays), and the path must be absolute and on one line. Both scripts print the sentences for the user themselves (`reply:`, `ask:`), so the skill only relays them.

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
* A path is stored: print `reply: Vault is already configured: <path>. Use /wiki-vault:overwrite to change it.`
  * Not a folder any more: print `reply: Vault is configured as <path>, but that folder no longer exists. Use /wiki-vault:overwrite to point to the new location.`
  * No `CLAUDE.md` in it: the same reply with `that folder has no CLAUDE.md`
* No path is stored: print `configured: none`
  * Then, when the current folder or a parent has `.obsidian`, that vault as the first `candidate: <path> (current folder)` line (real path, so short names like `USERNA~1` become long ones); it is not repeated from `obsidian.json`
  * Then one `candidate: <path>` line per vault in Obsidian's `obsidian.json` (`%APPDATA%/obsidian` on Windows, `~/Library/Application Support/obsidian` on macOS, `~/.config/obsidian` on Linux) whose folder exists, cleaned like add.py does, the open vault first, then by last-opened time (newest first), entries without these fields last in file order, with ` (has CLAUDE.md)` when it has one
  * `obsidian.json` missing or unreadable: no candidate lines; it is never written

### add.py (add)

* Check the arguments: one vault path, optional `--force` before or after it
  * Unknown option or wrong number of paths: stop with a usage error
* Make the path canonical, so one form is stored
  * A leading `~` becomes the home folder, taken from `HOME` like `vault.py` does
  * Clean it through `vault.py`; empty, not absolute, or it holds a line break: stop with a user error
  * Git Bash `/c/...` becomes `C:/...` on Windows, and the drive letter is upper case
  * A WSL `/mnt/...` path left over after `vault.py` on Windows: stop with `reply: Not a Windows path: <path>. ...`
  * Existing folder: each part gets the case it has on disk; links are not resolved
  * Unicode is stored in NFC form
  * A control character (tab, NUL), a character a Windows folder cannot have (`< > : " | ? *`), a part that ends in a dot or space, or a reserved name like `CON` or `COM1`: stop with a user error, on every OS
* Refuse `~/.claude`, the plugin root and anything inside them, also with `--force`
  * Case, Unicode form and slash style do not matter: stop with `reply: Not a vault folder: <path>`
* Check that no path is stored yet
  * A path is stored: stop with `reply: Vault is already configured: <path>. ...`
  * File cannot be read: stop with a system error
* Check that the path is a folder
  * Inside a vault's `.obsidian`, `.trash` or `.git`, also with `--force`: stop with `reply: Not a vault folder: <path>. Use <root> instead.`
  * A file, also with `--force`: stop with `reply: Not a folder: <path>`
  * Parent missing or not a folder, also with `--force`: stop with `reply: Parent folder not found: <parent>`
  * Only the last part missing and no `--force`: stop with `ask: Folder not found: <path>. Configure it anyway?` and `yes: --force "<path>"`
  * A symlink or Windows junction (found through the reparse tag): keep the path as typed and add `notice: <path> links to <target>`
  * A network share like `//server/share/Vault`: keep it as typed and add `notice: <path> is a network share; the skills may be slow or fail when it is offline`
* Check for `.obsidian` in the folder, skipped with `--force`
  * A parent folder has one: stop with `ask:` to use the root instead, `yes: "<root>"` and `no: --force "<path>"`
  * Exactly one direct subfolder has one: stop with `ask:` to use that subfolder instead, `yes: "<subfolder>"` and `no: --force "<path>"`
  * No parent has one: warn `no .obsidian folder in <path>`, naming the subfolders that are vaults when there are several
* Check that the folder is writable (`os.access`, no test file is created)
  * Not writable: warn `<path> is not writable; the skills that write notes will fail`, the path is still saved
* Check for `CLAUDE.md` in the folder
  * Missing: warn `no CLAUDE.md in <path>`, since the other skills stop without it
* Write the path through a temp file, so a failed write leaves no half file
  * Write fails: stop with a system error
* Print `path: <saved path>`, `reply: Vault configured: <saved path>`, then each `warning:` and `notice:` line

User errors (exit 3) go to stdout as `reply:` or `ask:` lines; system and usage errors go to stderr.

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
