import json
import os
import shutil
import time
from datetime import date, datetime
from pathlib import Path

import pytest

import backfill_ledger as bl
import ledger
from config import Paths
from orgfile import OrgDoc
from people import People
from state import State

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 2, 7, 0)
J = "https://rmt.atlassian.net/browse/"

LEGACY_BLOCK = f"""*** meetings (auto) 2026-10-21T06:31 · source: slack · attendees: Nick, Rob
   - Status on accuracy work; Rob wants the CSV proofs runbook by Friday.
   - Decided (committed): Align Jira buckets with David this week — Nick
   - Open: Who owns the accuracy dashboard?
*** TODO draft the CSV proofs runbook - @Nick - [[{J}DEV-10173][DEV-10173]] :auto:
    DEADLINE: <2026-10-23 Fri>
*** send the sample CSV file - @Rob :auto:
*** TODO build a proof-diff tool for CSV exports - @Nick :auto:
*** TODO revisit accuracy targets - @Nick :auto:
    - when: TBD
"""
FOLLOWUP_DAY = """* <2026-10-28 Wed>

** TODO sync with Rob on the roadmap - @Nick :auto:
   SCHEDULED: <2026-10-28 Wed>
   - from: [[file:worklog.org::*Rob 1-1][2026-10-20 Rob 1-1]]

"""
KEYS = ["k1|worklog.org|2026-10-20/Rob 1-1", "k1|worklog.org|2026-10-20/Rob 1-1/items", "k1|worklog.org|2026-10-28/followup/0"]

CLASSIFIED = {
    "action_items": [{"category": "commitment", "effort": "M", "jira": "DEV-10173"},
                     {"category": "waiting_on", "effort": None, "jira": None},
                     {"category": "commitment", "effort": "L", "jira": None}],
    "follow_ups": [{"category": "follow_up", "effort": "S"}, {"category": "decision", "effort": "S"}],
    "open_questions": [{"category": "open_question", "effort": None}],
}


def _legacy_digest():
    d = json.loads((FIX / "digest-good.json").read_text())
    for it in d["action_items"] + d["follow_ups"]:
        it.pop("category", None)
        it.pop("effort", None)
    d["open_questions"] = [q["text"] for q in d["open_questions"]]
    d["landed"] = {"file": "worklog.org", "heading": "Rob 1-1"}
    return d


def _age(p):
    old = time.time() - 3600
    os.utime(p, (old, old))


def _setup(org_dir, digest=None, keys=KEYS, block=LEGACY_BLOCK):
    base = (FIX / "worklog-sample.org").read_text()
    wl = base.replace("** Rob 1-1\n   - my own notes about accuracy\n", "** Rob 1-1\n   - my own notes about accuracy\n" + block)
    wl = wl.replace("* TODO\n", FOLLOWUP_DAY + "* TODO\n", 1)
    (org_dir / "worklog.org").write_text(wl)
    _age(org_dir / "worklog.org")
    shutil.copy(FIX / "tron-tasks-sample.org", org_dir / "tron-tasks.org")
    dj = org_dir / "meetings" / "digests" / "2026-10-20-rob-1-1.json"
    dj.write_text(json.dumps(digest or _legacy_digest(), indent=2) + "\n")
    paths = Paths(org_dir)
    st = State.load(paths.state_file)
    for k in keys:
        st.processed[k] = {"file": str(paths.worklog), "line": 1, "at": "2026-10-21T06:31"}
    st.save()
    return paths, dj


def fake_run(prompt: str) -> str:
    return "Here you go:\n" + json.dumps(CLASSIFIED)


def test_needs_classification_detects_legacy():
    assert bl.needs_classification(_legacy_digest())
    assert not bl.needs_classification(json.loads((FIX / "digest-good.json").read_text()))
    d = json.loads((FIX / "digest-good.json").read_text())
    d["open_questions"] = ["bare"]
    assert bl.needs_classification(d)


def test_classify_fills_fields_in_order():
    d = _legacy_digest()
    out = bl.classify(d, ["DEV-10173 · CSV Proofs"], run=fake_run)
    assert out is d
    assert [i["category"] for i in d["action_items"]] == ["commitment", "waiting_on", "commitment"]
    assert [i["effort"] for i in d["action_items"]] == ["M", None, "L"]
    assert [f["category"] for f in d["follow_ups"]] == ["follow_up", "decision"]
    assert d["open_questions"] == [{"text": "Who owns the accuracy dashboard?", "category": "open_question", "effort": None}]
    assert not bl.needs_classification(d)


def test_classify_links_jira_only_from_tickets_in_play():
    d = _legacy_digest()
    answer = json.loads(json.dumps(CLASSIFIED))
    answer["action_items"][1]["jira"] = "DEV-10716"
    answer["action_items"][2]["jira"] = "DEV-999"
    bl.classify(d, ["DEV-10716 · Trontology upgrade"], run=lambda p: json.dumps(answer))
    assert d["action_items"][1]["jira"] == "DEV-10716"
    assert d["action_items"][2]["jira"] is None
    assert d["action_items"][0]["jira"] == "DEV-10173"  # a key already in the digest stays


def test_classify_retries_once_then_raises():
    calls = []

    def flaky(prompt):
        calls.append(prompt)
        return "nope" if len(calls) == 1 else json.dumps(CLASSIFIED)

    d = _legacy_digest()
    bl.classify(d, [], run=flaky)
    assert len(calls) == 2 and "did not validate" in calls[1]
    with pytest.raises(ValueError):
        bl.classify(_legacy_digest(), [], run=lambda p: "garbage")


def test_backfill_appends_rows_for_landed_items(org_dir):
    paths, dj = _setup(org_dir)
    people = People.load(paths.people_file)
    state = State.load(paths.state_file)
    n = bl.backfill(paths, state, people, None, False, run=fake_run, now=NOW)
    assert n == 6
    st = State.load(paths.state_file)
    assert "worklog.org::*draft the CSV proofs runbook - @Nick" in st.ledger
    assert "worklog.org::*sync with Rob on the roadmap - @Nick" in st.ledger
    assert st.ledger["worklog.org::*revisit accuracy targets - @Nick"]["category"] == "decision"
    oq = [k for k in st.ledger if k.endswith("::Open: Who owns the accuracy dashboard?")]
    assert oq == ["worklog.org::*meetings (auto) 2026-10-21T06:31 · source: slack · attendees: Nick, Rob::Open: Who owns the accuracy dashboard?"]
    led = OrgDoc.load(paths.ledger)
    by = {r.category: [] for r in ledger.rows(led)}
    for r in ledger.rows(led):
        by[r.category].append(r)
    assert {k: len(v) for k, v in by.items()} == {"commitment": 2, "waiting_on": 1, "follow_up": 1, "decision": 1, "open_question": 1}
    assert by["commitment"][0].cells[0] == "<2026-10-23 Fri>" and by["commitment"][0].cells[4] == ""
    persisted = json.loads(dj.read_text())
    assert persisted["action_items"][0]["category"] == "commitment" and persisted["open_questions"][0]["category"] == "open_question"
    assert ":auto:\n" in (org_dir / "worklog.org").read_text() and ":commitment:auto:" not in (org_dir / "worklog.org").read_text()  # no retro-tagging


def test_backfill_prefills_x_for_done_headlines(org_dir):
    block = LEGACY_BLOCK.replace("*** TODO draft the CSV proofs runbook", "*** DONE draft the CSV proofs runbook")
    paths, _ = _setup(org_dir, block=block)
    n = bl.backfill(paths, State.load(paths.state_file), People.load(paths.people_file), None, False, run=fake_run, now=NOW)
    assert n == 6
    st = State.load(paths.state_file)
    assert st.ledger["worklog.org::*draft the CSV proofs runbook - @Nick"]["done_at"] == "2026-11-02T07:00"
    assert st.ledger["worklog.org::*send the sample CSV file - @Rob"]["done_at"] is None
    rows = {ledger.last_link_target(r.cells[2]): r for r in ledger.rows(OrgDoc.load(paths.ledger))}
    assert rows["worklog.org::*draft the CSV proofs runbook - @Nick"].cells[4] == "x"


def test_backfill_skips_unlanded_and_unfound(org_dir, capsys):
    paths, _ = _setup(org_dir, keys=[])
    assert bl.backfill(paths, State.load(paths.state_file), People.load(paths.people_file), None, False, run=fake_run, now=NOW) == 0
    assert not paths.ledger.exists()


def test_backfill_logs_missing_headline(org_dir, capsys):
    block = LEGACY_BLOCK.replace("*** send the sample CSV file - @Rob :auto:\n", "")
    paths, _ = _setup(org_dir, block=block)
    n = bl.backfill(paths, State.load(paths.state_file), People.load(paths.people_file), None, False, run=fake_run, now=NOW)
    assert n == 5
    assert "not found" in capsys.readouterr().out
    assert "worklog.org::*send the sample CSV file - @Rob" not in State.load(paths.state_file).ledger


def test_backfill_second_run_adds_nothing(org_dir):
    paths, _ = _setup(org_dir)
    assert bl.backfill(paths, State.load(paths.state_file), People.load(paths.people_file), None, False, run=fake_run, now=NOW) == 6
    calls = []
    assert bl.backfill(paths, State.load(paths.state_file), People.load(paths.people_file), None, False, run=lambda p: calls.append(p) or "x", now=NOW) == 0
    assert calls == []  # already classified: no model call
    assert len(ledger.rows(OrgDoc.load(paths.ledger))) == 6


def test_backfill_since_filters_by_digest_date(org_dir):
    paths, dj = _setup(org_dir)
    assert bl.backfill(paths, State.load(paths.state_file), People.load(paths.people_file), date(2026, 10, 21), False, run=fake_run, now=NOW) == 0
    assert "category" not in json.loads(dj.read_text())["action_items"][0]


def test_backfill_dry_run_writes_nothing(org_dir, capsys):
    paths, dj = _setup(org_dir)
    before = dj.read_text()
    assert bl.backfill(paths, State.load(paths.state_file), People.load(paths.people_file), None, True, run=fake_run, now=NOW) == 6
    assert dj.read_text() == before and not paths.ledger.exists()
    assert "| <2026-10-23 Fri> | @Nick | draft the CSV proofs runbook" in capsys.readouterr().out
    assert State.load(paths.state_file).ledger == {}


def test_main_exit_codes(org_dir, monkeypatch):
    _setup(org_dir)
    monkeypatch.setattr(bl, "run_claude", fake_run)
    assert bl.main(["--now", NOW.isoformat()]) == 0
    assert bl.main(["--now", NOW.isoformat()]) == 2


def test_main_guard_trips_on_hand_saved_ledger(org_dir, monkeypatch):
    paths, _ = _setup(org_dir)
    monkeypatch.setattr(bl, "run_claude", fake_run)
    paths.ledger.write_text("\n".join(ledger.PREAMBLE) + "\n")  # saved just now, as if open in nvim
    assert bl.main(["--now", NOW.isoformat()]) == 3
    assert State.load(paths.state_file).ledger == {}
    assert paths.ledger.read_text() == "\n".join(ledger.PREAMBLE) + "\n"


def test_backfill_locates_headline_as_landed_when_classifier_links_key(org_dir):
    """The classifier may add a key after landing; the worklog headline still has none."""
    paths, _ = _setup(org_dir)
    answer = json.loads(json.dumps(CLASSIFIED))
    answer["action_items"][2]["jira"] = "DEV-10900"  # in the tron fixture's In Progress
    n = bl.backfill(paths, State.load(paths.state_file), People.load(paths.people_file), None, False, run=lambda p: json.dumps(answer), now=NOW)
    assert n == 6
    e = State.load(paths.state_file).ledger["worklog.org::*build a proof-diff tool for CSV exports - @Nick"]
    assert e["jira"] == "DEV-10900" and e["headline"] == "build a proof-diff tool for CSV exports - @Nick"
    rows = {ledger.last_link_target(r.cells[2]): r for r in ledger.rows(OrgDoc.load(paths.ledger))}
    assert "[[https://rmt.atlassian.net/browse/DEV-10900][DEV-10900]] [[file:" in rows["worklog.org::*build a proof-diff tool for CSV exports - @Nick"].cells[2]
