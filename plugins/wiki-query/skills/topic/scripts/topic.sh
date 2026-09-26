#!/usr/bin/env bash
# topic.sh: list vault notes by frontmatter topic, or print the vault CLAUDE.md.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: topic.sh [--inject] <topic>...
       topic.sh [--inject] --rules

List notes in the configured Obsidian vault whose frontmatter topic matches,
one block per topic (case-insensitive, exact value). Read-only.
The vault path comes from ~/.claude/obsidian-wiki/vault-path (set by wiki-vault).
Use it from the topic skill; run it again with the topics the user gives.

arguments:
  <topic>...  one or more topics, space separated
  --rules     print the vault CLAUDE.md instead of a lookup
  --inject    for !`...` injection: report user errors as "ERROR: <text>" on
              stdout with exit 0 (--rules then prints nothing), so the skill
              does not abort
  -h, --help  show this help

output:
  "<topic>:" blocks with "- <note path>" lines, or "Nothing found.".
  No topics: "ERROR: no topic given" (soft fail, exit 0).

exit codes:
  0  done (also when nothing is found)
  1  system error (gawk or find.sh missing, lookup failed)
  2  bad usage (unknown option)
  3  user error (vault path missing, vault folder or its CLAUDE.md missing)

examples: topic.sh EDI      topic.sh ai tooling      topic.sh --inject --rules
EOF
}

sys() { echo "SYSTEM ERROR: topic.sh: $1" >&2; exit 1; }
bad() { echo "SYSTEM ERROR: topic.sh: $1. usage: topic.sh [--inject] <topic>... | --rules | --help" >&2; exit 2; }

inject=0
rules=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --inject) inject=1; shift ;;
    --rules) rules=1; shift ;;
    -*) bad "unknown option: $1" ;;
    *) break ;;
  esac
done
(( rules == 0 || $# == 0 )) || bad "--rules takes no topics"

# User error: hard fail (exit 3), or a soft fail on stdout when injected.
user() {
  (( inject )) || { echo "USER ERROR: $1" >&2; exit 3; }
  (( rules )) || echo "ERROR: $1"
  exit 0
}

# Dependencies first.
find_sh="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/find.sh"
[[ -f "$find_sh" ]] || sys "find.sh not found at $find_sh"
[[ "$(awk --version 2>/dev/null || true)" == *"GNU Awk"* ]] || sys "GNU awk (gawk) is required"

# Vault path, written only by wiki-vault.
conf="$HOME/.claude/obsidian-wiki/vault-path"
vault=""
if [[ -f "$conf" ]]; then IFS= read -r vault < "$conf" || true; fi
vault="${vault//$'\r'/}"
vault="${vault#"${vault%%[![:space:]]*}"}"
vault="${vault%"${vault##*[![:space:]]}"}"
vault="${vault//\\//}"
[[ -n "$vault" ]] || user "Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
[[ -d "$vault" ]] || user "vault folder not found: $vault. Fix it with /wiki-vault:overwrite <vault path>."
[[ -f "$vault/CLAUDE.md" ]] || user "vault folder has no CLAUDE.md: $vault. Fix it with /wiki-vault:overwrite <vault path>."

if (( rules )); then
  cat "$vault/CLAUDE.md"
  exit 0
fi

if [[ $# -eq 0 ]]; then
  echo "ERROR: no topic given"
  exit 0
fi

# find.sh: 0 found, 1 nothing found, 2 usage error.
rc=0
bash "$find_sh" --vault "$vault" topic "$@" || rc=$?
case "$rc" in
  0|1) exit 0 ;;
  2) bad "find.sh rejected the call" ;;
  *) sys "find.sh failed with exit $rc" ;;
esac
