#!/usr/bin/env bash
# Tests for the query skill scripts (context.sh, search.sh). Quiet on success, exit 1 on any failure.
set -u
here=$(cd "$(dirname "$0")" && pwd)
scripts="$here/../../skills/query/scripts"
vault="$here/fixture-vault"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0

# check <case> <expected exit> <command...>: compare stdout with expected/<case>.txt
check() {
  local case=$1 want=$2; shift 2
  local out got
  out=$("$@" 2>/dev/null); got=$?
  [ "$got" = "$want" ] || { echo "FAIL $case: exit $got, want $want"; fail=1; }
  [ "$out" = "$(cat "$here/expected/$case.txt")" ] || { echo "FAIL $case: output differs"; diff <(echo "$out") "$here/expected/$case.txt"; fail=1; }
}

# code <case> <expected exit> <stderr prefix or -> <command...>: check exit code and stderr prefix
code() {
  local case=$1 want=$2 prefix=$3; shift 3
  local err got
  err=$("$@" 2>&1 >/dev/null); got=$?
  [ "$got" = "$want" ] || { echo "FAIL $case: exit $got, want $want"; fail=1; }
  [ "$prefix" = - ] || [ "${err#"$prefix"}" != "$err" ] || { echo "FAIL $case: stderr '$err' lacks '$prefix'"; fail=1; }
}

# home <name> [vault-path content]: temp HOME, with a vault-path file when content is given
home() {
  mkdir -p "$tmp/$1/.claude/obsidian-wiki"
  [ $# -lt 2 ] || printf '%s' "$2" > "$tmp/$1/.claude/obsidian-wiki/vault-path"
  echo "$tmp/$1"
}

before=$(cd "$vault" && find . -type f -exec md5sum {} + | sort)
S="$scripts/search.sh" C="$scripts/context.sh"

# search.sh
check search-two-terms 0 bash "$S" --vault "$vault" edi mapping
check search-phrase-limit 0 bash "$S" --vault "$vault" --limit 1 "message mapping"
check search-nothing 0 bash "$S" --vault "$vault" zzzq
check search-dash-term 0 bash "$S" --vault "$vault" -- -orders
code search-limit-leading-zero 2 "SYSTEM ERROR:" bash "$S" --vault "$vault" --limit 08 edi
code search-help 0 - bash "$S" --help
code search-help-short 0 - bash "$S" -h
code search-no-term 2 "SYSTEM ERROR:" bash "$S" --vault "$vault"
code search-no-vault 2 "SYSTEM ERROR:" bash "$S" edi
code search-bad-limit 2 "SYSTEM ERROR:" bash "$S" --vault "$vault" --limit 0 edi
code search-bad-option 2 "SYSTEM ERROR:" bash "$S" --vault "$vault" --color edi
code search-empty-term 2 "SYSTEM ERROR:" bash "$S" --vault "$vault" " "
code search-missing-vault 3 "USER ERROR:" bash "$S" --vault "$vault/missing" edi
code search-no-deps 1 "SYSTEM ERROR:" env PATH=/nonexistent "$BASH" "$S" --vault "$vault" edi

# context.sh
ok=$(home ok "$vault"$'\r\n')
out=$(HOME=$ok bash "$C"); got=$?
[ "$got" = 0 ] && [ "$out" = "$(printf 'vault: %s\n--- vault CLAUDE.md ---\n' "$vault"; cat "$vault/CLAUDE.md")" ] \
  || { echo "FAIL context-ok: exit $got"; echo "$out"; fail=1; }
check context-no-file 0 env HOME="$(home nofile)" bash "$C"
check context-empty 0 env HOME="$(home empty "  ")" bash "$C"
out=$(HOME=$(home noclaude "$here") bash "$C"); got=$?
[ "$got" = 0 ] && [ "$out" = "ERROR: The configured vault folder has no CLAUDE.md: $here. Use /wiki-vault:overwrite <vault path> to fix the vault path." ] \
  || { echo "FAIL context-no-claude: exit $got"; echo "$out"; fail=1; }
code context-help 0 - bash "$C" --help
code context-bad-arg 2 "SYSTEM ERROR:" bash "$C" extra
code context-no-home 1 "SYSTEM ERROR:" env -u HOME bash "$C"

after=$(cd "$vault" && find . -type f -exec md5sum {} + | sort)
[ "$before" = "$after" ] || { echo "FAIL fixture vault changed"; fail=1; }

exit $fail
