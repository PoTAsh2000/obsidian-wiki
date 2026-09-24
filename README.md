# obsidian-wiki

A Claude Code plugin marketplace with four plugins that keep a personal Obsidian vault tidy.

Inspired by claude-obsidian (MIT). All code here is written from scratch: only the ideas are reused (inbox first, plan before apply, read-only query). It is recreated locally so the skills follow my own vault rules, stay small, and change only when I change them.

## Why

Notes pile up in the Inbox, links break, and knowledge I already have gets rewritten. These skills give every note one path through the vault and let Claude do the tedious parts without ever deleting a note.

```
save  ->  draft in 01. Inbox  ->  ingest  ->  review outside the Inbox  ->  apply  ->  evergreen
```

| Plugin | What it does |
|---|---|
| `wiki-save` | Saves a useful answer from the conversation as a `draft` note in `01. Inbox` |
| `wiki-ingest` | Plans and applies moving drafts out of the Inbox (`draft` to `review`); `apply` marks reviewed notes `evergreen` |
| `wiki-lint` | Checks the whole vault; moves stray drafts back to the Inbox and unlinks dead links, reports everything else |
| `wiki-query` | Answers questions from my notes, plus fast lookups by name, tag, topic and status. Read-only |

`wiki-ingest` depends on `wiki-lint`: installing ingest installs lint too.

## Install

At user scope, so the skills work in every project:

```
/plugin marketplace add <git url of obsidian-wiki>
/plugin install wiki-ingest@obsidian-wiki     (also installs wiki-lint)
/plugin install wiki-query@obsidian-wiki
/plugin install wiki-save@obsidian-wiki
```

Each plugin asks for the vault folder (`vault_path`) on install. If that value is not available, the skill falls back to `OBSIDIAN_VAULT` in `env` of `~/.claude/settings.json`, and if that is missing too, asks once and proposes the change.

Auto-update is off by default for third-party marketplaces. Turn it on once: `/plugin`, Marketplaces tab, `obsidian-wiki`, "Enable auto-update". To update right away: `/plugin marketplace update obsidian-wiki`.

## Examples

| Command | What it does |
|---|---|
| `/wiki-save:save` | Save the last useful answer as a `draft` (Claude proposes a title) |
| `/wiki-save:save ACE vs SOP` | Save as a `draft` with a given title |
| `/wiki-ingest:ingest` | List all `draft` notes, ask which one, then plan it |
| `/wiki-ingest:ingest all` | Plan every `draft` note |
| `/wiki-ingest:apply` | Mark every `review` note as `evergreen` (only runs when typed) |
| `/wiki-lint:lint` | Full vault check, JSON result |
| `/wiki-lint:lint --files "01. Inbox/"` | Same, for every note in one folder |
| `/wiki-query:query what is context engineering?` | Answer from my notes with `[[Note]]` citations |
| `/wiki-query:name context` | Notes whose filename or title contains "context" |
| `/wiki-query:tag ai tooling` | Notes per tag |
| `/wiki-query:status review draft` | Notes per status |

Normal language works too: "save this to my vault", "process my inbox", "check my vault", "what do I already know about EDI mapping?".

## Development

Installed plugins are copies in the cache, so load them straight from the repo while developing:

```
claude --plugin-dir ./plugins/wiki-lint --plugin-dir ./plugins/wiki-ingest
```

Run the tests before committing (`plugins/wiki-lint/tests/run.sh`, `plugins/wiki-query/tests/run.sh`), then push and run `/plugin marketplace update obsidian-wiki`. Development rules are in `CLAUDE.md`.
