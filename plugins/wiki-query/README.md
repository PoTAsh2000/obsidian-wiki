# wiki-query

Finds what you already know before you research or write it again. Ask a question and Claude answers from your own notes with `[[Note]]` citations, or list notes by name, tag, topic or status. It is read-only: it never writes to the vault.

## Skills

### `/wiki-query:query <question>`

Answers a question from your notes only. Claude searches with the key terms and synonyms, answers from the matching lines the search prints, opens only the matching section of a note when those lines are not enough, and cites every claim with the note it came from. It marks `draft` and `review` notes as not yet approved, and says so when your notes do not cover the question. Use it when you want to know what your notes say, not for general questions.

- `/wiki-query:query how do seals stay warm?`
- "what do my notes say about context engineering?"

### `/wiki-query:name <text>`

Lists notes whose filename or first `# ` title contains the text, case-insensitive. When nothing matches, it falls back to aliases. Use it when you know roughly what a note is called.

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

### `/wiki-query:status [--all] [<status>...]`

Lists notes per frontmatter status (`draft`, `review`, `evergreen`, `archived`), one block per status, oldest first with their `updated` (else `created`) date. Use it to see what is waiting for ingest or review. Without a status it shows how many notes have each status, and how many have none. A misspelled status gets a "did you mean" hint. A block shows at most the 50 oldest notes and ends with `- ... and <n> more`; `--all` shows every note. It never changes a status.

- `/wiki-query:status`
- `/wiki-query:status review draft`
- `/wiki-query:status --all evergreen`

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

* Check the arguments: optional `--limit` (1 to 200, default 20), `--excerpts` and `--links` (1 to 20), 1 to 20 terms of up to 200 characters
  * Missing or invalid argument: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Read every note, skipping dot folders, `Attachments`, `90. Templates`, the vault `CLAUDE.md` and notes that resolve outside the vault (symlinks, junctions)
  * A note cannot be read: stop with a system error
* Score each term, case-insensitive (Unicode normalized, so `cafe` with a decomposed accent from macOS matches `café`, and `strasse` matches `straße`): filename and title count most, then aliases, then tags and topic, then body lines
  * A whole word (plural included) scores full points, a match inside a word (`edi` in `credit`) a fifth
  * Body hits are weighted by how rare the term is across the notes (BM25 style, counted per run, nothing cached), so a rare term outweighs a common one
  * Each extra term that hits as a whole word in the same section as another adds 2 points (best section only, at most 6, so it never beats a filename or title hit)
* Print the notes with a hit, best first, with score, status, where each term hit and the shortest wikilink that is unique in the vault
  * Frontmatter `created`, `updated` (or `modified`) and `source` (or `url`) when set, so Claude can date and source evidence without opening the note
  * Equal score: notes in `99. Archived` come last and are marked `archived: yes`
  * Nothing matches: print `matches: 0`
* `--excerpts <n>`: under each note, the n best matching lines outside code fences (most rare terms as whole words, one per section first, printed in line order), with line number, nearest heading and the line range of that section (up to the next heading of the same or higher level), cut to 160 characters
* No note has a whole-word hit (or nothing matches): print a `suggest:` line per term with up to 10 close words from note names, titles, aliases, tags and topics
* `--links <n>`: for the top n notes, their `[[links]]` and `related` entries resolved like Obsidian (path and status, or `unresolved`), and the notes that link to them

### cite.py (query)

Checks the wikilinks of an answer before Claude replies.

* Check the arguments: one or more `[[Note]]`, `[[Note#Heading]]` or bare targets
  * None given: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
* Resolve each link like `search.py` and check its heading or `^block`
  * All ok: print nothing, exit 0
  * Otherwise one line per bad link (`unresolved`, `ambiguous`, `heading`) with the closest fix when there is one, exit 1

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

* Read the arguments from stdin (`-`, the form the skill uses, so user text never passes through shell quoting) or the command line
* Check the arguments: optional `--all`, zero or more statuses
  * Unknown option: stop with a usage error
* Get the vault from `vault.py`
  * Vault problem: print the `ERROR:` line and stop
  * A status with other characters than letters, digits, `_` or `-`: print an `ERROR:` line with the accepted form; Claude relays it and the user runs the skill again
* Read the `status`, `updated` and `created` of every note (keys in any case, the first spelling wins), skipping dot folders, `Attachments`, `90. Templates` (any case on Windows) and the vault `CLAUDE.md`
  * Symlinks and junctions are never followed, so only real files inside the vault count
  * Frontmatter needs a closing `---` or `...` line; a leading BOM is ignored
  * A note cannot be read: stop with a system error
* No status given: print `found: yes` and one `<status>: <count>` line per status in the vault, in lifecycle order (`draft`, `review`, `evergreen`, `archived`), then others alphabetically, then `(no status): <count>` for notes without a usable status (left out when 0)
* Otherwise print `found: yes` or `found: no`, then one block per status with the matching notes, oldest first, each with its `updated` (else `created`) date
  * Only an ISO date (`YYYY-MM-DD`, a time after it is cut off) counts; a bad `updated` falls back to `created`
  * No date or a non-ISO date: sorted last, a non-ISO one shown as `(bad date: <value>)`
  * More than 50 notes: the 50 oldest, then `- ... and <n> more` (`--all` shows every note)
  * Status without notes: `- nothing found`
  * No status has notes: `Nothing found.`
  * Unknown status close to one in the vault: a `did you mean: <status>` line

## Tests

`python3 -m unittest discover -s plugins/wiki-query/tests -t plugins/wiki-query`
