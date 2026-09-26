#!/usr/bin/env bash
# select.sh: pick the ingest candidates and index the other notes. Read-only.
set -euo pipefail
export LC_ALL=C

usage() {
  cat <<'EOF'
usage: select.sh --vault <dir> [all | <note name>]

List the ingest candidates (status: draft, directly in "01. Inbox") and index
every other note, so the plan needs no extra searches. Read-only.
Run after the full wiki-lint:lint run, because lint moves stray drafts into the Inbox.

arguments:
  --vault <dir>  vault root (required)
  (none) | all   every candidate
  <note name>    one candidate by filename without .md, case-insensitive

output (stdout):
  candidate: <path> [| same name: <path>, ...]   a draft to ingest; same name = filename clash elsewhere
  candidates: <n>
  note: <path> [| status: <s>] [| aliases: <a>, ...] [| title: <t>]   every other note (dot folders skipped)
  notes: <n>

exit codes:
  0  listed (candidates: 0 is a normal result)
  1  system error (awk or find missing)
  2  bad usage (wrong arguments, vault folder not found)
  3  user error (the named note does not exist, or is not a draft in 01. Inbox)

example: select.sh --vault "C:/Vault" "Tokens"
EOF
}

sys() { echo "SYSTEM ERROR: select.sh: $*" >&2; exit 1; }
bad() { echo "SYSTEM ERROR: select.sh: $*, see --help" >&2; exit 2; }
user() { echo "USER ERROR: select.sh: $*" >&2; exit 3; }

case "${1:-}" in -h|--help) usage; exit 0 ;; esac
for t in awk find xargs sort; do command -v "$t" > /dev/null || sys "$t not installed"; done

[ "${1:-}" = "--vault" ] && [ $# -ge 2 ] || bad "missing --vault <dir>"
vault=$2; shift 2
[ $# -le 1 ] || bad "too many arguments, quote a note name with spaces"
arg=${1:-all}
[ -n "$arg" ] || arg=all
command -v cygpath > /dev/null && vault=$(cygpath -u "$vault")
[ -d "$vault" ] || bad "vault folder not found: $vault"
cd "$vault"

# One record per note: path<TAB>status<TAB>aliases<TAB>title. Dot folders and the root CLAUDE.md are skipped.
records=$(find . -mindepth 1 -name '.*' -prune -o -type f -name '*.md' ! -path ./CLAUDE.md -print0 | xargs -0 -r awk '
  function clean(v) { gsub(/^[ \t]+|[ \t]+$/, "", v); gsub(/^["\x27]|["\x27]$/, "", v); return v }
  function addalias(v) { v = clean(v); if (v != "") al = al (al == "" ? "" : ", ") v }
  function flush() { if (path != "") print path "\t" st "\t" al "\t" ti }
  { sub(/\r$/, "") }
  FNR == 1 {
    flush()
    path = FILENAME; sub(/^\.\//, "", path)
    st = ""; al = ""; ti = ""; infm = 0; titled = 0; fence = 0; inal = 0
    if ($0 ~ /^---[ \t]*$/) { infm = 1; next }
  }
  infm {
    if ($0 ~ /^---[ \t]*$/) { infm = 0; next }
    if (match($0, /^([A-Za-z_]+):[ \t]*(.*)$/, m)) {
      inal = 0
      if (m[1] == "status") st = clean(m[2])
      else if (m[1] == "aliases") {
        v = m[2]
        if (v == "") inal = 1
        else if (v ~ /^\[.*\]$/) { v = substr(v, 2, length(v) - 2); n = split(v, parts, ","); for (i = 1; i <= n; i++) addalias(parts[i]) }
        else addalias(v)
      }
    } else if (inal && match($0, /^[ \t]*-[ \t]*(.*)$/, m)) addalias(m[1])
    next
  }
  titled { next }
  /^[ \t]*(```|~~~)/ { fence = !fence; next }
  !fence && /^# / { ti = clean(substr($0, 3)); titled = 1 }
  END { flush() }
' | sort) || sys "cannot read the notes in $vault"

want=${arg%.md}; want=${want##*/}
out=$(ARG="$arg" WANT="$want" awk -F '\t' '
  function name(p) { sub(/.*\//, "", p); sub(/\.md$/, "", p); return p }
  function folder(p) { if (p !~ /\//) return "vault root"; sub(/\/[^\/]*$/, "", p); return p }
  $1 == "" { next }
  {
    n++; p[n] = $1; s[n] = $2; a[n] = $3; t[n] = $4
    low[n] = tolower(name($1))
    cand[n] = ($1 ~ /^01\. Inbox\/[^\/]+$/ && $2 == "draft")
  }
  END {
    all = (ENVIRON["ARG"] == "all"); w = tolower(ENVIRON["WANT"])
    for (i = 1; i <= n; i++) if (cand[i] && (all || low[i] == w)) { pick[i] = 1; np++ }
    if (!all && np == 0) {
      msg = ""
      for (i = 1; i <= n; i++) if (low[i] == w)
        msg = msg (msg == "" ? "" : "; ") p[i] " has " (s[i] == "" ? "no status" : "status " s[i]) " in " folder(p[i])
      if (msg == "") msg = "no note named \"" ENVIRON["WANT"] "\" in the vault"
      else msg = msg ", only a draft directly in 01. Inbox can be ingested"
      print msg; exit 3
    }
    c = 0
    for (i = 1; i <= n; i++) if (pick[i]) {
      line = "candidate: " p[i]; same = ""
      for (j = 1; j <= n; j++) if (j != i && low[j] == low[i]) same = same (same == "" ? "" : ", ") p[j]
      if (same != "") line = line " | same name: " same
      print line; c++
    }
    print "candidates: " c
    k = 0
    for (i = 1; i <= n; i++) if (!pick[i]) {
      line = "note: " p[i]
      if (s[i] != "") line = line " | status: " s[i]
      if (a[i] != "") line = line " | aliases: " a[i]
      if (t[i] != "" && t[i] != name(p[i])) line = line " | title: " t[i]
      print line; k++
    }
    print "notes: " k
  }' <<< "$records") && rc=0 || rc=$?
case $rc in
  0) printf '%s\n' "$out" ;;
  3) user "$out" ;;
  *) sys "index failed (awk exit $rc)" ;;
esac
