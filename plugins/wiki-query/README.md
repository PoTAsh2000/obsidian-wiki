# wiki-query

Finds what you already know before you research or write it again. Ask a question and Claude answers from your own notes with `[[Note]]` citations, or list notes by name, tag, topic or status. It is read-only: it never writes to the vault.

## Skills

### `/wiki-query:query <question>`

Answers a question from your notes only. Claude searches with the key terms and synonyms, reads the best matches, and cites every claim with the note it came from. It marks `draft` and `review` notes as not yet approved, and says so when your notes do not cover the question. Use it when you want to know what your notes say, not for general questions.

- `/wiki-query:query how do seals stay warm?`
- "what do my notes say about context engineering?"

### `/wiki-query:name <text>`

Lists notes whose filename or title (frontmatter `title` or first `# ` heading) contains the text, and says on each line which one matched. When nothing matches, it falls back to the frontmatter `alias` or `aliases`. Case, accents, Unicode form (a name saved decomposed by macOS or iCloud), extra spaces, apostrophes and punctuation such as `-`, `_`, `.`, `:` or `(` do not matter (`+` and `#` do, so C++ and C# differ). Titles match as plain text, without bold, links or code marks. You can also paste a `[[wikilink]]`, a path or a file name such as `Projects/RBH.md`: only the note name is searched. Best matches come first (exact name, then starts with, then contains), at most 20; when not even an alias matches, notes whose filename or title holds every word in any order are listed. Each line has the `[[wikilink]]` to cite and the note status. Use it when you know roughly what a note is called.

- `/wiki-query:name dolphin`
- `/wiki-query:name context engineering`

### `/wiki-query:tag <tag>...`

Lists notes per frontmatter tag, one block per tag. A leading `#` is ignored.

- `/wiki-query:tag mammals reefs`
- `/wiki-query:tag #tooling`

### `/wiki-query:topic <topic>...`

Lists notes per frontmatter `topic`, one block per topic. The topic must match the whole value, case-insensitive.

- `/wiki-query:topic seals`
- `/wiki-query:topic ai tooling`

### `/wiki-query:status <status>...`

Lists notes per frontmatter status (`draft`, `review`, `evergreen`, `archived`), one block per status. Use it to see what is waiting for ingest or review. It never changes a status.

- `/wiki-query:status review draft`

## Vault

Every skill of this plugin first runs `vault.py`, which prints the configured vault path and the vault `CLAUDE.md`. Claude follows those rules for the rest of the skill. The scripts get the vault from `vault.py` as well, so none of them takes a vault option. A vault problem (no path configured, or no `CLAUDE.md` in the vault) is always one `ERROR: <message>` line: Claude relays it and stops.

## Scripts

### vault.py

Shared vault reader, the same file in every obsidian-wiki plugin at `plugins/<plugin>/scripts/vault.py`. Read-only. Every skill except wiki-vault runs it as its first step. The other scripts of the skills import it to get the vault, and the wiki-vault scripts use it to find, read and clean the stored path.

* Find the vault path file `~/.claude/obsidian-wiki/vault-path`
  * `HOME` is set: use it before the OS home folder
* Read the vault path from the first line
  * File missing or empty: print `ERROR:` with a hint to run `/wiki-vault:add`
  * Git Bash path like `/c/Users/...` on Windows: turn it into `C:/Users/...`
* Check that the vault has a `CLAUDE.md`
  * Missing: print `ERROR:` with a hint to run `/wiki-vault:overwrite`
* Print the vault path and the vault `CLAUDE.md`
  * `--path`: print only the vault path
  * `CLAUDE.md` cannot be read: stop with a system error

An `ERROR:` line always ends with exit 0, also in the scripts that import vault.py, so Claude relays the message and stops.

### search.py (query)

Ranks notes for the question, so Claude reads the best ones first.

* Check the arguments: optional `--limit` (1 to 200, default 20), one or more terms
  * Missing or invalid argument: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Read every note, skipping dot folders, `Attachments`, `90. Templates` and the vault `CLAUDE.md`
  * A note cannot be read: stop with a system error
* Score each term, case-insensitive: filename and title count most, then aliases, then tags and topic, then body lines
* Print the notes with a hit, best first, with score, status and where each term hit
  * Nothing matches: print `matches: 0`

### name.py (name)

* Check the arguments: optional `--limit` (1 to 200, default 20), then the search text
  * No text, only spaces or an invalid `--limit`: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Read the head of every note (frontmatter up to the first `# ` heading, at most 64 KiB), skipping dot folders, `Attachments`, `90. Templates` and the Excluded files set in Obsidian (`userIgnoreFilters` in `.obsidian/app.json`: path prefixes, `/regex/` on the path; a missing or invalid file skips only the fixed folders)
  * Skipped notes still count for shared names
  * Linked folders (symlinks, Windows junctions) are not entered, linked files outside the vault are skipped
  * A note cannot be read: stop with a system error
* A text in `[[ ]]` or ending in `.md`, `.canvas` or `.base` is reduced to the note name: no folder, extension, `|display` or `#heading`
* Compare after Unicode NFC, casefold, dropping accents and apostrophes and treating other ASCII punctuation (except `+` and `#`) and runs of whitespace as one space; paths print as on disk
  * A text of only punctuation: print `Nothing found.`
* Titles are compared and printed as plain text: `[[a|b]]` gives `b`, `[t](url)` gives `t`, emphasis and code marks and the closing `#`'s of a heading are dropped
* Print the notes whose filename, frontmatter `title` or first `# ` heading contains the text, each with its wikilink, `(filename)` or `(title: <title>)` and the status
  * Order: exact name, then starts with, then contains, then path
  * Two notes (or a note and a `.canvas` or `.base` file) with the same filename: link by path, as `[[folder/Name]]`, and mark `shared name`
  * Control and bidi characters are removed and titles and aliases are cut at 120 characters, so a note cannot add fake lines
  * More than `--limit` matches: end with `<n> more not shown`
  * No match: print the notes with a matching `alias` or `aliases` (key in any case, duplicates dropped) instead, linked as `[[Name|alias]]` with `|`, `[` and `]` removed from the alias
  * Still no match and several words: print the notes whose filename or title holds every word, in any order
  * Still no match: print `Nothing found.`, followed by `Close names:` and up to 5 notes whose filename, title or alias is spelled alike (`difflib` ratio at least 0.8), most alike first

### tag.py (tag)

* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Split the arguments into tags and drop a leading `#`
  * Tag with spaces, quotes, brackets or shell symbols: print an `ERROR:` line and stop
  * No tags: print `need: tags`, so Claude asks for them
* Read the `tags` of every note, skipping dot folders, `Attachments` and `90. Templates`
  * A note cannot be read: stop with a system error
* Print `found: yes` or `found: no`, then one block per tag with the matching notes
  * Tag without notes: `- nothing found`
  * No tag has notes: `Nothing found.`

### topic.py (topic)

* Check the options
  * Unknown option: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
  * No topics: print `ERROR: no topic given`, so Claude asks for them
* Read the `topic` of every note, skipping dot folders, `Attachments` and `90. Templates`
  * A note cannot be read: stop with a system error
* Print one block per topic with the matching notes
  * Topic without notes: `- nothing found`
  * No topic has notes: `Nothing found.`

### status.py (status)

* Check the arguments
  * Unknown option: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
  * No status given, or a status with other characters than letters, digits, `_` or `-`: print an `ERROR:` line, so Claude asks again
* Read the `status` of every note, skipping dot folders, `Attachments` and `90. Templates`
  * A note cannot be read: stop with a system error
* Print `found: yes` or `found: no`, then one block per status with the matching notes
  * Status without notes: `- nothing found`
  * No status has notes: `Nothing found.`

## Tests

`python3 -m unittest discover -s plugins/wiki-query/tests -t plugins/wiki-query`
