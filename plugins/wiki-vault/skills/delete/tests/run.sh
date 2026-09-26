#!/usr/bin/env bash
# Tests for delete.sh with a temp HOME. Quiet on success, exit 1 on any failure.
set -uo pipefail  # no -e: collect every failure before exiting
here=$(cd "$(dirname "$0")" && pwd)
script="$here/../scripts/delete.sh"
tmp=$(mktemp -d)
trap 'chmod -R u+w "$tmp" 2>/dev/null; rm -rf "$tmp"' EXIT
fail=0

# check <case> <expected exit> <expected stdout> <args...>: run with HOME=$tmp/home
check() {
  local case=$1 want=$2 wantout=$3; shift 3
  local out got
  out=$(HOME="$tmp/home" bash "$script" "$@" 2>"$tmp/err"); got=$?
  [ "$got" = "$want" ] || { echo "FAIL $case: exit $got, want $want"; fail=1; }
  [ "$out" = "$wantout" ] || { echo "FAIL $case: stdout '$out', want '$wantout'"; fail=1; }
}
# errline <case> <prefix>: stderr is one line starting with prefix
errline() {
  [ "$(wc -l < "$tmp/err")" -eq 1 ] && grep -q "^$2" "$tmp/err" || { echo "FAIL $1: stderr '$(cat "$tmp/err")'"; fail=1; }
}
setup() { rm -rf "$tmp/home"; mkdir -p "$tmp/home/.claude/obsidian-wiki"; }
cfg="$tmp/home/.claude/obsidian-wiki/vault-path"

# removed: path, file gone, vault untouched
setup; mkdir -p "$tmp/vault"; echo keep > "$tmp/vault/note.md"
printf '%s\n' "$tmp/vault" > "$cfg"
check removed 0 "removed: $tmp/vault"
[ ! -e "$cfg" ] || { echo "FAIL removed: file still there"; fail=1; }
[ "$(cat "$tmp/vault/note.md")" = keep ] || { echo "FAIL removed: vault changed"; fail=1; }

# idempotent: second run reports none
check again 0 "removed: none"

# no config folder at all
rm -rf "$tmp/home"; mkdir -p "$tmp/home"
check no-folder 0 "removed: none"

# path with spaces and CRLF ending
setup; printf 'C:/My Vault/Wiki\r\n' > "$cfg"
check crlf-spaces 0 "removed: C:/My Vault/Wiki"

# empty file: removed, reported as none
setup; : > "$cfg"
check empty 0 "removed: none"
[ ! -e "$cfg" ] || { echo "FAIL empty: file still there"; fail=1; }

# whitespace-only file: reported as none
setup; printf '  \t\n' > "$cfg"
check blank 0 "removed: none"

# help
check help 0 "$(HOME="$tmp/home" bash "$script" --help)" --help
HOME="$tmp/home" bash "$script" -h | grep -q '^usage: delete.sh' || { echo "FAIL -h"; fail=1; }

# exit 2: any argument, file untouched
setup; printf '%s\n' /v > "$cfg"
check usage 2 "" extra
errline usage "SYSTEM ERROR:"
[ -e "$cfg" ] || { echo "FAIL usage: file removed"; fail=1; }

# exit 1: HOME unset
out=$(env -u HOME bash "$script" 2>"$tmp/err"); got=$?
[ "$got" = 1 ] && [ -z "$out" ] || { echo "FAIL no-home: exit $got"; fail=1; }
errline no-home "SYSTEM ERROR:"

# exit 1: vault-path is a folder
setup; rm -f "$cfg"; mkdir "$cfg"
check not-file 1 ""
errline not-file "SYSTEM ERROR:"

exit $fail
