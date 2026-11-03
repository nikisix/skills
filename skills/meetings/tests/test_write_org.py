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
import ledger

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
    writes = write_org.plan_writes(digest, key, paths, people, NOW, today=today, done=done, ledger=state.ledger)
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
    assert "*** meetings (auto) 2026-10-22T06:31 · source: slack · attendees: Nick, Rob" in block
    assert any(l.startswith("*** TODO draft the CSV proofs runbook - @Nick - [[") and l.endswith(":auto:") for l in block)
    assert "*** TODO revisit accuracy targets - @Nick :follow_up:auto:" in block
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
        "** TODO sync with Rob on the roadmap - @Nick :follow_up:auto:",
        "   SCHEDULED: <2026-10-28 Wed>",
        "   - from: [[file:worklog.org::*Rob 1-1][2026-10-20 Rob 1-1]]",  # links the heading it merged into
    ]
    assert "** TODO sync with Rob on the roadmap - @Nick :follow_up:auto:" not in lines[: lines.index("* <2026-10-21 Wed>")]


def test_followup_future_month_goes_to_worklog(org):
    d = _digest(follow_ups=[{"text": "roadmap review", "with": ["Rob"], "when": "2026-11-04"}])
    paths, writes, _ = _run(org, d)
    assert {w.file for w in writes} == {paths.worklog, paths.ledger}
    lines = (org / "worklog.org").read_text().splitlines()
    assert lines.index("* <2026-10-21 Wed>") < lines.index("* <2026-11-04 Wed>") < lines.index("* TODO")


def test_past_month_goes_to_archive(org):
    d = _digest(date="2026-09-15", title="Sept planning", attendees=["Nick"],
                follow_ups=[{"text": "sept retro", "with": ["Rob"], "when": "2026-09-20"}])
    paths, writes, _ = _run(org, d)
    arch = org / "2026" / "2026-09-worklog.org"
    assert {w.file for w in writes} == {arch, paths.ledger}
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
    assert "*** meetings (auto) 2026-10-22T06:31" in out
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


def test_plan_records_landing(org):
    paths, people, _ = _setup(org)
    d = _digest()
    write_org.plan_writes(d, "k1", paths, people, NOW, today=TODAY)
    assert d["landed"] == {"file": "worklog.org", "heading": "Rob 1-1"}
    d2 = _digest(date="2026-09-15", title="Sept planning", attendees=["Nick"])
    write_org.plan_writes(d2, "k2", paths, people, NOW, today=TODAY)
    assert d2["landed"] == {"file": "2026/2026-09-worklog.org", "heading": "Sept planning"}


def test_cli_writes_landing_into_digest_file(org, tmp_path):
    dj = tmp_path / "d.json"
    dj.write_text(json.dumps(_digest()))
    assert write_org.main([str(dj), "--key", "k1", "--now", NOW.isoformat(), "--today", TODAY.isoformat()]) == 0
    assert json.loads(dj.read_text())["landed"] == {"file": "worklog.org", "heading": "Rob 1-1"}


def test_merge_bullets_precede_existing_children(org):
    d = _digest(title="CSV Proofs", attendees=["Nick"], date="2026-10-21", follow_ups=[])
    _run(org, d)
    lines = (org / "worklog.org").read_text().splitlines()
    h = lines.index("** CSV Proofs - @Nick - [[https://rmt.atlassian.net/browse/DEV-10173][DEV-10173]]")
    marker = next(i for i, l in enumerate(lines) if l.startswith("*** meetings (auto)"))
    done = lines.index("*** DONE incorporate Marcus' ontology edits")
    todo = next(i for i, l in enumerate(lines) if l.startswith("*** TODO draft the CSV proofs runbook"))
    assert h < marker < done < todo < lines.index("* TODO")


def test_last_month_day_still_in_worklog(org):
    paths = Paths(org)
    # November 2 with October still in worklog.org: October meetings stay in worklog.org
    assert write_org.target_file(paths, date(2026, 10, 30), date(2026, 11, 2)) == paths.worklog
    assert write_org.target_file(paths, date(2026, 9, 15), date(2026, 11, 2)) == org / "2026" / "2026-09-worklog.org"


def test_cli_usage_error_exits_1():
    assert write_org.main(["--bogus"]) == 1  # argparse's 2 would read as "nothing to do"


def test_chat_never_merges_under_hand_written_heading(org):
    d = _digest(title="Slack DM Rob", attendees=["Nick", "Rob"], kind="chat", follow_ups=[])
    _run(org, d)
    lines = (org / "worklog.org").read_text().splitlines()
    assert "*** Slack DM Rob :chat:auto:" in lines and "** Slack DM Rob :chat:auto:" not in lines
    i = lines.index("** Rob 1-1")
    assert lines[i + 1] == "   - my own notes about accuracy" and not lines[i + 2].startswith("*** meetings (auto)")


def test_chat_blocks_group_under_one_slack_heading_per_day(org):
    _run(org, _digest(title="Slack DM Rob", attendees=["Nick", "Rob"], kind="chat", follow_ups=[]), key="k1")
    old = time.time() - 3600
    os.utime(org / "worklog.org", (old, old))  # a later run, past the mtime guard
    _run(org, _digest(title="Slack #tron", attendees=["Nick", "Rob"], kind="chat", follow_ups=[]), key="k2")
    lines = (org / "worklog.org").read_text().splitlines()
    groups = [i for i, l in enumerate(lines) if l == "** Slack :chat:auto:"]
    assert len(groups) == 1, "one Slack group per day, reused by the second chat"
    g = groups[0]
    day = max(i for i, l in enumerate(lines[:g]) if l.startswith("* <"))
    assert lines[day].startswith(f"* <{_digest()['date']}")  # the group sits under the digest's day
    rob, tron = lines.index("*** Slack DM Rob :chat:auto:"), lines.index("*** Slack #tron :chat:auto:")
    assert g < rob < tron
    nxt = next(i for i in range(g + 1, len(lines)) if lines[i].startswith("* ") or lines[i].startswith("** "))
    assert nxt > tron  # both conversations sit inside the group
    assert lines[rob + 1].startswith("**** meetings (auto)")
    assert any(l.startswith("**** TODO ") and l.endswith(":auto:") for l in lines[rob:tron])
    assert not any(l.startswith("*** TODO ") for l in lines[g:nxt])


def test_guard_ignores_the_pipelines_own_save(org, tmp_path):
    """Two digests in one run: the first save is ours, so the second must not be refused."""
    d1, d2 = tmp_path / "d1.json", tmp_path / "d2.json"
    d1.write_text(json.dumps(_digest()))
    d2.write_text(json.dumps(_digest(title="Second Meeting")))
    common = ["--now", NOW.isoformat(), "--today", TODAY.isoformat()]
    assert write_org.main([str(d1), "--key", "k1", *common]) == 0
    assert write_org.main([str(d2), "--key", "k2", *common]) == 0
    assert any(k.startswith("k2|") for k in State.load(Paths(org).state_file).processed)


def test_guard_trips_on_a_human_save_after_ours(org, tmp_path):
    d1, d2 = tmp_path / "d1.json", tmp_path / "d2.json"
    d1.write_text(json.dumps(_digest()))
    d2.write_text(json.dumps(_digest(title="Second Meeting")))
    common = ["--now", NOW.isoformat(), "--today", TODAY.isoformat()]
    assert write_org.main([str(d1), "--key", "k1", *common]) == 0
    later = time.time() + 1
    os.utime(org / "worklog.org", (later, later))  # an editor saved after our write
    assert write_org.main([str(d2), "--key", "k2", *common]) == 3


# --- action-items.org ledger rows --------------------------------------------

OQ_TEXT = "Who owns the accuracy dashboard?"
COMMON = ["--now", NOW.isoformat(), "--today", TODAY.isoformat()]


def _cli(org, tmp_path, digest, key="k1"):
    dj = tmp_path / f"{key}.json"
    dj.write_text(json.dumps(digest))
    return write_org.main([str(dj), "--key", key, *COMMON])


def _rows_by_target(org):
    led = OrgDoc.load(org / "action-items.org")
    return led, {ledger.last_link_target(r.cells[2]): r for r in ledger.rows(led)}


def test_rows_land_per_category_with_links(org, tmp_path):
    assert _cli(org, tmp_path, _digest()) == 0
    led, by = _rows_by_target(org)
    assert led.lines[:3] == ledger.PREAMBLE
    heads = [l for l in led.lines if l.startswith("* ")]
    assert heads == ["* Decision", "* Commitment", "* Waiting-on", "* Follow-up", "* Open question"]
    r = by["worklog.org::*draft the CSV proofs runbook - @Nick"]
    assert r.category == "commitment" and r.cells[0] == "<2026-10-23 Fri>" and r.cells[1] == "@Nick" and r.cells[3] == "M"
    assert r.cells[2] == ("draft the CSV proofs runbook [[https://rmt.atlassian.net/browse/DEV-10173][DEV-10173]] "
                          "[[file:worklog.org::*draft the CSV proofs runbook - @Nick][↗]]")
    assert by["worklog.org::*send the sample CSV file - @Rob"].category == "waiting_on"
    assert by["worklog.org::*send the sample CSV file - @Rob"].cells[1] == "@Rob"
    fu = by["worklog.org::*sync with Rob on the roadmap - @Nick"]
    assert fu.category == "follow_up" and fu.cells[1] == "@Rob" and fu.cells[0] == "<2026-10-28 Wed>"
    oq = [r for r in ledger.rows(led) if r.category == "open_question"]
    assert len(oq) == 1 and "meetings (auto)" in ledger.last_link_target(oq[0].cells[2]) and oq[0].cells[1] == ""
    st = State.load(Paths(org).state_file)
    e = st.ledger["worklog.org::*draft the CSV proofs runbook - @Nick"]
    assert e["kind"] == "headline" and e["category"] == "commitment" and e["done_at"] is None and e["day"] == "2026-10-20"
    assert e["jira"] == "DEV-10173" and e["jira_source"] == "digest" and e["key"].startswith("k1|action-items.org|commitment/")
    assert e["headline"] == "draft the CSV proofs runbook - @Nick - [[https://rmt.atlassian.net/browse/DEV-10173][DEV-10173]]"
    assert any(k.endswith("::Open: " + OQ_TEXT) for k in st.ledger)
    q = next(v for k, v in st.ledger.items() if k.endswith("::Open: " + OQ_TEXT))
    assert q["kind"] == "bullet" and q["headline"].startswith("meetings (auto) 2026-10-22T06:31")


def test_rerun_adds_no_rows(org, tmp_path):
    assert _cli(org, tmp_path, _digest()) == 0
    n = len(ledger.rows(OrgDoc.load(org / "action-items.org")))
    assert _cli(org, tmp_path, _digest()) == 2
    assert len(ledger.rows(OrgDoc.load(org / "action-items.org"))) == n


def test_locator_collision_gets_suffix(org, tmp_path):
    assert _cli(org, tmp_path, _digest(), key="k1") == 0
    assert _cli(org, tmp_path, _digest(date="2026-10-21", title="Rob again", follow_ups=[]), key="k2") == 0
    text = (org / "worklog.org").read_text()
    assert "*** TODO draft the CSV proofs runbook (2) - @Nick - [[" in text
    st = State.load(Paths(org).state_file)
    assert "worklog.org::*draft the CSV proofs runbook (2) - @Nick" in st.ledger
    assert "worklog.org::*draft the CSV proofs runbook - @Nick" in st.ledger
    assert json.loads((tmp_path / "k2.json").read_text())["action_items"][0]["text"] == "draft the CSV proofs runbook (2)"


def test_jira_inherited_from_hand_heading(org, tmp_path):
    wl = org / "worklog.org"
    wl.write_text(wl.read_text().replace("** Rob 1-1\n", "** Rob 1-1 - [[https://rmt.atlassian.net/browse/DEV-77][DEV-77]]\n"))
    old = time.time() - 3600
    os.utime(wl, (old, old))
    assert _cli(org, tmp_path, _digest()) == 0
    st = State.load(Paths(org).state_file)
    e = st.ledger["worklog.org::*send the sample CSV file - @Rob"]
    assert e["jira"] == "DEV-77" and e["jira_source"] == "heading"
    assert st.ledger["worklog.org::*draft the CSV proofs runbook - @Nick"]["jira_source"] == "digest"
    _, by = _rows_by_target(org)
    assert "[[https://rmt.atlassian.net/browse/DEV-77][DEV-77]] [[file:" in by["worklog.org::*send the sample CSV file - @Rob"].cells[2]
    assert "*** send the sample CSV file - @Rob :waiting_on:auto:" in wl.read_text()  # headline unchanged


def test_archive_month_row_links_archive_file(org, tmp_path):
    assert _cli(org, tmp_path, _digest(date="2026-09-15", title="Sept planning", attendees=["Nick"], follow_ups=[])) == 0
    _, by = _rows_by_target(org)
    r = by["2026/2026-09-worklog.org::*draft the CSV proofs runbook - @Nick"]
    assert r.cells[2].endswith("[[file:2026/2026-09-worklog.org::*draft the CSV proofs runbook - @Nick][↗]]")
    assert State.load(Paths(org).state_file).ledger["2026/2026-09-worklog.org::*draft the CSV proofs runbook - @Nick"]["file"] == "2026/2026-09-worklog.org"


def test_deleted_heading_is_recreated_at_end(org, tmp_path):
    ai = org / "action-items.org"
    ai.write_text("\n".join(ledger.PREAMBLE + ["* Commitment", ledger.HEADER, ledger.RULE, ""]) + "\n")
    old = time.time() - 3600
    os.utime(ai, (old, old))
    assert _cli(org, tmp_path, _digest()) == 0
    lines = OrgDoc.load(ai).lines
    assert lines[:3] == ledger.PREAMBLE and lines.count("* Commitment") == 1
    assert lines.index("* Commitment") < lines.index("* Waiting-on")
    assert len([r for r in ledger.rows(OrgDoc.load(ai)) if r.category == "commitment"]) == 2


def test_ledger_guard_trips_independently(org, tmp_path):
    ai = org / "action-items.org"
    ai.write_text("\n".join(ledger.PREAMBLE) + "\n")
    ai.touch()
    assert _cli(org, tmp_path, _digest()) == 3
    assert ":auto:" not in (org / "worklog.org").read_text()


def test_digest_with_no_items_creates_no_ledger(org, tmp_path):
    assert _cli(org, tmp_path, _digest(action_items=[], follow_ups=[], open_questions=[])) == 0
    assert not (org / "action-items.org").exists()
