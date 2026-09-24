#!/usr/bin/env bash
# Tests for lint.sh. Quiet on success, lists every failure and exits 1 otherwise.
set -u
here=$(cd "$(dirname "$0")" && pwd)
lint="$here/../scripts/lint.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fails=0
fail() { echo "FAIL: $*"; fails=$((fails + 1)); }
sums() { (cd "$1" && find . -type f -print0 | sort -z | xargs -0 md5sum); }
fresh() { rm -rf "$tmp/v"; cp -r "$here/fixture-vault" "$tmp/v"; }

# 1. --dry-run: expected JSON, exit 1, no file changed
fresh
before=$(sums "$tmp/v")
bash "$lint" --vault "$tmp/v" --dry-run > "$tmp/out.json"; rc=$?
[ "$rc" = 1 ] || fail "dry-run exit code $rc, expected 1"
diff "$here/expected.json" "$tmp/out.json" > "$tmp/d" || { fail "dry-run JSON differs"; cat "$tmp/d"; }
[ "$before" = "$(sums "$tmp/v")" ] || fail "dry-run changed files"

# 2. real run: same JSON, fixed vault equals expected-vault byte for byte
bash "$lint" --vault "$tmp/v" > "$tmp/out.json"; rc=$?
[ "$rc" = 1 ] || fail "run exit code $rc, expected 1"
diff "$here/expected.json" "$tmp/out.json" > "$tmp/d" || { fail "run JSON differs"; cat "$tmp/d"; }
diff -r "$here/expected-vault" "$tmp/v" > "$tmp/d" || { fail "fixed vault differs from expected-vault"; cat "$tmp/d"; }

# 3. second run has nothing left to fix
bash "$lint" --vault "$tmp/v" > "$tmp/out.json"
grep -q '"movedToInbox": \[\],' "$tmp/out.json" || fail "second run moved notes"
grep -q '"removedDeadLinks": \[\],' "$tmp/out.json" || fail "second run removed links"

# 4. --files mode: a note, a folder and a stray draft
fresh
bash "$lint" --vault "$tmp/v" --dry-run --files "30. Knowledge/Bad Frontmatter.md" "10. Daily/" "30. Knowledge/Stray Draft.md" > "$tmp/out.json"; rc=$?
[ "$rc" = 1 ] || fail "--files exit code $rc, expected 1"
diff "$here/expected-files.json" "$tmp/out.json" > "$tmp/d" || { fail "--files JSON differs"; cat "$tmp/d"; }

# 5. clean note: exit 0
bash "$lint" --vault "$tmp/v" --files "01. Inbox/Good Draft.md" > /dev/null; rc=$?
[ "$rc" = 0 ] || fail "clean note exit code $rc, expected 0"

# 6. usage errors: exit 2
bash "$lint" --vault "$tmp/v" --bogus > /dev/null 2>&1; [ $? = 2 ] || fail "unknown flag not exit 2"
bash "$lint" --vault "$tmp/nope" > /dev/null 2>&1; [ $? = 2 ] || fail "missing vault not exit 2"
bash "$lint" --vault "$tmp/v" --files "No Such.md" > /dev/null 2>&1; [ $? = 2 ] || fail "missing --files path not exit 2"
bash "$lint" --vault "$tmp/v" --files > /dev/null 2>&1; [ $? = 2 ] || fail "--files without paths not exit 2"
bash "$lint" > /dev/null 2>&1; [ $? = 2 ] || fail "no vault path not exit 2"
rm "$tmp/v/CLAUDE.md"
bash "$lint" --vault "$tmp/v" --dry-run > /dev/null 2>&1; [ $? = 2 ] || fail "vault without CLAUDE.md not exit 2"

[ "$fails" = 0 ] || { echo "$fails failure(s)"; exit 1; }
