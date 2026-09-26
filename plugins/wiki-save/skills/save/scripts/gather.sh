#!/usr/bin/env bash
# gather.sh: read-only context for wiki-save:save. Injected before the model runs.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: gather.sh

Print the context wiki-save:save needs, as key: value lines, then the vault CLAUDE.md.
Read-only: changes nothing. Reads the vault path from ~/.claude/obsidian-wiki/vault-path.
Used through !` injection at the start of wiki-save:save; run by hand to debug.

output:
  vault: <vault root>
  today: <YYYY-MM-DD>
  draft_file: <free temp path for the note draft, not created>
  topics: <existing topics, comma separated>
  vault_claude_md:
  <content of <vault>/CLAUDE.md>
  Soft fail (exit 0): a single "ERROR: <message>" line, relay it to the user and stop.

exit codes:
  0  context printed, or soft fail (ERROR: line)
  1  system error (missing tool)
  2  bad usage (arguments given)

example: gather.sh
EOF
}

case "${1:-}" in -h|--help) usage; exit 0 ;; esac
[[ $# -eq 0 ]] || { echo "usage: gather.sh (no arguments, see --help)" >&2; exit 2; }

for dep in awk find sort date xargs head tr; do
  command -v "$dep" >/dev/null || { echo "SYSTEM ERROR: gather.sh: $dep not installed" >&2; exit 1; }
done

cfg="$HOME/.claude/obsidian-wiki/vault-path"
vault=$(head -n 1 "$cfg" 2>/dev/null | tr -d '\r' || true)
vault=${vault%/}; vault=${vault%\\}
if [[ -z "$vault" ]]; then
  echo "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
  exit 0
fi
if [[ ! -f "$vault/CLAUDE.md" || ! -d "$vault/01. Inbox" ]]; then
  echo "ERROR: The configured vault $vault has no CLAUDE.md or no 01. Inbox folder. Use /wiki-vault:overwrite <vault path> to fix it."
  exit 0
fi

draft="${TMPDIR:-/tmp}/wiki-save-$(date +%Y%m%d-%H%M%S)-$$.md"
command -v cygpath >/dev/null && draft=$(cygpath -m "$draft")

# Distinct frontmatter topics, skipping dot folders and templates.
topics=$(cd "$vault" && find . -type d \( -name '.?*' -o -path './90. Templates' \) -prune -o \
    -type f -name '*.md' -print0 | xargs -0 -r awk '
  { sub(/\r$/, "") }
  FNR == 1 { infm = ($0 ~ /^---[ \t]*$/); next }
  infm && /^---[ \t]*$/ { infm = 0; nextfile }
  infm && /^topic:/ {
    v = $0; sub(/^topic:[ \t]*/, "", v); gsub(/^["\x27]|["\x27][ \t]*$/, "", v); sub(/[ \t]+$/, "", v)
    if (v != "") print v
  }' | sort -fu | awk 'NR > 1 { printf ", " } { printf "%s", $0 } END { print "" }')

echo "vault: $vault"
echo "today: $(date +%F)"
echo "draft_file: $draft"
echo "topics: $topics"
echo "vault_claude_md:"
tr -d '\r' < "$vault/CLAUDE.md"
