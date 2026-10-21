#!/usr/bin/env python3
"""usage: delete.py [--dry-run]

Remove the obsidian-wiki vault path file ~/.claude/obsidian-wiki/vault-path.
Never touches the vault folder itself. Safe to run again: nothing to remove is not an error.
Run when the user asks to remove or forget the vault path.

arguments:
  --dry-run   run every check and report, but leave the file in place

output (stdout): the reply for the user, relayed verbatim
  Vault path removed: <path>         the file held <path> and is now removed
  To restore it, run /wiki-vault:add <path>   second line, only after a real removal
  No vault path configured.          file missing or empty (an empty file is removed)
  Would remove vault path: <path>    --dry-run: nothing removed
  Cleaned up <n> leftover temp file(s).   second line, only when n > 0
  Would clean up <n> leftover temp file(s).   --dry-run

Leftover temp files are plain files named vault-path.tmp.<digits> (written by add and
overwrite) or vault-path.del.<8 chars> (a claim left by an interrupted delete), older
than a minute, so a running add, overwrite or delete keeps its own. Nothing else in the
folder is touched. When the folder is then empty it is removed too (not with --dry-run).

Control characters in <path> are shown as \\xNN (\\uNNNN for bidi controls) and a path
over 300 characters is cut with "...", so the relayed reply carries no terminal escapes.

On Windows the claim rename and removal are retried for about half a second while
another process holds the file open.

The file is first renamed to a unique claim name and read from there, so the reported
path is always the content removed, and a file written meanwhile by add or overwrite stays.
A vault-path file or obsidian-wiki folder that is a symlink, junction or other reparse
point is refused: wiki-vault only writes a plain file, so the user decides.

exit codes:
  0  done (see output)
  1  system error (link refused, file could not be read or removed)
  2  bad usage (any other argument, or --dry-run with another argument)

example: python3 delete.py
"""

import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path

# vault.py lives in the plugin scripts folder: plugins/wiki-vault/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from vault import config_file, stored_path  # noqa: E402

REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
# add/overwrite temp files, and delete claims (tempfile.mkstemp: 8 chars of [a-z0-9_])
TEMP = re.compile(r"vault-path\.(tmp\.\d+|del\.[a-z0-9_]{8})")
STALE = 60  # seconds: a younger file may belong to a running add, overwrite or delete
UNSAFE = re.compile("[\x00-\x1f\x7f-\x9f‪-‮⁦-⁩]")
MAX_SHOWN = 300


def safe(text):
    """Escape control and bidi characters and cap the length for the verbatim reply."""
    text = UNSAFE.sub(lambda m: f"\\x{ord(m[0]):02x}" if ord(m[0]) < 256
                      else f"\\u{ord(m[0]):04x}", text)
    return text if len(text) <= MAX_SHOWN else text[:MAX_SHOWN] + "..."


def retry(fn, *args):
    """Run fn, retrying a Windows sharing violation (PermissionError) for about 0.5 s."""
    for attempt in range(5):
        try:
            return fn(*args)
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.1)


class DeleteError(Exception):
    """A system error: the message goes to stderr and the exit code is 1."""


def is_link(path):
    """True when path is a symlink, junction or other reparse point (missing is False)."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & REPARSE)


def check(config):
    """Refuse links and non-files. Return True when the config file exists."""
    for path in (config.parent, config):
        if is_link(path):
            raise DeleteError(f"{path.as_posix()} is a link, refusing to remove anything")
    if not os.path.lexists(config):
        return False
    if not config.is_file():
        raise DeleteError(f"{config.as_posix()} is not a regular file")
    return True


def read(config):
    try:
        return stored_path(config)
    except (OSError, UnicodeDecodeError) as err:
        raise DeleteError(f"cannot read the vault path file: {err}")


def remove_config(config, dry_run=False):
    """Remove the config file and return the path it held ('' when none)."""
    if not check(config):
        return ""
    if dry_run:
        return read(config)
    # Claim: atomic rename to a unique sibling, so only what we read gets removed.
    fd, name = tempfile.mkstemp(prefix=config.name + ".del.", dir=config.parent)
    os.close(fd)
    claim = Path(name)
    try:
        retry(os.replace, config, claim)
    except FileNotFoundError:
        claim.unlink()
        return ""
    except OSError as err:
        claim.unlink()
        raise DeleteError(f"cannot remove {config.as_posix()}: {err}")
    try:
        path = read(claim)
    except DeleteError:
        if not config.exists():  # put it back, unless a new file was written meanwhile
            os.replace(claim, config)
        raise
    try:
        retry(claim.unlink)
    except OSError as err:
        raise DeleteError(f"cannot remove {claim.as_posix()}: {err}")
    return path


def clean_temps(folder, dry_run=False):
    """Remove stale temp and claim plain files (see TEMP). Return how many (would) go."""
    n = 0
    try:
        names = os.listdir(folder)
    except FileNotFoundError:
        return 0
    for name in names:
        if not TEMP.fullmatch(name):
            continue
        path = folder / name
        try:
            st = os.lstat(path)
            if (not stat.S_ISREG(st.st_mode) or getattr(st, "st_file_attributes", 0) & REPARSE
                    or time.time() - st.st_mtime < STALE):
                continue
            if not dry_run:
                path.unlink()
        except OSError:
            continue  # gone meanwhile or locked: leave it, it is not the user's data
        n += 1
    return n


def main(argv):
    # UTF-8 and LF output on every OS: Windows pipes default to cp1252 and CRLF.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    if argv in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if argv not in ([], ["--dry-run"]):
        print("SYSTEM ERROR: delete.py: unknown arguments, see --help", file=sys.stderr)
        return 2
    dry_run = argv == ["--dry-run"]
    try:
        config = config_file()
        path = remove_config(config, dry_run)
    except DeleteError as err:
        print(f"SYSTEM ERROR: delete.py: {err}", file=sys.stderr)
        return 1
    if not path:
        print("No vault path configured.")
    else:
        print(f"{'Would remove vault path' if dry_run else 'Vault path removed'}: {safe(path)}")
        if not dry_run:
            print(f"To restore it, run /wiki-vault:add {safe(path)}")
    cleaned = clean_temps(config.parent, dry_run)
    if cleaned:
        print(f"{'Would clean' if dry_run else 'Cleaned'} up {cleaned} leftover temp file(s).")
    if not dry_run:
        try:
            os.rmdir(config.parent)  # fails safely when anything is left; a link was refused
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
