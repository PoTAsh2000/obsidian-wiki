---
name: delete
description: Remove the configured Obsidian vault folder for all obsidian-wiki plugins. Use when the user runs /wiki-vault:delete or asks to remove or forget their Obsidian vault path for the wiki skills.
model: haiku
effort: low
allowed-tools: Bash(python3:*)
---

# Delete the vault path

Removes `~/.claude/obsidian-wiki/vault-path`. It never touches the vault itself. Run exactly:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/delete.py"
```

On exit 0, reply with its stdout verbatim. On any other exit code, report the `SYSTEM ERROR:` line to the user and stop. Do not remove the file another way.

Do nothing else.
