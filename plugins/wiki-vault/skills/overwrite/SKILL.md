---
name: overwrite
description: Replace the configured Obsidian vault folder for all obsidian-wiki plugins with a new path. Use when the user runs /wiki-vault:overwrite or asks to change or update their Obsidian vault path for the wiki skills.
argument-hint: "[vault path]"
model: haiku
effort: low
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/overwrite.sh *)
---

# Overwrite the vault path

Replaces the vault path in `~/.claude/obsidian-wiki/vault-path`, the one place all obsidian-wiki skills read it from. `overwrite.sh` does every check and the write. It never touches the vault itself. Do nothing else: no other commands, no retries beyond what is listed here.

## 1. Get the path

Use `$ARGUMENTS` as the path. Empty: ask the user once for the absolute path to the root folder of their vault.

## 2. Save

Run exactly, with the path in double quotes:

```bash
${CLAUDE_SKILL_DIR}/scripts/overwrite.sh "<path>"
```

- Exit 0: output is `path: <path>` and `old: <old path or none>`. Reply `Vault configured: <path>`, and add ` (was: <old path>)` when `old` is not `none`.
- Exit 3 with `USER ERROR: folder not found`: ask the user whether to configure it anyway. Yes: run the same command with `--force` before the path and reply as for exit 0. No: reply `Run /wiki-vault:overwrite later when you are ready to configure the vault.` and stop.
- Other exit 3: show the error line to the user, ask once for a corrected absolute path and go back to step 2.
- Exit 1 or 2: fix the call once if the error shows how (see `overwrite.sh --help`). Still failing: show the error line to the user and stop.
