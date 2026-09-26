#!/usr/bin/env bash
# status.sh <status>...: gather everything the status skill needs in one read-only run.
# Built for !`...` injection: user errors are soft fails (exit 0, "ERROR: ..." on stdout).
set -euo pipefail

usage() {
  cat <<'EOF'
usage: status.sh <status>...

List notes in the configured Obsidian vault by frontmatter status. Read-only.
Reads the vault path from $HOME/.claude/obsidian-wiki/vault-path, prints the
vault CLAUDE.md and the lookup result of find.sh. Run by the status skill.

arguments:
  <status>  one or more of draft, review, evergreen, archived (any word of
            letters, digits, _ or -). Several may also come as one
            space-separated argument.

output (stdout):
  vault: <path>, found: yes|no, then the vault CLAUDE.md between
  "--- vault CLAUDE.md ---" and "--- end CLAUDE.md ---", then the lookup
  result after "--- result ---".
  A user error prints one line "ERROR: <message>" instead, with exit 0.

exit codes:
  0  done (also for "Nothing found." and for ERROR: lines)
  1  system error (find.sh or gawk missing, find.sh failed)
  2  bad usage (unknown option)

example: status.sh review draft
EOF
}

soft() { echo "ERROR: $1"; exit 0; }

# Split all arguments on whitespace, so "$ARGUMENTS" may arrive as one string.
read -r -a words <<< "$*" || true
for w in ${words[@]+"${words[@]}"}; do
  case "$w" in
    -h|--help) usage; exit 0 ;;
    -*) echo "SYSTEM ERROR: status.sh: unknown option '$w'" >&2; usage >&2; exit 2 ;;
  esac
done

# Dependencies first.
here=$(cd "$(dirname "$0")" && pwd)
find_sh="$here/../../../scripts/find.sh"
[ -f "$find_sh" ] || { echo "SYSTEM ERROR: status.sh: find.sh not found at $find_sh" >&2; exit 1; }
{ awk --version 2>/dev/null || true; } | grep -q GNU \
  || { echo "SYSTEM ERROR: status.sh: find.sh needs GNU awk as awk" >&2; exit 1; }

# Vault path, configured by wiki-vault only.
path_file="$HOME/.claude/obsidian-wiki/vault-path"
vault=
[ -f "$path_file" ] && vault=$(tr -d '\r' < "$path_file" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | head -n 1)
[ -n "$vault" ] || soft "Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
[ -d "$vault" ] || soft "Vault folder not found: $vault. Use /wiki-vault:overwrite <vault path> to fix it."
[ -f "$vault/CLAUDE.md" ] || soft "The vault folder $vault has no CLAUDE.md. Use /wiki-vault:overwrite <vault path> to point to the right vault."

# Statuses.
[ ${#words[@]} -ge 1 ] || soft "no status given"
for w in "${words[@]}"; do
  [[ "$w" =~ ^[A-Za-z0-9_-]+$ ]] || soft "invalid status '$w': use words of letters, digits, _ or -"
done

# Lookup. find.sh exits 0 found, 1 nothing found, 2 usage error.
rc=0
result=$(bash "$find_sh" --vault "$vault" status "${words[@]}" 2>&1) || rc=$?
case $rc in
  0) found=yes ;;
  1) found=no ;;
  *) echo "SYSTEM ERROR: status.sh: find.sh exited $rc: $result" >&2; exit 1 ;;
esac

echo "vault: $vault"
echo "found: $found"
echo "--- vault CLAUDE.md ---"
tr -d '\r' < "$vault/CLAUDE.md"
echo
echo "--- end CLAUDE.md ---"
echo "--- result ---"
printf '%s\n' "$result"
