#!/usr/bin/env bash
# save.sh: write a draft note into <vault>/01. Inbox, never overwriting anything.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: save.sh [--append] <vault> <title> <draft-file>

Create "<vault>/01. Inbox/<title>.md" from <draft-file>, or with --append add the
draft body to an existing draft note of that name in 01. Inbox.
The script adds the "# <title>" heading; the draft file holds frontmatter and body.
Use it in wiki-save:save after the model wrote the draft file (path from gather.sh).

arguments:
  <vault>       vault root, as printed by gather.sh
  <title>       note title; \ / : * ? " < > | # ^ [ ] become "-"
  <draft-file>  frontmatter (with status: draft) plus body, no "# Title" needed.
                --append uses only the body. Deleted after a successful save.

checks: no note with that filename anywhere in the vault (case-insensitive),
frontmatter present with status: draft, every [[link]] outside code points to an
existing file or to the note itself.

output (stdout): saved|appended: <path from vault root>, renamed: yes|no
on exit 3: exists: <path> and status: <status|none> per match, then appendable: yes|no
(yes only for a single match that is a draft directly in 01. Inbox)

exit codes:
  0  saved or appended
  1  system error (vault folder or 01. Inbox missing, write failed)
  2  bad usage (arguments, draft file missing or invalid, link to a missing note)
  3  user error (a note with that name exists, --append target is not an Inbox draft)

examples:
  save.sh "/c/Vault" "ACE vs SOP" /tmp/wiki-save-1.md
  save.sh --append "/c/Vault" "ACE vs SOP" /tmp/wiki-save-1.md
EOF
}

case "${1:-}" in -h|--help) usage; exit 0 ;; esac
mode=create
[[ "${1:-}" == "--append" ]] && { mode=append; shift; }
[[ $# -eq 3 ]] || { echo "usage: save.sh [--append] <vault> <title> <draft-file> (see --help)" >&2; exit 2; }
vault=${1%/}; title=$2; draft=$3

for dep in awk find sed tr grep sort head tail date; do
  command -v "$dep" >/dev/null || { echo "SYSTEM ERROR: save.sh: $dep not installed" >&2; exit 1; }
done
[[ -d "$vault/01. Inbox" ]] || { echo "SYSTEM ERROR: save.sh: no 01. Inbox folder in vault: $vault" >&2; exit 1; }
[[ -f "$draft" ]] || { echo "SYSTEM ERROR: save.sh: draft file not found: $draft" >&2; exit 2; }

# Filename: replace forbidden characters, collapse spaces, trim spaces and trailing dots.
name=$(printf '%s' "$title" | tr -d '\r\n' | sed -e 's/[][\\/:*?"<>|#^]/-/g' -e 's/[[:space:]]\+/ /g' -e 's/^ //' -e 's/[ .]*$//')
[[ -n "$name" ]] || { echo "USER ERROR: save.sh: title has no usable characters: $title" >&2; exit 3; }
renamed=no; [[ "$name" == "$title" ]] || renamed=yes

# All files in the vault except dot folders, as paths from the vault root.
files=$(cd "$vault" && find . -type d -name '.?*' -prune -o -type f -print | sed 's|^\./||')
lc() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
lname=$(lc "$name.md")
# Every file with that name, any folder, any case.
existing=$(printf '%s\n' "$files" | awk -v n="$lname" '{ b = $0; sub(/.*\//, "", b) } tolower(b) == n')

status_of() {
  awk '{ sub(/\r$/, "") } NR == 1 && !/^---[ \t]*$/ { exit } NR > 1 && /^---[ \t]*$/ { exit }
       NR > 1 && /^status:/ { v = $0; sub(/^status:[ \t]*/, "", v); gsub(/["\x27 \t]/, "", v); print v; exit }' "$1"
}

# Appendable only when the single match is a draft directly in 01. Inbox.
app=no
if [[ -n "$existing" && "$existing" != *$'\n'* && "$existing" == "01. Inbox/"* && "${existing#01. Inbox/}" != */* ]]; then
  [[ "$(status_of "$vault/$existing")" == draft ]] && app=yes
fi

if [[ "$mode" == create && -n "$existing" ]]; then
  while IFS= read -r p; do
    st=$(status_of "$vault/$p"); printf 'exists: %s\nstatus: %s\n' "$p" "${st:-none}"
  done <<< "$existing"
  printf 'appendable: %s\n' "$app"
  echo "USER ERROR: save.sh: a note named \"$name\" already exists: $(printf '%s' "$existing" | awk 'NR > 1 { printf ", " } { printf "%s", $0 }')" >&2
  exit 3
fi

# Draft parts: frontmatter (with fences) and body without a leading "# " heading.
fm=$(awk '{ sub(/\r$/, "") } NR == 1 && !/^---[ \t]*$/ { exit } { print } NR > 1 && /^---[ \t]*$/ { exit }' "$draft")
body=$(awk '{ sub(/\r$/, "") }
  NR == 1 && /^---[ \t]*$/ { infm = 1; next }
  infm { if (/^---[ \t]*$/) infm = 0; next }
  !started && /^[ \t]*$/ { next }
  !started { started = 1; if (/^# /) { skip = 1; next } }
  skip && /^[ \t]*$/ { skip = 0; next }
  { skip = 0; print }' "$draft")
[[ -n "$body" ]] || { echo "SYSTEM ERROR: save.sh: draft file has no body text: $draft" >&2; exit 2; }

# Every [[link]] outside code must point to an existing file or to this note.
# Append drops the draft frontmatter, so only the body counts there.
check=$body; [[ "$mode" == create ]] && check=$fm$'\n'$body
missing=$(printf '%s\n' "$check" | awk '
    /^[ \t]*(```|~~~)/ { fence = !fence; next }
    fence { next }
    { gsub(/`[^`]*`/, ""); print }' | grep -o '\[\[[^]]*\]\]' | sed -e 's/^\[\[//' -e 's/\]\]$//' -e 's/[|#].*//' | sort -u |
  F="$files" awk -v self="$lname" 'BEGIN { have[self] = 1; n = split(ENVIRON["F"], f, "\n"); for (i = 1; i <= n; i++) { b = f[i]; sub(/.*\//, "", b); have[tolower(b)] = 1 } }
    { t = $0; sub(/.*\//, "", t); if (t == "") next; k = tolower(t); if (!(k in have) && !((k ".md") in have)) print $0 }' || true)
if [[ -n "$missing" ]]; then
  echo "SYSTEM ERROR: save.sh: links to notes that do not exist: $(printf '%s' "$missing" | awk 'NR > 1 { printf ", " } { printf "[[%s]]", $0 }')" >&2
  exit 2
fi

if [[ "$mode" == create ]]; then
  printf '%s\n' "$fm" | grep -Eq "^status:[[:space:]]*[\"']?draft[\"']?[[:space:]]*$" ||
    { echo "SYSTEM ERROR: save.sh: draft file needs frontmatter with status: draft" >&2; exit 2; }
  target="01. Inbox/$name.md"
  set -o noclobber
  { printf '%s\n# %s\n\n%s\n' "$fm" "$name" "$body" > "$vault/$target"; } 2>/dev/null ||
    { echo "SYSTEM ERROR: save.sh: could not create $target" >&2; exit 1; }
  rm -f "$draft"
  printf 'saved: %s\nrenamed: %s\n' "$target" "$renamed"
else
  if [[ "$app" != yes ]]; then
    echo "USER ERROR: save.sh: no single draft note \"$name\" in 01. Inbox to append to${existing:+ (found: $(printf '%s' "$existing" | awk 'NR > 1 { printf ", " } { printf "%s", $0 }'))}" >&2
    exit 3
  fi
  f="$vault/$existing"
  [[ -z "$(tail -c 1 "$f")" ]] || printf '\n' >> "$f"
  printf '\n## %s\n\n%s\n' "$(date +%F)" "$body" >> "$f" || { echo "SYSTEM ERROR: save.sh: could not append to $existing" >&2; exit 1; }
  rm -f "$draft"
  printf 'appended: %s\nrenamed: %s\n' "$existing" "$renamed"
fi
