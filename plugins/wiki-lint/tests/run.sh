#!/usr/bin/env bash
# Tests for lint.sh and vault.sh. Quiet on success, lists every failure and exits 1 otherwise.
set -u
here=$(cd "$(dirname "$0")" && pwd)
lint="$here/../scripts/lint.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fails=0
fail() { echo "FAIL: $*"; fails=$((fails + 1)); }
sums() { (cd "$1" && find . -type f -print0 | sort -z | xargs -0 md5sum); }
fresh() { rm -rf "$tmp/v"; cp -r "$here/fixture-vault" "$tmp/v"; }

# 1. --dry-run: expected JSON, exit 4, no file changed
fresh
before=$(sums "$tmp/v")
bash "$lint" --vault "$tmp/v" --dry-run > "$tmp/out.json"; rc=$?
[ "$rc" = 4 ] || fail "dry-run exit code $rc, expected 4"
diff "$here/expected.json" "$tmp/out.json" > "$tmp/d" || { fail "dry-run JSON differs"; cat "$tmp/d"; }
[ "$before" = "$(sums "$tmp/v")" ] || fail "dry-run changed files"

# 2. real run: same JSON, fixed vault equals expected-vault byte for byte
bash "$lint" --vault "$tmp/v" > "$tmp/out.json"; rc=$?
[ "$rc" = 4 ] || fail "run exit code $rc, expected 4"
diff "$here/expected.json" "$tmp/out.json" > "$tmp/d" || { fail "run JSON differs"; cat "$tmp/d"; }
diff -r "$here/expected-vault" "$tmp/v" > "$tmp/d" || { fail "fixed vault differs from expected-vault"; cat "$tmp/d"; }

# 3. second run has nothing left to fix
bash "$lint" --vault "$tmp/v" > "$tmp/out.json"
grep -q '"movedToInbox": \[\],' "$tmp/out.json" || fail "second run moved notes"
grep -q '"removedDeadLinks": \[\],' "$tmp/out.json" || fail "second run removed links"

# 4. --files mode: a note, a folder and a stray draft
fresh
bash "$lint" --vault "$tmp/v" --dry-run --files "30. Knowledge/Bad Frontmatter.md" "10. Daily/" "30. Knowledge/Stray Draft.md" > "$tmp/out.json"; rc=$?
[ "$rc" = 4 ] || fail "--files exit code $rc, expected 4"
diff "$here/expected-files.json" "$tmp/out.json" > "$tmp/d" || { fail "--files JSON differs"; cat "$tmp/d"; }

# 5. clean note: exit 0
bash "$lint" --vault "$tmp/v" --files "01. Inbox/Good Draft.md" > /dev/null; rc=$?
[ "$rc" = 0 ] || fail "clean note exit code $rc, expected 0"

# expect <code> <stderr prefix or -> <label> -- <command...>: exit code and stderr prefix
expect() {
  local want=$1 prefix=$2 label=$3 rc=0; shift 4
  "$@" > "$tmp/o" 2> "$tmp/e" || rc=$?
  [ "$rc" = "$want" ] || fail "$label: exit $rc, expected $want"
  [ "$prefix" = - ] || grep -q "^$prefix" "$tmp/e" || fail "$label: stderr lacks '$prefix'"
}

# 6. --help: exit 0, usage on stdout
expect 0 - "lint --help" -- bash "$lint" --help
grep -q '^usage: lint.sh' "$tmp/o" || fail "lint --help: no usage line"
expect 0 - "lint -h" -- bash "$lint" -h

# 7. usage errors: exit 2
expect 2 "SYSTEM ERROR:" "unknown flag" -- bash "$lint" --vault "$tmp/v" --bogus
expect 2 "SYSTEM ERROR:" "--files without paths" -- bash "$lint" --vault "$tmp/v" --files
expect 2 "SYSTEM ERROR:" "no vault path" -- bash "$lint"
expect 2 "SYSTEM ERROR:" "--vault without value" -- bash "$lint" --vault

# 8. user errors: exit 3
expect 3 "USER ERROR:" "missing vault" -- bash "$lint" --vault "$tmp/nope"
expect 3 "USER ERROR:" "missing --files path" -- bash "$lint" --vault "$tmp/v" --files "No Such.md"
fresh
printf '# Rules\n\nNo lists here.\n' > "$tmp/v/CLAUDE.md"
expect 3 "USER ERROR:" "CLAUDE.md without type list" -- bash "$lint" --vault "$tmp/v" --dry-run
rm "$tmp/v/CLAUDE.md"
expect 3 "USER ERROR:" "vault without CLAUDE.md" -- bash "$lint" --vault "$tmp/v" --dry-run

# 9. system error: exit 1 when a required tool is missing (no awk on PATH), nothing changed
fresh
before=$(sums "$tmp/v")
mkdir -p "$tmp/bin"
for t in find sort date mktemp grep sed tr mv cat rm dirname cygpath; do
  p=$(command -v "$t" 2> /dev/null) || continue
  printf '#!/bin/sh\nexec "%s" "$@"\n' "$p" > "$tmp/bin/$t"; chmod +x "$tmp/bin/$t"
done
bashbin=$(command -v bash)
expect 1 "SYSTEM ERROR:" "missing awk" -- env PATH="$tmp/bin" "$bashbin" "$lint" --vault "$tmp/v"
[ "$before" = "$(sums "$tmp/v")" ] || fail "missing awk changed files"

# 10. vault.sh: injected context, soft fails on exit 0
vsh="$here/../scripts/vault.sh"
h="$tmp/home"; mkdir -p "$h/.claude/obsidian-wiki"
expect 0 - "vault.sh --help" -- bash "$vsh" --help
grep -q '^usage: vault.sh' "$tmp/o" || fail "vault.sh --help: no usage line"
expect 2 "SYSTEM ERROR:" "vault.sh with argument" -- env HOME="$h" bash "$vsh" extra
expect 1 "SYSTEM ERROR:" "vault.sh without HOME" -- env -u HOME bash "$vsh"
expect 0 - "vault.sh no config" -- env HOME="$h" bash "$vsh"
[ "$(cat "$tmp/o")" = "vault: missing" ] || fail "vault.sh no config: got '$(cat "$tmp/o")'"
printf '  \n' > "$h/.claude/obsidian-wiki/vault-path"
expect 0 - "vault.sh empty config" -- env HOME="$h" bash "$vsh"
[ "$(cat "$tmp/o")" = "vault: missing" ] || fail "vault.sh empty config: got '$(cat "$tmp/o")'"
printf '%s\n' "$tmp/nope" > "$h/.claude/obsidian-wiki/vault-path"
expect 0 - "vault.sh missing folder" -- env HOME="$h" bash "$vsh"
grep -q '^error: vault not found$' "$tmp/o" || fail "vault.sh missing folder: no error line"
rm -rf "$tmp/empty"; mkdir "$tmp/empty"
printf '%s\n' "$tmp/empty" > "$h/.claude/obsidian-wiki/vault-path"
expect 0 - "vault.sh no CLAUDE.md" -- env HOME="$h" bash "$vsh"
grep -q '^error: no CLAUDE.md$' "$tmp/o" || fail "vault.sh no CLAUDE.md: no error line"
fresh
printf '%s\r\n' "$tmp/v" > "$h/.claude/obsidian-wiki/vault-path"
expect 0 - "vault.sh ok" -- env HOME="$h" bash "$vsh"
{ printf 'vault: %s\nclaude-md:\n' "$tmp/v"; cat "$tmp/v/CLAUDE.md"; } > "$tmp/want"
diff "$tmp/want" "$tmp/o" > "$tmp/d" || { fail "vault.sh ok: output differs"; cat "$tmp/d"; }
[ "$before" = "$(sums "$tmp/v")" ] || fail "vault.sh changed files"

[ "$fails" = 0 ] || { echo "$fails failure(s)"; exit 1; }
