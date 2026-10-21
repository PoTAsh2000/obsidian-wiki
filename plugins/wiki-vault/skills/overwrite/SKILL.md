---
name: overwrite
description: Replace the configured Obsidian vault folder for all obsidian-wiki plugins with a new path. Use when the user runs /wiki-vault:overwrite or asks to change or update their Obsidian vault path for the wiki skills.
argument-hint: "[vault path]"
model: haiku
effort: low
allowed-tools: Bash(python3:*)
---

# Overwrite the vault path

Replaces the vault path in `~/.claude/obsidian-wiki/vault-path`. `overwrite.py` does every check and the write; it never touches the vault. Run no other commands.

## 1. Get the path

Use `$ARGUMENTS`. Empty: ask the user once for the absolute path to their vault root folder.

## 2. Save

Run exactly, path in double quotes:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/overwrite.py" "<path>"
```

- Exit 0: reply the text after `reply: ` as is.
- Exit 3: ask the text after `ask: ` as is, once. With `on-no:`: yes runs the same command with `--force` before the path; no replies the text after `on-no: ` and stops. With `on-yes:` too: yes runs without `--force` on the path after `on-yes: `, anyway runs with `--force`. Without `on-no:`: the answer is the new path, back to step 2.
- Exit 1 or 2: fix the call once if the error shows how (`overwrite.py --help`). Still failing: show the error line and stop.
