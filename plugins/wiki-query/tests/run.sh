#!/usr/bin/env bash
# Tests for find.sh against the fixture vault. Quiet on success, exit 1 on any failure.
set -u
here=$(cd "$(dirname "$0")" && pwd)
find="$here/../scripts/find.sh"
vault="$here/fixture-vault"
fail=0

# check <case> <expected exit> <args...>: compare stdout with expected/<case>.txt
check() {
  local case=$1 want=$2; shift 2
  local out got
  out=$(bash "$find" --vault "$vault" "$@"); got=$?
  [ "$got" = "$want" ] || { echo "FAIL $case: exit $got, want $want"; fail=1; }
  [ "$out" = "$(cat "$here/expected/$case.txt")" ] || { echo "FAIL $case: output differs"; diff <(echo "$out") "$here/expected/$case.txt"; fail=1; }
}

# code <case> <expected exit> <command...>: only check the exit code
code() {
  local case=$1 want=$2; shift 2
  "$@" >/dev/null 2>&1; local got=$?
  [ "$got" = "$want" ] || { echo "FAIL $case: exit $got, want $want"; fail=1; }
}

before=$(cd "$vault" && find . -type f -exec md5sum {} + | sort)

check name-middle 0 name engine
check name-mixed-case-spaces 0 name CONTEXT ENG
check name-filename-beats-alias 0 name context
check name-title 0 name mapping
check name-title-after-code 0 name loose
check name-alias-only 0 name sop
check nothing 1 name not a title
check tag-several 0 tag ai tooling missing
check tag-mixed-case 0 tag AI
check nothing 1 tag missing
check topic 0 topic EDI
check status 0 status review draft

# usage errors
code usage-no-args 2 bash "$find" --vault "$vault"
code usage-unknown-field 2 bash "$find" --vault "$vault" color red
code usage-no-value 2 bash "$find" --vault "$vault" tag
code usage-bad-vault 2 bash "$find" --vault "$vault/missing" tag ai
code usage-no-vault 2 bash "$find" tag ai

after=$(cd "$vault" && find . -type f -exec md5sum {} + | sort)
[ "$before" = "$after" ] || { echo "FAIL fixture vault changed"; fail=1; }

bash "$here/name-skill.sh" || fail=1

exit $fail
