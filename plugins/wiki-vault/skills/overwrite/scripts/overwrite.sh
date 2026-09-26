#!/usr/bin/env bash
# Replace the obsidian-wiki vault path in ~/.claude/obsidian-wiki/vault-path.
set -euo pipefail

usage() {
  cat <<'USAGE'
usage: overwrite.sh [--force] <vault-path>

Replace the vault path in ~/.claude/obsidian-wiki/vault-path, which all
obsidian-wiki skills read. Never touches the vault itself. Backslashes become
slashes and trailing slashes are removed before saving.

arguments:
  <vault-path>  absolute path to the vault root, like C:/Notes/Vault or /home/me/Vault
options:
  --force       save even when the folder does not exist
  -h, --help    show this help

output (exit 0):
  path: <saved path>
  old: <previous path, or none>

exit codes:
  0  saved (also when the path was already the same)
  1  system error (cannot create the config folder or write the file)
  2  bad usage (wrong arguments)
  3  user error (path not absolute, or folder not found without --force)

example: overwrite.sh "D:/Obsidian/MyVault"
USAGE
}

force=0
args=()
for a in "$@"; do
  case "$a" in
    -h|--help) usage; exit 0 ;;
    --force) force=1 ;;
    -*) echo "SYSTEM ERROR: overwrite.sh: unknown option '$a', see --help" >&2; exit 2 ;;
    *) args+=("$a") ;;
  esac
done
[[ ${#args[@]} -eq 1 ]] || { echo "SYSTEM ERROR: usage: overwrite.sh [--force] <vault-path>" >&2; exit 2; }

path="${args[0]//\\//}"
while [[ "$path" == */ && "$path" != "/" && ! "$path" =~ ^[A-Za-z]:/$ ]]; do path="${path%/}"; done
[[ -n "$path" ]] || { echo "SYSTEM ERROR: overwrite.sh: empty vault path" >&2; exit 2; }
[[ "$path" != *$'\n'* && "$path" != *$'\r'* ]] || { echo "USER ERROR: vault path contains a line break" >&2; exit 3; }
[[ "$path" == /* || "$path" =~ ^[A-Za-z]:/ ]] || { echo "USER ERROR: vault path is not absolute: $path" >&2; exit 3; }
[[ $force -eq 1 || -d "$path" ]] || { echo "USER ERROR: folder not found: $path" >&2; exit 3; }

[[ -n "${HOME:-}" ]] || { echo "SYSTEM ERROR: overwrite.sh: HOME is not set" >&2; exit 1; }
dir="$HOME/.claude/obsidian-wiki"
file="$dir/vault-path"

old=""
if [[ -f "$file" ]]; then old=$(head -n 1 "$file" | tr -d '\r'); fi

mkdir -p "$dir" 2>/dev/null || { echo "SYSTEM ERROR: overwrite.sh: cannot create $dir" >&2; exit 1; }
tmp="$file.tmp.$$"
if ! { printf '%s\n' "$path" > "$tmp" && mv -f "$tmp" "$file"; } 2>/dev/null; then
  rm -f "$tmp"
  echo "SYSTEM ERROR: overwrite.sh: cannot write $file" >&2
  exit 1
fi

echo "path: $path"
echo "old: ${old:-none}"
