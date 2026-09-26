---
name: add
description: Configure the Obsidian vault folder once for all obsidian-wiki plugins. Use when the user runs /wiki-vault:add or asks to set up or configure their Obsidian vault path for the wiki skills.
argument-hint: "[vault path]"
model: haiku
effort: low
allowed-tools: Bash(bash "${CLAUDE_SKILL_DIR}/scripts/*)
---

# Add the vault path

Stores the vault path in `~/.claude/obsidian-wiki/vault-path`, the one place all obsidian-wiki skills read it from. Only adds; it never changes a path that is already there and never touches the vault itself.

## 1. Current state

!`bash "${CLAUDE_SKILL_DIR}/scripts/status.sh"`

- `configured: <path>` (not `none`): reply `Vault is already configured: <path>. Use /wiki-vault:overwrite to change it.` and stop.
- `configured: none`: go on.

## 2. Get the path

Use `$ARGUMENTS` as the path. Empty: ask the user once for the absolute path to the root folder of their vault.

## 3. Save

Run exactly this, with the path as one quoted argument (the script turns every `\` into `/`):

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/add.sh" -- "<path>"
```

- Exit 0: reply `Vault configured: <path>` with the path from the `configured:` line.
- Exit 3, `folder not found: <path>`: ask the user whether to configure it anyway. Yes: run the same command with `--allow-missing` before `--`, then reply as for exit 0. No: reply `Run /wiki-vault:add later when you are ready to configure the vault.` and stop.
- Exit 3, `already configured: <path>`: reply `Vault is already configured: <path>. Use /wiki-vault:overwrite to change it.` and stop.
- Exit 2: fix the call once (see `add.sh --help`) and run it again. Still failing: report the error and stop.
- Exit 1: report the `SYSTEM ERROR:` line to the user and stop.

Do nothing else.
