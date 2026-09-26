---
name: save
description: Save a useful answer or insight from the current conversation as a new draft note in the user's Obsidian vault Inbox. Use when the user says "save this to my vault", "save this to Obsidian", "put this in my notes" or "add this to my wiki". Do not use for general save requests about code, files, commits, settings or memory that do not mention the vault, Obsidian or notes.
argument-hint: "[title]"
allowed-tools: Bash(bash ${CLAUDE_SKILL_DIR}/scripts/*), Write, Read, Grep, Glob
---

# Save to the vault

Saves one useful answer from this conversation as exactly one new `draft` note in `01. Inbox`, or appends it to an existing Inbox draft when the user picks that. It never changes any other note, never overwrites a file and never deletes a note. `save.sh` enforces this.

## 1. Read the vault CLAUDE.md

Context gathered by `gather.sh` (vault path, today, a free draft file path, existing topics, then the vault `CLAUDE.md`):

!`bash ${CLAUDE_SKILL_DIR}/scripts/gather.sh`

- A line starting with `ERROR:` above: reply with the text after `ERROR: ` exactly and stop. Never ask for the vault path and never write it; only `wiki-vault` does that.
- Otherwise read the vault `CLAUDE.md` above first. Its rules and frontmatter schema win over this skill on any difference, except that this skill only ever creates a `draft` note in `01. Inbox`.

## 2. Pick the content

Take only the useful answer or insight the user wants to keep, usually the last substantial answer. Not the transcript, not the back-and-forth. Rewrite it as a standalone note in short sections. English, no em dashes.

## 3. Pick the title

- Title given as argument (`$ARGUMENTS`): use it.
- No title: propose one short title and ask the user to confirm or change it before saving.

## 4. Write the draft file

Use the Write tool on the `draft_file` path from step 1 (a temp file, not in the vault). Content:

- Frontmatter with every property the vault `CLAUDE.md` requires, in its order. `status: draft` always. Dates are `today`. `type` only from the allowed values; if none fits, use `knowledge` and mention it. `topic`: reuse one from `topics` when it fits. Tags lowercase kebab-case. Put this session in the sources property, for example `claude session <today>`.
- `related`: only notes that really relate. Find candidates with Grep/Glob on filenames, titles and `aliases` in the vault; never open or edit them beyond reading. `[]` when none. Link them in the body with `[[Note]]` where it helps.
- Then the body. No `# Title` heading: `save.sh` adds it from the title.

## 5. Save

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/save.sh '<vault>' '<Title>' '<draft_file>'
```

Keep the single quotes; write a `'` inside a value as `'\''`. Do not fix forbidden filename characters yourself, `save.sh` does that.

- Exit 0: go to step 6.
- Exit 3, `appendable: yes` (a draft of that name is in `01. Inbox`): offer two choices, append to it or save under another title (propose one). Only after the user picks append, run the same command with `--append` right after `save.sh`. It adds the body under a `## <today>` heading and does not touch the existing frontmatter or text. Another title: rerun step 5 with it.
- Exit 3, `appendable: no`: a note with that name exists elsewhere, with another status or more than once. Say which notes (`exists:`) and their `status:`, propose a different title and rerun step 5 with it once the user agrees. Any other exit 3: report the error to the user and stop.
- Exit 2: fix the call or the draft file as the error says (for example remove a link to a note that does not exist), then rerun once. Check `--help` if unsure. Still failing: report the error and stop.
- Exit 1: report the error and stop.

## 6. Report

One line with the path from the vault root: `Saved as draft: <saved path>` or `Appended to draft: <appended path>`. If `renamed: yes`, say that characters not allowed in filenames were replaced. Mention `/wiki-ingest:ingest` to process it later.
