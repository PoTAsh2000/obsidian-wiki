---
name: add
description: Configure the Obsidian vault folder once for all obsidian-wiki plugins. Use when the user runs /wiki-vault:add or asks to set up or configure their Obsidian vault path for the wiki skills.
argument-hint: "[vault path]"
---

# Add the vault path

Stores the vault path in `~/.claude/obsidian-wiki/vault-path`, the one place all obsidian-wiki skills read it from. Only adds; it never changes a path that is already there.

## 1. Check if a path is configured

```bash
cat ~/.claude/obsidian-wiki/vault-path 2>/dev/null
```

Output not empty: reply `Vault is already configured: <path>. Use /wiki-vault:overwrite to change it.` and stop.

## 2. Get the path

Use `$ARGUMENTS` as the path. Empty: ask the user once for the absolute path to the root folder of their vault. Replace every `\` with `/`.

## 3. Check the folder

```bash
[ -d "<path>" ]
```

Folder not found: ask the user whether to configure it anyway. No: reply `Run /wiki-vault:add later when you are ready to configure the vault.` and stop.

## 4. Save

```bash
mkdir -p ~/.claude/obsidian-wiki && printf '%s\n' "<path>" > ~/.claude/obsidian-wiki/vault-path
```

Reply `Vault configured: <path>`.
