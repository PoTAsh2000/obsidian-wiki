#!/usr/bin/env bash
# search.sh: rank vault notes by search terms for the query skill. Read-only.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: search.sh --vault <dir> [--limit <n>] <term>...

Rank the notes in an Obsidian vault by how well they match the terms. Read-only.
Case-insensitive substring match on filename, first "# " title, aliases, tags,
topic and body lines. Skips dot folders, Attachments, "90. Templates" and
the vault root CLAUDE.md.

arguments:
  --vault <dir>  vault root (required)
  --limit <n>    max notes to list, 1-200, default 20
  <term>...      one or more terms; quote a phrase as one term

output (sorted by score, then path):
  terms: <term>, ...
  matches: <notes with any hit>
  shown: <listed>
  - <path> | score: <n> | status: <status or none> | terms: <hit>/<given> | in: <fields>
  fields: name, title, alias, tag, topic, body:<line hits summed over terms>

exit codes:
  0  searched (matches: 0 means nothing found)
  1  system error (gawk, find or sort missing)
  2  bad usage (missing or invalid argument)
  3  user error (vault folder not found)

example: search.sh --vault "$HOME/Vault" "EDI" "mapping" "edifact"
EOF
}

bad() { echo "SYSTEM ERROR: search.sh: $1, see --help" >&2; exit 2; }

vault="" limit=20 terms=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --vault) [[ $# -ge 2 ]] || bad "--vault needs a folder"; vault="$2"; shift 2 ;;
    --limit) [[ $# -ge 2 ]] || bad "--limit needs a number"; limit="$2"; shift 2 ;;
    --) shift; terms+=("$@"); break ;;
    -*) bad "unknown option: $1" ;;
    *) terms+=("$1"); shift ;;
  esac
done
[[ -n "$vault" ]] || bad "no vault: pass --vault <dir>"
[[ "$limit" =~ ^[1-9][0-9]{0,2}$ ]] && (( limit <= 200 )) || bad "invalid --limit: $limit"
[[ ${#terms[@]} -ge 1 ]] || bad "no search term given"
for t in "${terms[@]}"; do
  [[ -n "${t//[[:space:]]/}" ]] || bad "empty search term"
  [[ "$t" != *$'\n'* && "$t" != *$'\t'* ]] || bad "search term contains a newline or tab"
done

for dep in find xargs sort; do
  command -v "$dep" >/dev/null 2>&1 || { echo "SYSTEM ERROR: search.sh: $dep not installed" >&2; exit 1; }
done
awk 'BEGIN { exit (PROCINFO["version"] == "") }' 2>/dev/null \
  || { echo "SYSTEM ERROR: search.sh: GNU awk (gawk) required" >&2; exit 1; }

dir="$vault"
command -v cygpath >/dev/null 2>&1 && dir=$(cygpath -u "$vault")
[[ -d "$dir" ]] || { echo "USER ERROR: search.sh: vault folder not found: $vault" >&2; exit 3; }
cd "$dir"

joined=$(printf '%s\n' "${terms[@]}")
shown_terms=""
for t in "${terms[@]}"; do shown_terms+="${shown_terms:+, }$t"; done
echo "terms: $shown_terms"

ranked=$(find . -type d \( -name '.?*' -o -path ./Attachments -o -path './90. Templates' \) -prune -o \
    -type f -name '*.md' ! -path ./CLAUDE.md -print0 | TERMS="$joined" xargs -0 -r awk '
  function clean(v) { gsub(/^[ \t]+|[ \t]+$/, "", v); gsub(/^["\x27]|["\x27]$/, "", v); return tolower(v) }
  function add(k, v) { v = clean(v); if (v == "") return; if (k == "status") status = v; else meta[k] = meta[k] "\n" v }
  function addlist(k, v,   n, i, parts) {
    if (v ~ /^\[.*\]$/) { v = substr(v, 2, length(v) - 2); n = split(v, parts, ","); for (i = 1; i <= n; i++) add(k, parts[i]) }
    else add(k, v)
  }
  BEGIN { nt = split(tolower(ENVIRON["TERMS"]), term, "\n"); if (term[nt] == "") nt-- }
  { sub(/\r$/, "") }
  BEGINFILE {
    path = FILENAME; sub(/^\.\//, "", path)
    name = path; sub(/.*\//, "", name); sub(/\.md$/, "", name); name = tolower(name)
    split("", meta); split("", body); status = "none"; title = ""; nb = 0
    infm = 0; titled = 0; fence = 0; listkey = ""
  }
  FNR == 1 && /^---[ \t]*$/ { infm = 1; next }
  infm {
    if ($0 ~ /^---[ \t]*$/) { infm = 0; next }
    if (match($0, /^([A-Za-z_]+):[ \t]*(.*)$/, m)) {
      listkey = ""
      if (m[1] ~ /^(aliases|tags|topic|status)$/) { if (m[2] == "") listkey = m[1]; else addlist(m[1], m[2]) }
    } else if (listkey != "" && match($0, /^[ \t]*-[ \t]*(.*)$/, m)) add(listkey, m[1])
    next
  }
  /^[ \t]*(```|~~~)/ { fence = !fence }
  !titled && !fence && /^# / { title = tolower(substr($0, 3)); titled = 1 }
  { line = tolower($0); for (i = 1; i <= nt; i++) if (index(line, term[i])) body[i]++ }
  ENDFILE {
    score = 0; hit = 0; delete in_
    for (i = 1; i <= nt; i++) {
      t = term[i]; h = 0
      if (index(name, t)) { score += 10; in_["name"] = 1; h = 1 }
      if (title != "" && index(title, t)) { score += 10; in_["title"] = 1; h = 1 }
      if (index(meta["aliases"], t)) { score += 6; in_["alias"] = 1; h = 1 }
      if (index(meta["tags"], t)) { score += 4; in_["tag"] = 1; h = 1 }
      if (index(meta["topic"], t)) { score += 4; in_["topic"] = 1; h = 1 }
      if (body[i] > 0) { score += (body[i] > 5 ? 5 : body[i]); nb += body[i]; h = 1 }
      hit += h
    }
    if (hit > 0) {
      f = ""
      split("name title alias tag topic", order, " ")
      for (j = 1; j <= 5; j++) if (order[j] in in_) f = f (f == "" ? "" : ",") order[j]
      if (nb > 0) f = f (f == "" ? "" : ",") "body:" nb
      printf "%d\t%s\t- %s | score: %d | status: %s | terms: %d/%d | in: %s\n", score, path, path, score, status, hit, nt, f
    }
    nb = 0
  }
' | LC_ALL=C sort -t "$(printf '\t')" -k1,1nr -k2,2)

matches=0
[[ -n "$ranked" ]] && matches=$(printf '%s\n' "$ranked" | wc -l | tr -d ' ')
shown=$(( matches < limit ? matches : limit ))
echo "matches: $matches"
echo "shown: $shown"
[[ "$shown" -gt 0 ]] && printf '%s\n' "$ranked" | awk -F '\t' -v n="$shown" 'NR <= n { print $3 }'
exit 0
