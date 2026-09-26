#!/usr/bin/env bash
# apply.sh: set frontmatter status review to evergreen in the configured vault. Model-run, has side effects.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: apply.sh [<note name> | <folder>/<note>.md]

Mark review notes in the vault as evergreen. The only edit is the frontmatter
line "status: review", which becomes "status: evergreen". No moves, no other
change. The vault comes from ~/.claude/obsidian-wiki/vault-path.

arguments:
  none or ""        every note in the vault with status review (dot folders skipped)
  <note name>       one note by filename without .md, case-insensitive, any folder
  <folder>/<n>.md   one note by its path from the vault root (to pick between matches)

output (stdout):
  evergreen: <path from vault root>   one line per changed note
  count: <n>                          number of changed notes (0 is a normal result)
  match: <path>                       exit 3 only, one line per note with that name

exit codes:
  0  done (count may be 0)
  1  system error (tool missing, vault path missing, edit failed)
  2  bad usage (more than one argument)
  3  user error (no note with that name, several matches, status is not review)

examples: apply.sh
          apply.sh "Context Engineering"
          apply.sh "30. Knowledge/Context Engineering.md"
EOF
}

sys() { echo "SYSTEM ERROR: apply.sh: $1" >&2; exit 1; }
user() { echo "USER ERROR: apply.sh: $1" >&2; exit 3; }

case "${1:-}" in -h|--help) usage; exit 0 ;; esac
[ $# -le 1 ] || { echo "SYSTEM ERROR: apply.sh: expected at most one argument, got $#. Quote a name with spaces. See --help" >&2; exit 2; }

for tool in find xargs awk sed sort tr wc; do
  command -v "$tool" >/dev/null || sys "$tool not installed"
done

vault=
[ -f "$HOME/.claude/obsidian-wiki/vault-path" ] && vault=$(tr -d '\r\n' < "$HOME/.claude/obsidian-wiki/vault-path")
[ -n "$vault" ] || sys "Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault."
[ -f "$vault/CLAUDE.md" ] || sys "the vault folder $vault has no CLAUDE.md, check it with /wiki-vault:overwrite <vault path>"
cd "$vault" || sys "cannot enter vault folder $vault"

# Argument: trim spaces, drop a leading "./".
arg=${1:-}
arg=$(printf '%s' "$arg" | awk '{ gsub(/^[ \t]+|[ \t]+$/, ""); print }')
arg=${arg#./}
mode=all
if [ -n "$arg" ]; then
  case "$arg" in
    */*) mode=path; case "$arg" in *.md) ;; *) arg="$arg.md" ;; esac ;;
    *) mode=name; arg=${arg%.md} ;;
  esac
fi

# One record per note: path<TAB>status line number (0 = none)<TAB>status value.
# Only the first status line inside the frontmatter (block between the first two --- lines) counts.
records=$(find . -type d -name '.?*' -prune -o -type f -name '*.md' -print0 | xargs -0 -r awk '
  function emit() { if (path != "") printf "%s\t%d\t%s\n", path, ln, val }
  FNR == 1 {
    emit(); path = FILENAME; sub(/^\.\//, "", path); ln = 0; val = ""; infm = 0
    line = $0; sub(/\r$/, "", line)
    if (line ~ /^---[ \t]*$/) infm = 1
    next
  }
  !infm { next }
  {
    line = $0; sub(/\r$/, "", line)
    if (line ~ /^---[ \t]*$/) { infm = 0; next }
    if (ln == 0 && line ~ /^status:/) {
      ln = FNR; v = line
      sub(/^status:[ \t]*/, "", v); sub(/[ \t]+$/, "", v)
      if (v ~ /^".*"$/ || v ~ /^\047.*\047$/) v = substr(v, 2, length(v) - 2)
      val = v
    }
  }
  END { emit() }' | sort)

# Select the notes for this mode.
selected=$(M="$mode" A="$arg" awk -F '\t' '
  BEGIN { m = ENVIRON["M"]; a = tolower(ENVIRON["A"]) }
  m == "all" && $2 > 0 && $3 == "review" { print; next }
  m == "path" && tolower($1) == a { print; next }
  m == "name" { n = $1; sub(/.*\//, "", n); sub(/\.md$/, "", n); if (tolower(n) == a) print }
' <<< "$records")

if [ "$mode" != all ]; then
  [ -n "$selected" ] || user "no note named \"$arg\" in the vault"
  if [ "$(printf '%s\n' "$selected" | wc -l)" -gt 1 ]; then
    printf '%s\n' "$selected" | awk -F '\t' '{ print "match: " $1 }'
    user "several notes named \"$arg\", run again with one path from the match lines"
  fi
  IFS=$'\t' read -r p ln val <<< "$selected"
  [ "$ln" -gt 0 ] || user "$p has no status in its frontmatter, nothing changed"
  [ "$val" = review ] || user "$p has status $val, not review, nothing changed"
fi

count=0
while IFS=$'\t' read -r p ln val; do
  [ -n "$p" ] || continue
  # Replace only that line, keep a CRLF line ending if the file uses one (-b: no CRLF translation on Windows).
  sed -b -i -e "${ln}s/^status:.*\(\r\)\$/status: evergreen\1/" -e "${ln}s/^status:[^\r]*\$/status: evergreen/" -- "$p" || sys "edit failed for $p"
  echo "evergreen: $p"
  count=$((count + 1))
done <<< "$selected"
echo "count: $count"
