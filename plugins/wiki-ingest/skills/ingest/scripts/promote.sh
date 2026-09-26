#!/usr/bin/env bash
# promote.sh: move one approved note out of "01. Inbox" and set its status.
set -euo pipefail
export LC_ALL=C

usage() {
  cat <<'EOF'
usage: promote.sh --vault <dir> <note> <folder> <review|archived>

Move a draft from "01. Inbox" to <folder> with its filename unchanged, and set
the frontmatter status. Run only for rows the user approved. Never deletes.
When <folder> is the note's own folder, only the status is set (merge target).
Safe to rerun: a moved note whose status is still draft gets its status set;
a note already at <folder>/<name> with <status> is reported as already done.

arguments:
  --vault <dir>  vault root (required)
  <note>         note path from the vault root, e.g. "01. Inbox/Tokens.md"
  <folder>       destination folder from the vault root, e.g. "30. Knowledge"
  <status>       review (filed draft or merge target), archived (merge source)

output (stdout):
  path: <path after the move>
  status: <status now in the frontmatter>
  unchanged: already done      only on a rerun that finds the work done

exit codes:
  0  moved or status set (or already done)
  1  system error (tool missing, write failed)
  2  bad usage (wrong arguments, vault folder not found)
  3  user error (note missing, not a draft in 01. Inbox, folder missing, name clash)

example: promote.sh --vault "C:/Vault" "01. Inbox/Tokens.md" "30. Knowledge" review
EOF
}

sys() { echo "SYSTEM ERROR: promote.sh: $*" >&2; exit 1; }
bad() { echo "SYSTEM ERROR: promote.sh: $*, see --help" >&2; exit 2; }
user() { echo "USER ERROR: promote.sh: $*" >&2; exit 3; }

case "${1:-}" in -h|--help) usage; exit 0 ;; esac
for t in awk mv mktemp; do command -v "$t" > /dev/null || sys "$t not installed"; done
awk --version 2> /dev/null | grep GNU > /dev/null || sys "GNU awk (gawk) required"

[ "${1:-}" = "--vault" ] && [ $# -eq 5 ] || bad "expected --vault <dir> <note> <folder> <status>"
vault=$2 note=$3 folder=$4 status=$5
case $status in review|archived) ;; *) bad "status must be review or archived, got '$status'" ;; esac
note=${note//\\//}; note=${note#./}
folder=${folder//\\//}; folder=${folder#./}; folder=${folder%/}
case "/$note/$folder/" in */../*|*/.*) bad "path leaves the vault or enters a dot folder" ;; esac
[ -n "$folder" ] && [ "${note%.md}" != "$note" ] || bad "note must be a .md path and folder must not be empty"
command -v cygpath > /dev/null && vault=$(cygpath -u "$vault")
[ -d "$vault" ] || bad "vault folder not found: $vault"
cd "$vault"

name=${note##*/}
src_dir=.; [ "$note" != "$name" ] && src_dir=${note%/*}
dest="$folder/$name"

# fm_status <file>: the frontmatter status value, empty when none.
fm_status() {
  awk '{ sub(/\r$/, "") } NR == 1 { sub(/^\xef\xbb\xbf/, ""); if ($0 !~ /^---[ \t]*$/) exit; next } /^---[ \t]*$/ { exit }
    /^status:/ { v = $0; sub(/^status:[ \t]*/, "", v); gsub(/[ \t"\x27]+$|^["\x27]/, "", v); print v; exit }' "$1"
}

# set_status <file>: rewrite or add the frontmatter status line, keeping line endings.
set_status() {
  local tmp
  tmp=$(mktemp "$1.XXXXXX") || sys "cannot create a temp file next to $1"
  if ! awk -v BINMODE=3 -v S="$status" '
    { cr = ($0 ~ /\r$/) ? "\r" : ""; line = $0; sub(/\r$/, "", line) }
    NR == 1 { sub(/^\xef\xbb\xbf/, "", line); if (line !~ /^---[ \t]*$/) bad = 1; else infm = 1; print; next }
    infm && line ~ /^---[ \t]*$/ { if (!done) print "status: " S cr; infm = 0; done = 1; print; next }
    infm && line ~ /^status:/ { print "status: " S cr; done = 1; next }
    { print }
    END { if (bad || !done) exit 3 }' "$1" > "$tmp"; then
    rm -f "$tmp"; user "$1 has no frontmatter, add one before promoting"
  fi
  mv -f "$tmp" "$1" || { rm -f "$tmp"; sys "cannot write $1"; }
}

report() { echo "path: $1"; echo "status: $(fm_status "$1")"; }

# In place: only the status changes (merge target).
if [ "$src_dir" = "$folder" ]; then
  [ -f "$note" ] || user "note not found: $note"
  [ "$folder" != "01. Inbox" ] || user "$note stays in 01. Inbox, a draft gets review only by moving out"
  set_status "$note"
  report "$note"; exit 0
fi

if [ ! -f "$note" ]; then
  [ "$src_dir" = "01. Inbox" ] && [ -f "$dest" ] || user "note not found: $note"
  cur=$(fm_status "$dest")
  if [ "$cur" = "$status" ]; then report "$dest"; echo "unchanged: already done"; exit 0; fi
  # Resume: an earlier run moved the draft but did not set the status.
  [ "$cur" = draft ] || user "note not found: $note, and $dest has ${cur:+status }${cur:-no status}"
  set_status "$dest"; report "$dest"; exit 0
fi
[ "$src_dir" = "01. Inbox" ] || user "$note is not in 01. Inbox, ingest only moves Inbox drafts"
cur=$(fm_status "$note")
[ "$cur" = draft ] || user "$note has ${cur:+status }${cur:-no status}, ingest only moves drafts"
[ -d "$folder" ] || user "destination folder not found: $folder"
[ ! -e "$dest" ] || user "name clash: $dest already exists, $note stays in 01. Inbox"

mv -n "$note" "$dest" || sys "cannot move $note to $dest"
[ ! -e "$note" ] || user "name clash: $dest already exists, $note stays in 01. Inbox"
set_status "$dest"
report "$dest"
