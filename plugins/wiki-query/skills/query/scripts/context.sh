#!/usr/bin/env bash
# context.sh: read-only context for the query skill (injected into SKILL.md).
set -euo pipefail

usage() {
  cat <<'EOF'
usage: context.sh

Print the configured vault path and the vault CLAUDE.md for the query skill.
Read-only. Runs through SKILL.md injection before the model starts.
Reads the vault path from ~/.claude/obsidian-wiki/vault-path (written by wiki-vault).

output:
  vault: <path>                   then the vault CLAUDE.md after "--- vault CLAUDE.md ---"
  ERROR: <message>                soft fail: vault path missing or vault has no CLAUDE.md

exit codes:
  0  context printed, or a soft ERROR line for the model to relay
  1  system error (HOME not set, cannot read a file)
  2  bad usage (any argument other than --help)

example: context.sh
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) echo "SYSTEM ERROR: context.sh: takes no arguments, see --help" >&2; exit 2 ;;
esac

[[ -n "${HOME:-}" ]] || { echo "SYSTEM ERROR: context.sh: HOME not set" >&2; exit 1; }
conf="$HOME/.claude/obsidian-wiki/vault-path"
vault=""
if [[ -f "$conf" ]]; then
  vault=$(tr -d '\r' < "$conf" | head -n 1)
  vault="${vault#"${vault%%[![:space:]]*}"}"
  vault="${vault%"${vault##*[![:space:]]}"}"
fi

if [[ -z "$vault" ]]; then
  echo "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
  exit 0
fi

dir="$vault"
command -v cygpath >/dev/null 2>&1 && dir=$(cygpath -u "$vault")
if [[ ! -f "$dir/CLAUDE.md" ]]; then
  echo "ERROR: The configured vault folder has no CLAUDE.md: $vault. Use /wiki-vault:overwrite <vault path> to fix the vault path."
  exit 0
fi

rules=$(cat "$dir/CLAUDE.md" 2>/dev/null) || { echo "SYSTEM ERROR: context.sh: cannot read $vault/CLAUDE.md" >&2; exit 1; }
echo "vault: $vault"
echo "--- vault CLAUDE.md ---"
printf '%s\n' "$rules"
