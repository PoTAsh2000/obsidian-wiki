---
name: status
description: List notes in the user's Obsidian vault by frontmatter status (draft, review, evergreen, archived), one block per status. Use when the user asks which of their notes have a status, for example "which notes in my vault are still in review", "list my draft notes". Read-only, never use it to change a status.
argument-hint: "<status>..."
---

# Find notes by status

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
bash "${CLAUDE_PLUGIN_ROOT}/scripts/find.sh" --vault "<vault>" status $ARGUMENTS
```

- Show the output exactly as printed, in a code block. Do not add, remove, reorder or summarize lines, and do not open the notes.
- Exit 0 means something was found, 1 means nothing was found (the output says "Nothing found."). Both are normal results.
- Exit 2 is a usage error: show the message and the usage line from stderr.
- No arguments given: ask for one or more statuses, separated by spaces, then run the command.
