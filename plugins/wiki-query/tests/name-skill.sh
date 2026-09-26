#!/usr/bin/env bash
# Tests for skills/name/scripts (gather.sh, name.sh) with a temp HOME and a copy
# of the fixture vault. Quiet on success, exit 1 on any failure.
set -u
here=$(cd "$(dirname "$0")" && pwd)
dir="$here/../skills/name/scripts"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0

vault="$tmp/vault"
cp -r "$here/fixture-vault" "$vault"
printf '# Vault rules\r\nBe kind.\r\n' > "$vault/CLAUDE.md"
mkdir -p "$tmp/home/.claude/obsidian-wiki" "$tmp/nocm"
conf="$tmp/home/.claude/obsidian-wiki/vault-path"

# run <case> <want exit> <want stdout or -> <stderr regex or -> <script> <args...>
run() {
  local case=$1 want=$2 wout=$3 werr=$4 script=$5; shift 5
  local out err got
  out=$(HOME="$tmp/home" bash "$dir/$script" "$@" 2>"$tmp/err"); got=$?
  err=$(cat "$tmp/err")
  [ "$got" = "$want" ] || { echo "FAIL $case: exit $got, want $want"; fail=1; }
  [ "$wout" = - ] || [ "$out" = "$wout" ] || { echo "FAIL $case: stdout differs"; diff <(echo "$out") <(echo "$wout"); fail=1; }
  [ "$werr" = - ] || [[ "$err" =~ $werr ]] || { echo "FAIL $case: stderr '$err' does not match '$werr'"; fail=1; }
}

missing="Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."

# --help
run gather-help 0 - - gather.sh --help
run gather-h 0 - - gather.sh -h
run name-help 0 - - name.sh --help
run name-h 0 - - name.sh -h

# vault path missing, empty, folder missing, no CLAUDE.md
run gather-no-conf 0 "ERROR: $missing" '^$' gather.sh
run name-no-conf 3 '' "^USER ERROR: $missing\$" name.sh context
printf '  \r\n\n' > "$conf"
run gather-empty-conf 0 "ERROR: $missing" '^$' gather.sh
run name-empty-conf 3 '' '^USER ERROR: Vault path is missing' name.sh context
printf '%s\n' "$tmp/gone" > "$conf"
run gather-no-folder 0 - - gather.sh
[[ "$(HOME="$tmp/home" bash "$dir/gather.sh")" == "ERROR: The configured vault folder does not exist: "*"/wiki-vault:overwrite"* ]] || { echo "FAIL gather-no-folder: message"; fail=1; }
run name-no-folder 3 '' '^USER ERROR: The configured vault folder does not exist' name.sh context
printf '%s\n' "$tmp/nocm" > "$conf"
run gather-no-claude-md 0 "ERROR: The configured vault folder has no CLAUDE.md: $tmp/nocm. Use /wiki-vault:overwrite <vault path> to fix it." '^$' gather.sh
run name-no-claude-md 3 '' '^USER ERROR: The configured vault folder has no CLAUDE.md' name.sh context

# configured vault, CRLF and surrounding spaces in the vault-path file
printf '  %s  \r\n' "$vault" > "$conf"
run gather-ok 0 "vault: $vault
----- begin vault CLAUDE.md -----
# Vault rules
Be kind.

----- end vault CLAUDE.md -----" '^$' gather.sh

# same output as find.sh, exit 0 also for nothing found
run name-middle 0 "$(cat "$here/expected/name-middle.txt")" '^$' name.sh -- engine
run name-words 0 "$(cat "$here/expected/name-mixed-case-spaces.txt")" '^$' name.sh CONTEXT ENG
run name-alias 0 "$(cat "$here/expected/name-alias-only.txt")" '^$' name.sh sop
run name-nothing 0 "Nothing found." '^$' name.sh -- not a title
run name-dash-text 0 "Nothing found." '^$' name.sh -- -zz-

# usage errors
run gather-args 2 '' '^SYSTEM ERROR: gather.sh' gather.sh extra
run name-no-args 2 '' '^SYSTEM ERROR: name.sh: no text' name.sh
run name-only-dashdash 2 '' '^SYSTEM ERROR: name.sh: no text' name.sh --
run name-blank 2 '' '^SYSTEM ERROR: name.sh: text is empty' name.sh -- "  "

# system error: find.sh missing (copy of the skill scripts without the plugin script)
mkdir -p "$tmp/plug/skills/name/scripts"
cp "$dir/name.sh" "$tmp/plug/skills/name/scripts/"
out=$(HOME="$tmp/home" bash "$tmp/plug/skills/name/scripts/name.sh" context 2>&1); got=$?
[ "$got" = 1 ] && [[ "$out" == "SYSTEM ERROR: name.sh: plugin script not found"* ]] || { echo "FAIL name-no-find-sh: exit $got, '$out'"; fail=1; }

# system error: find.sh fails with an unexpected exit
mkdir -p "$tmp/plug/scripts"
printf '#!/usr/bin/env bash\nexit 2\n' > "$tmp/plug/scripts/find.sh"
out=$(HOME="$tmp/home" bash "$tmp/plug/skills/name/scripts/name.sh" context 2>&1); got=$?
[ "$got" = 1 ] && [[ "$out" == "SYSTEM ERROR: name.sh: find.sh failed with exit 2" ]] || { echo "FAIL name-find-fails: exit $got, '$out'"; fail=1; }

# read-only: the vault copy is unchanged
before=$(cd "$here/fixture-vault" && find . -type f -exec md5sum {} + | sort)
after=$(cd "$vault" && find . -type f ! -name CLAUDE.md -exec md5sum {} + | sort)
[ "$before" = "$after" ] || { echo "FAIL vault changed"; fail=1; }

exit $fail
