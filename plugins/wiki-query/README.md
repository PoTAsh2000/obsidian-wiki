# wiki-query

Finds what you already know before you research or write it again. Ask a question and Claude answers from your own notes with `[[Note]]` citations, or list notes by name, tag, topic or status. It is read-only: it never writes to the vault.

## Skills

### `/wiki-query:query <question>`

Answers a question from your notes only. Claude searches with the key terms and synonyms, reads the best matches, and cites every claim with the note it came from. It marks `draft` and `review` notes as not yet approved, and says so when your notes do not cover the question. Use it when you want to know what your notes say, not for general questions.

- `/wiki-query:query how do seals stay warm?`
- "what do my notes say about context engineering?"

### `/wiki-query:name <text>`

Lists notes whose filename or first `# ` title contains the text, case-insensitive. When nothing matches, it falls back to aliases. Use it when you know roughly what a note is called.

- `/wiki-query:name dolphin`
- `/wiki-query:name context engineering`

### `/wiki-query:tag <tag>...`

Lists notes per frontmatter tag, one block per tag, with each note's status. A leading `#` is ignored. A parent tag also finds nested tags: `proj` finds `proj/edi`. Tags joined with `+` give one block of the notes that have all of them: `ai+tooling`. Without a tag it shows the vault's tags with counts, nested tags under their parent. Add `--inline` to also find inline `#tags` in the note body.

- `/wiki-query:tag mammals reefs`
- `/wiki-query:tag #tooling`
- `/wiki-query:tag ai+tooling`
- `/wiki-query:tag tooling --inline`

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

* Check the search text
  * No text or only spaces: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Read every note, skipping dot folders, `Attachments` and `90. Templates`
  * A note cannot be read: stop with a system error
* Print the notes whose filename or title contains the text
  * No match: print the notes with a matching alias instead
  * Still no match: print `Nothing found.`

### tag.py (tag)

* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Split the arguments into tags, drop a leading `#` and repeated tags (case-insensitive, also for non-ASCII letters)
  * Tag with anything but letters, digits, `_`, `-` and `/`, or with only digits (`2026`): print an `ERROR:` line and stop, as Obsidian does not read it as a tag
* Read the `tags` and `status` from the frontmatter of every note (`.md` in any case, so also `.MD`), skipping dot folders, `Attachments` and `90. Templates`
  * Only the lines up to the closing `---` are read, not the whole note
  * A note cannot be read: skip it; a vault folder cannot be listed: stop with a system error
  * Accept the spellings Obsidian reads: `tags:` or `tag:`, an inline list, a `- item` list, `a, b`, a leading `#` and a trailing `# comment`
  * Notes with a BOM or with CRLF or CR line endings are read the same way
  * Digit-only values (`"2026"`) are not tags: they never match and are not counted
* With the word `--inline`: also read `#tag` words in the note body, skipping fenced and inline code, headings, URLs and wikilinks; a note matched through a body-only tag shows `inline` after its status
* No tags: print `need: tags` and the vault's tags with note counts, most used first, at most 50 lines, so Claude asks which ones
  * Nested tags are indented under their parent, and the parent counts every note with it or a child once, so a whole branch can be picked
* Print `found: yes` or `found: no`, then one block per tag with the matching notes and their status
  * A parent tag also matches nested tags (`proj` finds `proj/edi`); the matched nested tag is shown after the status
  * Tags joined with `+` (`ai+tooling`): one block of the notes that have every tag, nested matching per tag
  * At most 100 notes per block, then a `- ... N more` line with the number left out
  * Tag without notes: `- nothing found`
  * No tag has notes: `Nothing found.`
  * Tag without notes and a similar vault tag (near spelling, or a nested tag ending in it): a `did you mean` line

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
