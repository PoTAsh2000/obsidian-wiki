#!/usr/bin/env bash
# name.sh: list notes in the configured vault whose filename or title contains a text.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: name.sh [--] <text>...

List notes in the vault configured by wiki-vault whose filename or title
contains <text> (case-insensitive), falling back to aliases. Read-only.
Wraps the plugin script find.sh with the vault path already filled in.

arguments:
  <text>  the text to look for; several words are joined with one space
  --      end of options, use before a text that starts with a dash

output (relay as printed):
  - <path>                                     one line per match
  No filename or title matches "<text>". Found through aliases:
  - <path> (alias: <alias>)                    alias fallback
  Nothing found.                               no match (still exit 0)

exit codes:
  0  lookup done (matches or "Nothing found.")
  1  system error (gawk, find or xargs missing, find.sh missing or failed)
  2  bad usage (no text given)
  3  user error (vault path missing, vault folder or its CLAUDE.md missing)

example: name.sh -- context engineering
EOF
}

case "${1:-}" in -h|--help) usage; exit 0 ;; --) shift ;; esac
[[ $# -ge 1 ]] || { echo "SYSTEM ERROR: name.sh: no text given. usage: name.sh [--] <text>..." >&2; exit 2; }
text="$*"
[[ "$text" =~ [^[:space:]] ]] || { echo "SYSTEM ERROR: name.sh: text is empty. usage: name.sh [--] <text>..." >&2; exit 2; }

# Dependencies of find.sh, checked before anything else.
for dep in find xargs; do
  command -v "$dep" >/dev/null 2>&1 || { echo "SYSTEM ERROR: name.sh: $dep not found" >&2; exit 1; }
done
awk --version 2>/dev/null | grep 'GNU Awk' >/dev/null || { echo "SYSTEM ERROR: name.sh: GNU awk (gawk) not found as awk" >&2; exit 1; }
find_sh="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/find.sh"
[[ -f "$find_sh" ]] || { echo "SYSTEM ERROR: name.sh: plugin script not found: $find_sh" >&2; exit 1; }

conf="$HOME/.claude/obsidian-wiki/vault-path"
vault=""
[[ -f "$conf" ]] && vault=$(sed -n '/[^[:space:]]/{p;q;}' "$conf" | tr -d '\r')
vault="${vault#"${vault%%[![:space:]]*}"}"
vault="${vault%"${vault##*[![:space:]]}"}"

if [[ -z "$vault" ]]; then
  echo "USER ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault." >&2
  exit 3
fi
[[ -d "$vault" ]] || { echo "USER ERROR: The configured vault folder does not exist: $vault. Use /wiki-vault:overwrite <vault path> to fix it." >&2; exit 3; }
[[ -f "$vault/CLAUDE.md" ]] || { echo "USER ERROR: The configured vault folder has no CLAUDE.md: $vault. Use /wiki-vault:overwrite <vault path> to fix it." >&2; exit 3; }

# find.sh: exit 0 found, 1 nothing found, 2 usage error.
rc=0
out=$(bash "$find_sh" --vault "$vault" name "$text") || rc=$?
case "$rc" in
  0|1) printf '%s\n' "$out" ;;
  *) echo "SYSTEM ERROR: name.sh: find.sh failed with exit $rc" >&2; exit 1 ;;
esac
