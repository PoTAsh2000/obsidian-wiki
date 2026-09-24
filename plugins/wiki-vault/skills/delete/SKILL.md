---
name: delete
description: Remove the configured Obsidian vault folder for all obsidian-wiki plugins. Use when the user runs /wiki-vault:delete or asks to remove or forget their Obsidian vault path for the wiki skills.
---

# Delete the vault path

Removes `~/.claude/obsidian-wiki/vault-path`. It never touches the vault itself.

```bash
cat ~/.claude/obsidian-wiki/vault-path 2>/dev/null && rm ~/.claude/obsidian-wiki/vault-path
```

- Output shows a path: reply `Vault path removed: <path>`.
- No output: reply `No vault path configured.`
