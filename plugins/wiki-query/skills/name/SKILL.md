---
name: name
description: List notes in the user's Obsidian vault whose filename or title contains a text, falling back to aliases. Use when the user asks to find or look up a note by name in their vault or notes, for example "which note in my vault is called context", "find my note about RBH". Do not use for general questions that do not mention the vault, Obsidian or their notes.
argument-hint: "<text>"
---

# Find notes by name

Read-only. Lists matching notes in the vault and changes nothing.

## 1. Find the vault

Resolve the vault path in this order and stop at the first that gives a folder:

1. The plugin option set at install: `${user_config.vault_path}`. It counts as set only when it shows a real path here, not an empty value or the literal placeholder.
2. Read `~/.claude/settings.json` and take `env.OBSIDIAN_VAULT`.
3. Neither is set: ask the user once for the vault folder. Show the exact change to `~/.claude/settings.json` (add `"OBSIDIAN_VAULT": "<path>"` under `env`, keeping everything else). Write it only after their OK. Without an OK, use the path for this run only.

The path is valid when it contains `CLAUDE.md`. If not, say so and ask for the path again.

## 2. Read the vault CLAUDE.md

Read `<vault>/CLAUDE.md` before anything else in the vault. Its rules win over this skill on any difference, except that this skill never writes to the vault. The only write it may make is the `settings.json` change in step 1, after the user's OK.

## 3. Run the lookup

Run this in Bash, with the vault path from step 1:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/find.sh" --vault "<vault>" name "$ARGUMENTS"
```

- Show the output exactly as printed, in a code block. Do not add, remove, reorder or summarize lines, and do not open the notes.
- Exit 0 means something was found, 1 means nothing was found (the output says "Nothing found."). Both are normal results.
- Exit 2 is a usage error: show the message and the usage line from stderr.
- No arguments given: ask for the text to search, then run the command.
