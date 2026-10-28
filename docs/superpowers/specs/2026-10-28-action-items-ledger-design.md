# Action items ledger — design spec

## Context

> Draft 2026-10-28. Extends the meetings pipeline
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

## Calls made in this document (builder may revisit; Nick should skim)

| Call | Choice | Why |
|---|---|---|
| EFFORT scale | `S` / `M` / `L`, estimated by the model, blank when it cannot say | Three buckets is what a glance can use; hours would be false precision from a transcript |
| Row locator | The WHAT cell ends with an org link to the worklog item; that link target is the row's identity in `state.json`. No ID column | Keeps Nick's five columns; the link doubles as "jump to source" |
| Open questions in worklog | Stay as `- Open:` bullets under the marker; done = bullet becomes `- Resolved [date]:` | They never were headlines; turning them into headlines would change the worklog shape already approved |
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
| WHEN             | WHO    | WHAT                                                    | EFFORT | DONE |
|------------------+--------+---------------------------------------------------------+--------+------|
| <2026-10-28 Wed> | @Mitch | Statutory classification and state scoping [[file:worklog.org::*Quick call to resolve how statutory classification and state scoping will work for Statutory Disability / PFML. - @Nick][↗]] | M |  |

* Commitment
| WHEN | WHO | WHAT | EFFORT | DONE |
|------+-----+------+--------+------|

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
  locator link `[[file:worklog.org::*<headline>][↗]]` (or `[[file:2026/2026-09-worklog.org::*…][↗]]`
  for a past month; for an open question `[[file:worklog.org::Open: <text>][↗]]`, an org text-search
  link). **EFFORT** `S` / `M` / `L` or blank. **DONE** blank.
- Realignment: after appending, the writer pads every cell of that table to the column's widest cell.
  No other change to existing rows is ever made.

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

  `<locator>` is the link target exactly as written in the cell (`worklog.org::*<headline>` or
  `worklog.org::Open: <text>`). The headline string is the full headline text without stars and
  keyword, including the owner suffix and tags, which is what org's `::*` search matches on.
- The ledger file is subject to the same mtime guard as the worklog (exit 3 when Nick saved it in the
  last 15 minutes and the save was not ours). `apply()` already handles several files per run.
- The merge rule (meeting block merged under a hand-written heading) does not change; the locator is the
  item's own headline, not the block's.

## Done-sync (`sync_done.py`, new)

Runs first in `cmd_daily` (before fetch) and via `run.sh done`. Steps:

1. Load `action-items.org`. Walk every table row under any heading. For each row whose **DONE** cell is
   non-blank, read the locator from the last org link in **WHAT**. Skip rows with no link, rows whose
   locator is not in `state.ledger`, and entries with `done_at` set (already propagated).
2. **Worklog edit.** Load the ledger entry's file. `kind: headline`: find the headline whose text (after
   stars and keyword) equals the stored headline, in the stored day's section first, anywhere in the
   file second; replace its keyword (`TODO`, `INPROGRESS`, none) with `DONE` and insert
   `CLOSED: [YYYY-MM-DD Day HH:MM]` as the first body line, indented like `DEADLINE:`. `kind: bullet`:
   find `- Open: <text>` under the stored day and rewrite it to `- Resolved [YYYY-MM-DD]: <text>`. Not
   found: log `done-sync: <locator>: worklog item not found, skipped` and leave `done_at` unset so a
   later run retries after Nick fixes it.
3. **Tron edit**, only when the entry has a Jira key. Find the headline in `tron-tasks.org` whose link
   text is that key.
   - Top-level task (`**` directly under a `* Bucket`): move its whole subtree (`section_end`) to the
     end of the target bucket's section. `x` -> `In Review`; a bucket word -> its heading per the table
     below. Same bucket already: no-op.
   - Sub-task (`***` or deeper): swap its status tag. `x` or `closed` -> `:closed:`; `progress` ->
     `:in_progress:`; `todo` -> `:to_do:`; any other word on a sub-task: log
     `done-sync: <key>: bucket '<word>' is for whole tasks, sub-task tag unchanged` and continue.
   - Key not found in the file: log and continue (the worklog edit still stands).

   | DONE word | tron bucket heading |
   |---|---|
   | `x` | In Review |
   | `review` | In Review |
   | `ready` | Ready for QA |
   | `qa` | In QA |
   | `accepted` | Accepted |
   | `closed` | Closed |
   | `blocked` | Blocked (do not sync) |
   | `maybe` | Maybe (do not sync) |
   | `todo` | To Do |
   | `progress` | In Progress |
   | `refine` | Needs Refinement |
   | anything else | log `unknown DONE word '<w>', tron untouched`; worklog edit still applied |

   Words are matched case-insensitively with surrounding whitespace and `[ ]`/`[X]` brackets stripped,
   so `[X]`, `X`, `x`, `done` all mean `x`.
4. Both files are under the mtime guard. A guard trip skips the whole done-sync with exit 3 (the daily
   run continues to fetch and digest; `run.sh daily` still exits 3 at the end so the retry fires).
   `tron-tasks.org` lives in OneDrive; the guard reads its mtime like any file.
5. On success set `done_at` to now in the ledger entry. The DONE cell is never modified by the pipeline:
   Nick wrote it, it stays as written.
6. Log every edit as `done-sync: <file>:<line> <before> -> <after>` so the day's log is the undo list.
   Edits are visible in `git diff worklog.org` (the org repo) and in OneDrive's version history for
   `tron-tasks.org`.

This is the one place the pipeline changes existing lines. The runbook's principle paragraph gains:
"…only adds lines, except done-sync, which makes exactly the edits a filled DONE cell asks for."

## Backfill (`run.sh ledger-backfill`, run once)

For every `meetings/digests/*.json` whose items lack `category`:

1. Run `classify.py` on the digest: a `claude -p` call with `references/classify-prompt.md`, which
   receives the digest's items and returns `{index -> {category, effort}}` per list. Fill the fields
   into the digest file in place. Cache nothing beyond the digest file itself.
2. For each item whose worklog write key is in `state.processed`, build the locator from the processed
   entry's file and the rendered headline (re-rendered from the digest with the same renderer; tags
   differ, so the headline is matched **without** its tag suffix during backfill and the locator is
   written as the headline actually present in the file), then append the row as in Landing.
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

- Two items with identical text in one day (locator collision): the second gets ` (2)` appended to its
  worklog headline at landing time so locators stay unique; state records the actual headline.
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

Prompt wording for the classification rules and the classify-only prompt; the tolerant table reader;
whether `sync_done.py` shares the org editing helpers with `write_org.py` via `orgfile.py` (preferred:
add `replace_line`, `move_section` to `OrgDoc`); test fixture shapes.
