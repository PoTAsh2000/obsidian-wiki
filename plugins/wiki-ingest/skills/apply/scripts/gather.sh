#!/usr/bin/env bash
# gather.sh: read-only context for /wiki-ingest:apply. Injected into SKILL.md, never changes anything.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: gather.sh

Read-only context for /wiki-ingest:apply, injected before the model starts.
Reads the vault path from ~/.claude/obsidian-wiki/vault-path and prints the
vault CLAUDE.md, so the model needs no tool call to find and read it.

output (stdout):
  vault: <path>                     then the vault CLAUDE.md after a marker line
  ERROR: <message to relay>         soft fail: vault path missing or no CLAUDE.md

exit codes:
  0  context printed, or a soft fail printed as ERROR:
  1  system error (required tool missing)
  2  bad usage (any argument other than --help)

example: gather.sh
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) echo "SYSTEM ERROR: gather.sh: takes no arguments, see --help" >&2; exit 2 ;;
esac
[ $# -le 1 ] || { echo "SYSTEM ERROR: gather.sh: takes no arguments, see --help" >&2; exit 2; }

for tool in cat tr; do
  command -v "$tool" >/dev/null || { echo "SYSTEM ERROR: gather.sh: $tool not installed" >&2; exit 1; }
done

vault=
if [ -f "$HOME/.claude/obsidian-wiki/vault-path" ]; then
  vault=$(tr -d '\r\n' < "$HOME/.claude/obsidian-wiki/vault-path")
fi
if [ -z "$vault" ]; then
  echo "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
  exit 0
fi
if [ ! -f "$vault/CLAUDE.md" ]; then
  echo "ERROR: The vault folder $vault has no CLAUDE.md. Check the path with /wiki-vault:overwrite <vault path>."
  exit 0
fi

echo "vault: $vault"
echo "--- vault CLAUDE.md ---"
cat "$vault/CLAUDE.md" || { echo "SYSTEM ERROR: gather.sh: cannot read $vault/CLAUDE.md" >&2; exit 1; }
