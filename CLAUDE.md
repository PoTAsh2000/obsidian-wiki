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

- Script-first rules from the user `CLAUDE.md` apply: Python 3.10+ standard library only (no pip packages), invoked as `python3`. Readable code the user can edit. Compact machine-friendly output, quiet on success, non-zero exit on findings.
- Skill-only scripts live in `plugins/<plugin>/skills/<skill>/scripts/`. The only file in `plugins/<plugin>/scripts/` is `vault.py`, byte-identical in every plugin.
- Every script gets the vault only through `require_vault()` from `vault.py`. No script takes a `--vault` option or reads the vault path file itself.
- Only `vault.py` prints the vault path and the vault `CLAUDE.md`. Every skill except `wiki-vault` injects it as step 1.
- A vault problem (path missing, no `CLAUDE.md`) is always one line `ERROR: <message>` on stdout with exit 0, in every script.
- `wiki-vault` scripts find, read and clean the stored path only with `config_file()`, `stored_path()` and `clean_path()` from `vault.py`. None of them checks `HOME` itself.
- Exception: `lint.py` changes files without an approved dry-run first, because the user chose that for lint. It still has `--dry-run`, used by the tests.
- Tests are `unittest` in `plugins/<plugin>/tests/<skill>/`, with fixtures next to them. Run them with `python3 -m unittest discover -s plugins/<plugin>/tests -t plugins/<plugin>`. A change to a script needs the tests of its plugin to pass.
- A change to `vault.py` goes to every copy (and `tests/test_vault.py` to every copy), then `python3 tests/check_vault_copies.py` must pass.

## Versioning

- `plugin.json` has no `version` field. The commit hash is the version, so every push is an update.

## Language

- English, no em dashes.
