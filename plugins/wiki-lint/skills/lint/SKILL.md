---
name: lint
description: Check the user's Obsidian vault for broken links, stray drafts, bad frontmatter, empty sections, duplicate names, old Inbox notes and orphans, and fix stray drafts and dead links. Use when the user says "check my vault", "lint my vault", "find broken links in my notes" or "is my Obsidian vault tidy?", and when another wiki skill invokes wiki-lint:lint. Do not use for linting code, checking a repository or questions that do not mention the vault, Obsidian or notes.
argument-hint: "[--files <path>...] [--dry-run]"
allowed-tools: Bash(python3 *)
---

# Lint the vault

`lint.py` checks the vault and fixes exactly two things on its own, without a plan or confirm: it moves `draft` notes outside `01. Inbox` into the Inbox (filename unchanged) and unlinks dead links (the text stays). Everything else is only reported. This skill never deletes a note, never changes `status` and never fixes a finding by itself.

## 1. Read the vault CLAUDE.md

The vault path (from `~/.claude/obsidian-wiki/vault-path`, written only by `wiki-vault`) and the vault `CLAUDE.md`, gathered read-only:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vault.py"`

- Output starts with `ERROR:` (no vault path configured, or the vault folder has no `CLAUDE.md`): reply with the text after `ERROR: ` exactly and stop.
- Otherwise the `vault:` line is the vault, and the text after `--- vault CLAUDE.md ---` is the vault `CLAUDE.md`. Read it now and follow it. Its rules win over this skill on any difference, except that lint only makes the two fixes above. Do not read that file again.

Never ask for the path and never write it.

## 2. Run the script

Run exactly this once:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/lint.py" $ARGUMENTS
```

- No arguments: full vault check and fixes.
- `--files <path>...`: only these notes or folders, paths from the vault root, each one quoted (`--files "30. Knowledge/Tokens.md" "01. Inbox/"`). A folder means every note in it, subfolders included. Checks stray draft, frontmatter, outgoing dead links, ambiguous links and empty sections; no orphans, duplicates or inbox age.
- `--dry-run`: same JSON, no file changed. Use it when the user asks what lint would do.

Run it straight away, no confirm: the user chose that lint fixes without asking. Never run `lint.py` any other way, and never edit notes to fix findings in this skill.

Any script that prints a line starting with `ERROR:` is handled the same way: reply with the text after `ERROR: ` and stop.

Exit codes:

- `0` clean, `4` fixes or findings: both are normal results, go to step 3.
- `2` usage error (`SYSTEM ERROR:` with the usage line): fix the call once, for example quote each `--files` path, then run again. If it fails again, show the error line and stop.
- `3` user error (`USER ERROR:`, for example a `--files` path that does not exist or a vault `CLAUDE.md` without the `type` or status lists): show the error line to the user and stop. Do not retry or guess another path.
- `1` system error (`SYSTEM ERROR:`, for example a write that failed): show the error line, tell the user what to fix, and stop. Do not retry.

## 3. Explain the result by impact

The script prints one JSON object with `movedToInbox`, `removedDeadLinks`, `placeholderLinks`, `orphans` and `findings` (each finding has `category`, `path`, `line`, `detail`). Paths are from the vault root. Do not paste the JSON; summarize it in this order and skip empty groups:

1. **What lint changed:** each note moved to the Inbox (`from` to `to`), and each dead link it unlinked (`path:line` and the original link), so the user can restore a link that should have pointed somewhere.
2. **Broken or risky:** `ambiguous-link` (a link hits more than one note), `duplicate-name` (two notes or aliases with the same name, which makes links ambiguous), `status-location` (`archived` outside `99. Archived`, or a stray draft that could not move because the Inbox already has that name).
3. **Rule violations:** `frontmatter-missing` and `frontmatter-invalid` (checked against the `type` and `status` lists in the vault `CLAUDE.md`), `empty-section`.
4. **Housekeeping:** `inbox-age` (Inbox notes older than 7 days, time for ingest) and `orphans` (no incoming links; not always a problem).
5. **For information:** `placeholderLinks` such as `[[{{title}}]]` in templates, which lint never unlinks.

End with at most three concrete next steps, for example "run `/wiki-ingest:ingest` for the old Inbox notes". Anything else that needs changing is a proposal for the user. Follow the vault rules: moving a note to `99. Archived` or merging notes needs the user's OK in this conversation, and no note is ever deleted.

When another skill invoked lint (for example wiki-ingest with `--files`), keep the summary short and give the lists it needs (`orphans`, changed paths, findings) as they are.
