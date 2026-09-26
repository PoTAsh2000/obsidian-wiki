#!/usr/bin/env bash
# status.sh: print the configured vault path. Read-only, safe to inject.
set -euo pipefail

usage() {
  cat <<'USAGE'
usage: status.sh

Print the vault path stored in ~/.claude/obsidian-wiki/vault-path.
Read-only. Injected by /wiki-vault:add before the model starts.

output:
  configured: <path>   a path is stored
  configured: none     file missing or empty

exit codes:
  0  printed the state
  1  system error (HOME not set, file not readable)
  2  bad usage (arguments given)

example: status.sh
USAGE
}

case "${1:-}" in -h|--help) usage; exit 0 ;; esac
[[ $# -eq 0 ]] || { echo "usage: status.sh (no arguments)" >&2; exit 2; }
[[ -n "${HOME:-}" ]] || { echo "SYSTEM ERROR: status.sh: HOME is not set" >&2; exit 1; }

file="$HOME/.claude/obsidian-wiki/vault-path"
path=""
if [[ -e "$file" ]]; then
  [[ -r "$file" && -f "$file" ]] || { echo "SYSTEM ERROR: status.sh: cannot read $file" >&2; exit 1; }
  path=$(head -n 1 "$file" | tr -d '\r')
fi
echo "configured: ${path:-none}"
