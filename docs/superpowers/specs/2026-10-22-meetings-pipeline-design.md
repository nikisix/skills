# Meetings pipeline — design spec

## Context

> Approved 2026-10-22. Implementation plan: [../plans/2026-10-22-meetings-pipeline.md](../plans/2026-10-22-meetings-pipeline.md).

Meetings produce decisions, commitments, and "let's sync next week" moments that currently evaporate:
nobody writes them down, Nick's own commitments never become TODOs in `worklog.org`, and follow-up
meetings never get booked. Teams transcription is on for meetings Nick organizes; everything else
(Slack huddles via side-by-side captions, other people's Teams meetings) will be pasted in by hand
until Slack AI notes is paid for.

Goal: a `meetings` skill (scripts + prompts) that runs on a schedule, ingests transcripts, digests them
with the `meeting-minutes` extraction contract, and lands results in the org files: a meeting block
under the right day in `worklog.org`, ticket suggestions in `suggested-tron-tasks.org`, follow-ups as
`SCHEDULED` org items. A separate weekly job scans arXiv against open work items and files relevant
papers into the suggestions file.

This is a **separate project** from the Jira/Clockwork sync. Its runbook goes in `CLAUDE-meetings.md`,
imported from `CLAUDE.md` via `@CLAUDE-meetings.md` (only `CLAUDE.md` auto-loads).

## Decisions already made (user)

| Decision | Choice |
|---|---|
| Sources | Teams (own meetings) via Graph; everything else hand-pasted into an inbox folder |
| Calendar | **Org only** — `SCHEDULED: <date>` timestamps, no Graph calendar writes |
| worklog write policy | Append meeting block directly under the day header, with greppable `(auto)` marker |
| Digestion runtime | `claude -p` headless invoking the skill; prompts live in SKILL.md |
| Ticket suggestions | `suggested-tron-tasks.org` (new file, outside the Jira sync) |
| Research | arXiv scan against open work items, filed in `arxiv.org` |
| Collisions | **Merge under existing hand-written heading** when title/attendees fuzzy-match; else new `:auto:` block |
| Dated follow-ups | **Under the target day's header** (find-or-create), with a backlink to the meeting |
| Write window | Editor is nvim (no auto-reload); run **~06:30** before the file is open, same slot as org-alerts |

## Calls I made (builder-check round — correct me while reading)

- **People roster:** `meetings/people.yaml` alias map (`Reeder: David`, `JT: …`, `Rob`, `Lars`, …), seeded
  from the Jira team in `jira-sync.md` plus names already in `worklog.org`. Known non-team people render
  as `@Rob`; only genuinely unresolvable names render `@?`. Your own items carry `- @Nick` (matches the
  tron-tasks shape, greppable).
- **Digests dated before the first day header** (e.g. a September Teams backfill): the writer picks the
  target file by month — `worklog.org` for the current month, `2026/2026-0M-worklog.org` otherwise —
  and runs the same find-or-create logic there. First-run Teams fetch window = **14 days**, not 60.
- **Concurrency guard:** atomic write (tmp + rename) and skip-with-log if `worklog.org` mtime is within
  the last 15 min; the launchd job retries hourly until 09:00 if skipped.
- **Obsidian:** `meetings/` is inside the vault; the runbook tells you to exclude it in Obsidian
  settings so transcripts aren't indexed (not automatable from here).

## Architecture

```
                 ┌──────────────┐    ┌───────────────┐
  Teams (Graph)  │ fetch_teams  │    │ hand-paste    │  Slack captions, others' Teams
  m365 CLI ─────►│ .py          │    │ txt/vtt/docx  │
                 └──────┬───────┘    └──────┬────────┘
                        ▼                   ▼
                   meetings/inbox/YYYY-MM-DD-HHMM-<slug>.<ext>
                        │
                        ▼  normalize.py  (txt|vtt|docx → one text shape + metadata)
                        │
                        ▼  claude -p "/meetings digest <file>"   ← SKILL.md prompt
                   meetings/digests/<same-stem>.json   (strict schema, LLM output)
                        │
                        ▼  write_org.py  (deterministic, idempotent)
         ┌──────────────┼──────────────────────┐
         ▼              ▼                      ▼
   worklog.org    suggested-tron-tasks.org   meetings/archive/<stem>.<ext>
   (meeting block) (** suggestions)          (+ state.json: processed keys)

   weekly: arxiv_scan.py  → tron-tasks.org open items + worklog TODOs → queries → arxiv pkg
           → claude -p relevance gate → "* arXiv" section in arxiv.org
```

**Key principle: two-stage.** The LLM only ever emits JSON (`digests/*.json`). A deterministic Python
writer renders org and edits files. This keeps the "append directly" policy idempotent and testable;
the model never touches `worklog.org`.

## Layout

```
~/org/ringmaster/
  CLAUDE.md                      (+ `@CLAUDE-meetings.md` import line)
  CLAUDE-meetings.md             runbook for this project
  suggested-tron-tasks.org       NEW — ticket suggestions (sync never reads it)
  arxiv.org                      NEW — arXiv papers from the weekly scan
  worklog.org                    existing — meeting blocks appended
  meetings/                      NEW; README + people.yaml committed, the rest gitignored
    people.yaml                  alias → canonical owner map (Reeder→David, JT, Rob, Lars, …)
    inbox/                       drop transcripts here (hand-paste or fetcher)
    digests/                     LLM JSON output, one per transcript
    archive/                     processed transcripts (moved from inbox)
    state.json                   processed keys, last Teams poll time, seen arXiv ids
    logs/                        launchd/cron run logs

~/.claude/skills/meetings/
  SKILL.md                       /meetings {fetch|digest|write|run|arxiv|status}
  scripts/
    fetch_teams.py               m365 CLI wrapper → inbox
    normalize.py                 txt/vtt/docx → canonical text + metadata header
    write_org.py                 digest JSON → worklog.org / suggested-tron-tasks.org
    arxiv_scan.py                weekly research scan
    run.sh                       orchestrator invoked by the scheduler
  references/
    digest-schema.json           the JSON contract the digest prompt must satisfy
    minutes-contract.md          adapted from github/awesome-copilot meeting-minutes
  tests/                         pytest for normalize + write_org (fixtures = sample transcripts)
```

All scripts are `uv run --script` with inline `# /// script` dependency blocks (uv 0.11 is installed;
no venv management). Dependencies: `webvtt-py` (VTT), `python-docx` (Teams .docx export), `arxiv`.

## Input conventions

- **Filename carries metadata:** `YYYY-MM-DD-HHMM-<slug>.{txt,vtt,docx}`. Date → worklog day header;
  slug → meeting title (`csv-proofs-sync` → "CSV Proofs Sync"). `HHMM` optional; defaults `0000`.
  The fetcher names files the same way from `startDateTime` + `subject`.
- **Optional front-matter** (first lines, `key: value`, blank line) overrides filename: `title:`,
  `date:`, `source: teams|slack|manual`, `attendees:`.
- **Hand-paste:** save the captions/transcript as `.txt` in `inbox/`; nothing else required.
- **Processed key:** Teams = `teams:<meetingId>:<transcriptId>`; file = `sha256` of normalized text.
  Keys live in `state.json`; a known key is skipped (idempotent reruns).

## Digest contract (LLM output)

Adapted from `meeting-minutes` (extraction) + the useful parts of `meeting-analyzer`
(decision firmness; missing owner/date is a finding). **Hidden-layer analysis (tensions, personas) is
NOT written to org files** — it's noise in a committed worklog. (My call.)

```json
{
  "title": "...", "date": "YYYY-MM-DD", "source": "teams|slack|manual",
  "attendees": ["Nick", "Rob"],
  "summary": "1-3 sentences",
  "decisions": [{"text": "...", "firmness": "committed|leaning|discussed", "by": "Rob"}],
  "action_items": [{"text": "...", "owner": "Nick|Rob|null", "due": "YYYY-MM-DD|null",
                    "jira": "DEV-10173|null", "ticket_worthy": true}],
  "follow_ups": [{"text": "sync on X", "with": ["Rob"], "when": "YYYY-MM-DD|null"}],
  "open_questions": ["..."],
  "source_quality": "verbatim|captions|notes"
}
```

Owner resolution: the prompt is given the team roster from `jira-sync.md` (Abhi, David, Nick, Joseph)
and maps first names; unknown → `null` (surfaced as a finding, not guessed).

## Org rendering (write_org.py)

**worklog.org** — pick target file by month (see calls above), then find-or-create `* <YYYY-MM-DD Day>`
in chronological position among the day headers (they precede the `* TODO`, `* Misc`,
`* AI Roadmap & Epics` sections; respect an existing `PTO` suffix).

**Heading match (merge):** among that day's `**` headings, fuzzy-match the digest title and attendee
names (token overlap, e.g. digest "Rob 1:1" ↔ `** Rob 1-1`; "David Reeder sync" ↔ `** Reeder MR`,
via `people.yaml` aliases). Match → append children under **your** heading, `:auto:` only on the
appended lines. No match → new `** <title> :meeting:auto:` heading. Idempotency key =
`digest-hash + target heading path`.

```org
** Rob 1-1                                   ← your heading, untouched
   - your own notes …
   - meetings (auto) 2026-10-21T15:04 · source: teams · attendees: Nick, Rob
   - <summary>
   - Decided (committed): ... — Rob
   - Open: ...
*** TODO draft the runbook - @Nick :auto:
    DEADLINE: <2026-10-24 Fri>
*** send Rob the CSV sample - @Rob :auto:
*** TODO sync with Rob on X - @Nick :auto:   ← date-less follow-up stays here; - when: TBD

* <2026-10-28 Wed>                            ← dated follow-ups go to the target day, at `**`
** TODO sync with Rob on X - @Nick :auto:
   SCHEDULED: <2026-10-28 Wed>
   - from: [[file:worklog.org::*Rob 1-1][2026-10-21 Rob 1-1]]
```

Rendering rules (my calls, following the observed conventions):
- Nick's action items → `*** TODO <text> - @Nick`; due date → `DEADLINE:` on the next line
  (org-alerts reads DEADLINE/SCHEDULED within 3 lines of the headline).
- Others' items → `*** <text> - @Owner`, **no keyword** (agenda stays Nick's own); unresolvable
  owner → `@?`.
- **Dated** follow-ups → created under the target day (find-or-create, same month-file rule) as a
  level-2 day item `** TODO <text> - @Nick :auto:` + `SCHEDULED:` + `- from:` backlink (a day's own
  items are `**`; `***` is reserved for children of a meeting/item). Not duplicated under the
  meeting. **Undated** follow-ups stay under the meeting with `- when: TBD`.
- Known Jira key → append ` - [[https://rmt.atlassian.net/browse/DEV-X][DEV-X]]` (tron-tasks shape).
- `:auto:` tag + `meetings (auto)` line are the greppable/reversible markers (Clockwork pattern).
  Rollback: `grep -n ':auto:\|meetings (auto)'` and delete; nothing else is touched.

**suggested-tron-tasks.org** — only `ticket_worthy` items with no existing Jira key. Headline mirrors
tron-tasks so accepting = cut/paste into `Needs Refinement`:

```org
* Suggested
** <summary> - @Nick
   - source: [[file:worklog.org::*CSV Proofs Sync][2026-10-21 CSV Proofs Sync]]
   - why: <one line from the digest>
* arXiv
** <paper title> — relevant to: <work item headline>
   - [[https://arxiv.org/abs/XXXX][arXiv:XXXX]] · <date> · <one-line why>
```

Dedup: skip if a normalized headline already exists in `tron-tasks.org` or `suggested-tron-tasks.org`.

## arXiv scan (weekly)

1. Inputs: `**` headlines from tron-tasks `In Progress` + `To Do`, plus `TODO`/`INPROGRESS` items
   from `worklog.org` and `* TODO` section.
2. `claude -p` turns each into 1–2 arXiv queries (cached in `state.json` per headline hash).
3. `arxiv` package search, `submittedDate` window = since last run (first run: 30 days), cs.* categories.
4. `claude -p` relevance gate: keep only "could change how we'd do this item", with a one-line why.
5. Append to `* arXiv` in `arxiv.org`; seen ids in `state.json`.

The deepagents `arxiv_search.py` is a 30-line wrapper; reuse its query shape, not the file.

## Scheduling

- **Daily 06:30 local** (before nvim has the file open; same slot as org-alerts): `run.sh daily` =
  `fetch_teams` → for each new inbox file: `normalize` → `claude -p` digest → `write_org` → archive.
  mtime guard: skip + retry hourly until 09:00 if `worklog.org` was saved in the last 15 min.
- **Weekly** (Mon 07:00): `run.sh arxiv`.
- Mechanism: **launchd user agent** (`~/Library/LaunchAgents/com.ntomasino.meetings.plist`,
  `StartCalendarInterval`) rather than crontab — cron often can't read the login keychain that
  `claude` and `m365` store tokens in. Nick already has launchd agents (`com.ringmastertech.tron-mount.*`)
  and a crontab; both patterns exist, launchd is the safer one here. Absolute paths everywhere,
  a lockfile, logs to `meetings/logs/`.
- Headless invocation: `claude -p "/meetings digest <file>" --output-format json --allowedTools
  "Read,Bash(uv run:*)" --permission-mode acceptEdits` (exact flags confirmed in Phase 0).

## Teams fetch

`m365` CLI (PnP CLI for Microsoft 365, npm) in delegated mode:
`teams meeting list --isOrganizer --startDateTime --endDateTime` → `teams meeting transcript list -m`
→ `teams meeting transcript get -m -i -f inbox/<name>.vtt`. Transcripts expire with the meeting
(~60 days), so backfill is bounded; daily polling is plenty.

**Risk:** the default PnP Entra app may be blocked by tenant admin consent. Fallback = own Entra app
registration with `OnlineMeetings.Read` + `OnlineMeetingTranscript.Read.All`, `m365 setup` pointed at it.
Phase 0 proves this before anything else is built.

## Phases

0. **Spike (throwaway):** `npm i -g @pnp/cli-microsoft365`; `m365 login`; list one of own transcripts;
   `claude -p` from a launchd job writes a log line. Proves auth + scheduler.
1. **Inbox → worklog:** `normalize.py`, `digest-schema.json`, SKILL.md digest prompt, `write_org.py`,
   tests. Hand-paste path works end-to-end — covers Slack and others' meetings immediately.
2. **Teams fetcher:** `fetch_teams.py` + state keys.
3. **Suggestions:** `ticket_worthy` → `suggested-tron-tasks.org` + dedup.
4. **arXiv weekly job.**
5. **Schedule + runbook:** launchd plists, `CLAUDE-meetings.md`, `@import` in `CLAUDE.md`.

Repo artifacts after approval: this spec → `docs/superpowers/specs/2026-10-22-meetings-pipeline-design.md`
(brainstorming convention; my call), `CLAUDE-meetings.md`, `meetings/README.md`, `.gitignore` additions
(`meetings/inbox/ meetings/digests/ meetings/archive/ meetings/logs/ meetings/state.json`).

## Verification

1. `uv run --script scripts/normalize.py tests/fixtures/sample.vtt` → canonical text with header.
2. `claude -p "/meetings digest tests/fixtures/sample.txt"` → JSON validates against `digest-schema.json`.
3. **Canary:** `write_org.py --dry-run` on one digest prints the exact org block + insertion line;
   then real write; confirm (a) the block merged under the existing hand-written heading when one
   matches, (b) a dated follow-up landed under its target day header, (c) `grep -c ':auto:'` grew by
   the expected count, and (d) `git diff` shows only added lines — none of your lines changed.
4. **Idempotency:** rerun `run.sh daily`; `git diff worklog.org` is empty. Unit tests cover:
   heading match / no match, PTO-suffixed day, day creation between existing days, pre-October date
   → archive file, mtime guard.
5. `launchctl kickstart -k gui/$UID/com.ntomasino.meetings` → log in `meetings/logs/` shows a run.
6. arXiv: `arxiv_scan.py --dry-run` prints candidate papers for one headline without writing.
