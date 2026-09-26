---
name: query
description: Answer a question from the user's own Obsidian vault notes, citing each note as a [[Note]] wikilink. Use only when the user asks what their notes, vault, wiki or Obsidian say, for example "what do I already know about EDI mapping?", "what do my notes say about context engineering?", "search my vault for ...". Do not use for general questions such as a plain "what is X?" that do not mention the user's notes, vault, wiki or Obsidian. Read-only.
argument-hint: "<question>"
allowed-tools: Read, Grep, Glob, Bash(${CLAUDE_SKILL_DIR}/scripts/*)
---

# Answer from my notes

Answers the question in `$ARGUMENTS` from the notes in the vault only. Read-only: never create, edit, move or delete a file in the vault, and never offer to. Saving an answer is `wiki-save:save`, and only when the user asks. No question given: ask for it, then continue.

## 1. Vault and vault CLAUDE.md

Gathered before this skill started (read the vault `CLAUDE.md` below first; the vault path comes from `~/.claude/obsidian-wiki/vault-path`, written by `wiki-vault`):

!`${CLAUDE_SKILL_DIR}/scripts/context.sh`

- The first line starts with `ERROR:`: reply with the text after `ERROR: ` exactly as printed and stop.
- Otherwise the `vault:` line is the vault, and the text after `--- vault CLAUDE.md ---` is the vault `CLAUDE.md`. Its rules win over this skill on any difference, except that this skill never writes to the vault. Do not read that file again.

Never ask for the vault path and never write it; only `wiki-vault` does that.

## 2. Find the relevant notes

Pick the key terms of the question plus synonyms, abbreviations and spelled-out forms (for example `EDI`, `EDIFACT`, `mapping`). Run exactly:

```bash
${CLAUDE_SKILL_DIR}/scripts/search.sh --vault "<vault>" -- <term> <term> ...
```

- Quote a multi-word phrase as one term. Add `--limit <n>` (max 200, before `--`) only when the default 20 is too few.
- Output: `matches:` and one line per note, best first, with `score`, `status`, how many terms hit and where (`name`, `title`, `alias`, `tag`, `topic`, `body:<line hits>`). It already skips dot folders, `Attachments`, `90. Templates` and the vault `CLAUDE.md`.
- `matches: 0` or weak hits only: run it once more with other synonyms. Use Grep on the vault only for something the script cannot match, such as a regex.
- Exit 2: fix the call once (run `--help` if unclear). Exit 1: report the `SYSTEM ERROR:` line to the user and stop. Exit 3: the vault folder is gone; tell the user to fix it with `/wiki-vault:overwrite` and stop.

Read the best matches with Read, starting with notes that hit in `name`, `title` or `alias`. Follow `[[links]]` and `related` from those notes when they look relevant. Stop when the question is covered; do not read the whole vault. Notes in `99. Archived` count only when nothing else covers the question; say so when you use one.

## 3. Answer

- Answer only from what the notes say. Do not fill gaps from general knowledge without marking it clearly as "Not in your notes:".
- Cite every claim with the note it came from, as a wikilink in the shortest form: `[[Context Engineering]]` (filename without `.md`, no folder).
- When a cited note is `draft` or `review` (see `status:` in the search output), mention its status once, since it is not yet approved.
- When notes contradict each other, show both with their citations.
- When the notes do not cover the question, say "Your notes do not cover this." and list the closest notes found, if any.
- End with a short "Sources:" list of the cited notes as `[[Note]]` links.
- English, no em dashes.
