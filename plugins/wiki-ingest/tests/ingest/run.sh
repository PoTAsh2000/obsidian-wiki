#!/usr/bin/env bash
# Tests for the wiki-ingest:ingest scripts. Quiet on success, exit 1 on any failure.
# Write tests run on a temp copy of the fixture vault with a temp HOME.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
scripts="$here/../../skills/ingest/scripts"
fixture="$here/fixture-vault"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0

# run <case> <expected exit> <expected stdout> <command...>
run() {
  local case=$1 want=$2 exp=$3; shift 3
  local out got
  out=$("$@" 2> "$tmp/err"); got=$?
  [ "$got" = "$want" ] || { echo "FAIL $case: exit $got, want $want ($(head -c 300 "$tmp/err"))"; fail=1; }
  [ "$exp" = "*" ] || [ "$out" = "$exp" ] || { echo "FAIL $case: stdout differs"; diff <(printf '%s\n' "$exp") <(printf '%s\n' "$out"); fail=1; }
}
# errline <case> <prefix>: stderr of the last run starts with the prefix
errline() { grep -q "^$2" "$tmp/err" || { echo "FAIL $1: stderr lacks '$2'"; fail=1; }; }
same() { cmp -s "$1" "$2" || { echo "FAIL $3: $1 differs"; diff "$2" "$1"; fail=1; }; }
fresh() { rm -rf "$tmp/v"; cp -r "$fixture" "$tmp/v"; }

before=$(cd "$fixture" && find . -type f -exec md5sum {} + | sort)

# --help exits 0 on every script
for s in context select promote relink; do
  run "help-$s" 0 "*" bash "$scripts/$s.sh" --help
  run "h-$s" 0 "*" bash "$scripts/$s.sh" -h
done

# ---- context.sh ----
mkdir -p "$tmp/home/.claude/obsidian-wiki"
run context-missing 0 "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault." \
  env HOME="$tmp/home" bash "$scripts/context.sh"
printf '\n' > "$tmp/home/.claude/obsidian-wiki/vault-path"
run context-empty 0 "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault." \
  env HOME="$tmp/home" bash "$scripts/context.sh"
printf '%s\r\n' "$fixture/01. Inbox" > "$tmp/home/.claude/obsidian-wiki/vault-path"
run context-no-claude 0 "ERROR: the vault folder $fixture/01. Inbox has no CLAUDE.md. Point wiki-vault to the right folder with /wiki-vault:overwrite <vault path>." \
  env HOME="$tmp/home" bash "$scripts/context.sh"
printf '%s\n' "$fixture" > "$tmp/home/.claude/obsidian-wiki/vault-path"
run context-ok 0 "$(printf 'vault: %s\n----- vault CLAUDE.md -----\n%s' "$fixture" "$(cat "$fixture/CLAUDE.md")")" \
  env HOME="$tmp/home" bash "$scripts/context.sh"
run context-usage 2 "" env HOME="$tmp/home" bash "$scripts/context.sh" extra
errline context-usage "SYSTEM ERROR:"

# ---- select.sh ----
index='note: 01. Inbox/No Status.md
note: 01. Inbox/Reviewed.md | status: review
note: 01. Inbox/Sub/Deep.md | status: draft
note: 30. Knowledge/ACE.md | status: evergreen | aliases: Agentic Context Engineering, ACE framework | title: Agentic Context Engineering
note: 30. Knowledge/Tokens.md | status: review
note: 40. Projects/Proj.md | status: review
note: 99. Archived/Old.md | status: archived'
run select-all 0 "candidate: 01. Inbox/ACE notes.md
candidate: 01. Inbox/Idea.md
candidate: 01. Inbox/Tokens.md | same name: 30. Knowledge/Tokens.md
candidates: 3
$index
notes: 7" bash "$scripts/select.sh" --vault "$fixture"
run select-all-word 0 "*" bash "$scripts/select.sh" --vault "$fixture" all
run select-name 0 "candidate: 01. Inbox/Idea.md
candidates: 1
note: 01. Inbox/ACE notes.md | status: draft
note: 01. Inbox/No Status.md
note: 01. Inbox/Reviewed.md | status: review
note: 01. Inbox/Sub/Deep.md | status: draft
note: 01. Inbox/Tokens.md | status: draft | aliases: tok, token count
note: 30. Knowledge/ACE.md | status: evergreen | aliases: Agentic Context Engineering, ACE framework | title: Agentic Context Engineering
note: 30. Knowledge/Tokens.md | status: review
note: 40. Projects/Proj.md | status: review
note: 99. Archived/Old.md | status: archived
notes: 9" bash "$scripts/select.sh" --vault "$fixture" IDEA
run select-not-draft 3 "" bash "$scripts/select.sh" --vault "$fixture" reviewed
errline select-not-draft "USER ERROR: select.sh: 01. Inbox/Reviewed.md has status review in 01. Inbox"
run select-no-status 3 "" bash "$scripts/select.sh" --vault "$fixture" "No Status"
errline select-no-status "USER ERROR: select.sh: 01. Inbox/No Status.md has no status"
run select-subfolder 3 "" bash "$scripts/select.sh" --vault "$fixture" deep
errline select-subfolder "USER ERROR: select.sh: 01. Inbox/Sub/Deep.md has status draft in 01. Inbox/Sub"
run select-missing 3 "" bash "$scripts/select.sh" --vault "$fixture" nope
errline select-missing "USER ERROR: select.sh: no note named \"nope\""
run select-too-many 2 "" bash "$scripts/select.sh" --vault "$fixture" a b
errline select-too-many "SYSTEM ERROR:"
run select-no-vault 2 "" bash "$scripts/select.sh" tokens
errline select-no-vault "SYSTEM ERROR:"
run select-bad-vault 2 "" bash "$scripts/select.sh" --vault "$tmp/missing"
errline select-bad-vault "SYSTEM ERROR:"
mkdir -p "$tmp/empty"
run select-empty 0 "candidates: 0
notes: 0" bash "$scripts/select.sh" --vault "$tmp/empty"

# ---- promote.sh ----
fresh
run promote-move 0 "path: 40. Projects/Tokens.md
status: review" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Tokens.md" "40. Projects" review
sed 's/^status: draft$/status: review/' "$fixture/01. Inbox/Tokens.md" > "$tmp/want"
same "$tmp/v/40. Projects/Tokens.md" "$tmp/want" promote-move
[ ! -e "$tmp/v/01. Inbox/Tokens.md" ] || { echo "FAIL promote-move: source still there"; fail=1; }
run promote-again 0 "path: 40. Projects/Tokens.md
status: review
unchanged: already done" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Tokens.md" "40. Projects/" review

fresh
run promote-clash 3 "" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Tokens.md" "30. Knowledge" review
errline promote-clash "USER ERROR: promote.sh: name clash"
same "$tmp/v/01. Inbox/Tokens.md" "$fixture/01. Inbox/Tokens.md" promote-clash
run promote-archive 0 "path: 99. Archived/ACE notes.md
status: archived" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/ACE notes.md" "99. Archived" archived
run promote-keep 2 "" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Idea.md" "40. Projects" keep
errline promote-keep "SYSTEM ERROR: promote.sh: status must be review or archived"
# resume: an earlier run moved the draft but did not set the status
mv "$tmp/v/01. Inbox/Idea.md" "$tmp/v/40. Projects/Idea.md"
run promote-resume 0 "path: 40. Projects/Idea.md
status: review" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Idea.md" "40. Projects" review
# a same-name note with another status is not taken for done work
run promote-twin 3 "" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Nope.md" "99. Archived" archived
run promote-twin-status 3 "" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Idea.md" "40. Projects" archived
errline promote-twin-status "USER ERROR: promote.sh: note not found: 01. Inbox/Idea.md, and 40. Projects/Idea.md has status review"
# a UTF-8 BOM before the frontmatter is kept and does not hide the status
printf '\xef\xbb\xbf---\nstatus: draft\n---\n# Bom\n' > "$tmp/v/01. Inbox/Bom.md"
run select-bom 0 "*" bash "$scripts/select.sh" --vault "$tmp/v" bom
run promote-bom 0 "path: 40. Projects/Bom.md
status: review" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Bom.md" "40. Projects" review
same "$tmp/v/40. Projects/Bom.md" <(printf '\xef\xbb\xbf---\nstatus: review\n---\n# Bom\n') promote-bom
run promote-in-place 0 "path: 30. Knowledge/ACE.md
status: review" bash "$scripts/promote.sh" --vault "$tmp/v" "30. Knowledge/ACE.md" "30. Knowledge" review
sed 's/^status: evergreen$/status: review/' "$fixture/30. Knowledge/ACE.md" > "$tmp/want"
same "$tmp/v/30. Knowledge/ACE.md" "$tmp/want" promote-in-place
run promote-not-draft 3 "" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Reviewed.md" "40. Projects" review
errline promote-not-draft "USER ERROR: promote.sh: 01. Inbox/Reviewed.md has status review"
run promote-not-inbox 3 "" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Sub/Deep.md" "40. Projects" review
errline promote-not-inbox "USER ERROR:"
run promote-inbox-in-place 3 "" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Reviewed.md" "01. Inbox" review
errline promote-inbox-in-place "USER ERROR:"
run promote-missing 3 "" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Nope.md" "40. Projects" review
errline promote-missing "USER ERROR:"
run promote-no-folder 3 "" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Tokens.md" "50. Nowhere" review
errline promote-no-folder "USER ERROR: promote.sh: destination folder not found"
run promote-bad-status 2 "" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Tokens.md" "40. Projects" evergreen
errline promote-bad-status "SYSTEM ERROR:"
run promote-escape 2 "" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Tokens.md" "../x" review
errline promote-escape "SYSTEM ERROR:"
run promote-args 2 "" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Tokens.md"
errline promote-args "SYSTEM ERROR:"
# CRLF note keeps its line endings; a note without status line gets one
printf -- '---\r\ntype: concept\r\nstatus: draft\r\n---\r\n# Crlf\r\n' > "$tmp/v/01. Inbox/Crlf.md"
run promote-crlf 0 "*" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/Crlf.md" "40. Projects" review
printf -- '---\r\ntype: concept\r\nstatus: review\r\n---\r\n# Crlf\r\n' > "$tmp/want"
same "$tmp/v/40. Projects/Crlf.md" "$tmp/want" promote-crlf
printf -- '---\ntype: concept\n---\n# Target\n' > "$tmp/v/40. Projects/Target.md"
run promote-add-status 0 "path: 40. Projects/Target.md
status: review" bash "$scripts/promote.sh" --vault "$tmp/v" "40. Projects/Target.md" "40. Projects" review
run promote-no-status 3 "" bash "$scripts/promote.sh" --vault "$tmp/v" "01. Inbox/No Status.md" "40. Projects" review
errline promote-no-status "USER ERROR: promote.sh: 01. Inbox/No Status.md has no status"
printf -- '# Bare\n' > "$tmp/v/40. Projects/Bare.md"
run promote-no-fm 3 "" bash "$scripts/promote.sh" --vault "$tmp/v" "40. Projects/Bare.md" "40. Projects" review
errline promote-no-fm "USER ERROR: promote.sh: 40. Projects/Bare.md has no frontmatter"
same "$tmp/v/40. Projects/Bare.md" <(printf -- '# Bare\n') promote-no-fm

# ---- relink.sh ----
fresh
run relink 0 "changed: 01. Inbox/Tokens.md
changed: 30. Knowledge/ACE.md
changed: 40. Projects/Proj.md
links: 5" bash "$scripts/relink.sh" --vault "$tmp/v" "01. Inbox/ACE notes.md" ACE
cat > "$tmp/want" <<'EOF'
---
type: concept
aliases:
  - Agentic Context Engineering
  - ACE framework
status: evergreen
---
# Agentic Context Engineering

See [[ACE]], [[ACE|the notes]] and [[ACE#Part]].
Not [[ACE notes long]] and not [[40. Projects/ACE notes]].

```
[[ACE notes]]
```
EOF
same "$tmp/v/30. Knowledge/ACE.md" "$tmp/want" relink
grep -qF 'related: ["[[ACE]]"]' "$tmp/v/40. Projects/Proj.md" || { echo "FAIL relink: related not rewritten"; fail=1; }
run relink-again 0 "links: 0" bash "$scripts/relink.sh" --vault "$tmp/v" "01. Inbox/ACE notes.md" ACE
run relink-no-target 3 "" bash "$scripts/relink.sh" --vault "$tmp/v" "01. Inbox/ACE notes.md" "Nope"
errline relink-no-target "USER ERROR:"
run relink-same 2 "" bash "$scripts/relink.sh" --vault "$tmp/v" ACE ace
errline relink-same "SYSTEM ERROR:"
run relink-bad-name 2 "" bash "$scripts/relink.sh" --vault "$tmp/v" "A|B" ACE
errline relink-bad-name "SYSTEM ERROR:"
run relink-args 2 "" bash "$scripts/relink.sh" --vault "$tmp/v" ACE

errline relink-args "SYSTEM ERROR:"

# system errors: required tools missing (exit 1)
bashbin=$(command -v bash)
for s in select promote relink; do
  run "sys-$s" 1 "" env PATH=/nonexistent "$bashbin" "$scripts/$s.sh" --vault "$tmp/v" a b c
  errline "sys-$s" "SYSTEM ERROR: $s.sh: .* not installed"
done

after=$(cd "$fixture" && find . -type f -exec md5sum {} + | sort)
[ "$before" = "$after" ] || { echo "FAIL fixture vault changed"; fail=1; }

exit $fail
