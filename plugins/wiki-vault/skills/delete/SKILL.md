---
name: delete
description: Remove the configured Obsidian vault folder for all obsidian-wiki plugins. Use when the user runs /wiki-vault:delete or asks to remove or forget their Obsidian vault path for the wiki skills.
model: haiku
effort: low
allowed-tools: 'Bash(bash "${CLAUDE_SKILL_DIR}/scripts/delete.sh")'
---

# Delete the vault path

Removes `~/.claude/obsidian-wiki/vault-path`. It never touches the vault itself. Run exactly:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/delete.sh"
```

- `removed: <path>`: reply `Vault path removed: <path>`.
- `removed: none`: reply `No vault path configured.`
- Exit 2 (bad usage): run it once more exactly as above, with no arguments.
- Exit 1, or exit 2 again: report the `SYSTEM ERROR:` line to the user and stop. Do not remove the file another way.

Do nothing else.
