---
name: save
description: Save a useful answer or insight from the current conversation as a new draft note in the user's Obsidian vault Inbox. Use when the user says "save this to my vault", "save this to Obsidian", "put this in my notes" or "add this to my wiki". Do not use for general save requests about code, files, commits, settings or memory that do not mention the vault, Obsidian or notes.
argument-hint: "[title]"
---

# Save to the vault

Saves one useful answer from this conversation as exactly one new `draft` note in `01. Inbox`. It never changes any other note, never overwrites a file and never deletes anything.

## 1. Find the vault

Read the vault path configured by `wiki-vault`:

```bash
cat ~/.claude/obsidian-wiki/vault-path 2>/dev/null
```

- No output: reply exactly `Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault.` and stop.
- The folder does not contain `CLAUDE.md` or a `01. Inbox` folder: say so, point to `/wiki-vault:overwrite`, and stop.

Never ask for the path and never write it; only `wiki-vault` does that.

## 2. Read the vault CLAUDE.md

Read `<vault>/CLAUDE.md` before anything else in the vault. Its rules and frontmatter schema win over this skill on any difference, except that this skill only ever creates a `draft` note in `01. Inbox`.

## 3. Pick the content

Take only the useful answer or insight the user wants to keep, usually the last substantial answer. Not the transcript, not the back-and-forth. Rewrite it as a standalone note: a `# <Title>` heading, then the content in short sections. English, no em dashes.

## 4. Pick the title

- Title given as argument (`$ARGUMENTS`): use it.
- No title: propose one short title and ask the user to confirm or change it before writing.
- The filename is `<Title>.md`. Replace characters that are not allowed in filenames or break Obsidian links (`\ / : * ? " < > | # ^ [ ]`) with a space or dash, and tell the user if you did.

## 5. Check for an existing file

Look for `<vault>/01. Inbox/<Title>.md`, case-insensitive (Windows treats `Tokens.md` and `tokens.md` as the same file). Also search the whole vault for a note with the same filename, since links use the shortest form `[[Title]]` and a duplicate name makes them ambiguous.

- **No file with that name anywhere:** go to step 6.
- **It exists in `01. Inbox` with `status: draft`:** never overwrite. Offer two choices: append to it, or save under another title (propose one). Append only after the user picks it: add the new content at the end under a `## <YYYY-MM-DD>` heading. Do not touch its frontmatter or existing text.
- **Any other case** (a different status, no status, or a note with that name in another folder): do not append and do not overwrite. Say which note and status it is, propose a different title, and go back to step 5 with that title.

## 6. Write the note

Create the file with the Write tool, only after step 5 found no file. Frontmatter, following the vault schema:

```yaml
---
type: knowledge
topic: AI
aliases: []
tags: [ai, tooling]
status: draft
created: YYYY-MM-DD
related: ["[[Existing Note]]"]
source: claude session YYYY-MM-DD
---
```

- `type`: one of the allowed values in the vault `CLAUDE.md`. Never invent a new one; if none fits, use `knowledge` and mention it.
- `topic`: the main topic, reuse an existing topic from the vault when one fits.
- `tags`: lowercase kebab-case.
- `status`: always `draft`, nothing else.
- `created` and the `source` date: today, from `date +%F`.
- `related`: existing notes that are really related. Find them by searching filenames, titles and `aliases` in the vault. Only link notes that exist; use `[]` when there are none. Link them in the body with `[[Note]]` where it helps. Never edit those notes.

## 7. Report

One line with the path from the vault root, for example `Saved as draft: 01. Inbox/ACE vs SOP.md`, or `Appended to draft: 01. Inbox/ACE vs SOP.md`. Mention `/wiki-ingest:ingest` to process it later.
