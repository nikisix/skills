# Action items ledger — design spec

## Context

> Approved 2026-10-28 after builder check. Extends the meetings pipeline
> ([2026-10-22-meetings-pipeline-design.md](./2026-10-22-meetings-pipeline-design.md)). Runbook:
> `~/org/ringmaster/CLAUDE-meetings.md`.

The pipeline lands every extracted item inside the day it came from in `worklog.org`. That is the right
place for the record, but a bad place for a morning triage: Nick's commitments, the things he is waiting
on, and the questions nobody answered are scattered across days and nested three or four levels deep.

Goal: one file, `action-items.org`, that Nick opens each morning, with every open item in a table under
its category, that he **checks off and edits by hand**, and whose check-offs flow back: the worklog item
is marked done, and when the item maps to a tron task, that task moves to the bucket he names.

## Decisions already made (user)

| Decision | Choice |
|---|---|
| File | `action-items.org` next to `worklog.org`, top-level heading per category, one table each |
| Categories, in this order | **Decision** (unresolved, needs more discussion or a meeting) · **Commitment** (what Nick committed to, new TODOs) · **Waiting-on** (what Nick is waiting on) · **Follow-up** (a follow-up task) · **Open question** (unresolved, including disagreements) |
| Columns | `WHEN · WHO · WHAT · EFFORT · DONE` |
| Ownership | Nick's file: he checks rows off and edits them. The pipeline appends rows and never rewrites a row |
| Check-off semantics | `x` in DONE = finished from Nick's side: worklog item -> `DONE` + `CLOSED:`; a tron **sub-task** gets `:closed:`; a whole tron **task** moves to **In Review**. Any other word names the tron bucket directly (`review`, `qa`, `ready`, `accepted`, `closed`, `blocked`, `todo`, `progress`, `refine`, `maybe`) and still closes the worklog item |
| Tagging | Every digested item carries its category; worklog headlines get it as an org tag (`:commitment:auto:`) |
| Sub-task check-off | Mirrors the task rule: `x` on a tron sub-task writes `:in_review:`; every bucket word maps to the matching child tag jira-sync already transitions (`needs_refinement to_do reopen in_progress in_review ready_for_qa in_qa accepted closed`) |
| Finding the ticket | Items rarely arrive with a key. The digest prompt is shown the tickets in play (tron `* In Progress` tasks and sub-tasks, plus today's worklog headings that carry a `DEV-` link) and links an item to one when it clearly is work on that ticket. Done-sync also reads a `DEV-` link Nick typed into the row or the worklog headline |
| Open-question rows | The ↗ opens the meeting block's marker headline (nvim-orgmode cannot follow a text-search link); the row is matched to its state entry by that link plus the start of its WHAT text |

## Calls made in this document (builder may revisit; Nick should skim)

| Call | Choice | Why |
|---|---|---|
| EFFORT scale | `S` / `M` / `L`, estimated by the model, blank when it cannot say | Three buckets is what a glance can use; hours would be false precision from a transcript |
| Row locator | The WHAT cell ends with an org link to the worklog item; that link target is the row's identity in `state.json`. No ID column | Keeps Nick's five columns; the link doubles as "jump to source" |
| Link target form | The headline **without keyword and tags**, cut at a word boundary so the whole target stays within 56 characters: `worklog.org::*<headline prefix>`. nvim-orgmode resolves `::*` by a lowercased prefix match on the title with the tag node stripped, so a target carrying `:commitment:auto:` never matches and a shortened one still does. A prefix another row already uses is extended word by word (`short_target`); a dangling `-` or `·` is dropped | Same string is the state identity and what done-sync and backfill match on; a full headline (median 118 characters) cannot fit a 140-wide table |
| Table width and column order | `\| EFFORT \| DONE \| WHEN \| WHO \| WHAT \|`, lines at most 140 characters. WHAT wraps at word boundaries (links never split) onto continuation rows whose four fixed cells are blank; the last chunk ends with the ↗ link, which distinguishes a continuation row from an open-question row. `ledger.py --reformat` rebuilds every table to this layout (and migrates full-headline targets plus their state keys); a plain append wraps to the width the table currently leaves | The narrow fixed columns first keep the triage cells visible; one hard width keeps the file readable in a terminal |
| Open questions in worklog | Stay as `- Open:` bullets under the marker; done = bullet becomes `- Resolved [date]:` | They never were headlines; turning them into headlines would change the worklog shape already approved |
| Locator uniqueness | A locator already present in `state.ledger` (any day, any file) gets ` (2)`, ` (3)` appended to the worklog headline at landing | Two Slack days can yield identical items; done-sync's file-wide search needs unique targets |
| Jira sync direction | Documented in the runbook: jira-sync's default pass is Jira -> org and would revert a done-sync bucket move; the move reaches Jira only when Nick runs the org -> Jira direction | Not this project's code, but the user must know which run to do next |
| Backfill | One classification-only pass over the digests already on disk, rows appended, worklog lines **not** retro-tagged | Retro-tagging edits lines Nick may have touched; the row carries the category anyway |
| Table alignment | The writer realigns the table it appends to (whitespace only) | An unaligned org table is unreadable in nvim; only whitespace changes, never content |
| When done-sync runs | At the start of every `daily` run, and on demand (`run.sh done`) | Morning: Nick checks rows off, the next run (or `run.sh done`) propagates |

## Non-goals

- No direct Jira calls. A tron bucket move is picked up by the existing Jira sync on its next run, which
  is exactly the transition Nick wants; this project does not talk to Jira.
- No re-rendering of the ledger. Rows are appended once; the file is Nick's afterwards.
- No reverse flow from worklog to ledger except at backfill (see below). If Nick flips a worklog line to
  `DONE` by hand, the ledger row stays open until he checks it; the daily run does not reconcile.
- No calendar, no Slack posting, no reminders.

## The ledger file

```org
#+TITLE: Action items
#+STARTUP: showall

* Decision
| EFFORT | DONE | WHEN             | WHO    | WHAT                                                                                 |
|--------+------+------------------+--------+--------------------------------------------------------------------------------------|
| M      |      | <2026-10-28 Wed> | @Mitch | Quick call to resolve how statutory classification and state scoping will work for   |
|        |      |                  |        | Statutory Disability / PFML. [[file:worklog.org::*Quick call to resolve how statutory][↗]] |

* Commitment
| EFFORT | DONE | WHEN | WHO | WHAT |
|--------+------+------+-----+------|

* Waiting-on
...
* Follow-up
...
* Open question
...
```

- The writer creates the file with the five headings in this order and an empty table (header + rule)
  under each when it is missing. A heading Nick deleted is recreated at the end of the file; a table he
  deleted is recreated under its heading. He can reorder headings freely.
- A row is appended as the last row of its category's table (the table ends at the first line that does
  not start with `|`). Rows Nick added by hand are left alone and are invisible to done-sync (no
  state entry, no link target the pipeline knows).
- Cells: **WHEN** org date `<YYYY-MM-DD Day>` from `due` / `when`, blank if none. **WHO** `@Name` from
  the roster (owner for action items, the `with` list for follow-ups, `@?` when unknown; for
  Waiting-on this is the person owing the item). **WHAT** the item text, then one space, then the
  locator link `[[file:worklog.org::*<headline prefix>][↗]]` (or `[[file:2026/2026-09-worklog.org::*…][↗]]`
  for a past month; for an open question the block marker's target). **EFFORT** `S` / `M` / `L` or
  blank. **DONE** blank. Columns are written in the order EFFORT, DONE, WHEN, WHO, WHAT.
- Wrapping: WHAT is cut at word boundaries into chunks that keep the line within 140 characters given
  the table's current fixed-column widths; chunks after the first go on continuation rows with blank
  EFFORT/DONE/WHEN/WHO. Links are never split.
- Realignment: after appending, the writer pads every cell of that table to the column's widest cell.
  No other change to existing rows is ever made. `ledger.py --reformat` is the one deliberate rewrite:
  it rebuilds every table (same cells, new line breaks and padding) and is idempotent.

## Classification

The digest schema gains two fields on each `action_items[]` and `follow_ups[]` entry, and
`open_questions[]` becomes an array of objects:

```
category: "decision" | "commitment" | "waiting_on" | "follow_up" | "open_question"   (required)
effort:   "S" | "M" | "L" | null                                                       (required, nullable)
open_questions[]: { text, category, effort }
```

The prompts (`digest-prompt.md`, `chat-prompt.md`) carry Nick's definitions verbatim and these rules:

- `commitment`: Nick owns it. `waiting_on`: someone else owes it to Nick. These two are the default
  split for action items by owner; the model overrides only when the text clearly says otherwise.
- `decision`: the item cannot move until people talk again (a choice between options, an escalation, a
  "let's meet on this"). A follow-up whose purpose is to decide something is `decision`, not
  `follow_up`.
- `follow_up`: a concrete later task or sync with no decision pending.
- `open_question`: asked and not answered, including a disagreement left standing.
- `effort`: Nick's own effort to clear the item. `S` under an hour, `M` a half day to a day, `L` more.
  `null` for items others own unless the text implies Nick's share.
- `jira`: the prompt receives `{{TICKETS}}`, one line per candidate: `DEV-10724 · TRON REFACTOR / perform
  refactor`, built from every task and sub-task under `* In Progress` in `tron-tasks.org` plus every
  heading under the current day in `worklog.org` that carries a `DEV-` link. The model sets `jira` to a
  candidate's key when the item is clearly work on that ticket, keeps a key written in the text, and
  otherwise leaves `null`. It never invents a key.

Made decisions (`decisions[]`, any firmness) are **not** rows: a made decision is not an action item.

Compatibility: the writer runs `normalize_digest()` first, which turns a legacy string open question
into `{text, category: "open_question", effort: null}` and fills a missing `category` by the owner rule
above and a missing `effort` with `null`. Validation still rejects new digests without the fields; the
normalizer exists for the digests already on disk.

## Landing (changes to `write_org.py` and `render.py`)

- Headline tag: `_item_lines()` emits `:<category>:auto:` (tag names: `decision`, `commitment`,
  `waiting_on`, `follow_up`, `open_question`). `followup_item()` likewise. Open-question bullets are
  unchanged in the worklog.
- After the worklog writes are planned, the planner adds one ledger write per item (action items,
  follow-ups, open questions). Write key: `<digest key>|action-items.org|<category>/<locator>`. The
  write records a **ledger entry** in `state.json`:

  ```
  state.ledger[<locator>] = {
    "key": <write key>, "file": "worklog.org", "day": "2026-10-27",
    "kind": "headline" | "bullet", "text": <item text>, "jira": "DEV-10724" | null,
    "category": "commitment", "done_at": null
  }
  ```

  `<locator>` is the link target exactly as written in the cell (`worklog.org::*<headline prefix>` or,
  for an open question, the state identity `<marker locator>::Open: <text>`). The headline string in
  the locator is the headline text without stars, keyword, and tags, for a keyed item also without
  its Jira link (`<text> - @Owner`), then cut at a word boundary to keep the target within 56
  characters (`LOCATOR_MAX`): a link inside a link target nests brackets and breaks the row's own
  link, and nvim-orgmode's `::*` prefix match resolves the shorter form. The entry's `headline`
  keeps the full text (with the Jira link) for exact matching by done-sync and backfill, and a rerun
  of the same digest reuses the locator its entry already holds (`own_entry`) rather than recomputing
  one. Targets written before the cut existed are migrated by `ledger.py --reformat`
  (`migrate_locators`: the link in the cell, the `ledger` key, the entry's `locator` and `key`, and the
  `processed` key all move together; the state is saved without the disk merge so the old keys go).
- The ledger file is subject to the same mtime guard as the worklog (exit 3 when Nick saved it in the
  last 15 minutes and the save was not ours). `apply()` already handles several files per run.
- Key inheritance: an item with `jira: null` that lands under a hand-written heading carrying a `DEV-`
  link records that key in its ledger entry (`"jira_source": "heading"`); the worklog headline is not
  changed. An item whose key is known (from the digest or inherited) shows it in WHAT after the text as
  `[[https://rmt.atlassian.net/browse/DEV-N][DEV-N]]`, before the ↗ link.
- Open-question rows link to the block's marker headline (`worklog.org::*meetings (auto) …`) since
  nvim-orgmode has no text-search links. Their state identity is `<marker locator>::Open: <text>`; the
  row is matched to its entry by the link target plus the WHAT text: an exact text match first, else
  the single entry whose first 40 characters match; two candidates mean the row is untracked (reported,
  never guessed). Several questions from one block share the link and differ in the text.
- The merge rule (meeting block merged under a hand-written heading) does not change; the locator is the
  item's own headline, not the block's.
- `tron-tasks.org` in the org dir is a symlink into OneDrive; every write resolves it first so
  `save_atomic`'s `os.replace` does not replace the symlink with a file. Tron headlines are matched by
  the `DEV-` key as a substring, not by `Heading.parse` (some tron lines have `- @Joseph [[…]]` with no
  ` - ` before the link).

## Done-sync (`sync_done.py`, new)

Runs first in `cmd_daily` (before fetch) and via `run.sh done`. Steps:

1. Load `action-items.org`. Walk every table row under any heading. For each row whose **DONE** cell is
   non-blank, read the locator from the last org link in **WHAT**. Skip rows with no link, rows whose
   locator is not in `state.ledger`, and entries with `done_at` set (already propagated).
2. **Worklog edit.** Load the ledger entry's file. `kind: headline`: find the headline whose text (after
   stars and keyword) equals the stored headline, in the stored day's section first, anywhere in the
   file second, then the same comparison with any trailing ` - [[…][DEV-N]]` stripped from both sides
   (a key Nick adds to the headline by hand must not hide the item, and it then feeds the tron edit); replace its keyword (`TODO`, `INPROGRESS`, none) with `DONE` and insert
   `CLOSED: [YYYY-MM-DD Day HH:MM]` as the first body line, indented like `DEADLINE:`. `kind: bullet`:
   find `- Open: <text>` under the stored day and rewrite it to `- Resolved [YYYY-MM-DD]: <text>`. Not
   found: log `done-sync: <locator>: worklog item not found, skipped` and leave `done_at` unset so a
   later run retries after Nick fixes it.
3. **Tron edit.** The key is resolved in this order: the ledger entry's `jira`; a `DEV-\d+` in the row's
   WHAT cell; a `DEV-\d+` in the worklog headline; a `DEV-\d+` in the nearest ancestor heading of that
   headline in the worklog. No key anywhere: worklog edit only. With a key, find the headline in
   `tron-tasks.org` containing that key.
   - Top-level task (`**` directly under a `* Bucket`): move its whole subtree (`section_end`) to the
     end of the target bucket's section. Same bucket already: no-op.
   - Sub-task (`***` or deeper): replace its status tag (add one if it has none) with the child tag for
     the word. `blocked` and `maybe` have no child tag (those buckets do not sync): log
     `done-sync: <key>: '<word>' has no sub-task tag, unchanged` and continue.
   - Key not found in the file: log and continue (the worklog edit still stands).

   | DONE word | tron bucket heading (whole task) | child tag (sub-task) |
   |---|---|---|
   | `x` | In Review | `:in_review:` |
   | `review` | In Review | `:in_review:` |
   | `ready` | Ready for QA | `:ready_for_qa:` |
   | `qa` | In QA | `:in_qa:` |
   | `accepted` | Accepted | `:accepted:` |
   | `closed` | Closed | `:closed:` |
   | `reopen` | Reopen | `:reopen:` |
   | `blocked` | Blocked (do not sync) | none, logged |
   | `maybe` | Maybe (do not sync) | none, logged |
   | `todo` | To Do | `:to_do:` |
   | `progress` | In Progress | `:in_progress:` |
   | `refine` | Needs Refinement | `:needs_refinement:` |
   | anything else | log `unknown DONE word '<w>', tron untouched`; worklog edit still applied | |

   Words are matched case-insensitively with surrounding whitespace and `[ ]`/`[X]` brackets stripped,
   so `[X]`, `X`, `x`, `done` all mean `x`.
4. Both files are under the mtime guard. A guard trip skips the whole done-sync with exit 3 (the daily
   run continues to fetch and digest; `run.sh daily` still exits 3 at the end so the retry fires).
   `tron-tasks.org` lives in OneDrive; the guard reads its mtime like any file.
5. Done-sync's own saves are registered in `state.own_saves` so the `write_org` calls later in the same
   run do not trip the guard on them.
6. On success set `done_at` to now in the ledger entry. The DONE cell is never modified by the pipeline:
   Nick wrote it, it stays as written.
7. Log every edit as `done-sync: <file>:<line> <before> -> <after>` so the day's log is the undo list.
   Edits are visible in `git diff worklog.org` (the org repo) and in OneDrive's version history for
   `tron-tasks.org`.

This is the one place the pipeline changes existing lines. The runbook's principle paragraph gains:
"…only adds lines, except done-sync, which makes exactly the edits a filled DONE cell asks for."

## Backfill (`run.sh ledger-backfill`, run once)

For every `meetings/digests/*.json` whose items lack `category` (`--since YYYY-MM-DD` limits the pass;
the full backlog is about 95 rows, most from the 10-22 and 10-23 Slack days). `normalize_digest()` fills
fields in memory only and never persists, so "lacks `category`" stays true until backfill writes it:

1. Run `classify.py` on the digest: a `claude -p` call with `references/classify-prompt.md`, which
   receives the digest's items and returns `{index -> {category, effort}}` per list. Fill the fields
   into the digest file in place. Cache nothing beyond the digest file itself.
2. For each item whose worklog write key is in `state.processed`, build the locator from the processed
   entry's file and the rendered headline without keyword and tags (the general locator form), confirm
   it is present in the file, then append the row as in Landing. Open questions use the block's marker
   headline as described under Landing.
3. If the located worklog headline already carries `DONE`, write `x` in the row's DONE cell and set
   `done_at` now, so the ledger starts in sync with hand-closed items.
4. Worklog lines are **not** retro-tagged.

Items never landed (digest without processed keys) get no row.

## Commands and docs

- `run.sh daily`: done-sync, then fetch, then digest as today.
- `run.sh done`: done-sync alone; `--dry-run` prints the edits.
- `run.sh ledger-backfill [--dry-run]`.
- `/meetings done`, `/meetings ledger` (counts per category, open vs done) in SKILL.md.
- Runbook: new section "Action items ledger" (file shape, DONE words table, what done-sync edits, how
  to undo), principle paragraph amended, rollback grep extended with `action-items.org`.
- `meetings-integrations.md`: a Ledger section with the backfill run and the first week's review.

## Edge cases the builder must handle

- Locator collision (same text, any day): the second gets ` (2)` appended to its worklog headline at
  landing time; state records the actual headline. nvim's prefix match will offer both in a picker for
  the shorter one; harmless.
- Item text containing `|` is written with `¦` in the cell (org tables split on `|`).
- WHO for an Open-question row is blank unless the question names who owes the answer.
- Nick edits the WHAT text but keeps the link: fine, the link is the identity. Deletes the link: the
  row is his; done-sync skips it, and `ledger` reports it as "untracked rows" once.
- Nick checks a row off and also flips the worklog line by hand: done-sync finds `DONE` already there,
  only adds `CLOSED:` if missing, logs nothing alarming.
- Nick fills DONE on a Waiting-on row (someone else's item): worklog headline gets `DONE` like any
  other; the tron rule applies if there is a key.
- Headline moved to another day by hand: step 2's "anywhere in the file second" finds it.
- Past-month items: file is `2026/YYYY-MM-worklog.org`; the locator link carries that path.
- A digest with zero items writes no rows and does not create the file.
- The ledger tables are parsed by a tolerant reader: leading `|`, any alignment, optional trailing `|`,
  `|---` rules skipped; a row with fewer than five cells is left alone.

## Tests (outline for the plan)

Renderer rows per category and WHO/WHEN rules · file creation with five headings · append to an
existing table and realignment · missing heading recreated · legacy string open questions normalized ·
headline tag per category · done-sync keyword flip with CLOSED · bullet resolve · tron sub-task tag swap
· tron task move for `x` and for each bucket word · unknown word logs and leaves tron · key not found ·
locator not found leaves `done_at` unset · idempotent second run · guard trip on either file ·
backfill pre-fills `x` for already-DONE headlines · run.sh ordering (done-sync before fetch).

## Left to the builder

Prompt wording for the classification and ticket-linking rules and the classify-only prompt (backfill
also runs the ticket-linking rule against the candidates as they stand today); the tolerant table reader;
whether `sync_done.py` shares the org editing helpers with `write_org.py` via `orgfile.py` (preferred:
add `replace_line`, `move_section` to `OrgDoc`); test fixture shapes.
