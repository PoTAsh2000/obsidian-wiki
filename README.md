# obsidian-wiki

A Claude Code plugin marketplace that keeps a personal Obsidian vault tidy. It is inspired by [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) (MIT), which builds on Karpathy's LLM Wiki pattern: drop knowledge in an inbox, let Claude file and link it, and query what you already know. All code here is written from scratch; only the ideas are reused (inbox first, plan before apply, read-only query).

I recreated it myself for three reasons:

- **No native Windows support.** claude-obsidian does not write to a vault from Windows.
- **The WSL workaround is too cumbersome** for the handful of tools I actually use:
  - it needs WSL with a Linux distro, just to install the Python engine in there;
  - I have to run Claude Code inside a WSL terminal whenever I work with the vault.
- **Easy to use and manage.** Small separate plugins, so I update only what I want, when I want it, without bloat I will never use.

## How this marketplace improves my Obsidian workflow

Each plugin gives Claude one clear job in the vault: save an answer, file a draft, check vault health, or answer from my notes. Claude always follows the vault's own `CLAUDE.md` rules, so I never have to explain folders, frontmatter or linking again, and no skill ever deletes a note.

Together the plugins form a knowledge cycle. Research and writing produce `draft` notes in the Inbox, ingest files them (`review`), apply approves them (`evergreen`), and lint keeps the vault healthy along the way. Query feeds existing knowledge back into new work, so I build on what I already know instead of rewriting it.

![Obsidian wiki knowledge cycle](assets/obsidian-wiki-cycle.svg)

## Install and usage guide

### Requirements

The plugins run small Python scripts. You need Python 3.10 or newer, available as the command `python3`. The scripts use the standard library only, so there are no pip packages to install.

- **Windows:** the python.org installer does not create `python3`. Install Python from the Microsoft Store, which provides `python3`. If `python3` opens the Store instead, check Settings, Apps, Advanced app settings, App execution aliases.
- **macOS:** `brew install python`. The Xcode Command Line Tools (`xcode-select --install`) also provide `python3`, but check the version: it can be older than 3.10.
- **Linux:** usually preinstalled. If it is missing or older than 3.10, install a newer `python3` with your package manager.

Check it with `python3 --version`.

### Install

At user scope, so the skills work in every project:

```
/plugin marketplace add https://github.com/PoTAsh2000/obsidian-wiki.git
/plugin install wiki-vault@obsidian-wiki
/wiki-vault:add C:/Users/you/Obsidian/MyVault
/plugin install wiki-query@obsidian-wiki
```

Install the other plugins the same way: `wiki-save`, `wiki-ingest` and `wiki-lint`.

Some plugins depend on others. `wiki-ingest` calls `wiki-lint` to check notes before and after filing them, so installing `wiki-ingest` installs `wiki-lint` automatically. The other plugins stand on their own.

You configure the vault folder once with `wiki-vault`. It stores the path in `~/.claude/obsidian-wiki/vault-path`, and every other skill reads it from there. When no path is configured, a skill stops and tells you to run `/wiki-vault:add`.

Auto-update is off by default for third-party marketplaces. Turn it on once: `/plugin`, Marketplaces tab, `obsidian-wiki`, "Enable auto-update". To update right away: `/plugin marketplace update obsidian-wiki`.

### Examples

| Command | What it does |
|---|---|
| `/wiki-vault:add C:/Users/you/Obsidian/MyVault` | Configure the vault folder for all plugins (asks for it when no path is given) |
| `/wiki-vault:overwrite D:/Notes/Vault` | Replace the configured vault folder |
| `/wiki-vault:delete` | Remove the configured vault folder |
| `/wiki-save:save` | Save the last useful answer as a `draft` in `01. Inbox` (Claude proposes a title) |
| `/wiki-save:save Dolphin sleep patterns` | Same, with a given title |
| `/wiki-ingest:ingest` | List all `draft` notes, ask which one, then plan moving it out of the Inbox |
| `/wiki-ingest:ingest all` | Plan every `draft` note |
| `/wiki-ingest:apply` | Mark every `review` note as `evergreen` (only runs when typed) |
| `/wiki-lint:lint` | Full vault check: moves stray drafts, unlinks dead links, reports the rest |
| `/wiki-lint:lint --files "01. Inbox/"` | Same, for every note in one folder |
| `/wiki-query:query how do seals stay warm?` | Answer from my notes with `[[Note]]` citations |
| `/wiki-query:name dolphin` | Notes whose filename or title contains "dolphin" |
| `/wiki-query:tag mammals reefs` | Notes per tag |
| `/wiki-query:topic seals` | Notes per topic |
| `/wiki-query:status review draft` | Notes per status |

Normal language works too: "save this to my vault", "process my inbox", "check my vault", "what do I already know about orca migration?".

### Troubleshooting

Every failure is one fixed line. What it means and how to fix it:

| Message | Fix |
|---|---|
| `Vault path is missing. Install wiki-vault@obsidian-wiki and use /wiki-vault:add <vault path> ...` | No vault folder is configured. Run `/wiki-vault:add C:/Users/you/Obsidian/MyVault`. |
| `ERROR: The configured vault folder has no CLAUDE.md: <path>. ...` | The stored path is wrong or the vault has no `CLAUDE.md` at its root. Fix the path with `/wiki-vault:overwrite <vault path>`, or add a `CLAUDE.md` to the vault. |
| `python3: command not found`, or `python3` opens the Microsoft Store | Python is missing or only the Store stub is there. Install Python 3.10 or newer as described under Requirements, then check App execution aliases on Windows. |
| A `SyntaxError` or `ImportError` from a script | Your `python3` is older than 3.10. Check with `python3 --version` and install a newer one. |

## Development

Each plugin has the same layout:

```
plugins/<plugin>/
  scripts/vault.py                  shared, byte-identical in every plugin
  skills/<skill>/SKILL.md
  skills/<skill>/scripts/<name>.py  skill-only scripts, e.g. wiki-lint's lint.py
  tests/test_vault.py               shared, byte-identical in every plugin
  tests/<skill>/test_<name>.py      unittest tests with their fixtures
```

A `SKILL.md` runs its scripts with `python3 "${CLAUDE_SKILL_DIR}/scripts/<name>.py"` and the shared helper with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vault.py"`, and allows them with exactly `allowed-tools: Bash(python3:*)` (colon prefix form; `check_rules.py` rejects `Bash(python3 *)` and narrowed per-script rules). A script line that deletes a temp or consumed input file carries `# allow-delete: <reason>`.

Run the tests from the repo root:

```bash
python3 -m unittest discover -s tests                                          # repo checks (check_rules.py)
python3 -m unittest discover -s plugins/wiki-lint/tests -t plugins/wiki-lint   # one plugin, the fast path
```

`check_rules.py` checks that every script runs on Python 3.10 with the standard library only, opens text files with `encoding="utf-8"`, that no script outside `wiki-vault` deletes a file, and that every `SKILL.md` is well formed. It is quiet when everything passes.

## Contribution

This repo was originally created for my personal use. If you find a bug or want to see a feature, feel free to [open an issue](https://github.com/PoTAsh2000/obsidian-wiki/issues/new/choose) using the bug or feature template. A change will probably only be accepted if it still matches my own use case.

If you like the repo, feel free to give it a star <img src="assets/star.svg" alt="star" width="16" height="16">
