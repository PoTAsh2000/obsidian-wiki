#!/usr/bin/env bash
# relink.sh: point every wikilink to one note at another note (approved merge).
set -euo pipefail
export LC_ALL=C

usage() {
  cat <<'EOF'
usage: relink.sh --vault <dir> <old note> <new name>

Rewrite links to <old note> in every note to [[new name]], for an approved merge.
Keeps #heading and |display parts, matches case-insensitively. A bare link [[Old]]
matches by filename; a path link [[01. Inbox/Old]] only when the path is <old note>.
Skips fenced code blocks and dot folders. Never deletes.

arguments:
  --vault <dir>  vault root (required)
  <old note>     merge source path from the vault root, e.g. "01. Inbox/ACE notes.md"
  <new name>     merge target filename without .md, must exist in the vault

output (stdout):
  changed: <path>    one line per note that was rewritten
  links: <n>         number of links rewritten (0 on a second run)
  skipped-ambiguous: <n>   bare links left alone because several notes have
                           the old filename; the model reports them

exit codes:
  0  done (also when nothing had to change)
  1  system error (tool missing, write failed)
  2  bad usage (wrong arguments, vault folder not found)
  3  user error (no note named <new name> in the vault)

example: relink.sh --vault "C:/Vault" "01. Inbox/ACE notes.md" "ACE"
EOF
}

sys() { echo "SYSTEM ERROR: relink.sh: $*" >&2; exit 1; }
bad() { echo "SYSTEM ERROR: relink.sh: $*, see --help" >&2; exit 2; }
user() { echo "USER ERROR: relink.sh: $*" >&2; exit 3; }

case "${1:-}" in -h|--help) usage; exit 0 ;; esac
for t in awk find mktemp mv; do command -v "$t" > /dev/null || sys "$t not installed"; done
awk --version 2> /dev/null | grep GNU > /dev/null || sys "GNU awk (gawk) required"
[ "${BASH_VERSINFO[0]}" -ge 4 ] || sys "bash 4 or newer required"

[ "${1:-}" = "--vault" ] && [ $# -eq 4 ] || bad "expected --vault <dir> <old note> <new name>"
oldpath=${3//\\//}; oldpath=${oldpath#./}; oldpath=${oldpath%.md}
vault=$2 new=${4%.md}
old=${oldpath##*/} new=${new##*/}
[ -n "$old" ] && [ -n "$new" ] || bad "names must not be empty"
case "$old$new" in *'['*|*']'*|*'|'*|*'#'*) bad "names must not contain [ ] | #" ;; esac
[ "${old,,}" != "${new,,}" ] || bad "old and new name are the same"
command -v cygpath > /dev/null && vault=$(cygpath -u "$vault")
[ -d "$vault" ] || bad "vault folder not found: $vault"
cd "$vault"

notes=()
while IFS= read -r -d '' f; do notes+=("${f#./}"); done < <(find . -mindepth 1 -name '.*' -prune -o -type f -name '*.md' -print0 | sort -z)
found=0 twins=0
for f in "${notes[@]}"; do
  n=${f##*/}; n=${n%.md}
  [ "${n,,}" = "${new,,}" ] && found=1
  [ "${n,,}" = "${old,,}" ] && twins=$((twins + 1))
done
[ "$found" = 1 ] || user "no note named \"$new\" in the vault, create or pick the merge target first"
amb=0; [ "$twins" -gt 1 ] && amb=1

total=0 skipped=0
for f in "${notes[@]}"; do
  grep -qiF -- "$old" "$f" || continue
  tmp=$(mktemp "$f.XXXXXX") || sys "cannot create a temp file next to $f"
  result=$(OLD="$old" OLDPATH="$oldpath" NEW="$new" awk -v BINMODE=3 -v OUT="$tmp" -v AMB="$amb" '
    BEGIN { o = tolower(ENVIRON["OLD"]); op = tolower(ENVIRON["OLDPATH"]); nw = ENVIRON["NEW"] }
    {
      line = $0
      if (line ~ /^[ \t]*(```|~~~)/) { fence = !fence; print line > OUT; next }
      if (fence) { print line > OUT; next }
      res = ""
      while (match(line, /\[\[[^]|#\r\n]*[]|#]/)) {
        res = res substr(line, 1, RSTART - 1)
        tgt = substr(line, RSTART + 2, RLENGTH - 3); end = substr(line, RSTART + RLENGTH - 1, 1)
        t = tgt; gsub(/^[ \t]+|[ \t]+$/, "", t); sub(/\.md$/, "", t); sub(/^\//, "", t); t = tolower(t)
        hit = index(t, "/") ? t == op : t == o
        if (hit && AMB && !index(t, "/")) { hit = 0; s++ }
        if (hit) { res = res "[[" nw end; n++ } else res = res substr(line, RSTART, RLENGTH)
        line = substr(line, RSTART + RLENGTH)
      }
      print res line > OUT
    }
    END { close(OUT); print n + 0, s + 0 }' "$f") || { rm -f "$tmp"; sys "cannot rewrite $f"; }
  count=${result% *}; skipped=$((skipped + ${result#* }))
  if [ "$count" -gt 0 ]; then
    mv -f "$tmp" "$f" || { rm -f "$tmp"; sys "cannot write $f"; }
    echo "changed: $f"; total=$((total + count))
  else
    rm -f "$tmp"
  fi
done
echo "links: $total"
[ "$skipped" = 0 ] || echo "skipped-ambiguous: $skipped"
