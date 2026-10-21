---
name: current
description: Show the configured Obsidian vault folder of all obsidian-wiki plugins and check it. Use when the user runs /wiki-vault:current or asks which vault path is configured for the wiki skills.
model: haiku
effort: low
allowed-tools: Bash(python3:*)
---

# Show the vault path

Shows the path in `~/.claude/obsidian-wiki/vault-path`, or why it is not usable. Changes nothing. Run exactly:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/current.py"
```

On exit 0, reply with its stdout verbatim. On any other exit code, report the `SYSTEM ERROR:` line to the user and stop.

Do nothing else.
