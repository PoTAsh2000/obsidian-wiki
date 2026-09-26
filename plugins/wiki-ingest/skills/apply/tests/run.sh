#!/usr/bin/env bash
# Tests for gather.sh and apply.sh. Uses a temp HOME and a copy of the fixture vault.
# Quiet on success, lists every failure and exits 1 otherwise.
set -u
here=$(cd "$(dirname "$0")" && pwd)
gather="$here/../scripts/gather.sh"
apply="$here/../scripts/apply.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fails=0
fail() { echo "FAIL: $*"; fails=$((fails + 1)); }
sums() { (cd "$1" && find . -type f -print0 | sort -z | xargs -0 md5sum); }
export HOME="$tmp/home"
cfg="$HOME/.claude/obsidian-wiki"
fresh() { rm -rf "$tmp/v" "$HOME"; cp -r "$here/fixture-vault" "$tmp/v"; mkdir -p "$cfg"; printf '%s\n' "$tmp/v" > "$cfg/vault-path"; }

# run <script> <args...>: sets out, err, rc
run() { local s=$1; shift; out=$(bash "$s" "$@" 2>"$tmp/err"); rc=$?; err=$(cat "$tmp/err"); }
# expect <case> <want rc> <want stdout> [stderr prefix]
expect() {
  [ "$rc" = "$2" ] || fail "$1: exit $rc, want $2"
  [ "$out" = "$3" ] || { fail "$1: stdout differs"; diff <(printf '%s\n' "$3") <(printf '%s\n' "$out"); }
  [ -z "${4:-}" ] || [[ "$err" == "$4"* ]] || fail "$1: stderr '$err' does not start with '$4'"
}
unchanged() { [ "$before" = "$(sums "$tmp/v")" ] || fail "$1: vault changed"; }

missing="ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."

# gather.sh
fresh; before=$(sums "$tmp/v")
run "$gather" --help; [ "$rc" = 0 ] && [[ "$out" == usage:* ]] || fail "gather --help"
run "$gather" -h; [ "$rc" = 0 ] || fail "gather -h exit $rc"
run "$gather" extra; expect gather-usage 2 "" "SYSTEM ERROR:"
run "$gather"; expect gather-ok 0 "vault: $tmp/v
--- vault CLAUDE.md ---
$(cat "$tmp/v/CLAUDE.md")"
printf '%s\r\n' "$tmp/v" > "$cfg/vault-path"
run "$gather"; [ "$rc" = 0 ] && [[ "$out" == "vault: $tmp/v"$'\n'* ]] || fail "gather-crlf-path"
: > "$cfg/vault-path"; run "$gather"; expect gather-empty-path 0 "$missing"
rm -f "$cfg/vault-path"; run "$gather"; expect gather-no-path 0 "$missing"
printf '%s\n' "$tmp" > "$cfg/vault-path"; run "$gather"
expect gather-no-claude-md 0 "ERROR: The vault folder $tmp has no CLAUDE.md. Check the path with /wiki-vault:overwrite <vault path>."
unchanged gather

# apply.sh: usage and system errors change nothing
fresh; before=$(sums "$tmp/v")
run "$apply" --help; [ "$rc" = 0 ] && [[ "$out" == usage:* ]] || fail "apply --help"
run "$apply" -h; [ "$rc" = 0 ] || fail "apply -h exit $rc"
run "$apply" Twin Draft; expect apply-usage 2 "" "SYSTEM ERROR:"
rm -f "$cfg/vault-path"; run "$apply"; expect apply-no-path 1 "" "SYSTEM ERROR:"
printf '%s\n' "$tmp" > "$cfg/vault-path"; run "$apply"; expect apply-no-claude-md 1 "" "SYSTEM ERROR:"
printf '%s\n' "$tmp/v" > "$cfg/vault-path"

# apply.sh: user errors change nothing
run "$apply" Missing; expect apply-not-found 3 "" "USER ERROR:"
run "$apply" Evergreen; expect apply-evergreen 3 "" "USER ERROR: apply.sh: 30. Knowledge/Evergreen.md has status evergreen"
run "$apply" draft; expect apply-draft 3 "" "USER ERROR: apply.sh: 01. Inbox/Draft.md has status draft"
run "$apply" "Body Status"; expect apply-body-status 3 "" "USER ERROR:"
run "$apply" "No Status"; expect apply-no-status 3 "" "USER ERROR: apply.sh: 30. Knowledge/No Status.md has no status"
run "$apply" "No Frontmatter"; expect apply-no-frontmatter 3 "" "USER ERROR:"
run "$apply" Hidden; expect apply-dot-folder 3 "" "USER ERROR: apply.sh: no note named"
run "$apply" twin; expect apply-several 3 "match: 30. Knowledge/Twin.md
match: 40. Projects/Twin.md" "USER ERROR: apply.sh: several notes"
unchanged apply-errors

# apply.sh: one note by name (case-insensitive, spaces, .md suffix) and by path
run "$apply" "  reviewed ONE.md "; expect apply-name 0 "evergreen: 30. Knowledge/Reviewed One.md
count: 1"
cmp -s "$tmp/v/30. Knowledge/Reviewed One.md" "$here/expected-vault/30. Knowledge/Reviewed One.md" || fail "apply-name: wrong edit"
run "$apply" "40. Projects/Twin"; expect apply-path 0 "evergreen: 40. Projects/Twin.md
count: 1"
run "$apply" "Reviewed One"; expect apply-name-again 3 "" "USER ERROR: apply.sh: 30. Knowledge/Reviewed One.md has status evergreen"

# apply.sh: no argument changes the rest, vault equals expected-vault byte for byte
run "$apply" ""; expect apply-all 0 "evergreen: 20. Customers/Quoted.md
evergreen: 30. Knowledge/Reviewed CRLF.md
evergreen: 30. Knowledge/Twin.md
count: 3"
diff -r "$here/expected-vault" "$tmp/v" > "$tmp/d" || { fail "vault differs from expected-vault"; cat "$tmp/d"; }

# idempotent: a second run changes nothing
before=$(sums "$tmp/v")
run "$apply"; expect apply-all-again 0 "count: 0"
unchanged apply-all-again

# fixtures untouched
[ -z "$(cd "$here/fixture-vault" && grep -rl evergreen --include='*.md' . | grep -v Evergreen.md)" ] || fail "fixture vault changed"

[ "$fails" = 0 ] || { echo "$fails failure(s)"; exit 1; }
