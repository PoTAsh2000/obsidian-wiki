#!/usr/bin/env bash
# find.sh --vault <dir> <name|tag|topic|status> <value>...
# Read-only lookups in an Obsidian vault. Paths from the vault root, sorted.
# Vault: --vault (required).
# Exit 0 found, 1 nothing found, 2 usage error.
set -u

usage() { echo "usage: find.sh --vault <dir> <name|tag|topic|status> <value>..." >&2; [ -n "${1:-}" ] && echo "$1" >&2; exit 2; }

vault=
if [ "${1:-}" = "--vault" ]; then
  [ $# -ge 2 ] || usage "--vault needs a folder"
  vault=$2; shift 2
fi
[ -n "$vault" ] || usage "vault path not set: use --vault"
cd "$vault" 2>/dev/null || usage "vault folder not found: $vault"

field=${1:-}
case "$field" in name|tag|topic|status) ;; *) usage "unknown field: ${field:-none}" ;; esac
shift
[ $# -ge 1 ] || usage "no value given"

# Step 1: one record per fact, "path<TAB>kind<TAB>value", kind in name, title, aliases, tags, topic, status.
# Scope: every folder except dot folders, Attachments and 90. Templates.
records=$(find . -type d \( -name '.?*' -o -path ./Attachments -o -path './90. Templates' \) -prune -o \
    -type f -name '*.md' -print0 | xargs -0 -r awk '
  function clean(v) { gsub(/^[ \t]+|[ \t]+$/, "", v); gsub(/^["\x27]|["\x27]$/, "", v); return v }
  function out(k, v) { v = clean(v); if (v != "") print path "\t" k "\t" v }
  function outlist(k, v,   n, i, parts) {
    if (v ~ /^\[.*\]$/) { v = substr(v, 2, length(v) - 2); n = split(v, parts, ","); for (i = 1; i <= n; i++) out(k, parts[i]) }
    else out(k, v)
  }
  { sub(/\r$/, "") }
  FNR == 1 {
    path = FILENAME; sub(/^\.\//, "", path)
    name = path; sub(/.*\//, "", name); sub(/\.md$/, "", name); out("name", name)
    infm = 0; titled = 0; fence = 0; listkey = ""
    if ($0 ~ /^---[ \t]*$/) { infm = 1; next }
  }
  infm {
    if ($0 ~ /^---[ \t]*$/) { infm = 0; next }
    if (match($0, /^([A-Za-z_]+):[ \t]*(.*)$/, m)) {
      listkey = ""
      if (m[1] ~ /^(aliases|tags|topic|status)$/) { if (m[2] == "") listkey = m[1]; else outlist(m[1], m[2]) }
    } else if (listkey != "" && match($0, /^[ \t]*-[ \t]*(.*)$/, m)) out(listkey, m[1])
    next
  }
  titled { next }
  /^[ \t]*(```|~~~)/ { fence = !fence; next }
  !fence && /^# / { out("title", substr($0, 3)); titled = 1 }
')

# Step 2: match and print.
if [ "$field" = name ]; then
  Q="$*" awk -F '\t' '
    BEGIN { q = tolower(ENVIRON["Q"]) }
    ($2 == "name" || $2 == "title") && index(tolower($3), q) { hit[$1] = 1 }
    $2 == "aliases" && !($1 in alias) && index(tolower($3), q) { alias[$1] = $3 }
    END {
      if ((n = asorti(hit, p)) > 0) { for (i = 1; i <= n; i++) print "- " p[i]; exit 0 }
      if ((n = asorti(alias, p)) > 0) {
        print "No filename or title matches \"" ENVIRON["Q"] "\". Found through aliases:"
        for (i = 1; i <= n; i++) print "- " p[i] " (alias: " alias[p[i]] ")"
        exit 0
      }
      print "Nothing found."; exit 1
    }' <<< "$records"
else
  kind=$field; [ "$kind" = tag ] && kind=tags
  printf '%s\n' "$@" | awk -F '\t' -v kind="$kind" '
    NR == FNR { nv++; val[nv] = $0; next }
    $2 == kind { for (i = 1; i <= nv; i++) if (tolower($3) == tolower(val[i])) hit[i, $1] = 1 }
    END {
      for (k in hit) any = 1
      if (!any) { print "Nothing found."; exit 1 }
      for (i = 1; i <= nv; i++) {
        print val[i] ":"
        n = 0; delete p
        for (k in hit) { split(k, s, SUBSEP); if (s[1] == i) p[++n] = s[2] }
        if (n == 0) print "- nothing found"
        asort(p)
        for (j = 1; j <= n; j++) print "- " p[j]
      }
    }' - <(printf '%s\n' "$records")
fi
