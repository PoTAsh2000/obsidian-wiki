#!/usr/bin/env bash
# Tests for skills/topic/scripts/topic.sh with a temp HOME and a copy of the fixture vault.
# Quiet on success, exit 1 on any failure.
set -u
here=$(cd "$(dirname "$0")" && pwd)
script="$here/../skills/topic/scripts/topic.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0

vault="$tmp/vault"
cp -r "$here/fixture-vault" "$vault"
printf '# Vault rules\nNever write.\n' > "$vault/CLAUDE.md"
home="$tmp/home"
mkdir -p "$home/.claude/obsidian-wiki"
conf="$home/.claude/obsidian-wiki/vault-path"
printf '%s\n' "$vault" > "$conf"

# run <case> <expected exit> <expected stdout> <args...>
run() {
  local case=$1 want=$2 wantout=$3; shift 3
  local out got
  out=$(HOME="$home" bash "$script" "$@" 2>"$tmp/err"); got=$?
  [ "$got" = "$want" ] || { echo "FAIL $case: exit $got, want $want: $(cat "$tmp/err")"; fail=1; }
  [ "$out" = "$wantout" ] || { echo "FAIL $case: output differs"; diff <(echo "$out") <(echo "$wantout"); fail=1; }
}
# err <case> <expected stderr prefix>: check stderr of the last run
err() { grep -q "^$2" "$tmp/err" || { echo "FAIL $1: stderr '$(cat "$tmp/err")' lacks '$2'"; fail=1; }; }

before=$(cd "$vault" && find . -type f -exec md5sum {} + | sort)

run found 0 "$(cat "$here/expected/topic.txt")" EDI
run found-lower 0 "$(sed 's/^EDI:/edi:/' "$here/expected/topic.txt")" edi
run several 0 "$(cat "$here/expected/topic.txt"; printf '%s\n' 'missing:' '- nothing found')" EDI missing
run nothing 0 "Nothing found." missing
run no-topic 0 "ERROR: no topic given"
run no-topic-inject 0 "ERROR: no topic given" --inject
run inject-found 0 "$(cat "$here/expected/topic.txt")" --inject EDI
run rules 0 "$(cat "$vault/CLAUDE.md")" --rules
run rules-inject 0 "$(cat "$vault/CLAUDE.md")" --inject --rules
run help 0 "$(HOME="$home" bash "$script" -h)" --help
[ -n "$(HOME="$home" bash "$script" --help)" ] || { echo "FAIL help: empty"; fail=1; }

# usage errors
run bad-option 2 "" --color; err bad-option "SYSTEM ERROR: topic.sh: unknown option"
run rules-extra 2 "" --rules EDI; err rules-extra "SYSTEM ERROR: topic.sh: --rules takes"
run rules-inject-order 0 "$(cat "$vault/CLAUDE.md")" --rules --inject

# vault path given with CRLF, backslashes and spaces around it
printf '  %s \r\n' "${vault//\//\\}" > "$conf"
run crlf-backslash 0 "$(cat "$here/expected/topic.txt")" EDI
printf '%s\n' "$vault" > "$conf"

# user errors
rm "$conf"
run no-config 3 "" EDI; err no-config "USER ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault.$"
: > "$conf"
run empty-config 3 "" --rules; err empty-config "USER ERROR: Vault path is missing."
printf '%s\n' "$tmp/nope" > "$conf"
run no-folder 3 "" EDI; err no-folder "USER ERROR: vault folder not found"
mkdir "$tmp/bare"; printf '%s\n' "$tmp/bare" > "$conf"
run no-claude-md 3 "" EDI; err no-claude-md "USER ERROR: vault folder has no CLAUDE.md"
run no-claude-md-inject 0 "ERROR: vault folder has no CLAUDE.md: $tmp/bare. Fix it with /wiki-vault:overwrite <vault path>." --inject EDI
rm "$conf"
run no-config-inject 0 "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault." --inject EDI
run no-config-inject-rules 0 "" --inject --rules
printf '%s' "$vault" > "$conf"
run no-newline-config 0 "Nothing found." missing

# system error: find.sh missing
mkdir -p "$tmp/plugin/skills/topic/scripts"
cp "$script" "$tmp/plugin/skills/topic/scripts/"
out=$(HOME="$home" bash "$tmp/plugin/skills/topic/scripts/topic.sh" EDI 2>"$tmp/err"); got=$?
[ "$got" = 1 ] || { echo "FAIL no-find-sh: exit $got, want 1"; fail=1; }
err no-find-sh "SYSTEM ERROR: topic.sh: find.sh not found"
# system error: find.sh crashes
mkdir -p "$tmp/plugin/scripts"; printf 'exit 5\n' > "$tmp/plugin/scripts/find.sh"
out=$(HOME="$home" bash "$tmp/plugin/skills/topic/scripts/topic.sh" EDI 2>"$tmp/err"); got=$?
[ "$got" = 1 ] || { echo "FAIL find-sh-crash: exit $got, want 1"; fail=1; }
err find-sh-crash "SYSTEM ERROR: topic.sh: find.sh failed with exit 5"

after=$(cd "$vault" && find . -type f -exec md5sum {} + | sort)
[ "$before" = "$after" ] || { echo "FAIL vault changed"; fail=1; }

exit $fail
