---
name: name
description: List notes in the user's Obsidian vault whose filename or title contains a text, falling back to aliases. Use when the user asks to find or look up a note by name in their vault or notes, for example "which note in my vault is called context", "find my note about RBH". Do not use for general questions that do not mention the vault, Obsidian or their notes.
argument-hint: "<text>"
model: haiku
effort: low
allowed-tools:
  - Bash(bash "${CLAUDE_PLUGIN_ROOT}/skills/name/scripts/gather.sh")
  - Bash(bash "${CLAUDE_PLUGIN_ROOT}/skills/name/scripts/name.sh" *)
---

# Find notes by name

Read-only. Lists matching notes in the vault and changes nothing. Never write to the vault, never ask for the vault path and never write it; only `wiki-vault` does that.

## 1. Vault and vault CLAUDE.md

!`bash "${CLAUDE_PLUGIN_ROOT}/skills/name/scripts/gather.sh"`

- If the line above starts with `ERROR:`, reply with the text after `ERROR: ` exactly and stop.
- Otherwise it shows the vault path and the vault `CLAUDE.md`, which you have now read. Its rules win over this skill on any difference, except that this skill never writes to the vault.

## 2. Run the lookup

Search text: `$ARGUMENTS`

- Search text empty: ask the user for the text to search, then run the command below with it.
- Otherwise run exactly this Bash command, with the search text in double quotes (escape `"`, `$` and backticks in it with a backslash):

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/name/scripts/name.sh" -- "<search text>"
```

## 3. Report

- Exit 0: show stdout exactly as printed, in a code block. Do not add, remove, reorder or summarize lines, and do not open the notes. `Nothing found.` is a normal result.
- Exit 3 (`USER ERROR:`): reply with the text after `USER ERROR: ` exactly and stop.
- Exit 1 or 2 (`SYSTEM ERROR:`): fix the call once if the message shows how (run `name.sh --help` for usage), otherwise show the error line and stop.
