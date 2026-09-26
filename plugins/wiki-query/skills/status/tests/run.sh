#!/usr/bin/env bash
# Tests for status.sh with a temp HOME and a temp copy of the shared fixture vault.
# Quiet on success, exit 1 on any failure.
set -u
here=$(cd "$(dirname "$0")" && pwd)
script="$here/../scripts/status.sh"
fixture="$here/../../../tests/fixture-vault"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0

vault="$tmp/vault"
cp -r "$fixture" "$vault"
printf '# Vault rules\r\nKeep notes short.\r\n' > "$vault/CLAUDE.md"
mkdir -p "$tmp/home/.claude/obsidian-wiki" "$tmp/nohome" "$tmp/noclaude"
printf '  %s  \r\n' "$vault" > "$tmp/home/.claude/obsidian-wiki/vault-path"

# run <home> <args...>: sets out, err, rc
run() {
  local h=$1; shift
  out=$(HOME="$h" bash "$script" "$@" 2>"$tmp/err"); rc=$?
  err=$(cat "$tmp/err")
}
want_rc() { [ "$rc" = "$2" ] || { echo "FAIL $1: exit $rc, want $2"; fail=1; }; }
want_out() { [ "$out" = "$2" ] || { echo "FAIL $1: output differs"; diff <(echo "$out") <(echo "$2"); fail=1; }; }
want_err() { case "$err" in *"$2"*) ;; *) echo "FAIL $1: stderr lacks '$2': $err"; fail=1 ;; esac; }

header="vault: $vault
found: yes
--- vault CLAUDE.md ---
# Vault rules
Keep notes short.

--- end CLAUDE.md ---
--- result ---"

before=$(cd "$vault" && find . -type f -exec md5sum {} + | sort)

# success, separate arguments and one space-separated argument ("$ARGUMENTS")
run "$tmp/home" review draft
want_rc found-separate 0
want_out found-separate "$header
$(cat "$here/../../../tests/expected/status.txt")"
run "$tmp/home" "review draft"
want_rc found-one-string 0
want_out found-one-string "$header
$(cat "$here/../../../tests/expected/status.txt")"

# nothing found is exit 0 with found: no
run "$tmp/home" missing
want_rc nothing 0
want_out nothing "${header/found: yes/found: no}
Nothing found."

# help
run "$tmp/home" --help
want_rc help 0
case "$out" in "usage: status.sh"*) ;; *) echo "FAIL help: no usage line"; fail=1 ;; esac
run "$tmp/home" -h
want_rc help-short 0

# soft user errors: exit 0, one ERROR line
run "$tmp/nohome" review
want_rc no-path 0
want_out no-path "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
mkdir -p "$tmp/empty/.claude/obsidian-wiki"; : > "$tmp/empty/.claude/obsidian-wiki/vault-path"
run "$tmp/empty" review
want_out empty-path "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
mkdir -p "$tmp/gone/.claude/obsidian-wiki"; echo "$tmp/missing" > "$tmp/gone/.claude/obsidian-wiki/vault-path"
run "$tmp/gone" review
want_rc bad-folder 0
case "$out" in "ERROR: Vault folder not found"*) ;; *) echo "FAIL bad-folder: $out"; fail=1 ;; esac
mkdir -p "$tmp/noclaude/.claude/obsidian-wiki"; echo "$fixture" > "$tmp/noclaude/.claude/obsidian-wiki/vault-path"
run "$tmp/noclaude" review
want_rc no-claude-md 0
case "$out" in "ERROR: The vault folder"*"has no CLAUDE.md"*) ;; *) echo "FAIL no-claude-md: $out"; fail=1 ;; esac
run "$tmp/home"
want_rc no-status 0
want_out no-status "ERROR: no status given"
run "$tmp/home" ""
want_out no-status-empty-string "ERROR: no status given"
run "$tmp/home" 'rev;iew'
want_rc invalid 0
case "$out" in "ERROR: invalid status 'rev;iew'"*) ;; *) echo "FAIL invalid: $out"; fail=1 ;; esac

# usage error: exit 2
run "$tmp/home" --bogus
want_rc usage-option 2
want_err usage-option "SYSTEM ERROR:"

# system error: exit 1 when find.sh is missing
mkdir -p "$tmp/plug/skills/status/scripts"
cp "$script" "$tmp/plug/skills/status/scripts/status.sh"
out=$(HOME="$tmp/home" bash "$tmp/plug/skills/status/scripts/status.sh" review 2>&1); rc=$?
want_rc system-no-find 1
case "$out" in *"SYSTEM ERROR: status.sh: find.sh not found"*) ;; *) echo "FAIL system-no-find: $out"; fail=1 ;; esac

# system error: exit 1 when find.sh fails
mkdir -p "$tmp/plug/scripts"
printf 'echo "usage: broken" >&2; exit 2\n' > "$tmp/plug/scripts/find.sh"
out=$(HOME="$tmp/home" bash "$tmp/plug/skills/status/scripts/status.sh" review 2>&1); rc=$?
want_rc system-find-failed 1
case "$out" in *"SYSTEM ERROR: status.sh: find.sh exited 2"*) ;; *) echo "FAIL system-find-failed: $out"; fail=1 ;; esac

after=$(cd "$vault" && find . -type f -exec md5sum {} + | sort)
[ "$before" = "$after" ] || { echo "FAIL vault changed"; fail=1; }

exit $fail
