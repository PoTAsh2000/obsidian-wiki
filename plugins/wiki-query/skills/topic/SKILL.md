---
name: topic
description: List notes in the user's Obsidian vault by frontmatter topic, one block per topic. Use when the user asks which of their notes have a topic, for example "which notes in my vault have topic EDI", "list my AI notes by topic". Do not use for general questions about a topic that do not mention the vault, Obsidian or their notes.
argument-hint: "<topic>..."
model: haiku
effort: low
allowed-tools: Bash(bash "${CLAUDE_SKILL_DIR}/scripts/topic.sh" *)
---

# Find notes by topic

Read-only. Lists matching notes in the vault and changes nothing. The script reads the vault path configured by `wiki-vault`; never ask for the path and never write it.

## 1. Read the vault CLAUDE.md

The vault `CLAUDE.md`, printed by the script (empty when the vault is not set up). Its rules win over this skill on any difference, except that this skill never writes to the vault:

!`bash "${CLAUDE_SKILL_DIR}/scripts/topic.sh" --inject --rules`

## 2. Lookup result

!`bash "${CLAUDE_SKILL_DIR}/scripts/topic.sh" --inject $ARGUMENTS`

## 3. Reply

- Result is `ERROR: no topic given`: ask the user for one or more topics, separated by spaces. Then run exactly `bash "${CLAUDE_SKILL_DIR}/scripts/topic.sh" <topic>...` and reply as below with its output.
- Result is any other `ERROR: <text>`: reply with `<text>` exactly and stop. Do not retry.
- Otherwise show the result exactly as printed, in a code block. Do not add, remove, reorder or summarize lines, do not open the notes, and do not run anything else. `Nothing found.` is a normal result.

If a run of `topic.sh` exits non-zero:

- Exit 3 (stderr `USER ERROR: <text>`): reply with `<text>` exactly and stop. Do not retry.
- Exit 2 (bad call): run `bash "${CLAUDE_SKILL_DIR}/scripts/topic.sh" --help`, fix the call once. If it still fails, show the stderr line and stop.
- Exit 1 (system error): show the stderr line and stop.
