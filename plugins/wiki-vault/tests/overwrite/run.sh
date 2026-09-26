#!/usr/bin/env bash
# Tests for skills/overwrite/scripts/overwrite.sh. Uses a temp HOME only.
# Quiet on success, exit 1 on any failure.
set -u
here=$(cd "$(dirname "$0")" && pwd)
script="$here/../../skills/overwrite/scripts/overwrite.sh"
tmp=$(mktemp -d)
trap 'chmod -R u+w "$tmp" 2>/dev/null; rm -rf "$tmp"' EXIT
vault="$tmp/My Vault"
other="$tmp/Other"
mkdir -p "$vault" "$other"
export HOME="$tmp/home"
cfg="$HOME/.claude/obsidian-wiki/vault-path"
fail=0

# run <case> <want exit> <want stdout> <args...>
run() {
  local case=$1 want=$2 wantout=$3; shift 3
  local out got
  out=$(bash "$script" "$@" 2>"$tmp/err"); got=$?
  [ "$got" = "$want" ] || { echo "FAIL $case: exit $got, want $want ($(cat "$tmp/err"))"; fail=1; }
  [ "$out" = "$wantout" ] || { echo "FAIL $case: stdout '$out', want '$wantout'"; fail=1; }
}
# cfgis <case> <want content or MISSING>
cfgis() {
  local got=MISSING
  [ -f "$cfg" ] && got=$(cat "$cfg")
  [ "$got" = "$2" ] || { echo "FAIL $1: config '$got', want '$2'"; fail=1; }
}
# errhas <case> <text>
errhas() { grep -qF -- "$2" "$tmp/err" || { echo "FAIL $1: stderr lacks '$2'"; fail=1; }; }

# help
run help 0 "$(bash "$script" --help)" -h
bash "$script" --help | grep -q '^usage: overwrite.sh' || { echo "FAIL help: no usage line"; fail=1; }

# bad usage, exit 2, nothing written
run no-args 2 ""
errhas no-args "SYSTEM ERROR:"
run two-args 2 "" "$vault" "$other"
run bad-option 2 "" --nope "$vault"
run empty-arg 2 "" ""
cfgis usage-no-write MISSING

# user errors, exit 3, nothing written
run relative 3 "" "some/folder"
errhas relative "USER ERROR: vault path is not absolute"
run missing-folder 3 "" "$tmp/nope"
errhas missing-folder "USER ERROR: folder not found: $tmp/nope"
cfgis user-error-no-write MISSING

# first save, no old path, config folder created
run first 0 "path: $vault"$'\n'"old: none" "$vault"
cfgis first "$vault"

# overwrite shows the old path
run replace 0 "path: $other"$'\n'"old: $vault" "$other"
cfgis replace "$other"

# idempotent
run same 0 "path: $other"$'\n'"old: $other" "$other"
cfgis same "$other"

# backslashes and trailing slashes normalized
win='C:\Users\me\Vault\'
run backslash 0 "path: C:/Users/me/Vault"$'\n'"old: $other" --force "$win"
cfgis backslash "C:/Users/me/Vault"

# missing folder with --force is saved, option after the path works too
run force 0 "path: $tmp/nope"$'\n'"old: C:/Users/me/Vault" "$tmp/nope" --force
cfgis force "$tmp/nope"

# missing folder without --force keeps the old path
run keep-old 3 "" "$tmp/nope2"
cfgis keep-old "$tmp/nope"

# old config with CRLF is read cleanly
printf '%s\r\n' "$vault" > "$cfg"
run crlf-old 0 "path: $other"$'\n'"old: $vault" "$other"

# system error: config folder cannot be created, exit 1
HOME="$tmp/blocked" ; export HOME
mkdir -p "$HOME" && : > "$HOME/.claude"
run system-error 1 "" "$vault"
errhas system-error "SYSTEM ERROR:"
HOME="$tmp/home"

# no temp files left behind
ls "$tmp/home/.claude/obsidian-wiki" | grep -q tmp && { echo "FAIL tmp-left"; fail=1; }

# script hygiene
grep -q $'\r' "$script" && { echo "FAIL crlf: script has CRLF"; fail=1; }
bash -n "$script" || { echo "FAIL syntax"; fail=1; }

exit $fail
