#!/usr/bin/env bash
# tag.sh ['<tag> <tag>...']: gather everything the tag skill needs in one read-only call.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: tag.sh ['<tag> <tag>...']

List notes in the configured Obsidian vault by frontmatter tag, one block per tag.
Read-only. Reads the vault path from ~/.claude/obsidian-wiki/vault-path, prints the
vault CLAUDE.md, then the lookup result of find.sh. Injected by the tag skill.

arguments:
  tags  one quoted string (or several arguments) with tags separated by spaces,
        case-insensitive, a leading # is ignored. Allowed: letters, digits, _ - /
        and other characters except spaces, quotes, brackets and shell symbols.

output (stdout, key: value):
  ERROR: <message>   soft fail, relay the message as-is
  need: tags         no tag given, ask the user for tags and rerun
  vault: <dir>, found: yes|no, then claude-md and result blocks

exit codes:
  0  done (also for "Nothing found.", ERROR: and need: lines)
  1  system error (missing tool, find.sh missing or failed)
  There is no usage error: every argument except -h/--help is read as tags.

example: tag.sh 'ai #tooling'
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
esac

for dep in find xargs awk tr mktemp; do
  command -v "$dep" >/dev/null || { echo "SYSTEM ERROR: tag.sh: $dep not installed" >&2; exit 1; }
done
# find.sh is shared by all wiki-query skills and lives in the plugin root.
find_sh="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/find.sh"
[[ -f "$find_sh" ]] || { echo "SYSTEM ERROR: tag.sh: find.sh not found at $find_sh" >&2; exit 1; }

# Vault path, configured only by wiki-vault. Soft fail so the model can relay it.
path_file="$HOME/.claude/obsidian-wiki/vault-path"
vault=
[[ -f "$path_file" ]] && vault=$(tr -d '\r' < "$path_file" | awk 'NF { sub(/^[ \t]+/, ""); sub(/[ \t]+$/, ""); print; exit }')
if [[ -z "$vault" ]]; then
  echo "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
  exit 0
fi
if [[ ! -f "$vault/CLAUDE.md" ]]; then
  echo "ERROR: The configured vault folder $vault does not contain CLAUDE.md. Use /wiki-vault:overwrite <vault path> to point to the right folder."
  exit 0
fi

# Tags: split every argument on whitespace (no glob expansion), drop a leading #.
bad='[][[:space:]#,;|&<>(){}"'\''`$*?\\]'
tags=()
set -f
for arg in "$@"; do
  for t in $arg; do
    t=${t#\#}
    [[ -z "$t" ]] && continue
    if [[ "$t" =~ $bad ]]; then
      echo "ERROR: Invalid tag '$t'. Use letters, digits, _ - or /, separated by spaces."
      exit 0
    fi
    tags+=("$t")
  done
done
set +f

if [[ ${#tags[@]} -eq 0 ]]; then
  echo "vault: $vault"
  echo "need: tags"
  exit 0
fi

rc=0
errfile=$(mktemp)
trap 'rm -f "$errfile"' EXIT
result=$(bash "$find_sh" --vault "$vault" tag "${tags[@]}" 2>"$errfile") || rc=$?
case $rc in
  0) found=yes ;;
  1) found=no ;;
  *) echo "SYSTEM ERROR: tag.sh: find.sh failed (exit $rc): $(head -2 "$errfile" | tr '\n' ' ')" >&2; exit 1 ;;
esac

echo "vault: $vault"
echo "found: $found"
echo "claude-md: begin"
awk '{ sub(/\r$/, ""); print }' "$vault/CLAUDE.md"
echo "claude-md: end"
echo "result: begin"
printf '%s\n' "$result"
echo "result: end"
