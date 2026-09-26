---
name: status
description: List notes in the user's Obsidian vault by frontmatter status (draft, review, evergreen, archived), one block per status. Use when the user asks which of their notes have a status, for example "which notes in my vault are still in review", "list my draft notes". Read-only, never use it to change a status.
argument-hint: "<status>..."
model: haiku
effort: low
allowed-tools:
  - Bash(bash "${CLAUDE_SKILL_DIR}/scripts/status.sh")
  - Bash(bash "${CLAUDE_SKILL_DIR}/scripts/status.sh" *)
---

# Find notes by status

Read-only. Lists matching notes in the vault and changes nothing. Never write to the vault and never write the vault path; only `wiki-vault` does that.

The script below already read the vault path from `~/.claude/obsidian-wiki/vault-path`, read the vault `CLAUDE.md` and ran the lookup:

!`bash "${CLAUDE_SKILL_DIR}/scripts/status.sh" "$ARGUMENTS"`

## What to do

1. Read the vault `CLAUDE.md` above, between `--- vault CLAUDE.md ---` and `--- end CLAUDE.md ---`. Its rules win over this skill on any difference, except that this skill never writes to the vault.
2. Output starts with `ERROR: Vault path is missing.`, `ERROR: Vault folder not found` or `ERROR: The vault folder`: reply with the text after `ERROR: ` exactly, and stop.
3. Output is `ERROR: no status given`: if arguments were passed to this skill, run the command in step 5 with them. Otherwise ask for one or more statuses, separated by spaces, then run the command in step 5.
4. Output starts with `ERROR: invalid status`: show that line to the user, ask for a corrected status, then run the command in step 5.
5. Command, only for steps 3 and 4:

   ```bash
   bash "${CLAUDE_SKILL_DIR}/scripts/status.sh" <status>...
   ```

   Handle its output with steps 1 to 6. If it exits 1 or 2, show its stderr line to the user and stop; do not retry.
6. Otherwise show every line after `--- result ---` exactly as printed, in a code block. Do not add, remove, reorder or summarize lines, and do not open the notes. `found: no` (the result says "Nothing found.") is a normal result, not an error.
