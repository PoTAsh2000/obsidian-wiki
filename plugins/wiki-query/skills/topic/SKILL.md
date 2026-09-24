---
name: topic
description: List notes in the user's Obsidian vault by frontmatter topic, one block per topic. Use when the user asks which of their notes have a topic, for example "which notes in my vault have topic EDI", "list my AI notes by topic". Do not use for general questions about a topic that do not mention the vault, Obsidian or their notes.
argument-hint: "<topic>..."
---

# Find notes by topic

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
bash "${CLAUDE_PLUGIN_ROOT}/scripts/find.sh" --vault "<vault>" topic $ARGUMENTS
```

- Show the output exactly as printed, in a code block. Do not add, remove, reorder or summarize lines, and do not open the notes.
- Exit 0 means something was found, 1 means nothing was found (the output says "Nothing found."). Both are normal results.
- Exit 2 is a usage error: show the message and the usage line from stderr.
- No arguments given: ask for one or more topics, separated by spaces, then run the command.
