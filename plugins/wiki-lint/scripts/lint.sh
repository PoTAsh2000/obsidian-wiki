#!/usr/bin/env bash
# lint.sh: check an Obsidian vault against the vault CLAUDE.md rules.
# Fixes two things itself: moves stray drafts into "01. Inbox" and unlinks dead links.
# Everything else is reported. Output: one JSON object on stdout.
# Exit: 0 clean, 1 fixes or findings, 2 usage error.
#
# Usage: lint.sh [--vault <dir>] [--dry-run] [--files <path>...]
#   Vault: --vault, else CLAUDE_PLUGIN_OPTION_VAULT_PATH, else OBSIDIAN_VAULT.
#   --files: only these notes or folders (relative to the vault root).
set -u
export LC_ALL=C

die() { echo "lint.sh: $*" >&2; exit 2; }
usage() { die "usage: lint.sh [--vault <dir>] [--dry-run] [--files <path>...]"; }

vault=${CLAUDE_PLUGIN_OPTION_VAULT_PATH:-${OBSIDIAN_VAULT:-}}
dry=0 files_mode=0 files=()
while [ $# -gt 0 ]; do
  case $1 in
    --vault) [ $# -ge 2 ] || usage; vault=$2; shift 2 ;;
    --dry-run) dry=1; shift ;;
    --files)
      files_mode=1; shift
      while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do files+=("$1"); shift; done ;;
    *) usage ;;
  esac
done
[ -n "$vault" ] || die "no vault path: set CLAUDE_PLUGIN_OPTION_VAULT_PATH or OBSIDIAN_VAULT, or pass --vault"
command -v cygpath > /dev/null && vault=$(cygpath -u "$vault")
[ -d "$vault" ] || die "vault not found: $vault"
cd "$vault" || die "cannot enter vault: $vault"
[ -f CLAUDE.md ] || die "no CLAUDE.md in vault root: $vault"
[ "$files_mode" = 0 ] || [ ${#files[@]} -gt 0 ] || usage

# Allowed values come from the vault CLAUDE.md at runtime, so the lists can grow.
types=$(grep -m1 'Allowed `type` values' CLAUDE.md | sed 's/^[^:]*://' | grep -o '`[^`]*`' | tr -d '`' | tr '\n' ' ')
statuses=$(awk '/^#+ /{s = /^#+ Status lifecycle/} s && /^- `/' CLAUDE.md | grep -o '^- `[^`]*`' | sed 's/^- `//; s/`$//' | tr '\n' ' ')
[ -n "${types// /}" ] || die "no 'Allowed \`type\` values' line in CLAUDE.md"
[ -n "${statuses// /}" ] || die "no '- \`status\`' items under 'Status lifecycle' in CLAUDE.md"

tmp=$(mktemp -d) || die "cannot create temp dir"
trap 'rm -rf "$tmp"' EXIT

find . -mindepth 1 -name '.*' -prune -o -type f -printf '%P\t%TY-%Tm-%Td\n' | sort > "$tmp/list"
: > "$tmp/sel"
for f in "${files[@]}"; do
  f=${f#./}; f=${f%/}
  if [ -d "$f" ]; then printf '%s/\n' "$f" >> "$tmp/sel"
  elif [ -f "$f" ]; then printf '%s\n' "$f" >> "$tmp/sel"
  else die "not found in vault: $f"; fi
done

awk -v BINMODE=3 -v LIST="$tmp/list" -v SEL="$tmp/sel" -v TMP="$tmp" -v FILESMODE="$files_mode" \
    -v TYPES="$types" -v STATUSES="$statuses" -v CUTOFF="$(date -d '7 days ago' +%F)" -f /dev/stdin > "$tmp/out.json" <<'AWK'
function top(p,   i) { i = index(p, "/"); return i ? substr(p, 1, i - 1) : "" }
function base(p) { sub(/.*\//, "", p); return p }
function dir(p) { if (p !~ /\//) return ""; sub(/\/[^\/]*$/, "", p); return p }
function exempt(p,   t) { t = top(p); return t == "10. Daily" || t == "90. Templates" || t == "99. Archived" }
function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
function unquote(s) { if (s ~ /^".*"$/ || s ~ /^'.*'$/) s = substr(s, 2, length(s) - 2); return s }
function js(s) { gsub(/\\/, "\\\\", s); gsub(/"/, "\\\"", s); gsub(/\t/, "\\t", s); gsub(/\r/, "\\r", s); gsub(/\n/, "\\n", s); return "\"" s "\"" }
function selected(p,   i) {
  if (!FILESMODE) return 1
  for (i = 1; i <= nsel; i++)
    if (p == sel[i] || (sel[i] ~ /\/$/ && index(p, sel[i]) == 1)) return 1
  return 0
}
function urldecode(s,   out, i, c) {
  if (index(s, "%") == 0) return s
  out = ""
  for (i = 1; i <= length(s); i++) {
    c = substr(s, i, 1)
    if (c == "%" && substr(s, i + 1, 2) ~ /^[0-9A-Fa-f][0-9A-Fa-f]$/) { out = out sprintf("%c", strtonum("0x" substr(s, i + 1, 2))); i += 2 }
    else out = out c
  }
  return out
}
function normalize(p,   n, a, i, out, k) {
  n = split(p, a, "/"); k = 0
  for (i = 1; i <= n; i++) {
    if (a[i] == "" || a[i] == ".") continue
    if (a[i] == "..") { if (k > 0) k--; continue }
    out[++k] = a[i]
  }
  p = ""
  for (i = 1; i <= k; i++) p = p (i > 1 ? "/" : "") out[i]
  return p
}
# Inline code spans become spaces, so links inside them are never seen.
function maskcode(s,   out, i, n, run, j, m, found) {
  if (index(s, "`") == 0) return s
  out = ""; i = 1; n = length(s)
  while (i <= n) {
    if (substr(s, i, 1) != "`") { out = out substr(s, i, 1); i++; continue }
    run = 0; while (substr(s, i + run, 1) == "`") run++
    found = 0; j = i + run
    while (j <= n) {
      if (substr(s, j, 1) != "`") { j++; continue }
      m = 0; while (substr(s, j + m, 1) == "`") m++
      if (m == run) { found = 1; break }
      j += m
    }
    if (found) { out = out sprintf("%*s", j + run - i, ""); i = j + run }
    else { out = out substr(s, i, run); i += run }
  }
  return out
}
function additem(p, key, v, ln) { v = unquote(trim(v)); if (v == "") return; n = ++items[p, key]; item[p, key, n] = v; itemline[p, key, n] = ln }
function finding(cat, p, ln, detail) { nfind++; F[sprintf("%s\001%08d\001%s\001%s", p, ln, cat, detail)] = sprintf("{\"category\": %s, \"path\": %s, \"line\": %d, \"detail\": %s}", js(cat), js(p), ln, js(detail)) }
function addlist(arr, key, v) { if (index("\001" arr[key] "\001", "\001" v "\001") == 0) arr[key] = arr[key] (arr[key] == "" ? "" : "\001") v }
function joinsorted(s, sep,   a, n, i, out) { n = split(s, a, "\001"); asort(a); out = ""; for (i = 1; i <= n; i++) out = out (i > 1 ? sep : "") a[i]; return out }

# Sets RES ("ok", "amb", "dead") and RESLIST (\001-joined final paths).
function resolve(t, fromdir, ismd,   lt, h, r, b, cands, n, a, i, c, list) {
  h = index(t, "#"); if (h) t = substr(t, 1, h - 1)
  RESLIST = ""
  if (t == "") { RES = "self"; return }
  lt = tolower(t)
  if (ismd && fromdir != "") {
    r = tolower(normalize(fromdir "/" t))
    if (r in exists) { RES = "ok"; RESLIST = exists[r]; return }
    if ((r ".md") in exists) { RES = "ok"; RESLIST = exists[r ".md"]; return }
  }
  sub(/^\/+/, "", lt)
  if (lt in exists) { RES = "ok"; RESLIST = exists[lt]; return }
  if ((lt ".md") in exists) { RES = "ok"; RESLIST = exists[lt ".md"]; return }
  b = base(lt); list = ""
  cands = bybase[b] (bybase[b ".md"] != "" && bybase[b] != "" ? "\001" : "") bybase[b ".md"]
  n = split(cands, a, "\001")
  for (i = 1; i <= n; i++) {
    c = tolower(a[i])
    if (c == lt || c == lt ".md" || substr(c, length(c) - length(lt)) == "/" lt || substr(c, length(c) - length(lt) - 3) == "/" lt ".md")
      addlist(L_, "x", a[i])
  }
  list = L_["x"]; delete L_
  if (list == "" && lt !~ /\//) list = aliasowners[lt]
  RESLIST = list
  RES = list == "" ? "dead" : (index(list, "\001") ? "amb" : "ok")
}

# Checks one link token; returns the replacement (the token itself unless dead).
function handle(p, k, tok,   fp, emb, body, inner, pp, target, disp, rest, text, dest, sp, i, n, a) {
  fp = final[p]
  emb = substr(tok, 1, 1) == "!"; body = emb ? substr(tok, 2) : tok
  if (substr(body, 1, 2) == "[[") {
    inner = substr(body, 3, length(body) - 4)
    if (inner ~ /\{\{/) { placeholder(fp, k, tok); return tok }
    pp = index(inner, "|")
    if (pp) { target = substr(inner, 1, pp - 1); disp = substr(inner, pp + 1); sub(/\\$/, "", target) }
    else { target = inner; disp = inner }
    resolve(target, "", 0)
  } else {
    i = index(body, "](")
    text = substr(body, 2, i - 2); dest = substr(body, i + 2, length(body) - i - 2)
    if (substr(dest, 1, 1) == "<") dest = substr(dest, 2, length(dest) - 2)
    else { sp = index(dest, " "); if (sp) dest = substr(dest, 1, sp - 1) }
    if (dest == "" || dest ~ /^#/ || dest ~ /^[A-Za-z][A-Za-z0-9+.-]*:/) return tok
    if (dest ~ /\{\{/) { placeholder(fp, k, tok); return tok }
    dest = urldecode(dest)
    disp = text != "" ? text : dest
    resolve(dest, dir(fp), 1)
  }
  if (RES == "self") return tok
  if (RES == "amb") finding("ambiguous-link", fp, k, tok " matches " joinsorted(RESLIST, ", "))
  if (RES == "ok" || RES == "amb") {
    n = split(RESLIST, a, "\001")
    for (i = 1; i <= n; i++) if (a[i] != fp) incoming[a[i]]++
    return tok
  }
  D[sprintf("%s\001%08d\001%04d", fp, k, ++nseq)] = sprintf("{\"path\": %s, \"line\": %d, \"deadLink\": %s}", js(fp), k, js(tok))
  ndead++
  return disp
}
function placeholder(fp, k, tok) { P[sprintf("%s\001%08d\001%04d", fp, k, ++nseq)] = sprintf("{\"path\": %s, \"line\": %d, \"link\": %s}", js(fp), k, js(tok)) }

function scanline(p, k,   raw, masked, out, pos, rest, tok, rep) {
  raw = line[p, k]
  if (index(raw, "[") == 0) return
  masked = maskcode(raw); out = ""; pos = 1; rest = masked
  while (match(rest, /!?\[\[[^]]*\]\]|!?\[[^]]*\]\((<[^>]*>|[^)]*)\)/)) {
    tok = substr(raw, pos + RSTART - 1, RLENGTH)
    out = out substr(raw, pos, RSTART - 1)
    rep = handle(p, k, tok)
    out = out rep
    pos += RSTART - 1 + RLENGTH
    rest = substr(masked, pos)
  }
  out = out substr(raw, pos)
  if (out != raw) { line[p, k] = out; changed[p] = 1 }
}

# Walks the body: links outside code, and empty-section check when wanted.
function scanbody(p, checksections,   k, n, c, infence, fch, flen, m, incomment, hl, hlev, htext, nh, i, j, lev, kind, e, nev) {
  n = nlines[p]
  for (k = 2; k < fmend[p]; k++) scanline(p, k)
  infence = 0; incomment = 0; nev = 0
  for (k = fmend[p] + 1; k <= n; k++) {
    c = line[p, k]; sub(/\r$/, "", c)
    if (match(c, /^ {0,3}(```+|~~~+)/)) {
      m = substr(c, RSTART, RLENGTH); sub(/^ +/, "", m)
      if (!infence) { infence = 1; fch = substr(m, 1, 1); flen = length(m) }
      else if (substr(m, 1, 1) == fch && length(m) >= flen && trim(substr(c, RLENGTH + 1)) == "") infence = 0
      ev[++nev] = "c"; continue
    }
    if (infence) { ev[++nev] = "c"; continue }
    scanline(p, k)
    kind = "c"
    if (incomment) { kind = "i"; if (index(c, "-->")) incomment = 0 }
    else if (c ~ /^#{1,6}([ \t]|$)/) { match(c, /^#+/); kind = "h" RLENGTH; hline[nev + 1] = k; htext[nev + 1] = trim(c) }
    else if (trim(c) == "" || c ~ /^[ \t]*\^[A-Za-z0-9-]+[ \t]*$/) kind = "i"
    else if (c ~ /^[ \t]*<!--/) {
      e = index(c, "-->")
      if (!e) { incomment = 1; kind = "i" }
      else if (trim(substr(c, e + 3)) == "") kind = "i"
    }
    ev[++nev] = kind
  }
  if (!checksections) { delete ev; return }
  for (i = 1; i <= nev; i++) {
    if (substr(ev[i], 1, 1) != "h") continue
    lev = substr(ev[i], 2) + 0
    for (j = i + 1; j <= nev && ev[j] == "i"; j++) ;
    if (j > nev || (substr(ev[j], 1, 1) == "h" && substr(ev[j], 2) + 0 <= lev))
      finding("empty-section", final[p], hline[i], htext[i])
  }
  delete ev; delete hline; delete htext
}

BEGIN {
  RS = "\n"
  while ((getline l < LIST) > 0) { split(l, a, "\t"); fpath[++nf] = a[1]; fdate[a[1]] = a[2] }
  close(LIST)
  while ((getline l < SEL) > 0) sel[++nsel] = l
  close(SEL)
  split(TYPES, a, " "); for (i in a) oktype[a[i]] = 1
  split(STATUSES, a, " "); for (i in a) okstatus[a[i]] = 1

  # Read notes: every .md outside Attachments, except the vault CLAUDE.md.
  for (i = 1; i <= nf; i++) {
    p = fpath[i]; final[p] = p
    if (tolower(p) !~ /\.md$/ || tolower(top(p)) == "attachments" || p == "CLAUDE.md") continue
    notes[++nn] = p
    RS = "^$"; content = ""; getline content < p; close(p); RS = "\n"
    trail[p] = content ~ /\n$/
    if (trail[p]) content = substr(content, 1, length(content) - 1)
    nlines[p] = split(content, a, "\n")
    for (k = 1; k <= nlines[p]; k++) line[p, k] = a[k]
    # Frontmatter
    fmend[p] = 0; key = ""
    c = line[p, 1]; sub(/\r$/, "", c)
    if (c == "---") for (k = 2; k <= nlines[p]; k++) { c = line[p, k]; sub(/\r$/, "", c); if (c == "---") { fmend[p] = k; break } }
    for (k = 2; k < fmend[p]; k++) {
      c = line[p, k]; sub(/\r$/, "", c)
      if (match(c, /^[A-Za-z0-9_-]+:/)) {
        key = tolower(substr(c, 1, RLENGTH - 1)); v = trim(substr(c, RLENGTH + 1))
        fmline[p, key] = k
        if (v ~ /^\[.*\]$/) { m = split(substr(v, 2, length(v) - 2), b, ","); for (j = 1; j <= m; j++) additem(p, key, b[j], k) }
        else if (v != "") {
          sub(/[ \t]+#.*$/, "", v); v = unquote(v)
          if (key == "tags" || key == "aliases") additem(p, key, v, k); else fmval[p, key] = v
        }
      } else if (key != "" && match(c, /^[ \t]*-[ \t]*/)) additem(p, key, substr(c, RLENGTH + 1), k)
    }
    status[p] = tolower(fmval[p, "status"])
  }

  # 1. Stray drafts into the Inbox.
  for (i = 1; i <= nf; i++) taken[tolower(fpath[i])] = 1
  for (i = 1; i <= nn; i++) {
    p = notes[i]
    if (status[p] != "draft" || top(p) == "01. Inbox" || !selected(p)) continue
    to = "01. Inbox/" base(p)
    if (tolower(to) in taken) { finding("status-location", p, fmline[p, "status"], "draft outside 01. Inbox, not moved: " to " already exists"); continue }
    taken[tolower(to)] = 1; final[p] = to; nmoved++
    M[nmoved] = sprintf("{\"from\": %s, \"to\": %s}", js(p), js(to))
    print p "\t" to > (TMP "/moves")
  }

  # Link index on final paths.
  for (i = 1; i <= nf; i++) { fp = final[fpath[i]]; exists[tolower(fp)] = fp; addlist(bybase, tolower(base(fp)), fp) }
  for (i = 1; i <= nn; i++) { p = notes[i]; for (j = 1; j <= items[p, "aliases"]; j++) addlist(aliasowners, tolower(item[p, "aliases", j]), final[p]) }

  # 2. Dead links (all folders) and the per-note checks.
  for (i = 1; i <= nn; i++) {
    p = notes[i]
    if (!selected(p)) continue
    fp = final[p]; checks = !exempt(fp)
    scanbody(p, checks)
    if (status[p] == "archived" && top(fp) != "99. Archived") finding("status-location", fp, fmline[p, "status"], "status archived outside 99. Archived")
    if (!checks) continue
    if (!fmend[p]) { finding("frontmatter-missing", fp, 1, "no frontmatter"); continue }
    split("type status created", req, " ")
    for (j = 1; j <= 3; j++) if (fmval[p, req[j]] == "" && !items[p, req[j]]) finding("frontmatter-missing", fp, 1, "no " req[j])
    v = fmval[p, "type"]; if (v != "" && !(v in oktype)) finding("frontmatter-invalid", fp, fmline[p, "type"], "type '" v "' is not in the vault CLAUDE.md list")
    v = fmval[p, "status"]; if (v != "" && !(v in okstatus)) finding("frontmatter-invalid", fp, fmline[p, "status"], "status '" v "' is not in the vault CLAUDE.md list")
    v = fmval[p, "created"]; if (v != "" && v !~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/) finding("frontmatter-invalid", fp, fmline[p, "created"], "created '" v "' is not YYYY-MM-DD")
    for (j = 1; j <= items[p, "tags"]; j++) { v = item[p, "tags", j]; if (v !~ /^[a-z0-9]+(-[a-z0-9]+)*$/) finding("frontmatter-invalid", fp, itemline[p, "tags", j], "tag '" v "' is not lowercase kebab-case") }
    if (!FILESMODE && top(fp) == "01. Inbox") {
      v = fmval[p, "created"]
      if (v ~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/) { if (v < CUTOFF) finding("inbox-age", fp, fmline[p, "created"], "created " v ", older than 7 days") }
      else if (fdate[p] < CUTOFF) finding("inbox-age", fp, 1, "file date " fdate[p] ", older than 7 days")
    }
  }

  # 3. Whole-vault checks: duplicates and orphans (full mode only).
  # Archived notes are left out of duplicates: a merge adds their name as an alias by design.
  if (!FILESMODE) {
    for (i = 1; i <= nn; i++) { fp = final[notes[i]]; if (top(fp) != "99. Archived") { nm = tolower(base(fp)); sub(/\.md$/, "", nm); addlist(named, nm, fp); nameof[fp] = nm } }
    for (i = 1; i <= nn; i++) {
      p = notes[i]; fp = final[p]
      if (!(fp in nameof)) continue
      nm = nameof[fp]; others = ""
      m = split(named[nm], b, "\001"); for (j = 1; j <= m; j++) if (b[j] != fp) others = others (others == "" ? "" : "\001") b[j]
      if (others != "") finding("duplicate-name", fp, 1, "same name as " joinsorted(others, ", "))
      for (j = 1; j <= items[p, "aliases"]; j++) {
        al = item[p, "aliases", j]; la = tolower(al)
        if (la == nm) continue
        if (la in named) finding("duplicate-name", fp, itemline[p, "aliases", j], "alias '" al "' equals the name of " joinsorted(named[la], ", "))
        others = ""
        m = split(aliasowners[la], b, "\001"); for (x = 1; x <= m; x++) if (b[x] != fp && (b[x] in nameof)) others = others (others == "" ? "" : "\001") b[x]
        if (others != "") finding("duplicate-name", fp, itemline[p, "aliases", j], "alias '" al "' is also an alias of " joinsorted(others, ", "))
      }
    }
    for (i = 1; i <= nn; i++) { fp = final[notes[i]]; if (!exempt(fp) && base(fp) != "Home.md" && !incoming[fp]) O[fp] = js(fp) }
  }

  # Rewritten notes go to temp files; lint.sh copies them in unless --dry-run.
  for (i = 1; i <= nn; i++) {
    p = notes[i]
    if (!changed[p]) continue
    f = TMP "/rw" i; out = ""
    for (k = 1; k <= nlines[p]; k++) out = out line[p, k] (k < nlines[p] || trail[p] ? "\n" : "")
    printf "%s", out > f; close(f)
    print i "\t" final[p] > (TMP "/rewrites")
  }

  printf "{\n  \"movedToInbox\": ["; for (i = 1; i <= nmoved; i++) printf "%s\n    %s", (i > 1 ? "," : ""), M[i]; printf "%s],\n", (nmoved ? "\n  " : "")
  emit("removedDeadLinks", D, ","); emit("placeholderLinks", P, ","); emit("orphans", O, ","); emit("findings", F, "")
  printf "}\n"
  exit (nmoved || ndead || nfind) ? 1 : 0
}
function emit(name, arr, tail,   n, keys, i) {
  n = asorti(arr, keys)
  printf "  \"%s\": [", name
  for (i = 1; i <= n; i++) printf "%s\n    %s", (i > 1 ? "," : ""), arr[keys[i]]
  printf "%s]%s\n", (n ? "\n  " : ""), tail
}
AWK
rc=$?
[ "$rc" -le 1 ] || die "internal error (awk exit $rc)"

if [ "$dry" = 0 ]; then
  if [ -f "$tmp/moves" ]; then
    while IFS=$'\t' read -r from to; do
      [ -e "$to" ] && die "refusing to overwrite $to"
      mv -n -- "$from" "$to" || die "move failed: $from"
    done < "$tmp/moves"
  fi
  if [ -f "$tmp/rewrites" ]; then
    while IFS=$'\t' read -r i path; do cat "$tmp/rw$i" > "$path" || die "write failed: $path"; done < "$tmp/rewrites"
  fi
fi
cat "$tmp/out.json"
exit "$rc"
