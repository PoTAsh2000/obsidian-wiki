---
name: status
description: List notes in the user's Obsidian vault by frontmatter status (draft, review, evergreen, archived), one block per status. Use when the user asks which of their notes have a status, for example "which notes in my vault are still in review", "list my draft notes". Read-only, never use it to change a status.
argument-hint: "<status>..."
model: haiku
effort: low
allowed-tools: Bash(python3 *)
---

# Find notes by status

Read-only. Lists matching notes in the vault and changes nothing. Never write to the vault and never write the vault path; only `wiki-vault` does that.

## 1. Vault

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vault.py"`

- Output starts with `ERROR:`: reply with the text after `ERROR: ` exactly and stop.
- Otherwise the `vault:` line is the vault, and the text after `--- vault CLAUDE.md ---` is the vault `CLAUDE.md`. Read it now and follow it. Do not read that file again. Its rules win over this skill on any difference, except that this skill never writes to the vault.

## 2. Lookup

The script below ran the lookup:

!`python3 "${CLAUDE_SKILL_DIR}/scripts/status.py" "$ARGUMENTS"`

## What to do

Any script that prints a line starting with `ERROR:` is handled the same way: reply with the text after `ERROR: ` and stop. Steps 1 and 2 below are the exceptions.

1. Output is `ERROR: no status given`: if arguments were passed to this skill, run the command in step 3 with them. Otherwise ask for one or more statuses, separated by spaces, then run the command in step 3.
2. Output starts with `ERROR: invalid status`: show that line to the user, ask for a corrected status, then run the command in step 3.
3. Command, only for steps 1 and 2:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/status.py" <status>...
   ```

   Handle its output with steps 1 to 4. If it exits 1 or 2, show its stderr line to the user and stop; do not retry.
4. Otherwise show every line after the `found:` line exactly as printed, in a code block. Do not add, remove, reorder or summarize lines, and do not open the notes. `found: no` (the result says "Nothing found.") is a normal result, not an error.
