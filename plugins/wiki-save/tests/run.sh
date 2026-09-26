#!/usr/bin/env bash
# Tests for gather.sh and save.sh on a copy of the fixture vault with a temp HOME.
# Quiet on success, lists every failure and exits 1 otherwise.
set -u
here=$(cd "$(dirname "$0")" && pwd)
scripts="$here/../skills/save/scripts"
gather="$scripts/gather.sh"
save="$scripts/save.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fails=0
fail() { echo "FAIL: $*"; fails=$((fails + 1)); }
sums() { (cd "$1" && find . -type f -print0 | sort -z | xargs -0 md5sum); }
v="$tmp/my vault"
rm -rf "$v"; cp -r "$here/fixture-vault" "$v"
export HOME="$tmp/home"
cfg="$HOME/.claude/obsidian-wiki"
fixture_sums=$(sums "$here/fixture-vault")

# expect <case> <exit> <command...>: run, keep stdout in $out, check the exit code
expect() {
  local case=$1 want=$2; shift 2
  out=$("$@" 2>"$tmp/err"); rc=$?
  [ "$rc" = "$want" ] || fail "$case: exit $rc, want $want ($(cat "$tmp/err"))"
}
has() { printf '%s\n' "$out" | grep -qx -- "$2" || fail "$1: no line '$2' in: $out"; }
draft() { printf '%s' "$2" > "$tmp/$1.md"; echo "$tmp/$1.md"; }

## gather.sh
expect gather-help 0 bash "$gather" --help
expect gather-args 2 bash "$gather" extra
expect gather-no-config 0 bash "$gather"
has gather-no-config "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
mkdir -p "$cfg"; : > "$cfg/vault-path"
expect gather-empty-config 0 bash "$gather"
has gather-empty-config "ERROR: Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
printf '%s\n' "$tmp/nowhere" > "$cfg/vault-path"
expect gather-bad-vault 0 bash "$gather"
printf '%s\n' "$out" | grep -q '^ERROR: .*/wiki-vault:overwrite' || fail "gather-bad-vault: $out"
printf '%s/\r\n' "$v" > "$cfg/vault-path"
before=$(sums "$v")
expect gather-ok 0 bash "$gather"
has gather-ok "vault: $v"
has gather-ok "today: $(date +%F)"
has gather-ok "vault_claude_md:"
has gather-ok "# Fixture vault rules"
printf '%s\n' "$out" | grep -Eqx 'topics: (AI|ai), Docker' || fail "gather-ok topics: $(printf '%s\n' "$out" | grep '^topics:')"
printf '%s\n' "$out" | grep -q '^draft_file: .*wiki-save-.*\.md$' || fail "gather-ok draft_file missing"
[ "$before" = "$(sums "$v")" ] || fail "gather changed the vault"

## save.sh usage and system errors
expect save-help 0 bash "$save" -h
expect save-args 2 bash "$save" "$v" "Only Two"
expect save-no-draft 2 bash "$save" "$v" "New" "$tmp/missing.md"
d=$(draft nostatus $'---\ntype: knowledge\nstatus: review\n---\nBody.\n')
expect save-not-draft-status 2 bash "$save" "$v" "New" "$d"
d=$(draft nobody $'---\nstatus: draft\n---\n# Title only\n')
expect save-empty-body 2 bash "$save" "$v" "New" "$d"
d=$(draft badlink $'---\nstatus: draft\nrelated: ["[[Docker Basics]]", "[[Nope]]"]\n---\nSee [[Missing Note|x]].\n')
expect save-dead-link 2 bash "$save" "$v" "New" "$d"
grep -q 'Nope' "$tmp/err" && grep -q 'Missing Note' "$tmp/err" || fail "save-dead-link: $(cat "$tmp/err")"
mkdir -p "$tmp/noinbox"
expect save-no-inbox 1 bash "$save" "$tmp/noinbox" "New" "$d"
[ "$before" = "$(sums "$v")" ] || fail "failed saves changed the vault"

## save.sh create
d=$(draft ok $'---\ntype: knowledge\ntopic: AI\nstatus: draft\nrelated: ["[[docker basics]]"]\n---\n# Whatever Heading\n\nSee [[Context Engineering#Intro|CE]].\n\n## Part\n\nText.\n')
expect save-create 0 bash "$save" "$v" "ACE vs SOP" "$d"
has save-create "saved: 01. Inbox/ACE vs SOP.md"
has save-create "renamed: no"
want=$'---\ntype: knowledge\ntopic: AI\nstatus: draft\nrelated: ["[[docker basics]]"]\n---\n# ACE vs SOP\n\nSee [[Context Engineering#Intro|CE]].\n\n## Part\n\nText.'
[ "$(cat "$v/01. Inbox/ACE vs SOP.md")" = "$want" ] || fail "save-create content: $(cat "$v/01. Inbox/ACE vs SOP.md")"
[ ! -e "$d" ] || fail "save-create kept the draft file"

d=$(draft ren $'---\nstatus: draft\n---\nBody.\n')
expect save-rename 0 bash "$save" "$v" 'A/B: c? [x] #y^ ' "$d"
has save-rename "saved: 01. Inbox/A-B- c- -x- -y-.md"
has save-rename "renamed: yes"
grep -qx '# A-B- c- -x- -y-' "$v/01. Inbox/A-B- c- -x- -y-.md" || fail "save-rename heading"

d=$(draft dots $'---\nstatus: draft\n---\nBody.\n')
expect save-no-usable-title 3 bash "$save" "$v" ' ... ' "$d"

## save.sh collisions (user errors), nothing overwritten
before=$(sums "$v")
expect save-again 3 bash "$save" "$v" "ace vs sop" "$d"
has save-again "exists: 01. Inbox/ACE vs SOP.md"
has save-again "appendable: yes"
expect save-evergreen 3 bash "$save" "$v" "DOCKER basics" "$d"
has save-evergreen "exists: 20. Knowledge/Docker Basics.md"
has save-evergreen "status: evergreen"
has save-evergreen "appendable: no"
expect save-inbox-review 3 bash "$save" "$v" "Stuck Review" "$d"
has save-inbox-review "status: review"
has save-inbox-review "appendable: no"
expect append-review 3 bash "$save" --append "$v" "Stuck Review" "$d"
expect append-evergreen 3 bash "$save" --append "$v" "Docker Basics" "$d"
expect append-none 3 bash "$save" --append "$v" "No Such Note" "$d"
[ "$before" = "$(sums "$v")" ] || fail "collisions changed the vault"

## save.sh append
d=$(draft app $'---\nstatus: draft\n---\n# Existing Draft\n\nNew text.\n')
expect append-ok 0 bash "$save" --append "$v" "existing draft" "$d"
has append-ok "appended: 01. Inbox/Existing Draft.md"
want=$'---\ntype: knowledge\ntopic: AI\nstatus: draft\n---\n# Existing Draft\n\nOld text.\n\n## '"$(date +%F)"$'\n\nNew text.'
[ "$(cat "$v/01. Inbox/Existing Draft.md")" = "$want" ] || fail "append-ok content: $(cat "$v/01. Inbox/Existing Draft.md")"
[ ! -e "$d" ] || fail "append-ok kept the draft file"
expect append-rerun 2 bash "$save" --append "$v" "Existing Draft" "$d"

## links in code, a self link and a quoted status are fine
d=$(draft code $'---\nstatus: "draft"\nrelated: []\n---\nSee [[Code Links]] and `x = [[1]]`.\n\n```python\ny = [[1, 2]]\n```\n')
expect save-code-links 0 bash "$save" "$v" "Code Links" "$d"
has save-code-links "saved: 01. Inbox/Code Links.md"

## the same name in two folders: never appendable
mkdir -p "$v/30. Projects"; cp "$v/01. Inbox/Existing Draft.md" "$v/30. Projects/existing draft.md"
d=$(draft dup $'---\nstatus: draft\n---\nMore.\n')
before=$(sums "$v")
expect save-dup 3 bash "$save" "$v" "Existing Draft" "$d"
has save-dup "exists: 01. Inbox/Existing Draft.md"
has save-dup "exists: 30. Projects/existing draft.md"
has save-dup "appendable: no"
expect append-dup 3 bash "$save" --append "$v" "Existing Draft" "$d"
[ "$before" = "$(sums "$v")" ] || fail "duplicate name changed the vault"

[ "$fixture_sums" = "$(sums "$here/fixture-vault")" ] || fail "fixture vault changed"
[ "$fails" = 0 ] || { echo "$fails failure(s)"; exit 1; }
