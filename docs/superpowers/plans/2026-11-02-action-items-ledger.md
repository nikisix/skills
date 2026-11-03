# Action Items Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every digested item gets a category and effort, lands as a row in `action-items.org`, and a filled DONE cell flows back to the worklog item and the linked tron task.

**Architecture:** The digest schema grows `category`/`effort`; the existing planner in `write_org.py` adds ledger-row writes (with a `state.ledger` entry per row) next to its worklog writes, so one `apply()` and one mtime guard cover both files. A new `sync_done.py` reads the ledger's DONE cells and makes the only in-place edits the pipeline ever makes. A new `backfill_ledger.py` classifies the digests already on disk and appends their rows.

**Tech Stack:** Python 3.14 under `uv` (`~/code/skills/skills/meetings`), pytest with `pythonpath=["scripts"]`, `claude -p` for classification, bash `run.sh` for orchestration, launchd unchanged.

**Spec:** `docs/superpowers/specs/2026-10-28-action-items-ledger-design.md`

## Global Constraints

- American English in code, comments, docs, and data keys.
- The pipeline only adds lines, except `sync_done.py`, which makes exactly the edits a filled DONE cell asks for.
- Every write is keyed in `state.json`; reruns are no-ops. Done-sync acts once per ledger entry (`done_at`).
- The mtime guard (`write_org._recently_saved`, 15 min, `own_saves`) covers every file the pipeline writes: worklog, archive months, `action-items.org`, `tron-tasks.org`.
- Link target form everywhere: headline text **without stars, keyword, or tags** (`text - @Owner - [[url][DEV-N]]`), per the spec's "Link target form" call. The spec's Landing paragraph that says "including tags" is superseded; Task 8 corrects it.
- `tron-tasks.org` is a symlink: resolve before writing.
- Tests: `uv run --quiet pytest -q` from `~/code/skills/skills/meetings`; suite currently 135 green.
- Commits on branch `meetings` in `~/code/skills`; end messages with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. A ledger row whose WHAT text Nick rewrote entirely (open-question row): must become untracked and be reported, never matched to the wrong entry. Test in Task 6 (`test_oq_row_with_rewritten_text_is_untracked`).
2. A tron task whose key appears twice in the file (parent and a sub-task carrying the parent's key by mistake): done-sync must act on the first headline match and log it, not move both. Test in Task 6 (`test_duplicate_key_acts_on_first_match`).
3. A digest that lands in an archive month (`2026/2026-09-worklog.org`): the ledger link must carry that path and done-sync must open that file. Test in Task 5 (`test_archive_month_row_links_archive_file`).
4. A DONE word on a sub-task with no existing tag and other non-status tags (`:auto:`): the status tag is added, other tags kept. Test in Task 6 (`test_subtask_without_status_tag_gets_one`).
5. A row Nick checked whose worklog headline he also hand-edited (text changed): worklog not found, `done_at` stays unset, and the tron edit must **not** run either (no partial propagation). Test in Task 6 (`test_worklog_not_found_skips_tron_too`).

---

### Task 1: Schema, prompts, `normalize_digest`, ticket candidates

**Files:**
- Modify: `references/digest-schema.json`
- Modify: `references/digest-prompt.md`, `references/chat-prompt.md`
- Modify: `scripts/digest.py`
- Modify: `tests/fixtures/digest-good.json`
- Test: `tests/test_digest.py`

**Interfaces:**
- Produces: `digest.normalize_digest(d: dict, people: People) -> dict` (in place and returned). `digest.ticket_candidates(paths: Paths, today: date) -> list[str]` lines `DEV-N · Task / Sub-task`. `digest.CATEGORIES = ("decision", "commitment", "waiting_on", "follow_up", "open_question")`, `digest.EFFORTS = ("S", "M", "L")`. `build_prompt(header, body, people, open_items=None, tickets=None)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_schema_requires_category_and_effort(fixture_good):
    d = json.loads((FIX / "digest-good.json").read_text())
    assert digest.validate(d) == []
    del d["action_items"][0]["category"]
    assert any("category" in e for e in digest.validate(d))
    d = json.loads((FIX / "digest-good.json").read_text())
    d["open_questions"] = ["legacy string"]
    assert digest.validate(d)  # strings no longer valid

def test_normalize_fills_legacy_digest(people):
    d = {"action_items": [{"text": "a", "owner": "Nick", "due": None, "jira": None, "ticket_worthy": False},
                          {"text": "b", "owner": "Rob", "due": None, "jira": None, "ticket_worthy": False}],
         "follow_ups": [{"text": "c", "with": ["Rob"], "when": None}],
         "open_questions": ["why?"]}
    digest.normalize_digest(d, people)
    assert d["action_items"][0]["category"] == "commitment" and d["action_items"][0]["effort"] is None
    assert d["action_items"][1]["category"] == "waiting_on"
    assert d["follow_ups"][0]["category"] == "follow_up"
    assert d["open_questions"][0] == {"text": "why?", "category": "open_question", "effort": None}

def test_normalize_keeps_existing_fields(people):
    d = {"action_items": [{"text": "a", "owner": "Nick", "category": "decision", "effort": "L", ...}], ...}
    digest.normalize_digest(d, people)
    assert d["action_items"][0]["category"] == "decision" and d["action_items"][0]["effort"] == "L"

def test_ticket_candidates_from_in_progress_and_today(org_dir):
    # tron-tasks-sample.org has `* In Progress` with `** TRON REFACTOR - @Nick - [[…][DEV-10717]]`
    # and `*** perform refactor - [[…][DEV-10724]] :in_progress:`; worklog day today has
    # `** CSV Proofs - @Nick - [[…][DEV-10173]]`
    lines = digest.ticket_candidates(Paths(org_dir), date(2026, 10, 22))
    assert "DEV-10717 · TRON REFACTOR" in lines
    assert "DEV-10724 · TRON REFACTOR / perform refactor" in lines
    assert "DEV-10173 · CSV Proofs" in lines
    assert not any("DEV-10558" in l for l in lines)  # To Do section excluded

def test_prompt_carries_tickets_and_rules(people):
    p = digest.build_prompt("title: x\ndate: 2026-10-22\nkind: meeting", "body", people, tickets=["DEV-1 · A"])
    assert "DEV-1 · A" in p and "waiting_on" in p and "`effort`" in p
```

Extend `tests/fixtures/digest-good.json`: add `"category"` and `"effort"` to every action item and follow-up (Nick-owned -> `commitment`/`M`, others -> `waiting_on`/`null`, follow-ups -> `follow_up`/`S`), and turn `open_questions` entries into objects with `category: "open_question"`, `effort: null`. Check `tests/fixtures/tron-tasks-sample.org` has an `* In Progress` task with a sub-task; add `*** perform refactor - [[https://rmt.atlassian.net/browse/DEV-10724][DEV-10724]] :in_progress:` under `TRON REFACTOR` if missing, and add `** CSV Proofs - @Nick - [[https://rmt.atlassian.net/browse/DEV-10173][DEV-10173]]` under the 2026-10-22 day in `worklog-sample.org` if no keyed heading exists there.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --quiet pytest -q tests/test_digest.py -k "category or normalize or ticket_candidates or carries_tickets"`
Expected: FAIL — `normalize_digest` / `ticket_candidates` not defined; schema test passes the `del` case only after the schema change (first assertion fails on `validate(d) == []` because the fixture now has fields the schema rejects via `additionalProperties: false`).

- [ ] **Step 3: Schema**

In `digest-schema.json`: add to `action_items.items.properties` and `follow_ups.items.properties`
`"category": {"enum": ["decision","commitment","waiting_on","follow_up","open_question"]}`,
`"effort": {"enum": ["S","M","L",null]}`; append both to each `required`. Replace `open_questions.items` with
`{"type":"object","additionalProperties":false,"required":["text","category","effort"],"properties":{"text":{"type":"string","minLength":1,"pattern":"^[^\\n]*$"},"category":{…same enum…},"effort":{…}}}`.

- [ ] **Step 4: Prompts**

Add to both prompts, after the `open_questions` rule, a "Classification" block with Nick's five definitions verbatim from the spec's Decisions table, the owner default (`commitment` = {{ME}} owns it, `waiting_on` = someone else owes {{ME}}), the decision-beats-follow-up rule, `effort` S/M/L definitions (null for others' items unless {{ME}} has a share), and a "Tickets in play" block:

```
Tickets in play (key · task / sub-task):
{{TICKETS}}
Set `jira` to one of these keys only when the item is clearly work on that ticket, keep a key that was
written or said, otherwise `null`. Never invent a key.
```

`open_questions` rule becomes: "objects `{text, category, effort}`; `category` is usually `open_question`, `decision` when it needs a meeting to settle".

- [ ] **Step 5: `digest.py`**

```python
CATEGORIES = ("decision", "commitment", "waiting_on", "follow_up", "open_question")
EFFORTS = ("S", "M", "L")

def normalize_digest(d: dict, people: People) -> dict: ...
def ticket_candidates(paths: Paths, today: date) -> list[str]: ...
def build_prompt(header, body, people, open_items=None, tickets=None) -> str: ...  # replaces {{TICKETS}} ("- (none)" when empty)
```

`ticket_candidates`: load `paths.tron_tasks` if it exists; find the line `* In Progress`; for each heading in its section (`doc.section_end`), parse with `Heading.parse`; level-2 with a link -> `f"{link} · {title}"`, deeper with a link -> `f"{link} · {parent_title} / {title}"` (parent = nearest level-2 above). Then `paths.worklog` day `today`: every heading in that day's section with a link -> `f"{link} · {title}"`. Dedupe preserving order. `digest_file(...)` and `main` pass `ticket_candidates(paths, date.today())` (chat and meeting alike). `main` gains `--today` for tests.

- [ ] **Step 6: Run tests**

Run: `uv run --quiet pytest -q tests/test_digest.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add references/digest-schema.json references/digest-prompt.md references/chat-prompt.md scripts/digest.py tests/fixtures/ tests/test_digest.py
git commit -m "meetings: digest items carry category and effort; prompts see tickets in play"
```

---

### Task 2: Org file helpers for in-place edits

**Files:**
- Modify: `scripts/orgfile.py`
- Test: `tests/test_orgfile.py`

**Interfaces:**
- Produces: `headline_parts(line: str) -> tuple[int, str | None, str, list[str]] | None` (level, keyword, title-without-tags, tags; title keeps links and owner suffix verbatim). `OrgDoc.replace_line(idx: int, new: str) -> None`. `OrgDoc.set_keyword(idx: int, keyword: str) -> str` returns the new line. `OrgDoc.set_tags(idx: int, tags: list[str]) -> str`. `OrgDoc.move_section(idx: int, to_parent_idx: int) -> int` moves the subtree at `idx` to the end of `to_parent_idx`'s section (before trailing blanks) and returns the subtree's new index. `OrgDoc.find_headline(title: str, start: int = 0, end: int | None = None) -> int | None` exact match on `headline_parts(...)[2]`.
- The module docstring loses "existing lines are never rewritten".

- [ ] **Step 1: Write the failing tests**

```python
def test_headline_parts():
    assert headline_parts("*** TODO Ship it - @Nick - [[u][DEV-1]] :commitment:auto:") == (3, "TODO", "Ship it - @Nick - [[u][DEV-1]]", ["commitment", "auto"])
    assert headline_parts("** Plain") == (2, None, "Plain", [])
    assert headline_parts("- not a headline") is None

def test_set_keyword_and_tags():
    doc = OrgDoc(["*** TODO Ship it - @Nick :auto:"])
    assert doc.set_keyword(0, "DONE") == "*** DONE Ship it - @Nick :auto:"
    assert doc.set_tags(0, ["in_review", "auto"]) == "*** DONE Ship it - @Nick :in_review:auto:"
    doc2 = OrgDoc(["*** Ship it"]); assert doc2.set_keyword(0, "DONE") == "*** DONE Ship it"

def test_move_section_forward_and_backward():
    doc = OrgDoc(["* A", "** t1", "body", "* B", "** t2", "", "* C"])
    new = doc.move_section(1, 3)   # t1 -> end of B
    assert doc.lines == ["* A", "* B", "** t2", "** t1", "body", "", "* C"] and new == 3
    new = doc.move_section(3, 0)   # back to A
    assert doc.lines[:3] == ["* A", "** t1", "body"] and new == 1

def test_find_headline_scoped():
    doc = OrgDoc(["* D1", "** TODO x - @Nick :auto:", "* D2", "** DONE x - @Nick :auto:"])
    assert doc.find_headline("x - @Nick") == 1
    assert doc.find_headline("x - @Nick", start=2) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --quiet pytest -q tests/test_orgfile.py -k "headline_parts or set_keyword or move_section or find_headline"`
Expected: FAIL with ImportError / AttributeError

- [ ] **Step 3: Implement in `orgfile.py`**

`headline_parts` uses `HEADLINE_RE`, `TAGS_RE`, `KEYWORD_RE` in that order. `set_keyword` rebuilds from parts. `set_tags` rebuilds `f"{stars} {kw }{title} :{':'.join(tags)}:"` (no tag suffix when empty). `move_section`: slice out `lines[idx:section_end(idx)]`, compute the insertion point on the shortened list (`_append_point` logic: end of parent's section minus trailing blanks; if `to_parent_idx > idx` subtract the removed length first), insert, return the index.

- [ ] **Step 4: Run tests**

Run: `uv run --quiet pytest -q tests/test_orgfile.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/orgfile.py tests/test_orgfile.py
git commit -m "meetings: orgfile gains keyword/tag edits, subtree move, headline search"
```

---

### Task 3: Category tags in the renderer, `state.ledger`

**Files:**
- Modify: `scripts/render.py`, `scripts/state.py`
- Test: `tests/test_render.py`, `tests/test_people_state.py`, and the existing assertions in `tests/test_write_org.py`, `tests/test_digest.py`, `tests/test_run_sh.py` that pin ` :auto:` on item lines

**Interfaces:**
- Produces: `render.item_headline(item: dict, people: People) -> str` = `f"{org_text(text)}{_owner_suffix}{_jira_suffix}"` (the locator form). `render.followup_headline(fu: dict, people: People) -> str` = `f"{org_text(text)} - @{people.me}"`. `_item_lines` emits `:{category}:auto:`; `followup_item` and the undated follow-up line in `meeting_children` emit `:follow_up:auto:` (or the follow-up's own category when it is `decision`). `State.ledger: dict[str, dict]`, merged like `processed`, persisted under `"ledger"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_item_line_carries_category_tag(people):
    item = {"text": "Ship it", "owner": "Nick", "due": None, "jira": "DEV-1", "ticket_worthy": False, "category": "commitment", "effort": "S"}
    assert _item_lines(item, people)[0] == "*** TODO Ship it - @Nick - [[https://rmt.atlassian.net/browse/DEV-1][DEV-1]] :commitment:auto:"
    assert item_headline(item, people) == "Ship it - @Nick - [[https://rmt.atlassian.net/browse/DEV-1][DEV-1]]"

def test_followup_lines_carry_follow_up_tag(people):
    fu = {"text": "Sync w/ Rob", "with": ["Rob"], "when": "2026-10-24", "category": "follow_up", "effort": None}
    assert followup_item(fu, DIGEST, people)[0] == "** TODO Sync w/ Rob - @Nick :follow_up:auto:"
    fu["category"] = "decision"
    assert followup_item(fu, DIGEST, people)[0].endswith(":decision:auto:")

def test_state_ledger_round_trip_and_merge(tmp_path):
    s = State(path=tmp_path / "s.json"); s.ledger["worklog.org::*a - @Nick"] = {"done_at": None}; s.save()
    t = State.load(tmp_path / "s.json"); t.ledger["worklog.org::*b - @Nick"] = {"done_at": None}; t.save()
    assert set(State.load(tmp_path / "s.json").ledger) == {"worklog.org::*a - @Nick", "worklog.org::*b - @Nick"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --quiet pytest -q tests/test_render.py tests/test_people_state.py -k "category_tag or follow_up_tag or ledger"`
Expected: FAIL (`:auto:` without category; `ledger` attribute missing)

- [ ] **Step 3: Implement** in `render.py` and `state.py`. Category defaults when missing: action item -> `commitment` if `people.is_me(owner)` else `waiting_on`; follow-up -> `follow_up`.

- [ ] **Step 4: Run the whole suite and fix every assertion that pinned the old ` :auto:` item lines**

Run: `uv run --quiet pytest -q`
Expected: PASS after updating `test_render.py`, `test_write_org.py`, `test_digest.py`, `test_run_sh.py` expectations to the new tag suffixes (the chat-group and marker tests do not change: `** Slack :chat:auto:` and `*** meetings (auto) …` are untouched).

- [ ] **Step 5: Commit**

```bash
git add scripts/render.py scripts/state.py tests/
git commit -m "meetings: worklog items tagged with their category; state.ledger"
```

---

### Task 4: `ledger.py` — table model, row rendering, realignment, report

**Files:**
- Create: `scripts/ledger.py`
- Modify: `scripts/config.py` (`Paths.ledger -> org_dir / "action-items.org"`)
- Test: `tests/test_ledger.py`

**Interfaces:**
- Produces:
  ```python
  CATEGORIES: list[tuple[str, str]] = [("decision","Decision"),("commitment","Commitment"),("waiting_on","Waiting-on"),("follow_up","Follow-up"),("open_question","Open question")]
  PREAMBLE = ["#+TITLE: Action items", "#+STARTUP: showall", ""]
  HEADER = "| WHEN | WHO | WHAT | EFFORT | DONE |"; RULE = "|------+-----+------+--------+------|"
  @dataclass class Row: category: str; idx: int; cells: list[str]      # cells stripped, 5+ entries
  def split_cells(line: str) -> list[str]
  def is_rule(line: str) -> bool
  def section_index(doc: OrgDoc, category: str) -> int | None        # `* <Heading>` exact
  def table_bounds(doc: OrgDoc, section_idx: int) -> tuple[int, int] | None  # [first '|' line, one past last)
  def rows(doc: OrgDoc) -> list[Row]                                  # every data row under a known category
  def realign(doc: OrgDoc, section_idx: int) -> None                  # pad cells; rules rebuilt with '-' and '+'
  def link_target(file_rel: str, headline: str) -> str                 # "worklog.org::*headline"
  def what_cell(text: str, jira: str | None, target: str) -> str       # "text [[url][DEV]] [[file:target][↗]]", '|' -> '¦'
  def last_link_target(cell: str) -> str | None                        # from the last [[file:…][…]] link
  def row_line(when: str, who: str, what: str, effort: str, done: str = "") -> str
  def normalize_done(cell: str) -> str | None                          # None when blank; "x" for x/X/[X]/done; else lowercased word
  def report(doc: OrgDoc, ledger: dict) -> dict                        # {category: {"open": n, "done": n}, "untracked": n}
  ```

- [ ] **Step 1: Write the failing tests** (`tests/test_ledger.py`)

```python
def test_split_cells_tolerant():
    assert split_cells("| a | b |") == ["a", "b"] and split_cells("|a|b") == ["a", "b"]
    assert is_rule("|---+---|") and not is_rule("| - |")

def test_rows_and_bounds():
    doc = OrgDoc(PREAMBLE + ["* Commitment", HEADER, RULE, "| <2026-10-22 Wed> | @Nick | Ship it [[file:worklog.org::*Ship it - @Nick][↗]] | S | x |", "", "* Follow-up", HEADER, RULE])
    assert table_bounds(doc, 3) == (4, 7)
    r = rows(doc); assert len(r) == 1 and r[0].category == "commitment" and r[0].cells[4] == "x"
    assert last_link_target(r[0].cells[2]) == "worklog.org::*Ship it - @Nick"

def test_realign_pads_all_rows_whitespace_only():
    doc = OrgDoc(["* Decision", "| WHEN | WHO | WHAT | EFFORT | DONE |", "|---+---+---+---+---|", "|<2026-10-22 Wed>|@Mitch|Call|M||"])
    before = [split_cells(l) for l in doc.lines[1:]]
    realign(doc, 0)
    assert doc.lines[3] == "| <2026-10-22 Wed> | @Mitch | Call | M      |      |"
    assert doc.lines[2] == "|------------------+--------+------+--------+------|"
    assert [split_cells(l) for l in doc.lines[1:]] == before

def test_what_cell_and_pipe_escape():
    assert what_cell("a | b", "DEV-1", "worklog.org::*a ¦ b - @Nick") == "a ¦ b [[https://rmt.atlassian.net/browse/DEV-1][DEV-1]] [[file:worklog.org::*a ¦ b - @Nick][↗]]"

def test_normalize_done():
    assert normalize_done("") is None and normalize_done(" [X] ") == "x" and normalize_done("Done") == "x" and normalize_done("QA") == "qa"

def test_report_counts(org_dir):
    doc = OrgDoc(PREAMBLE + ["* Commitment", HEADER, RULE,
        "| | @Nick | a [[file:worklog.org::*a - @Nick][↗]] | | x |",
        "| | @Nick | b [[file:worklog.org::*b - @Nick][↗]] | | |",
        "| | @Nick | hand-written row | | |"])
    led = {"worklog.org::*a - @Nick": {"done_at": "2026-10-22T07:00"}, "worklog.org::*b - @Nick": {"done_at": None}}
    assert report(doc, led) == {"commitment": {"open": 1, "done": 1}, "untracked": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --quiet pytest -q tests/test_ledger.py`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement `scripts/ledger.py`** and add `Paths.ledger`. `report` counts rows per category whose link target is a ledger key as open/done by `done_at`, everything else as untracked; a `main()` prints it as `Decision: 2 open, 1 done` lines plus `untracked rows: n`.

- [ ] **Step 4: Run tests**

Run: `uv run --quiet pytest -q tests/test_ledger.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/ledger.py scripts/config.py tests/test_ledger.py
git commit -m "meetings: ledger table model, row rendering, realignment, report"
```

---

### Task 5: Ledger writes in the planner

**Files:**
- Modify: `scripts/write_org.py`
- Test: `tests/test_write_org.py`

**Interfaces:**
- Consumes: Task 2 `headline_parts`; Task 3 `item_headline`, `followup_headline`, `State.ledger`; Task 4 `ledger.*`; Task 1 `normalize_digest`.
- Produces: `Write.ledger_entry: dict | None` (new field, default `None`). `plan_writes(digest, key, paths, people, now, today=None, done=frozenset(), ledger=None)` — `ledger` is the existing `state.ledger` mapping used for locator uniqueness. `_Planner.ledger_row(category, when, who, text, jira, target, entry)` adds the section (`ledger/<category>/section` key) and table header when missing, then the row (`<category>/<target>` path), carrying `entry`. `apply()` records `state.ledger[entry["locator"]] = entry` for each applied write with an entry, and realigns every ledger table a row landed in before saving. `main()` calls `normalize_digest` first and passes `state.ledger`.
- Entry shape: `{"locator", "key", "file", "day", "kind": "headline"|"bullet", "headline", "text", "jira", "jira_source": "digest"|"heading"|None, "category", "done_at": None}`. For bullets, `locator = f"{marker_target}::Open: {text}"`, `headline` = the marker headline text.

- [ ] **Step 1: Write the failing tests**

```python
def test_rows_land_per_category_with_links(org, tmp_path):
    # digest-good.json: Nick action item (commitment, due), Rob action item (waiting_on), dated follow-up, one open question
    rc = write_org.main([str(dj), "--key", "k1", *common]); assert rc == 0
    led = OrgDoc.load(org / "action-items.org")
    assert led.lines[:3] == ledger.PREAMBLE
    r = {row.category: row for row in ledger.rows(led)}
    assert r["commitment"].cells[0] == "<2026-10-24 Fri>" and r["commitment"].cells[1] == "@Nick" and r["commitment"].cells[3] == "M"
    assert r["commitment"].cells[2].endswith("[[file:worklog.org::*Ship the CSV proofs - @Nick][↗]]")
    assert r["waiting_on"].cells[1] == "@Rob"
    assert r["follow_up"].cells[1] == "@Rob"
    assert "meetings (auto)" in ledger.last_link_target(r["open_question"].cells[2])
    st = State.load(Paths(org).state_file)
    e = st.ledger["worklog.org::*Ship the CSV proofs - @Nick"]
    assert e["kind"] == "headline" and e["category"] == "commitment" and e["done_at"] is None and e["day"] == "2026-10-22"
    assert any(k.endswith("::Open: " + OQ_TEXT) for k in st.ledger)

def test_rerun_adds_no_rows(org, tmp_path):
    assert write_org.main(args) == 0; n = len(ledger.rows(OrgDoc.load(org / "action-items.org")))
    assert write_org.main(args) == 2; assert len(ledger.rows(OrgDoc.load(org / "action-items.org"))) == n

def test_locator_collision_gets_suffix(org, tmp_path):
    # same digest text landed on two days under keys k1/k2 (digest(date=…))
    ...; assert "Ship the CSV proofs (2) - @Nick" in (org / "worklog.org").read_text()
    assert "worklog.org::*Ship the CSV proofs (2) - @Nick" in State.load(...).ledger

def test_jira_inherited_from_hand_heading(org, tmp_path):
    # worklog-sample has `** Rob 1-1` on the day; give it ` - [[…][DEV-77]]` in the fixture copy, digest title "Rob 1:1"
    ...; e = st.ledger[...]; assert e["jira"] == "DEV-77" and e["jira_source"] == "heading"
    assert "[[https://rmt.atlassian.net/browse/DEV-77][DEV-77]] [[file:" in row.cells[2]

def test_archive_month_row_links_archive_file(org, tmp_path):
    # digest date 2026-09-15, --today 2026-10-22 -> 2026/2026-09-worklog.org
    assert row.cells[2].endswith("[[file:2026/2026-09-worklog.org::*… - @Nick][↗]]"); assert e["file"] == "2026/2026-09-worklog.org"

def test_deleted_heading_is_recreated_at_end(org, tmp_path):
    (org / "action-items.org").write_text("\n".join(ledger.PREAMBLE + ["* Commitment", ledger.HEADER, ledger.RULE, ""]) + "\n")
    ...; lines = OrgDoc.load(org / "action-items.org").lines
    assert lines.index("* Commitment") < lines.index("* Waiting-on")

def test_ledger_guard_trips_independently(org, tmp_path):
    (org / "action-items.org").write_text(...); Path(org / "action-items.org").touch()
    assert write_org.main(args) == 3 and ":auto:" not in (org / "worklog.org").read_text()

def test_digest_with_no_items_creates_no_ledger(org, tmp_path):
    ...; assert not (org / "action-items.org").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --quiet pytest -q tests/test_write_org.py -k "rows_land or rerun_adds or collision or inherited or archive_month or recreated or ledger_guard or no_items"`
Expected: FAIL (no `action-items.org`, `plan_writes` rejects `ledger=`)

- [ ] **Step 3: Implement** in `write_org.py`. Order inside `plan_writes`: worklog writes as today, then for each action item (`item_headline`), each follow-up (`followup_headline`; file = `fu_file` when dated else the meeting file), each open question (marker target = `link_target(link_file, marker_headline)` where the marker headline is `meeting_body(...)[0]` without its stars), build the entry and call `p.ledger_row(...)`. Uniqueness: before rendering an item, while `link_target(file, headline)` is in `ledger` or already planned this run, append ` (n)` to the item's `text` (mutating the digest dict so the worklog headline and the row agree). WHO: `@`+canonical owner / `@?`; follow-ups `", ".join("@"+resolve(w))`; open questions blank. WHEN: `org_date(due|when)` or blank. Jira: item's key, else the matched hand-written heading's `link` (`jira_source: "heading"`).

- [ ] **Step 4: Run the suite**

Run: `uv run --quiet pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/write_org.py tests/test_write_org.py tests/fixtures/
git commit -m "meetings: every landed item also lands as a ledger row with a state entry"
```

---

### Task 6: `sync_done.py`

**Files:**
- Create: `scripts/sync_done.py`
- Test: `tests/test_sync_done.py`, fixture `tests/fixtures/tron-tasks-sample.org` (verify it has `* In Review`, `* Ready for QA`, `* In QA`, `* Accepted`, `* Closed`, `* Reopen`, `* To Do`, `* Needs Refinement`, `* Blocked (do not sync)`, `* Maybe (do not sync)` headings; add any missing ones at the end)

**Interfaces:**
- Consumes: Task 2 `headline_parts`, `set_keyword`, `set_tags`, `move_section`, `find_headline`; Task 4 `rows`, `last_link_target`, `normalize_done`; `write_org._recently_saved`, `GUARD_MINUTES`, `EXIT_GUARD`, `EXIT_NOTHING`.
- Produces:
  ```python
  DONE_WORDS: dict[str, tuple[str, str | None]] = {"x": ("In Review", "in_review"), "review": ("In Review", "in_review"), "ready": ("Ready for QA", "ready_for_qa"), "qa": ("In QA", "in_qa"), "accepted": ("Accepted", "accepted"), "closed": ("Closed", "closed"), "reopen": ("Reopen", "reopen"), "blocked": ("Blocked (do not sync)", None), "maybe": ("Maybe (do not sync)", None), "todo": ("To Do", "to_do"), "progress": ("In Progress", "in_progress"), "refine": ("Needs Refinement", "needs_refinement")}
  STATUS_TAGS = {"needs_refinement","to_do","reopen","in_progress","in_review","ready_for_qa","in_qa","accepted","closed"}
  @dataclass class Edit: file: Path; idx: int; before: str; after: str
  def match_entry(row: Row, ledger: dict) -> tuple[str, dict] | None     # headline rows by target; OQ rows by target + text[:40]
  def resolve_key(entry: dict, row: Row, doc: OrgDoc, hidx: int | None) -> str | None
  def plan(paths: Paths, state: State, now: datetime) -> tuple[list[Edit], list[str], dict[str, str]]   # edits, log lines, {locator: done_at}
  def main(argv=None) -> int                                                 # --dry-run, --now; exit 0 edits, 2 nothing, 3 guard
  ```
  Worklog `CLOSED:` line indented `level + 1` spaces: `CLOSED: [2026-10-28 Wed 07:12]`. Bullet rewrite: `- Open: t` -> `- Resolved [2026-10-28]: t`.

- [ ] **Step 1: Write the failing tests** (each builds `org_dir` with a worklog, a ledger, a tron file, and `state.json` whose `ledger` has the entries; helper `_setup(org_dir, rows=[...], entries={...})`)

```python
def test_x_flips_worklog_and_moves_task_to_in_review(org_dir): …  # `** TODO Ship it - @Nick :commitment:auto:` -> `** DONE …` + CLOSED line; tron `** Ship it - @Nick - [[…][DEV-5]]` moves from To Do to In Review; state done_at set; exit 0
def test_x_on_subtask_sets_in_review_tag(org_dir): …                  # `*** sub - [[…][DEV-6]] :to_do:` -> `:in_review:`
def test_subtask_without_status_tag_gets_one(org_dir): …              # `*** sub - [[…][DEV-6]] :auto:` -> `:auto:in_review:`? -> assert tags == ["in_review","auto"] order: status tag first
def test_bucket_word_moves_task(org_dir): parametrize over DONE_WORDS with a bucket: assert the task sits under that heading
def test_blocked_on_subtask_logs_and_keeps_tag(org_dir): …            # "no sub-task tag" in log, tag unchanged, worklog still flipped
def test_unknown_word_leaves_tron(org_dir): …                          # "unknown DONE word" in log; worklog flipped
def test_key_from_what_cell_and_from_headline(org_dir): …              # entry jira None; `DEV-9` typed in WHAT -> tron edited; second row: key only in worklog headline
def test_key_from_ancestor_heading(org_dir): …                          # `** CSV Proofs - [[…][DEV-10173]]` parent of the item
def test_open_question_bullet_resolved(org_dir): …                      # `- Open: why?` -> `- Resolved [2026-10-28]: why?`
def test_oq_row_with_rewritten_text_is_untracked(org_dir): …           # WHAT text changed beyond 40 chars -> no edit, no done_at
def test_worklog_not_found_skips_tron_too(org_dir): …                   # headline edited by hand -> log "not found", tron unchanged, done_at None
def test_already_done_headline_only_gets_closed(org_dir): …            # `** DONE …` present, no CLOSED -> only CLOSED added
def test_duplicate_key_acts_on_first_match(org_dir): …                  # key on `**` and on a `***` under it -> only the `**` moved, log mentions the second
def test_second_run_is_noop(org_dir): … exit 2 and files byte-identical
def test_guard_trips_on_tron_or_worklog(org_dir): … touch tron -> exit 3, nothing edited, done_at None
def test_symlinked_tron_is_written_through(org_dir, tmp_path): … tron-tasks.org -> symlink to tmp_path/real.org; after sync the symlink is still a symlink and real.org changed
def test_dry_run_prints_edits_and_changes_nothing(org_dir, capsys): …
def test_log_lines_name_file_and_line(org_dir, capsys): … "done-sync: worklog.org:12 ** TODO … -> ** DONE …"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --quiet pytest -q tests/test_sync_done.py`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement `scripts/sync_done.py`**. `plan()` loads the ledger doc; for each row with `normalize_done(cells[4])`: `match_entry`; skip `done_at`; open the entry's file (`paths.org_dir / entry["file"]`); locate (day section first via `find_day(entry["day"])` + `section_end`, then whole file); build the worklog edit; resolve the key; build the tron edit; append to `edits` only when the worklog edit succeeded (Review Focus 5); record `done_at`. Apply: group edits by file (resolve symlinks with `Path.resolve()`), guard every file first (`_recently_saved(f, state)` -> exit 3 before any write), apply in descending line order per file, `save_atomic`, register `own_saves`, update `state.ledger[...]["done_at"]`, `state.save()`. Tron move uses `move_section`; the moved subtree's log line names the bucket.

- [ ] **Step 4: Run the suite**

Run: `uv run --quiet pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/sync_done.py tests/test_sync_done.py tests/fixtures/tron-tasks-sample.org
git commit -m "meetings: done-sync propagates a filled DONE cell to the worklog and tron-tasks"
```

---

### Task 7: Backfill with classification

**Files:**
- Create: `scripts/backfill_ledger.py`, `references/classify-prompt.md`
- Test: `tests/test_backfill_ledger.py`

**Interfaces:**
- Consumes: Task 1 `validate`, `run_claude`, `extract_json`, `ticket_candidates`, `CATEGORIES`; Task 3 `item_headline`, `followup_headline`; Task 4/5 `plan_writes(... ledger=)`, `apply`.
- Produces: `classify(digest: dict, tickets: list[str], run: Callable[[str], str] = run_claude) -> dict` returns the digest with `category`/`effort` (and `jira` when the model links one) filled, raising `ValueError` on invalid output after one retry. `needs_classification(d: dict) -> bool`. `backfill(paths, state, people, since: date | None, dry_run: bool, run=run_claude, now=None) -> int` rows appended. `main(argv)` with `--since`, `--dry-run`. Exit 0 wrote, 2 nothing, 3 guard.
- Classify prompt returns `{"action_items": [{"category","effort","jira"}…], "follow_ups": [{"category","effort"}…], "open_questions": [{"category","effort"}…]}` with one entry per input item in order.

- [ ] **Step 1: Write the failing tests**

```python
def test_needs_classification_detects_legacy(): …
def test_classify_fills_fields_in_order(): fake run returning the JSON; assert categories applied by index; open_questions converted to objects
def test_classify_retries_once_then_raises(): first output garbage, second fine -> ok; two garbage -> ValueError
def test_backfill_appends_rows_for_landed_items(org_dir, monkeypatch):
    # write a legacy digest json + the worklog lines it produced (from the old renderer: `*** TODO Ship it - @Nick :auto:`) + state.processed keys
    n = backfill(paths, state, people, None, False, run=fake); assert n == 3
    assert "worklog.org::*Ship it - @Nick" in State.load(...).ledger
    assert json.loads(digest_path.read_text())["action_items"][0]["category"] == "commitment"  # persisted
def test_backfill_prefills_x_for_done_headlines(org_dir): … worklog has `*** DONE Ship it - @Nick :auto:` -> row DONE cell "x", entry done_at set
def test_backfill_skips_unlanded_and_unfound(org_dir, capsys): … digest without processed keys -> 0 rows; headline missing -> log "not found", no row
def test_backfill_since_filters_by_digest_date(org_dir): …
def test_backfill_dry_run_writes_nothing(org_dir): … digest file unchanged, no ledger file
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --quiet pytest -q tests/test_backfill_ledger.py`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement**. Row planning reuses `plan_writes` with a flag `ledger_only=True` (Task 5's planner skips worklog writes when set and, for each item, locates the existing headline by `item_headline` text with `find_headline` in the landed file instead of planning an insert; items not found are skipped with a log). Keep the flag out of `main()`'s CLI. Pre-fill: when the found headline's keyword is `DONE`, the row's DONE cell is `x` and the entry's `done_at` is `now`.

- [ ] **Step 4: Run the suite**

Run: `uv run --quiet pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_ledger.py references/classify-prompt.md scripts/write_org.py tests/test_backfill_ledger.py
git commit -m "meetings: one-time ledger backfill with classification of digests on disk"
```

---

### Task 8: Orchestration, skill commands, docs, spec correction

**Files:**
- Modify: `scripts/run.sh`, `SKILL.md`, `tests/test_run_sh.py`
- Modify: `~/org/ringmaster/CLAUDE-meetings.md`, `~/org/ringmaster/meetings-integrations.md`
- Modify: `docs/superpowers/specs/2026-10-28-action-items-ledger-design.md` (Landing paragraph: locator "without keyword and tags")
- Run: `~/code/skills/install-skill.sh meetings` (new files need symlinks)

**Interfaces:**
- Produces: `run.sh done [--dry-run]`, `run.sh ledger-backfill [--since D] [--dry-run]`, `run.sh ledger` (report); `cmd_daily` runs `sync_done.py` first and folds its exit 3 into `skipped`; `cmd_status` prints the ledger report.

- [ ] **Step 1: Write the failing tests** (`tests/test_run_sh.py`, same stub-`uv` technique the file already uses)

```python
def test_daily_runs_done_sync_before_fetch(stub_env): … order of stubbed script names starts with "sync_done.py", then "fetch_teams.py"
def test_daily_exit_3_when_done_sync_guard_trips(stub_env): … sync_done exits 3, rest fine -> run.sh exits 3
def test_done_and_backfill_commands_dispatch(stub_env): … `run.sh done --dry-run` -> sync_done.py called with --dry-run; `run.sh ledger-backfill --since 2026-10-01` likewise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --quiet pytest -q tests/test_run_sh.py`
Expected: FAIL

- [ ] **Step 3: Implement** `run.sh` changes; SKILL.md command rows `done`, `ledger`, `ledger-backfill` and a "Action items ledger" paragraph; runbook section "Action items ledger" (file shape, DONE words table with both columns, what done-sync edits and how to undo, the jira-sync direction caveat, backfill command), principle paragraph amended, rollback grep extended with `action-items.org`, exit-code note; integrations file "Ledger" section (backfill run, first-week review boxes). Spec correction. Re-run the installer.

- [ ] **Step 4: Run the suite**

Run: `uv run --quiet pytest -q`
Expected: PASS

- [ ] **Step 5: Commit (two repos)**

```bash
git add scripts/run.sh SKILL.md tests/test_run_sh.py docs/superpowers/specs/2026-10-28-action-items-ledger-design.md
git commit -m "meetings: run.sh done/ledger/ledger-backfill, daily runs done-sync first, docs"
cd ~/org/ringmaster && git add CLAUDE-meetings.md meetings-integrations.md && git commit -m "ringmaster: action items ledger runbook section"
```

---

### Task 9: Backfill the real org dir

**Files:** none in the repos; writes `~/org/ringmaster/action-items.org`, `meetings/digests/*.json`, `meetings/state.json`.

- [ ] **Step 1: Dry run**

Run: `bash ~/code/skills/skills/meetings/scripts/run.sh ledger-backfill --dry-run 2>&1 | tail -40`
Expected: per-digest "classified" lines, "would append N row(s)" totals, no "not found" lines beyond items Nick deleted by hand.

- [ ] **Step 2: Real run** (guard honored; worklog saved <15 min ago -> wait)

Run: `bash ~/code/skills/skills/meetings/scripts/run.sh ledger-backfill 2>&1 | tail -5; bash ~/code/skills/skills/meetings/scripts/run.sh ledger`
Expected: exit 0, `action-items.org` exists with five headings, report counts match the appended rows, every `DONE` worklog headline shows as done.

- [ ] **Step 3: Verify shape**

Run: `grep -c '^|' ~/org/ringmaster/action-items.org; grep -n '^\* ' ~/org/ringmaster/action-items.org; git -C ~/org/ringmaster status --short worklog.org`
Expected: five headings in spec order; worklog unchanged by the backfill (no retro-tagging).
