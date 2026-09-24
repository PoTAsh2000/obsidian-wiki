# obsidian-wiki development rules

This file is only loaded while developing inside this repo, never while a skill runs. Rules that must hold at runtime belong in each `SKILL.md`.

## Scope

- Stay inside the plugin you are working on. Do not change another plugin as a side effect.
- The only shared file is `.claude-plugin/marketplace.json`. Each plugin adds its own entry to `plugins` and touches no other entry.

## No overlap between skills

- `wiki-query` never writes.
- `wiki-save` only creates `draft` notes in `01. Inbox`.
- `wiki-lint` only moves stray drafts into `01. Inbox` and unlinks dead links. Everything else it reports.
- `wiki-ingest:ingest` only moves drafts out of `01. Inbox` and sets `review`.
- `wiki-ingest:apply` only sets `evergreen`.
- Only ingest and apply change `status`.
- No skill deletes a note.

## Every skill

- Starts with "read the vault `CLAUDE.md`".
- Resolves the vault path in this order: `CLAUDE_PLUGIN_OPTION_VAULT_PATH`, then `OBSIDIAN_VAULT` from `env` in `~/.claude/settings.json`, then asks the user once and writes `OBSIDIAN_VAULT` to `settings.json` only after their OK.
- Calls other plugins by skill name (for example `wiki-lint:lint`), never by script path. A skill only knows its own folder through `${CLAUDE_PLUGIN_ROOT}`.

## Scripts

- Script-first rules from the user `CLAUDE.md` apply: Bash and awk that run in Git Bash, compact machine-friendly output, quiet on success, non-zero exit on findings.
- Exception: `lint.sh` changes files without an approved dry-run first, because the user chose that for lint. It still has `--dry-run`, used by the tests.
- A change to `lint.sh` needs `plugins/wiki-lint/tests/run.sh` to pass.
- A change to `find.sh` needs `plugins/wiki-query/tests/run.sh` to pass.
- Only wiki-lint and wiki-query have `scripts/` and `tests/`. Other plugins get them only when a real need shows up.

## Versioning

- `plugin.json` has no `version` field. The commit hash is the version, so every push is an update.

## Language

- English, no em dashes.
