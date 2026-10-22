# Meetings Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `meetings` skill that turns Teams/hand-pasted transcripts into merged meeting blocks, dated
follow-ups, and ticket suggestions in the org files, on a launchd schedule, plus a weekly arXiv scan.

**Architecture:** Two-stage. `claude -p` (headless, driven by SKILL.md) emits a JSON digest that is
validated against a schema; deterministic Python (`write_org.py`, `suggest.py`) renders org text and edits
files idempotently with `:auto:` markers. Thin CLI wrappers (`fetch_teams.py` over `m365`,
`arxiv_scan.py` over the `arxiv` package) feed the same path. `run.sh` orchestrates; launchd schedules.

**Tech Stack:** Python 3.12 via `uv` project (`pyproject.toml` in the skill dir, `uv run --project`),
`webvtt-py`, `python-docx`, `jsonschema`, `pyyaml`, `arxiv`, `pytest`; `@pnp/cli-microsoft365` (npm);
Claude Code `claude -p`; macOS launchd.

**Spec:** `docs/superpowers/specs/2026-10-22-meetings-pipeline-design.md` (this repo).

## Global Constraints

- Skill source lives at `~/code/skills/skills/meetings/`; installed with `./install-skill.sh meetings`
  (symlinks into `~/.claude/skills/meetings/`). Scripts resolve their own dir via `readlink -f`.
- Org repo paths: `~/org/ringmaster/{worklog.org, suggested-tron-tasks.org, meetings/, 2026/YYYY-MM-worklog.org}`.
  Every script takes `--org-dir` (default `$MEETINGS_ORG_DIR` or `~/org/ringmaster`) so tests use a tmp dir.
- American English spelling everywhere, including identifiers.
- Markers: tag `:auto:` on every written headline; a `- meetings (auto) <ISO-minute> · source: … · attendees: …`
  bullet on every written block. Nothing else in the org files is ever modified — only lines are added.
- Day header shape: `* <YYYY-MM-DD Dow>` (3-letter English weekday), optional suffix (e.g. ` PTO`).
  Day items are `**`; children of an item are `***`. Indent continuation lines to the headline text column
  (3 spaces under `**`, 4 under `***`).
- Jira link shape: `[[https://rmt.atlassian.net/browse/DEV-NNNN][DEV-NNNN]]`.
- Owner suffix shape: ` - @Name`; unresolvable owner ` - @?`.
- Idempotency key = `sha256(normalized text)` for files, `teams:<meetingId>:<transcriptId>` for Teams;
  write key = `<digest key>|<target file>|<heading path>`; stored in `meetings/state.json`.
- Writes are atomic (`tmp` + `os.replace`); skipped with exit code 3 if target mtime < 15 min ago
  unless `--force`.
- Exit codes for writer CLIs: 0 wrote, 2 nothing to do (already processed), 3 mtime guard, 1 error.
- Never commit transcripts: `meetings/{inbox,digests,archive,logs}/` and `meetings/state.json` gitignored.

## Review Focus

1. A transcript whose digest title has no word in common with any heading on that day but shares an
   attendee with one (e.g. `** Rob 1-1` vs digest "Weekly catch-up", attendees Nick+Rob) — expected: merge
   under `** Rob 1-1` (attendee match counts). Test in Task 5.
2. A day header that exists but is the *last* day and is followed directly by `* TODO` — expected: new
   content is inserted before `* TODO`, never after it. Test in Task 4.
3. A dated follow-up whose target day is in a *future month* (e.g. meeting 2026-10-30, sync 2026-11-04)
   — expected: written into `worklog.org` (current-month file is the catch-all for future dates), not a
   not-yet-existing archive file. Test in Task 6.
4. A VTT with speaker tags in `<v Name>` form and duplicated cue text (Teams live captions repeat lines)
   — expected: speaker preserved as `Name: text`, consecutive identical lines collapsed. Test in Task 2.
5. `claude -p` returns prose around the JSON or invalid JSON — expected: `digest.py` extracts the first
   `{…}` block, validates, retries once with the validation error appended, then exits 1 with the raw
   output saved to `digests/<stem>.raw.txt`. Test in Task 3.

---

### Task 1: Skill scaffold, config, people map

**Files:**
- Create: `skills/meetings/pyproject.toml`, `skills/meetings/SKILL.md` (stub; filled in Task 3),
  `skills/meetings/scripts/config.py`, `skills/meetings/scripts/people.py`,
  `skills/meetings/scripts/state.py`, `skills/meetings/tests/conftest.py`,
  `skills/meetings/tests/test_people_state.py`, `skills/meetings/tests/fixtures/people.yaml`
- Create (org repo): `~/org/ringmaster/meetings/people.yaml`, `~/org/ringmaster/meetings/README.md`,
  `~/org/ringmaster/.gitignore` additions

**Interfaces:**
- Produces `config.Paths(org_dir: Path)` dataclass with properties `worklog`, `suggestions`,
  `meetings_dir`, `inbox`, `digests`, `archive`, `logs`, `state_file`, `people_file`, and
  `archive_for(date: datetime.date) -> Path` returning `org_dir/YYYY/YYYY-MM-worklog.org`;
  `config.paths_from_args(args) -> Paths` reads `--org-dir`/`$MEETINGS_ORG_DIR`.
- Produces `people.People.load(path) -> People`; `People.resolve(name: str) -> str | None` (case- and
  punctuation-insensitive alias → canonical first name); `People.is_me(name) -> bool`;
  `People.me == "Nick"`; `People.canonical_names -> list[str]`.
- Produces `state.State.load(path) -> State`; attributes `processed: dict[str, dict]`,
  `fetched: dict[str, dict]`, `last_teams_poll: str | None`, `arxiv_seen: set[str]`,
  `arxiv_queries: dict[str, list[str]]`; `State.save()` atomic.
- `people.yaml` shape:
  ```yaml
  me: Nick
  people:
    Nick: [nick, ntomasino, nick tomasino]
    David: [david, reeder, david reeder]
    Abhi: [abhi]
    Joseph: [joseph, jtarwater, jt]
    Rob: [rob]
  ```

- [ ] **Step 1: Write failing tests** in `tests/test_people_state.py`:
  `test_resolve_alias_case_insensitive` (`resolve("REEDER") == "David"`),
  `test_resolve_unknown_is_none`, `test_is_me`, `test_state_roundtrip` (save then load preserves
  `processed`, `arxiv_seen` as set), `test_archive_for_path` (`archive_for(date(2026,9,3))` ends with
  `2026/2026-09-worklog.org`).
- [ ] **Step 2: Run** `cd ~/code/skills/skills/meetings && uv run pytest -q` → FAIL (import errors).
- [ ] **Step 3: Implement** `pyproject.toml` (project `meetings-skill`, `requires-python = ">=3.12"`,
  deps `webvtt-py`, `python-docx`, `jsonschema`, `pyyaml`, `arxiv`; `[dependency-groups] dev = ["pytest"]`;
  `[tool.pytest.ini_options] pythonpath = ["scripts"]`), `config.py`, `people.py`, `state.py`,
  `conftest.py` with fixture `org_dir(tmp_path)` that creates the layout and copies
  `fixtures/people.yaml` + sets `MEETINGS_ORG_DIR`.
- [ ] **Step 4: Run** `uv run pytest -q` → PASS.
- [ ] **Step 5: Org repo side:** write `~/org/ringmaster/meetings/people.yaml` (seed from `jira-sync.md`
  team + names in `worklog.org`: Rob, Lars, Nathan, JT→Joseph, Jeremy, Marcus, Jenny, Johnathan, JHayes,
  Swanda, Delk, Wenzke, Reeder→David), `meetings/README.md` (what the folders are, naming convention,
  Obsidian-exclude note), append to `~/org/ringmaster/.gitignore`:
  `meetings/inbox/`, `meetings/digests/`, `meetings/archive/`, `meetings/logs/`, `meetings/state.json`.
- [ ] **Step 6: Commit** (skills repo): `git add skills/meetings docs && git commit -m "meetings: scaffold skill with config, people map, state"`.
  Org repo: `git -C ~/org add ringmaster/meetings ringmaster/.gitignore && git commit -m "ringmaster: meetings folder scaffold"`.

---

### Task 2: normalize.py — transcript → canonical text

**Files:**
- Create: `scripts/normalize.py`, `tests/test_normalize.py`,
  `tests/fixtures/2026-10-21-1500-csv-proofs-sync.vtt`, `tests/fixtures/2026-10-20-rob-1-1.txt`
  (with front-matter), `tests/fixtures/sample.docx` (generated in the test via python-docx, not checked in)

**Interfaces:**
- Produces `normalize.Meta` dataclass: `title: str`, `date: date`, `time: str | None` ("HH:MM"),
  `source: str` (`teams|slack|manual`), `attendees: list[str]`, `stem: str`, `key: str` (sha256 hex of body).
- Produces `parse_filename(name: str) -> Meta` (`YYYY-MM-DD[-HHMM]-<slug>.<ext>`; slug → Title Case
  title with `-`→space; `source` default `manual`, `.vtt` → `teams`).
- Produces `parse_frontmatter(text: str) -> tuple[dict, str]` (leading `key: value` lines up to first
  blank line; keys `title, date, time, source, attendees` (comma-separated)).
- Produces `read_transcript(path: Path) -> str` dispatching on suffix: `.txt`, `.vtt`
  (`webvtt-py`, `<v Name>` → `Name: `, drop timestamps, collapse consecutive duplicate lines), `.docx`
  (`python-docx`, paragraphs joined by newline).
- Produces `normalize(path: Path) -> tuple[Meta, str]` = filename meta ← front-matter overrides; body
  with CRLF→LF, trailing-space strip, ≥3 blank lines → 1.
- CLI: `normalize.py <file> [-o out.txt]` writes `title: …\ndate: …\ntime: …\nsource: …\nattendees: …\nkey: …\n\n<body>`;
  prints out path.

- [ ] **Step 1: Write failing tests:** `test_parse_filename_with_time`, `test_parse_filename_without_time`
  (time None; slug→title rule: `-` → space except between two digits, so `rob-1-1` → "Rob 1-1" and
  `csv-proofs-sync` → "Csv Proofs Sync"), `test_frontmatter_overrides_title`,
  `test_vtt_speakers_and_dedup` (Review Focus 4), `test_docx_paragraphs`, `test_key_is_stable_sha256`.
- [ ] **Step 2: Run** `uv run pytest tests/test_normalize.py -q` → FAIL.
- [ ] **Step 3: Implement** `scripts/normalize.py` per Interfaces.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -am "meetings: normalize transcripts (txt/vtt/docx) to canonical text"`.

---

### Task 3: Digest contract — schema, prompt, SKILL.md, digest.py

**Files:**
- Create: `references/digest-schema.json`, `references/digest-prompt.md`, `references/minutes-contract.md`,
  `scripts/digest.py`, `tests/test_digest.py`, `tests/fixtures/digest-good.json`,
  `tests/fixtures/digest-bad.json`; Modify: `SKILL.md`

**Interfaces:**
- `digest-schema.json` (draft 2020-12), required: `title, date, source, attendees, summary, decisions,
  action_items, follow_ups, open_questions, source_quality`. Items:
  `decisions[]: {text, firmness: committed|leaning|discussed, by: string|null}`;
  `action_items[]: {text, owner: string|null, due: date|null, jira: ^DEV-\d+$|null, ticket_worthy: bool}`;
  `follow_ups[]: {text, with: [string], when: date|null}`; `source_quality: verbatim|captions|notes`.
  `additionalProperties: false` at every level.
- `digest-prompt.md`: the extraction instructions — adapted from the awesome-copilot meeting-minutes
  schema (decisions + action items with owner/due) plus meeting-analyzer rules: firmness scale; do not
  upgrade discussion to decision; missing owner/date is recorded as `null`, never guessed; owners must be
  chosen from the provided roster or `null`; `ticket_worthy` = true only for engineering work ≥ half a
  day that has no existing Jira key; output **only** the JSON object. Placeholders `{{ROSTER}}`,
  `{{ME}}`, `{{TRANSCRIPT}}`.
- Produces `digest.extract_json(text: str) -> dict` (first balanced `{…}`; raises `ValueError`),
  `digest.validate(d: dict) -> list[str]` (jsonschema errors as strings; empty = valid),
  `digest.build_prompt(meta_header: str, body: str, people: People) -> str`,
  `digest.run_claude(prompt: str, timeout: int = 300) -> str` (subprocess:
  `claude -p --output-format json --max-turns 1` with prompt on stdin; returns `result` field),
  CLI `digest.py <normalized.txt> -o <digests/stem.json> [--validate-only <json>]` with retry-once
  behavior from Review Focus 5; exit 0 valid, 1 failed (raw saved to `<stem>.raw.txt`).
- `SKILL.md` frontmatter `name: meetings`, description triggers on "/meetings", "meeting transcript",
  "digest this meeting", "arxiv scan for my work items". Commands table: `digest <file>`, `write <digest>`,
  `run`, `fetch`, `arxiv`, `status`, each mapped to the exact `uv run --project <skill> python scripts/…`
  invocation. States the digest JSON contract is `references/digest-schema.json`.

- [ ] **Step 1: Write failing tests:** `test_good_digest_validates` (fixture → `[]`),
  `test_bad_digest_reports_errors` (extra key + firmness "maybe" → 2 errors), `test_extract_json_from_prose`,
  `test_cli_retries_then_fails` (monkeypatch `run_claude` to return invalid twice → exit 1, `.raw.txt`
  exists), `test_cli_retry_succeeds` (invalid then valid → exit 0, file written).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** schema, prompt, `digest.py`, fill `SKILL.md`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Live check (needs `claude` auth):** `uv run python scripts/normalize.py tests/fixtures/2026-10-20-rob-1-1.txt -o /tmp/n.txt && uv run python scripts/digest.py /tmp/n.txt -o /tmp/d.json`
  → exit 0 and `/tmp/d.json` validates. Record the exact `claude -p` flags that worked in SKILL.md.
- [ ] **Step 6: Commit** `git commit -am "meetings: digest schema, prompt, headless claude runner"`.

---

### Task 4: orgfile.py — org parsing and insertion primitives

**Files:**
- Create: `scripts/orgfile.py`, `tests/test_orgfile.py`, `tests/fixtures/worklog-sample.org`
  (sanitized copy of the real shape: 4 day headers incl. one ` PTO`, hand-written `** Rob 1-1`,
  `** Reeder MR :meeting:`, `** 1 on 1s` with `***` children, then `* TODO`, `* Misc`, `* AI Roadmap & Epics`).

**Interfaces:**
- Produces `OrgDoc(lines: list[str])`; `OrgDoc.load(path)`, `doc.save_atomic(path)`, `doc.text`.
- `DAY_RE = r"^\* <(\d{4}-\d{2}-\d{2}) [A-Z][a-z]{2}>(.*)$"`.
- `doc.find_day(d: date) -> int | None`; `doc.ensure_day(d: date) -> int` (insert
  `* <YYYY-MM-DD Dow>` + blank line in ascending order among day headers; if later than all, insert
  before the first non-day `* ` headline, else EOF); `doc.section_end(idx: int) -> int` (index after the
  subtree: next headline with level ≤ this one's); `doc.headings(parent_idx: int, level: int) -> list[Heading]`
  with `Heading(idx, level, keyword, title, tags, owner)` parsed from
  `^(\*+) (?:(TODO|INPROGRESS|DONE) )?(.*?)(?: - @(\S+))?(?:\s+:([\w:]+):)?\s*$`;
  `doc.insert(at: int, new_lines: list[str])`; `doc.contains_marker(start, end, needle) -> bool`;
  `day_header(d) -> str`.

- [ ] **Step 1: Write failing tests:** `test_find_day_existing`, `test_find_day_pto_suffix`,
  `test_ensure_day_inserts_between`, `test_ensure_day_after_last_day_before_todo` (Review Focus 2),
  `test_ensure_day_idempotent`, `test_headings_parse_keyword_owner_tags`, `test_section_end_last_day`,
  `test_save_atomic_roundtrip`.
- [ ] **Step 2: Run** → FAIL.  - [ ] **Step 3: Implement** `orgfile.py`.  - [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -am "meetings: org file parsing and insertion primitives"`.

---

### Task 5: Heading match + rendering

**Files:**
- Create: `scripts/render.py`, `tests/test_render.py`

**Interfaces:**
- Consumes `orgfile.Heading`, `people.People`.
- Produces `render.match_heading(title: str, attendees: list[str], headings: list[Heading], people: People) -> Heading | None`.
  Score = Jaccard of token sets after lowercasing, stripping punctuation except `-` between digits,
  dropping stopwords `{meeting, sync, call, with, and, the, on, re, w}`, and expanding attendee names via
  `people` aliases into the digest token set (so `Rob 1-1` matches "Weekly catch-up" w/ attendee Rob,
  Review Focus 1). Return best heading with score ≥ 0.34; ties → first. Headings tagged `auto` are
  excluded (never merge into our own block).
- Produces `render.meeting_block(d: dict, people: People, now: datetime, new_heading: bool) -> list[str]`:
  if `new_heading`, first line `** <title> :meeting:auto:`; then the marker bullet, summary bullet,
  `- Decided (<firmness>): <text> — <by>` per decision, `- Open: <q>` per question, then `***` items:
  mine → `*** TODO <text> - @Nick :auto:` (+ `    DEADLINE: <date Dow>` line if due; + ` - [[…][DEV-N]]`
  before the tag if jira), others → `*** <text> - @Owner :auto:`, unresolved → `@?`; undated follow-ups →
  `*** TODO <text> - @Nick :auto:` + `    - when: TBD`. Dated follow-ups are **not** included here.
- Produces `render.followup_item(fu: dict, d: dict, people: People) -> list[str]`:
  `** TODO <text> - @Nick :auto:`, `   SCHEDULED: <YYYY-MM-DD Dow>`, `   - from: [[file:worklog.org::*<title>][<date> <title>]]`.
- Produces `render.org_date(d: date) -> str` → `<2026-10-28 Wed>`.

- [ ] **Step 1: Write failing tests:** `test_match_exact_title`, `test_match_by_attendee_alias` (RF1),
  `test_match_excludes_auto_headings`, `test_no_match_below_threshold`, `test_block_new_heading_shape`,
  `test_block_merged_has_no_heading_line`, `test_mine_vs_others_keyword`, `test_jira_link_placement`,
  `test_followup_item_shape`.
- [ ] **Step 2: Run** → FAIL.  - [ ] **Step 3: Implement** `render.py`.  - [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -am "meetings: heading matching and org rendering"`.

---

### Task 6: write_org.py — the worklog writer

**Files:**
- Create: `scripts/write_org.py`, `tests/test_write_org.py`

**Interfaces:**
- Consumes Tasks 1, 4, 5.
- Produces `write_org.target_file(paths: Paths, d: date, today: date) -> Path`: same year+month as
  `today` **or later** → `paths.worklog`; earlier month → `paths.archive_for(d)` (Review Focus 3).
- Produces `write_org.plan_writes(digest: dict, key: str, paths, people, now) -> list[Write]` where
  `Write(file: Path, insert_at: int, lines: list[str], write_key: str)`; one for the meeting block
  (merged or new) + one per dated follow-up (target day via `ensure_day` in the right file).
- Produces `write_org.apply(writes, state, dry_run) -> int` honoring: skip any `write_key` already in
  `state.processed`; mtime guard per file (exit 3 → raise `MtimeGuard`); atomic save; record keys.
- CLI: `write_org.py <digest.json> --key <key> [--dry-run] [--force] [--now ISO] [--today YYYY-MM-DD]`.
  `--dry-run` prints `== <file>:<line>` followed by the lines, writes nothing.

- [ ] **Step 1: Write failing tests** (all on the Task 4 fixture copied into `org_dir`):
  `test_merge_under_existing_heading` (digest "Rob 1:1" → lines appended inside `** Rob 1-1` subtree,
  heading line unchanged), `test_new_heading_when_no_match`, `test_dated_followup_under_target_day`,
  `test_followup_future_month_goes_to_worklog` (RF3), `test_past_month_goes_to_archive`,
  `test_rerun_is_noop` (second apply → 0 writes, file bytes identical), `test_mtime_guard`
  (touch file, expect exit 3; `--force` → 0), `test_only_additions` (every line of the original file
  is present, in order, in the result), `test_dry_run_writes_nothing`.
- [ ] **Step 2: Run** → FAIL.  - [ ] **Step 3: Implement** `write_org.py`.  - [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -am "meetings: idempotent worklog writer with merge and follow-ups"`.

---

### Task 7: suggest.py — ticket suggestions

**Files:**
- Create: `scripts/suggest.py`, `tests/test_suggest.py`, `tests/fixtures/tron-tasks-sample.org`

**Interfaces:**
- Produces `suggest.existing_headlines(paths) -> set[str]` (normalized `**` titles from
  `org_dir/tron-tasks.org` if present and `suggested-tron-tasks.org`; normalization = lowercase, strip
  ` - @owner`, strip link, collapse whitespace).
- Produces `suggest.candidates(digest) -> list[dict]`: `action_items` with `ticket_worthy and not jira`.
- Produces `suggest.render(item, digest) -> list[str]`: `** <text> - @<Owner or Nick> :auto:`,
  `   - source: [[file:worklog.org::*<title>][<date> <title>]]`, `   - why: <digest summary, first sentence>`.
- CLI `suggest.py <digest.json> [--dry-run]` creates `suggested-tron-tasks.org` with
  `* Suggested\n\n* arXiv\n` if missing; appends under `* Suggested` (before `* arXiv`); skips duplicates;
  exit 0/2.

- [ ] **Step 1: Tests:** `test_creates_file_with_sections`, `test_appends_under_suggested_not_arxiv`,
  `test_dedup_against_tron_tasks`, `test_skips_items_with_jira_key`, `test_rerun_noop`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `git commit -am "meetings: ticket suggestions writer"`.

---

### Task 8: fetch_teams.py — m365 wrapper

**Files:**
- Create: `scripts/fetch_teams.py`, `tests/test_fetch_teams.py`, `tests/fixtures/m365-meetings.json`,
  `tests/fixtures/m365-transcripts.json`

**Interfaces:**
- Produces `fetch_teams.m365(args: list[str]) -> Any` (subprocess `m365 … -o json`, parsed; raises
  `RuntimeError` with stderr on non-zero). Monkeypatched in tests.
- Produces `list_meetings(start: datetime, end: datetime) -> list[dict]` (`teams meeting list
  --isOrganizer --startDateTime … --endDateTime …`), `list_transcripts(meeting_id) -> list[dict]`,
  `download(meeting_id, transcript_id, out: Path)` (`teams meeting transcript get -m -i -f`).
- Produces `inbox_name(meeting: dict) -> str` = `YYYY-MM-DD-HHMM-<slug(subject)>.vtt` in
  `America/Los_Angeles`.
- CLI `fetch_teams.py [--since ISO] [--dry-run]`: window = `state.last_teams_poll` or now-14d → now;
  skip keys in `state.fetched`; write files to `paths.inbox`; update `state.fetched[key] = {file, subject}`
  and `last_teams_poll`; print one line per file.

- [ ] **Step 1: Tests:** `test_inbox_name_localtime_slug`, `test_skips_fetched_keys`,
  `test_first_run_window_14_days`, `test_writes_state_after_download`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `git commit -am "meetings: Teams transcript fetcher over m365 CLI"`.

---

### Task 9: arxiv_scan.py — weekly research scan

**Files:**
- Create: `scripts/arxiv_scan.py`, `tests/test_arxiv_scan.py`, `references/arxiv-queries-prompt.md`,
  `references/arxiv-gate-prompt.md`

**Interfaces:**
- Produces `collect_work_items(paths) -> list[str]`: `**` titles under `* In Progress` and `* To Do` in
  `tron-tasks.org`, plus `TODO`/`INPROGRESS` headlines in `worklog.org` (day items and `* TODO` section),
  deduped, links/owners stripped.
- Produces `queries_for(items, state, run_claude) -> dict[str, list[str]]` (cached by `sha256(item)` in
  `state.arxiv_queries`; prompt asks for 1–2 arXiv queries per item, JSON `{item: [q, …]}`).
- Produces `search(query: str, since: date, max_results: int = 20) -> list[Paper]` using `arxiv.Client`
  + `arxiv.Search(query=…, sort_by=SubmittedDate)`, filtered `published.date() >= since`;
  `Paper(id, title, abstract, url, published)`.
- Produces `gate(items, papers, run_claude) -> list[Hit]` (`Hit(paper, item, why)`; prompt returns JSON
  array; keep only hits).
- Produces `append_hits(paths, hits)` under `* arXiv` as `** <title> — relevant to: <item> :auto:` +
  `   - [[<url>][arXiv:<id>]] · <published> · <why>`; skip ids in `state.arxiv_seen`.
- CLI `arxiv_scan.py [--since YYYY-MM-DD] [--dry-run]`; default since = last run date in state or 30 days.

- [ ] **Step 1: Tests** (monkeypatch `search` and `run_claude`): `test_collect_work_items_shapes`,
  `test_queries_cached_by_hash`, `test_gate_filters`, `test_append_hits_skips_seen`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `git commit -am "meetings: weekly arXiv scan against open work items"`.

---

### Task 10: run.sh orchestrator, launchd plists, runbook

**Files:**
- Create: `scripts/run.sh`, `launchd/com.ntomasino.meetings.daily.plist`,
  `launchd/com.ntomasino.meetings.arxiv.plist`, `scripts/install-launchd.sh`
- Create (org repo): `~/org/ringmaster/CLAUDE-meetings.md`; Modify: `~/org/ringmaster/CLAUDE.md`
  (append `@CLAUDE-meetings.md` line under a `## See also`)

**Interfaces:**
- `run.sh daily|arxiv|digest-one <file>|status`. `daily`: lockfile `meetings/logs/.lock` (`mkdir` lock);
  `fetch_teams.py` (non-fatal if `m365` missing/unauthenticated — log and continue); for each file in
  `inbox/`: `normalize` → `digest` → `write_org --key` → `suggest` → `mv` to `archive/` (on digest
  failure leave in inbox, log). Exit 3 from `write_org` → leave file in inbox for the next hourly run.
  Logs to `meetings/logs/YYYY-MM-DD.log`. All binaries absolute: `/opt/homebrew/bin/uv`,
  `$(command -v claude)` resolved at install time into the plist `PATH`.
- Daily plist: `StartCalendarInterval` at 06:30, 07:30, 08:30 (retries are safe: idempotent);
  arXiv plist: Monday 07:00. `install-launchd.sh` substitutes paths, copies to `~/Library/LaunchAgents/`,
  `launchctl bootstrap gui/$UID`.
- `CLAUDE-meetings.md`: purpose, folder layout, naming convention, the `:auto:` rollback grep, how to
  hand-paste (Slack captions → `.txt`), `/meetings` commands, Phase-0 auth steps (`npm i -g
  @pnp/cli-microsoft365`, `m365 login`, fallback Entra app with `OnlineMeetings.Read` +
  `OnlineMeetingTranscript.Read.All`), launchd install/verify, Obsidian exclude note.

- [ ] **Step 1: Write `run.sh`** and the plists; `bash -n scripts/run.sh`.
- [ ] **Step 2: End-to-end on a fixture:** copy `tests/fixtures/2026-10-20-rob-1-1.txt` into a tmp org dir
  (`MEETINGS_ORG_DIR=/tmp/orgtest`) seeded with the worklog fixture; `run.sh daily` → file archived, block
  merged under `** Rob 1-1`, follow-up under its day; `run.sh daily` again → log says "nothing to do", no diff.
- [ ] **Step 3: Runbook + import line**; `claude -p "what does CLAUDE-meetings.md say about rollback?"` from
  `~/org/ringmaster` to confirm the import loads.
- [ ] **Step 4: Install:** `./install-skill.sh meetings`; `scripts/install-launchd.sh`;
  `launchctl kickstart -k gui/$UID/com.ntomasino.meetings.daily`; confirm `meetings/logs/<today>.log`.
- [ ] **Step 5: Commit** both repos: `"meetings: orchestrator, launchd agents, runbook"` /
  `"ringmaster: add CLAUDE-meetings.md runbook"`.

---

### Task 11: Phase 0 live checks (needs the human)

- [ ] `npm i -g @pnp/cli-microsoft365`; user runs `! m365 login` (device code); `m365 teams meeting list
  --isOrganizer --startDateTime <7d ago> --endDateTime <now> -o json` returns ≥ 0 meetings without a
  consent error. If consent is blocked: register an Entra app, `m365 setup` with its client id, retry.
- [ ] `fetch_teams.py --dry-run` lists at least one transcript when a transcribed meeting exists.
- [ ] Canary on a real transcript: `run.sh digest-one <inbox file>` with `--dry-run` output reviewed, then
  the real run; `git -C ~/org diff ringmaster/worklog.org` shows only added `:auto:` lines.
