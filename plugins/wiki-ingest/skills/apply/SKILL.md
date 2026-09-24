---
name: apply
description: Marks reviewed notes in the Obsidian vault as evergreen (status review to evergreen). Runs only when the user types /wiki-ingest:apply.
argument-hint: "[note name]"
disable-model-invocation: true
---

# wiki-ingest:apply

Typing this command is the user's approval that their review is done. Run it only when the user typed `/wiki-ingest:apply`; never start it from another skill or from normal language.

Arguments: `$ARGUMENTS`

## 1. Vault path

Read the vault path configured by `wiki-vault`:

```bash
cat ~/.claude/obsidian-wiki/vault-path 2>/dev/null
```

- No output: reply exactly `Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault.` and stop.
- The folder does not contain `CLAUDE.md`: say so, point to `/wiki-vault:overwrite`, and stop.

Never ask for the path and never write it; only `wiki-vault` does that.

## 2. Read the vault rules

Read `CLAUDE.md` in the vault root before anything else, and follow it.

## 3. Find the notes

What apply may change: only the frontmatter line `status: review`, into `status: evergreen`. No other edit, no move, no link change, no extra plan or confirm. Never delete a note.

- **No argument:** Grep the vault for `^status:\s*["']?review["']?\s*$` in `*.md` files (every folder, skip dot folders). Keep only hits inside the frontmatter (the block between the first two `---` lines).
- **A note name:** find the note by filename (without `.md`), case-insensitive, anywhere in the vault. If there is no match, say so and stop. If several notes match, list their paths and ask which one. Read its frontmatter status. If it is not `review`, stop and say which status it has (or that it has none), and change nothing.

## 4. Apply

For each note, use Edit to replace the frontmatter `status` line with `status: evergreen`. Change nothing else in the file.

## 5. Report

End with the paths from the vault root, one per line:

```
Moved from review to evergreen:
- 30. Knowledge/Context Engineering.md
```

When nothing changed: `No notes moved from review to evergreen.`
