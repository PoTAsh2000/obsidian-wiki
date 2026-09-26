#!/usr/bin/env bash
# add.sh: store the vault path for all obsidian-wiki plugins, only if none is stored yet.
set -euo pipefail

usage() {
  cat <<'USAGE'
usage: add.sh [--allow-missing] [--] <vault path>

Store <vault path> in ~/.claude/obsidian-wiki/vault-path.
Only adds: never changes a path that is already stored.
Every "\" in the path becomes "/". Never touches the vault itself.

arguments:
  <vault path>     path to the vault root folder, one argument (quote it)
  --allow-missing  store the path even if the folder does not exist
  --               end of options, the next argument is the path

output:
  configured: <path>
  folder: found|missing

exit codes:
  0  stored
  1  system error (HOME not set, cannot write the file)
  2  bad usage (wrong arguments, empty path, newline in path)
  3  user error: "already configured: <path>" or "folder not found: <path>"

example: add.sh "C:/Users/me/Documents/Obsidian/MyVault"
USAGE
}

bad() { echo "usage: add.sh [--allow-missing] <vault path>" >&2; echo "add.sh: $1" >&2; exit 2; }

allow=0
args=()
opts=1
for a in "$@"; do
  [[ $opts -eq 1 ]] || { args+=("$a"); continue; }
  case "$a" in
    --) opts=0 ;;
    -h|--help) usage; exit 0 ;;
    --allow-missing) allow=1 ;;
    --*) bad "unknown option: $a" ;;
    *) args+=("$a") ;;
  esac
done
[[ ${#args[@]} -eq 1 ]] || bad "expected one vault path, got ${#args[@]} (quote a path with spaces)"
path=${args[0]//\\//}
[[ -n "$path" ]] || bad "empty vault path"
[[ "$path" != *$'\n'* && "$path" != *$'\r'* ]] || bad "newline in vault path"

[[ -n "${HOME:-}" ]] || { echo "SYSTEM ERROR: add.sh: HOME is not set" >&2; exit 1; }
dir="$HOME/.claude/obsidian-wiki"
file="$dir/vault-path"

if [[ -e "$file" && ! -f "$file" ]]; then
  echo "SYSTEM ERROR: add.sh: $file is not a regular file" >&2
  exit 1
fi
if [[ -s "$file" ]]; then
  old=$(head -n 1 "$file" | tr -d '\r')
  if [[ -n "$old" ]]; then
    echo "USER ERROR: add.sh: already configured: $old" >&2
    exit 3
  fi
fi

folder=found
if [[ ! -d "$path" ]]; then
  folder=missing
  [[ $allow -eq 1 ]] || { echo "USER ERROR: add.sh: folder not found: $path" >&2; exit 3; }
fi

mkdir -p "$dir" 2>/dev/null || { echo "SYSTEM ERROR: add.sh: cannot create $dir" >&2; exit 1; }
{ printf '%s\n' "$path" > "$file"; } 2>/dev/null || { echo "SYSTEM ERROR: add.sh: cannot write $file" >&2; exit 1; }
echo "configured: $path"
echo "folder: $folder"
