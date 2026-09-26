---
name: apply
description: Marks reviewed notes in the Obsidian vault as evergreen (status review to evergreen). Runs only when the user types /wiki-ingest:apply.
argument-hint: "[note name]"
disable-model-invocation: true
model: haiku
effort: low
allowed-tools: Bash(bash "${CLAUDE_SKILL_DIR}/scripts/*)
---

# wiki-ingest:apply

Typing this command is the user's approval that their review is done. Run it only when the user typed `/wiki-ingest:apply`; never start it from another skill or from normal language.

Arguments: `$ARGUMENTS`

## 1. Read the vault CLAUDE.md

The vault path from `~/.claude/obsidian-wiki/vault-path` (configured by `wiki-vault`) and the vault `CLAUDE.md`:

!`bash "${CLAUDE_SKILL_DIR}/scripts/gather.sh"`

- A line starting with `ERROR: `: reply exactly the text after `ERROR: ` and stop.
- Otherwise read the vault `CLAUDE.md` above and follow it. It is already loaded; do not open it again.

Never ask for the vault path and never write it; only `wiki-vault` does that.

## 2. Apply

What apply may change: only the frontmatter line `status: review`, into `status: evergreen`. No other edit, no move, no link change, no extra plan or confirm. Never delete a note. The script below does exactly this; never edit notes by hand.

Run exactly this, once:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/apply.sh" '$ARGUMENTS'
```

Keep the argument in single quotes; write a `'` inside it as `'\''`. No argument changes every `review` note in the vault. A note name changes that one note, found by filename without `.md`, case-insensitive, in any folder except dot folders such as `.obsidian` or `.trash`.

- **Exit 0:** go to step 3.
- **Exit 3 with `match:` lines:** several notes have that name. List their paths, one per line in backticks, and ask which one. Then run the same command with the chosen path (for example `"30. Knowledge/Twin.md"`) in place of the name.
- **Exit 3 otherwise:** tell the user the reason from stderr (no such note, or its status is not `review`) and stop. Nothing changed.
- **Exit 2:** the argument was split; run once more with the whole argument as one single-quoted string. If it fails again, show the stderr line and stop.
- **Exit 1:** show the stderr line and stop.

## 3. Report

End with the `evergreen:` paths, one per line in backticks. The backticks stop Markdown from reading a folder number like `30.` as a numbered list:

```
Moved from review to evergreen:
- `30. Knowledge/Context Engineering.md`
```

When `count: 0`: `No notes moved from review to evergreen.`
