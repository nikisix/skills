import json
import os
import shutil
import time
from datetime import date, datetime
from pathlib import Path

import pytest

import write_org
from config import Paths
from orgfile import OrgDoc
from people import People
from state import State

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 22, 6, 31)
TODAY = date(2026, 10, 22)


@pytest.fixture
def org(org_dir):
    shutil.copy(FIX / "worklog-sample.org", org_dir / "worklog.org")
    old = time.time() - 3600
    os.utime(org_dir / "worklog.org", (old, old))
    return org_dir


def _setup(org):
    paths = Paths(org)
    people = People.load(paths.people_file)
    state = State.load(paths.state_file)
    return paths, people, state


def _digest(**over):
    d = json.loads((FIX / "digest-good.json").read_text())
    d.update(over)
    return d


def _run(org, digest, key="k1", today=TODAY, done=frozenset()):
    paths, people, state = _setup(org)
    writes = write_org.plan_writes(digest, key, paths, people, NOW, today=today, done=done)
    n = write_org.apply(writes, state, dry_run=False, now=NOW)
    return paths, writes, n


def test_target_file_by_month(org):
    paths = Paths(org)
    assert write_org.target_file(paths, date(2026, 10, 5), TODAY) == paths.worklog
    assert write_org.target_file(paths, date(2026, 11, 4), TODAY) == paths.worklog
    assert write_org.target_file(paths, date(2026, 9, 30), TODAY) == org / "2026" / "2026-09-worklog.org"


def test_merge_under_existing_heading(org):
    paths, writes, n = _run(org, _digest())
    lines = (org / "worklog.org").read_text().splitlines()
    i = lines.index("** Rob 1-1")
    j = lines.index("** INPROGRESS Ontology 2.0 - RX Skeleton")
    block = lines[i + 1 : j]
    assert block[0] == "   - my own notes about accuracy"  # my line stays first and unchanged
    assert "   - meetings (auto) 2026-10-22T06:31 · source: slack · attendees: Nick, Rob" in block
    assert any(l.startswith("*** TODO draft the CSV proofs runbook - @Nick - [[") and l.endswith(":auto:") for l in block)
    assert "*** TODO revisit accuracy targets - @Nick :auto:" in block
    assert not any("** Rob 1:1" in l for l in lines)  # no second heading


def test_new_heading_when_no_match(org):
    d = _digest(title="Platform Weekly Sync", attendees=["Nick", "Lars"], date="2026-10-21", follow_ups=[])
    _run(org, d)
    lines = (org / "worklog.org").read_text().splitlines()
    i = lines.index("** Platform Weekly Sync :meeting:auto:")
    assert lines.index("** CSV Proofs - @Nick - [[https://rmt.atlassian.net/browse/DEV-10173][DEV-10173]]") < i < lines.index("* TODO")


def test_dated_followup_under_target_day(org):
    _run(org, _digest())
    lines = (org / "worklog.org").read_text().splitlines()
    day = lines.index("* <2026-10-28 Wed>")
    assert lines.index("* <2026-10-21 Wed>") < day < lines.index("* TODO")
    assert lines[day + 1 : day + 4] == [
        "** TODO sync with Rob on the roadmap - @Nick :auto:",
        "   SCHEDULED: <2026-10-28 Wed>",
        "   - from: [[file:worklog.org::*Rob 1-1][2026-10-20 Rob 1-1]]",  # links the heading it merged into
    ]
    assert "** TODO sync with Rob on the roadmap - @Nick :auto:" not in lines[: lines.index("* <2026-10-21 Wed>")]


def test_followup_future_month_goes_to_worklog(org):
    d = _digest(follow_ups=[{"text": "roadmap review", "with": ["Rob"], "when": "2026-11-04"}])
    paths, writes, _ = _run(org, d)
    assert {w.file for w in writes} == {paths.worklog}
    lines = (org / "worklog.org").read_text().splitlines()
    assert lines.index("* <2026-10-21 Wed>") < lines.index("* <2026-11-04 Wed>") < lines.index("* TODO")


def test_past_month_goes_to_archive(org):
    d = _digest(date="2026-09-15", title="Sept planning", attendees=["Nick"],
                follow_ups=[{"text": "sept retro", "with": ["Rob"], "when": "2026-09-20"}])
    paths, writes, _ = _run(org, d)
    arch = org / "2026" / "2026-09-worklog.org"
    assert {w.file for w in writes} == {arch}
    lines = arch.read_text().splitlines()
    assert lines[0] == "* <2026-09-15 Tue>"
    assert "** Sept planning :meeting:auto:" in lines
    assert lines.index("* <2026-09-15 Tue>") < lines.index("* <2026-09-20 Sun>")
    assert "   - from: [[file:2026/2026-09-worklog.org::*Sept planning][2026-09-15 Sept planning]]" in lines
    assert (org / "worklog.org").read_text() == (FIX / "worklog-sample.org").read_text()


def test_rerun_is_noop(org):
    paths, writes, n = _run(org, _digest())
    assert n == len(writes) > 0
    before = (org / "worklog.org").read_bytes()
    state = State.load(paths.state_file)
    assert set(w.write_key for w in writes) <= set(state.processed)
    _, writes2, n2 = _run(org, _digest(), done=set(state.processed))
    assert writes2 == [] and n2 == 0
    assert (org / "worklog.org").read_bytes() == before


def test_only_additions(org):
    original = (FIX / "worklog-sample.org").read_text().splitlines()
    _run(org, _digest())
    result = (org / "worklog.org").read_text().splitlines()
    it = iter(result)
    assert all(any(line == r for r in it) for line in original)  # original is a subsequence of result


def test_dry_run_writes_nothing(org, capsys):
    paths, people, state = _setup(org)
    writes = write_org.plan_writes(_digest(), "k1", paths, people, NOW, today=TODAY)
    n = write_org.apply(writes, state, dry_run=True, now=NOW)
    out = capsys.readouterr().out
    assert n == len(writes)
    assert out.startswith(f"== {paths.worklog}:")
    assert "   - meetings (auto) 2026-10-22T06:31" in out
    assert (org / "worklog.org").read_text() == (FIX / "worklog-sample.org").read_text()
    assert not paths.state_file.exists()


def test_mtime_guard(org, tmp_path):
    dj = tmp_path / "d.json"
    dj.write_text(json.dumps(_digest()))
    Path(org / "worklog.org").touch()  # saved just now -> nvim may have it open
    rc = write_org.main([str(dj), "--key", "k1", "--now", NOW.isoformat(), "--today", TODAY.isoformat()])
    assert rc == 3
    assert (org / "worklog.org").read_text() == (FIX / "worklog-sample.org").read_text()
    rc = write_org.main([str(dj), "--key", "k1", "--now", NOW.isoformat(), "--today", TODAY.isoformat(), "--force"])
    assert rc == 0
    assert ":auto:" in (org / "worklog.org").read_text()


def test_cli_nothing_to_do_exits_2(org, tmp_path):
    dj = tmp_path / "d.json"
    dj.write_text(json.dumps(_digest()))
    args = [str(dj), "--key", "k1", "--now", NOW.isoformat(), "--today", TODAY.isoformat()]
    assert write_org.main(args) == 0
    assert write_org.main(args) == 2
