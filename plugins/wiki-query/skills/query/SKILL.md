---
name: query
description: Answer a question from the user's own Obsidian vault notes, citing each note as a [[Note]] wikilink. Use only when the user asks what their notes, vault, wiki or Obsidian say, for example "what do I already know about EDI mapping?", "what do my notes say about context engineering?", "search my vault for ...". Do not use for general questions such as a plain "what is X?" that do not mention the user's notes, vault, wiki or Obsidian. Read-only.
argument-hint: "<question>"
allowed-tools: Read, Grep, Glob
---

# Answer from my notes

Answers the question in `$ARGUMENTS` from the notes in the vault only. Read-only: never create, edit, move or delete a file in the vault, and never offer to. Saving an answer is `wiki-save:save`, and only when the user asks.

## 1. Find the vault

Read the vault path configured by `wiki-vault`:

```bash
cat ~/.claude/obsidian-wiki/vault-path 2>/dev/null
```

- No output: reply exactly `Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault.` and stop.
- The folder does not contain `CLAUDE.md`: say so, point to `/wiki-vault:overwrite`, and stop.

Never ask for the path and never write it; only `wiki-vault` does that.

## 2. Read the vault CLAUDE.md

Read `<vault>/CLAUDE.md` before anything else in the vault. Its rules win over this skill on any difference, except that this skill never writes to the vault.

## 3. Find the relevant notes

- Search every folder except dot folders (`.obsidian`), `Attachments` and `90. Templates`. Use Grep on the vault for the key terms of the question and their synonyms, case-insensitive, in filenames, titles, `aliases`, `tags`, `topic` and body text.
- Read the best matches, starting with notes whose filename, title or alias matches the subject. Follow `[[links]]` and `related` from those notes when they look relevant. Stop when the question is covered; do not read the whole vault.
- Notes in `99. Archived` count only when nothing else covers the question; say so when you use one.

## 4. Answer

- Answer only from what the notes say. Do not fill gaps from general knowledge without marking it clearly as "Not in your notes:".
- Cite every claim with the note it came from, as a wikilink in the shortest form: `[[Context Engineering]]` (filename without `.md`, no folder).
- When a cited note is `draft` or `review`, mention its status once, since it is not yet approved.
- When notes contradict each other, show both with their citations.
- When the notes do not cover the question, say "Your notes do not cover this." and list the closest notes found, if any.
- End with a short "Sources:" list of the cited notes as `[[Note]]` links.
- English, no em dashes.
