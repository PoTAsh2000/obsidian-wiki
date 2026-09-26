#!/usr/bin/env bash
# vault.sh: read-only context for the lint skill (runs through !`...` injection).
set -euo pipefail

usage() {
  cat <<'EOF'
usage: vault.sh

Print the configured vault path and the vault CLAUDE.md. Read-only.
Runs through injection at the start of /wiki-lint:lint. No arguments.
Reads the path from $HOME/.claude/obsidian-wiki/vault-path (written by wiki-vault).

output (stdout):
  vault: <path>            configured vault folder
  vault: missing           no vault path configured (soft fail, exit 0)
  error: no CLAUDE.md      vault folder has no CLAUDE.md (soft fail, exit 0)
  error: vault not found   configured folder does not exist (soft fail, exit 0)
  then, on success, a "claude-md:" line followed by the vault CLAUDE.md

exit codes:
  0  printed (check for "vault: missing" and "error:" lines)
  1  system error (HOME not set)
  2  bad usage (any argument)

example: vault.sh
EOF
}

case ${1-} in -h|--help) usage; exit 0 ;; esac
[ $# -eq 0 ] || { echo "SYSTEM ERROR: vault.sh: no arguments allowed, see --help" >&2; exit 2; }
[ -n "${HOME-}" ] || { echo "SYSTEM ERROR: vault.sh: HOME is not set" >&2; exit 1; }

cfg="$HOME/.claude/obsidian-wiki/vault-path"
vault=
[ -f "$cfg" ] && vault=$(head -n 1 "$cfg" | tr -d '\r')
vault=${vault%"${vault##*[![:space:]]}"}
vault=${vault#"${vault%%[![:space:]]*}"}
if [ -z "$vault" ]; then echo "vault: missing"; exit 0; fi
echo "vault: $vault"

dir=$vault
command -v cygpath > /dev/null && dir=$(cygpath -u "$vault")
if [ ! -d "$dir" ]; then echo "error: vault not found"; exit 0; fi
if [ ! -f "$dir/CLAUDE.md" ]; then echo "error: no CLAUDE.md"; exit 0; fi
echo "claude-md:"
cat "$dir/CLAUDE.md"
