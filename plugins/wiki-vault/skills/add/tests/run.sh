#!/usr/bin/env bash
# Tests for status.sh and add.sh with a temp HOME. Quiet on success, exit 1 on any failure.
set -u
here=$(cd "$(dirname "$0")" && pwd)
status="$here/../scripts/status.sh"
add="$here/../scripts/add.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
vault="$tmp/My Vault"
mkdir -p "$vault"
fail=0

# run <case> <expected exit> <expected stdout> <expected stderr substring> <command...>
run() {
  local case=$1 want=$2 wout=$3 werr=$4; shift 4
  local out err got
  out=$("$@" 2>"$tmp/err"); got=$?
  err=$(cat "$tmp/err")
  [ "$got" = "$want" ] || { echo "FAIL $case: exit $got, want $want ($err)"; fail=1; }
  [ "$out" = "$wout" ] || { echo "FAIL $case: stdout '$out', want '$wout'"; fail=1; }
  [ -z "$werr" ] || [[ "$err" == *"$werr"* ]] || { echo "FAIL $case: stderr '$err', want '*$werr*'"; fail=1; }
}

# stored <case> <expected file content>
stored() {
  local got
  got=$(cat "$tmp/home/.claude/obsidian-wiki/vault-path" 2>/dev/null)
  [ "$got" = "$2" ] || { echo "FAIL $1: stored '$got', want '$2'"; fail=1; }
}

fresh() { rm -rf "$tmp/home"; mkdir -p "$tmp/home"; }
H() { HOME="$tmp/home" "$@"; }

# help
run status-help 0 "$(bash "$status" --help)" "" bash "$status" -h
run add-help 0 "$(bash "$add" --help)" "" bash "$add" -h
[[ "$(bash "$add" --help)" == usage:* ]] || { echo "FAIL add-help: no usage line"; fail=1; }

# status: none, then configured, empty file counts as none
fresh
run status-none 0 "configured: none" "" H bash "$status"
mkdir -p "$tmp/home/.claude/obsidian-wiki"; : > "$tmp/home/.claude/obsidian-wiki/vault-path"
run status-empty 0 "configured: none" "" H bash "$status"
printf 'C:/Vault\r\n' > "$tmp/home/.claude/obsidian-wiki/vault-path"
run status-set 0 "configured: C:/Vault" "" H bash "$status"
run status-usage 2 "" "usage:" H bash "$status" extra
run status-no-home 1 "" "SYSTEM ERROR:" env -u HOME bash "$status"

# add: success with spaces and backslashes
fresh
winpath="${vault//\//\\}"
run add-ok 0 "configured: $vault
folder: found" "" H bash "$add" "$winpath"
stored add-ok "$vault"

# add: never changes an existing path, also idempotent on the same path
run add-already 3 "" "USER ERROR: add.sh: already configured: $vault" H bash "$add" "$tmp/other"
run add-already-same 3 "" "already configured" H bash "$add" "$vault"
stored add-already "$vault"

# add: empty file counts as not configured
fresh
mkdir -p "$tmp/home/.claude/obsidian-wiki"; : > "$tmp/home/.claude/obsidian-wiki/vault-path"
run add-empty-file 0 "configured: $vault
folder: found" "" H bash "$add" "$vault"

# add: missing folder is a user error, --allow-missing stores it
fresh
run add-missing 3 "" "USER ERROR: add.sh: folder not found: $tmp/nope" H bash "$add" "$tmp/nope"
[ ! -e "$tmp/home/.claude/obsidian-wiki/vault-path" ] || { echo "FAIL add-missing: file written"; fail=1; }
run add-allow-missing 0 "configured: $tmp/nope
folder: missing" "" H bash "$add" --allow-missing "$tmp/nope"
stored add-allow-missing "$tmp/nope"

# add: -- ends options, so a path that looks like an option is still a path
fresh
run add-dashdash 0 "configured: -h
folder: missing" "" H bash "$add" --allow-missing -- -h
stored add-dashdash "-h"

# add: usage errors write nothing
fresh
run add-no-args 2 "" "expected one vault path" H bash "$add"
run add-two-args 2 "" "expected one vault path" H bash "$add" a b
run add-empty 2 "" "empty vault path" H bash "$add" ""
run add-newline 2 "" "newline" H bash "$add" "$vault
x"
run add-bad-option 2 "" "unknown option" H bash "$add" --force "$vault"
[ ! -e "$tmp/home/.claude" ] || { echo "FAIL usage: something written"; fail=1; }

# add: system errors
run add-no-home 1 "" "SYSTEM ERROR:" env -u HOME bash "$add" "$vault"
fresh
mkdir -p "$tmp/home/.claude/obsidian-wiki/vault-path"
run add-not-file 1 "" "SYSTEM ERROR:" H bash "$add" "$vault"

# the vault itself is never touched
[ -z "$(ls -A "$vault")" ] || { echo "FAIL vault changed"; fail=1; }

exit $fail
