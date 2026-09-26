#!/usr/bin/env bash
# Tests for tag.sh with a temp HOME and a copy of the wiki-query fixture vault.
# Quiet on success, exit 1 on any failure.
set -u
here=$(cd "$(dirname "$0")" && pwd)
tag="$here/../scripts/tag.sh"
plugin="$here/../../.."
expected="$plugin/tests/expected"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0

export HOME="$tmp/home"
mkdir -p "$HOME/.claude/obsidian-wiki"
vault="$tmp/vault"
cp -r "$plugin/tests/fixture-vault" "$vault"
printf '# Vault rules\nEnglish only.\n' > "$vault/CLAUDE.md"
bare="$tmp/bare"; mkdir -p "$bare"

# run <case> <expected exit> <args...>: sets $out
run() {
  local case=$1 want=$2; shift 2
  out=$(bash "$tag" "$@" 2>"$tmp/err"); local got=$?
  [ "$got" = "$want" ] || { echo "FAIL $case: exit $got, want $want"; cat "$tmp/err"; fail=1; }
}
# has <case> <line>: $out contains the exact line
has() { grep -qxF -- "$2" <<< "$out" || { echo "FAIL $1: missing line '$2'"; echo "$out"; fail=1; }; }
# result <case> <expected file>: result block equals the expected file
result() {
  local got; got=$(sed -n '/^result: begin$/,/^result: end$/p' <<< "$out" | sed '1d;$d')
  [ "$got" = "$(cat "$2")" ] || { echo "FAIL $1: result differs"; diff <(echo "$got") "$2"; fail=1; }
}

before=$(cd "$vault" && find . -type f -exec md5sum {} + | sort)

run help 0 --help; has help "usage: tag.sh ['<tag> <tag>...']"
run help-short 0 -h; has help-short "usage: tag.sh ['<tag> <tag>...']"

run no-path-file 0 ai
has no-path-file "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
: > "$HOME/.claude/obsidian-wiki/vault-path"
run empty-path-file 0 ai
has empty-path-file "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."

printf '%s\n' "$bare" > "$HOME/.claude/obsidian-wiki/vault-path"
run no-claude-md 0 ai
grep -q '^ERROR: .*does not contain CLAUDE.md.*/wiki-vault:overwrite' <<< "$out" || { echo "FAIL no-claude-md: $out"; fail=1; }

printf '%s\r\n' "$vault" > "$HOME/.claude/obsidian-wiki/vault-path"
run no-tags 0; has no-tags "need: tags"

run several 0 ai tooling missing
has several "found: yes"; has several "claude-md: begin"; has several "English only."
result several "$expected/tag-several.txt"
run mixed-case-hash 0 '#AI'; result mixed-case-hash "$expected/tag-mixed-case.txt"
run nothing 0 missing; has nothing "found: no"; result nothing "$expected/nothing.txt"

run invalid-tag 0 'a;b'; grep -q "^ERROR: Invalid tag 'a;b'" <<< "$out" || { echo "FAIL invalid-tag: $out"; fail=1; }
run bracket-tag 0 '[x]'; grep -q '^ERROR: Invalid tag' <<< "$out" || { echo "FAIL bracket-tag: $out"; fail=1; }
run only-hash 0 '#'; has only-hash "need: tags"
run nested-tag 0 'area/sub'; has nested-tag "found: no"
run dash-tag 0 '-ai'; has dash-tag "found: no"

# Injection form: SKILL.md pastes the arguments into '...' as one string.
inject() { out=$(bash -c "bash '$tag' '$1'" 2>"$tmp/err"); }
inject 'ai tooling missing'; result inject-several "$expected/tag-several.txt"
inject '#AI'; result inject-hash "$expected/tag-mixed-case.txt"
inject ''; has inject-empty "need: tags"
inject '*'; grep -q '^ERROR: Invalid tag' <<< "$out" || { echo "FAIL inject-glob: $out"; fail=1; }
inject 'a;b'; grep -q '^ERROR: Invalid tag' <<< "$out" || { echo "FAIL inject-semicolon: $out"; fail=1; }

# find.sh missing: copy tag.sh into a tree without scripts/find.sh
mkdir -p "$tmp/p/skills/tag/scripts"; cp "$tag" "$tmp/p/skills/tag/scripts/"
out=$(bash "$tmp/p/skills/tag/scripts/tag.sh" ai 2>"$tmp/err"); got=$?
[ "$got" = 1 ] && grep -q '^SYSTEM ERROR:' "$tmp/err" || { echo "FAIL no-find-sh: exit $got"; fail=1; }

# find.sh fails with exit 5: stub it
mkdir -p "$tmp/p/scripts"; printf 'echo boom >&2; exit 5\n' > "$tmp/p/scripts/find.sh"
out=$(bash "$tmp/p/skills/tag/scripts/tag.sh" ai 2>"$tmp/err"); got=$?
[ "$got" = 1 ] && grep -q '^SYSTEM ERROR:.*exit 5.*boom' "$tmp/err" || { echo "FAIL find-sh-fails: exit $got"; fail=1; }

after=$(cd "$vault" && find . -type f -exec md5sum {} + | sort)
[ "$before" = "$after" ] || { echo "FAIL vault changed"; fail=1; }

exit $fail
