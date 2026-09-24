---
name: lint
description: Check the user's Obsidian vault for broken links, stray drafts, bad frontmatter, empty sections, duplicate names, old Inbox notes and orphans, and fix stray drafts and dead links. Use when the user says "check my vault", "lint my vault", "find broken links in my notes" or "is my Obsidian vault tidy?", and when another wiki skill invokes wiki-lint:lint. Do not use for linting code, checking a repository or questions that do not mention the vault, Obsidian or notes.
argument-hint: "[--files <path>...] [--dry-run]"
---

# Lint the vault

Runs `lint.sh`, which checks the vault and fixes exactly two things on its own, without a plan or confirm: it moves `draft` notes outside `01. Inbox` into the Inbox (filename unchanged) and unlinks dead links (the text stays). Everything else is only reported. This skill never deletes a note, never changes `status` and never fixes a finding by itself.

## 1. Read the vault CLAUDE.md

First find the vault, then read `<vault>/CLAUDE.md` before anything else. Its rules win over this skill on any difference, except that lint only makes the two fixes above.

Resolve the vault path in this order and stop at the first that gives a folder:

1. Run `echo "$CLAUDE_PLUGIN_OPTION_VAULT_PATH"` in Bash.
2. Read `~/.claude/settings.json` and take `env.OBSIDIAN_VAULT`.
3. Neither is set: ask the user once for the vault folder. Show the exact change to `~/.claude/settings.json` (add `"OBSIDIAN_VAULT": "<path>"` under `env`, keeping everything else). Write it only after their OK. Without an OK, use the path for this run only.

The path is valid when it contains `CLAUDE.md`. If not, say so and ask again.

## 2. Run the script

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/lint.sh" --vault "<vault>" $ARGUMENTS
```

- No arguments: full vault check and fixes.
- `--files <path>...`: only these notes or folders, paths from the vault root, each one quoted (`--files "30. Knowledge/Tokens.md" "01. Inbox/"`). A folder means every note in it, subfolders included. Checks stray draft, frontmatter, outgoing dead links, ambiguous links and empty sections; no orphans, duplicates or inbox age.
- `--dry-run`: same JSON, no file changed. Use it when the user asks what lint would do.

Run it straight away, no confirm: the user chose that lint fixes without asking. Never run `lint.sh` any other way, and never edit notes to fix findings in this skill.

Exit code 0 means clean, 1 means fixes or findings (normal), 2 means a usage error: show the error line and stop.

## 3. Explain the result by impact

The script prints one JSON object with `movedToInbox`, `removedDeadLinks`, `placeholderLinks`, `orphans` and `findings` (each finding has `category`, `path`, `line`, `detail`). Paths are from the vault root. Do not paste the JSON; summarize it in this order and skip empty groups:

1. **What lint changed:** each note moved to the Inbox (`from` to `to`), and each dead link it unlinked (`path:line` and the original link), so the user can restore a link that should have pointed somewhere.
2. **Broken or risky:** `ambiguous-link` (a link hits more than one note), `duplicate-name` (two notes or aliases with the same name, which makes links ambiguous), `status-location` (`archived` outside `99. Archived`, or a stray draft that could not move because the Inbox already has that name).
3. **Rule violations:** `frontmatter-missing` and `frontmatter-invalid` (checked against the `type` and `status` lists in the vault `CLAUDE.md`), `empty-section`.
4. **Housekeeping:** `inbox-age` (Inbox notes older than 7 days, time for ingest) and `orphans` (no incoming links; not always a problem).
5. **For information:** `placeholderLinks` such as `[[{{title}}]]` in templates, which lint never unlinks.

End with at most three concrete next steps, for example "run `/wiki-ingest:ingest` for the old Inbox notes". Anything else that needs changing is a proposal for the user. Follow the vault rules: moving a note to `99. Archived` or merging notes needs the user's OK in this conversation, and no note is ever deleted.

When another skill invoked lint (for example wiki-ingest with `--files`), keep the summary short and give the lists it needs (`orphans`, changed paths, findings) as they are.
