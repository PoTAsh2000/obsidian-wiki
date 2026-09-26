#!/usr/bin/env bash
# delete.sh: remove ~/.claude/obsidian-wiki/vault-path. Never touches the vault.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: delete.sh

Remove the obsidian-wiki vault path file ~/.claude/obsidian-wiki/vault-path.
Never touches the vault folder itself. Safe to run again: nothing to remove is not an error.
Run when the user asks to remove or forget the vault path.

arguments: none

output (stdout, one line):
  removed: <path>   the file held <path> and is now removed
  removed: none     no path was configured (file missing or empty; an empty file is removed)

exit codes:
  0  done (see output)
  1  system error (HOME not set, file could not be read or removed)
  2  bad usage (any argument)

example: bash delete.sh
EOF
}

if [ $# -gt 0 ]; then
  case "$1" in
    -h|--help) usage; exit 0 ;;
  esac
  echo "SYSTEM ERROR: delete.sh: takes no arguments, see --help" >&2
  exit 2
fi

[ -n "${HOME:-}" ] || { echo "SYSTEM ERROR: delete.sh: HOME is not set" >&2; exit 1; }
file="$HOME/.claude/obsidian-wiki/vault-path"

if [ ! -e "$file" ]; then
  echo "removed: none"
  exit 0
fi
[ -f "$file" ] || { echo "SYSTEM ERROR: delete.sh: $file is not a regular file" >&2; exit 1; }

path=$(head -n 1 "$file" | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//') || { echo "SYSTEM ERROR: delete.sh: cannot read $file" >&2; exit 1; }
rm -f -- "$file" 2>/dev/null || { echo "SYSTEM ERROR: delete.sh: cannot remove $file" >&2; exit 1; }
[ ! -e "$file" ] || { echo "SYSTEM ERROR: delete.sh: $file still exists after remove" >&2; exit 1; }

echo "removed: ${path:-none}"
