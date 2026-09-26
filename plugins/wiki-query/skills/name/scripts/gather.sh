#!/usr/bin/env bash
# gather.sh: read-only context for /wiki-query:name, injected before the model runs.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: gather.sh

Read the vault path configured by wiki-vault and print it with the vault
CLAUDE.md. Read-only. Runs through injection in the name skill.

arguments: none

output:
  vault: <path>                     then the vault CLAUDE.md between marker lines
  ERROR: <message for the user>     soft fail: vault path missing, folder
                                    missing or no CLAUDE.md (still exit 0)

exit codes:
  0  context printed, or soft fail printed as ERROR: line
  2  bad usage (arguments given)

example: gather.sh
EOF
}

case "${1:-}" in -h|--help) usage; exit 0 ;; esac
[[ $# -eq 0 ]] || { echo "SYSTEM ERROR: gather.sh: takes no arguments, see --help" >&2; exit 2; }

conf="$HOME/.claude/obsidian-wiki/vault-path"
vault=""
[[ -f "$conf" ]] && vault=$(sed -n '/[^[:space:]]/{p;q;}' "$conf" | tr -d '\r')
vault="${vault#"${vault%%[![:space:]]*}"}"
vault="${vault%"${vault##*[![:space:]]}"}"

if [[ -z "$vault" ]]; then
  echo "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
  exit 0
fi
if [[ ! -d "$vault" ]]; then
  echo "ERROR: The configured vault folder does not exist: $vault. Use /wiki-vault:overwrite <vault path> to fix it."
  exit 0
fi
if [[ ! -f "$vault/CLAUDE.md" ]]; then
  echo "ERROR: The configured vault folder has no CLAUDE.md: $vault. Use /wiki-vault:overwrite <vault path> to fix it."
  exit 0
fi

echo "vault: $vault"
echo "----- begin vault CLAUDE.md -----"
tr -d '\r' < "$vault/CLAUDE.md"
echo
echo "----- end vault CLAUDE.md -----"
