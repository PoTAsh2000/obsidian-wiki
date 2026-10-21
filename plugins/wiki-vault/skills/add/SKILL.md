---
name: add
description: Configure the Obsidian vault folder once for all obsidian-wiki plugins. Use when the user runs /wiki-vault:add or asks to set up or configure their Obsidian vault path for the wiki skills.
argument-hint: "[vault path]"
model: haiku
effort: low
allowed-tools: Bash(python3:*)
---

# Add the vault path

Stores the vault path in `~/.claude/obsidian-wiki/vault-path`. Never changes a stored path or touches the vault.

## 1. Current state

!`python3 "${CLAUDE_SKILL_DIR}/scripts/status.py"`

A `reply:` line: relay its text and stop.

## 2. Get the path

Path: `$ARGUMENTS`. Empty: ask once to pick a `candidate:` path (without its ` (...)` marks) or type another; no candidates: ask once for the absolute path of the vault root folder.

## 3. Save

Run `python3 "${CLAUDE_SKILL_DIR}/scripts/add.py" "<path>"`, the path as one quoted argument.

- `reply:`: relay it and each `warning:` and `notice:` line as is, then stop.
- `ask:`: ask its question. Yes: rerun add.py with the `yes:` arguments instead of `"<path>"`. No: rerun with the `no:` arguments; no `no:` line: reply `Run /wiki-vault:add later when you are ready to configure the vault.` and stop.
- Exit 2: fix the call once (`add.py --help`) and retry. Still failing, or a `SYSTEM ERROR:` line: report it and stop.
