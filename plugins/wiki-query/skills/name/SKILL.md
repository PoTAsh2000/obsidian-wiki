---
name: name
description: List notes in the user's Obsidian vault whose filename or title contains a text, falling back to aliases. Use when the user asks to find or look up a note by name in their vault or notes, for example "which note in my vault is called context", "find my note about RBH". Do not use for general questions that do not mention the vault, Obsidian or their notes.
argument-hint: "<text>"
---

# Find notes by name

Read-only. Lists matching notes in the vault and changes nothing.

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

## 3. Run the lookup

Run this in Bash, with the vault path from step 1:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/find.sh" --vault "<vault>" name "$ARGUMENTS"
```

- Show the output exactly as printed, in a code block. Do not add, remove, reorder or summarize lines, and do not open the notes.
- Exit 0 means something was found, 1 means nothing was found (the output says "Nothing found."). Both are normal results.
- Exit 2 is a usage error: show the message and the usage line from stderr.
- No arguments given: ask for the text to search, then run the command.
