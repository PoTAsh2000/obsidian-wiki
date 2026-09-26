---
name: tag
description: List notes in the user's Obsidian vault by frontmatter tag, one block per tag. Use when the user asks which of their notes have a tag, for example "which notes in my vault are tagged ai", "list my notes with tag tooling". Do not use for tags in code, git or other tools.
argument-hint: "<tag>..."
allowed-tools: Bash(bash ${CLAUDE_SKILL_DIR}/scripts/*)
model: haiku
effort: low
---

# Find notes by tag

Read-only. Lists matching notes in the vault and changes nothing. Never ask for the vault path and never write it; only `wiki-vault` does that.

The lookup already ran:

!`bash ${CLAUDE_SKILL_DIR}/scripts/tag.sh '$ARGUMENTS'`

## What to do with the output above

1. Read the vault CLAUDE.md first: it is the text between `claude-md: begin` and `claude-md: end`. Its rules win over this skill on any difference, except that this skill never writes to the vault.
2. Then act on the first matching case:
   - A line `ERROR: <message>`: reply with `<message>` exactly. If the message is about an invalid tag, ask for corrected tags and rerun as below; otherwise stop.
   - A line `need: tags`: ask the user for one or more tags, separated by spaces. Then run `bash ${CLAUDE_SKILL_DIR}/scripts/tag.sh '<tags separated by spaces>'` (all tags in one pair of single quotes) and handle its output the same way.
   - `found: yes` or `found: no`: show the lines between `result: begin` and `result: end` exactly as printed, in a code block. Do not add, remove, reorder or summarize lines, and do not open the notes. `found: no` means the output says "Nothing found."; that is a normal result.
3. When you ran the script yourself and it exits 1 (`SYSTEM ERROR:`): run `bash ${CLAUDE_SKILL_DIR}/scripts/tag.sh --help` once and fix the call; if it still fails, show the error and stop.
