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
- Only `wiki-vault` writes `~/.claude/obsidian-wiki/vault-path`, and it never touches the vault.
- No skill deletes a note.

## Every skill (except `wiki-vault`)

- Starts with "read the vault `CLAUDE.md`".
- Reads the vault path from `~/.claude/obsidian-wiki/vault-path`. Missing or empty: replies `Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> to configure your vault.` and stops. Never asks for the path and never writes it.
- Calls other plugins by skill name (for example `wiki-lint:lint`), never by script path. A skill only knows its own folder through `${CLAUDE_PLUGIN_ROOT}`.

## Scripts

- Script-first rules from the user `CLAUDE.md` apply: Python 3 standard library only (no pip packages), invoked as `python3`. Readable code the user can edit. Compact machine-friendly output, quiet on success, non-zero exit on findings.
- Exception: `lint.py` changes files without an approved dry-run first, because the user chose that for lint. It still has `--dry-run`, used by the tests.
- Every plugin has `scripts/vault.py` and `tests/test_vault.py`, byte-identical in all plugins. Never edit one copy alone: change every copy the same way, then run `python3 tests/check_vault_copies.py`.
- Skill-only scripts live in `skills/<skill>/scripts/`.
- Tests are `unittest` at `plugins/<plugin>/tests/<skill>/test_<skill>.py`, with fixtures next to them. Run them with `python3 -m unittest discover -s plugins/<plugin>/tests -t plugins/<plugin>`.
- A change to a script needs the tests of its plugin to pass.

## Versioning

- `plugin.json` has no `version` field. The commit hash is the version, so every push is an update.

## Language

- English, no em dashes.
