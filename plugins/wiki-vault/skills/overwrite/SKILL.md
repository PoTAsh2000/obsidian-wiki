---
name: overwrite
description: Replace the configured Obsidian vault folder for all obsidian-wiki plugins with a new path. Use when the user runs /wiki-vault:overwrite or asks to change or update their Obsidian vault path for the wiki skills.
argument-hint: "[vault path]"
---

# Overwrite the vault path

Replaces the vault path in `~/.claude/obsidian-wiki/vault-path`, the one place all obsidian-wiki skills read it from.

## 1. Get the path

Use `$ARGUMENTS` as the path. Empty: ask the user once for the absolute path to the root folder of their vault. Replace every `\` with `/`.

## 2. Check the folder

```bash
[ -d "<path>" ]
```

Folder not found: ask the user whether to configure it anyway. No: reply `Run /wiki-vault:overwrite later when you are ready to configure the vault.` and stop.

## 3. Save

```bash
cat ~/.claude/obsidian-wiki/vault-path 2>/dev/null; mkdir -p ~/.claude/obsidian-wiki && printf '%s\n' "<path>" > ~/.claude/obsidian-wiki/vault-path
```

The first line of output is the old path, if there was one. Reply `Vault configured: <path>` and add `(was: <old path>)` when there was an old path.
