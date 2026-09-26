#!/usr/bin/env bash
# context.sh: read-only context for wiki-ingest:ingest, injected before the model starts.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: context.sh

Print the configured vault path and the vault CLAUDE.md. Read-only.
Injected at the top of wiki-ingest:ingest, so the model starts with both.
Reads the path from ~/.claude/obsidian-wiki/vault-path (written by wiki-vault only).

output (stdout):
  vault: <path>                 then the vault CLAUDE.md after a marker line
  ERROR: <message>              soft fail: path missing or no CLAUDE.md; relay and stop

exit codes:
  0  context printed, or a soft fail (ERROR: line)
  1  system error (file unreadable)
  2  bad usage (arguments given)

example: context.sh
EOF
}

case "${1:-}" in -h|--help) usage; exit 0 ;; esac
[ $# -eq 0 ] || { echo "SYSTEM ERROR: context.sh: takes no arguments, see --help" >&2; exit 2; }

for t in tr head sed; do command -v "$t" > /dev/null || { echo "SYSTEM ERROR: context.sh: $t not installed" >&2; exit 1; }; done

conf="$HOME/.claude/obsidian-wiki/vault-path"
vault=
if [ -f "$conf" ]; then
  vault=$(tr -d '\r' < "$conf" | head -n 1 | sed 's/^[[:space:]]*//; s/[[:space:]]*$//') ||
    { echo "SYSTEM ERROR: context.sh: cannot read $conf" >&2; exit 1; }
fi
if [ -z "$vault" ]; then
  echo "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
  exit 0
fi

dir=$vault
command -v cygpath > /dev/null && dir=$(cygpath -u "$vault")
if [ ! -f "$dir/CLAUDE.md" ]; then
  echo "ERROR: the vault folder $vault has no CLAUDE.md. Point wiki-vault to the right folder with /wiki-vault:overwrite <vault path>."
  exit 0
fi

echo "vault: $vault"
echo "----- vault CLAUDE.md -----"
tr -d '\r' < "$dir/CLAUDE.md" || { echo "SYSTEM ERROR: context.sh: cannot read $vault/CLAUDE.md" >&2; exit 1; }
