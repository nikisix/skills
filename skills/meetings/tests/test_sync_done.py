import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

import ledger
import sync_done
from config import Paths
from orgfile import OrgDoc, headline_parts
from state import State

NOW = datetime(2026, 10, 28, 7, 12)
ARGS = ["--now", NOW.isoformat()]
J = "https://rmt.atlassian.net/browse/"


def _link(key):
    return f"[[{J}{key}][{key}]]"


WORKLOG = f"""* <2026-10-22 Thu>

** Rob 1-1
*** meetings (auto) 2026-10-22T06:31 · source: slack · attendees: Nick, Rob
   - summary
   - Open: why?
*** TODO Ship it - @Nick :commitment:auto:
    DEADLINE: <2026-10-24 Sat>
*** send the sample - @Rob :waiting_on:auto:
*** DONE already - @Nick :commitment:auto:
** CSV Proofs - @Nick - {_link("DEV-10173")}
*** TODO under csv - @Nick :commitment:auto:
*** TODO keyed - @Nick - {_link("DEV-7")} :commitment:auto:

* TODO
"""

TRON = f"""* In Progress
** Trontology upgrade - @David - {_link("DEV-10716")}
*** sync the synonyms table - {_link("DEV-10718")} :in_progress:
*** untagged sub - {_link("DEV-6")} :auto:
* To Do
** Ship it - @Nick - {_link("DEV-5")}
*** notes
    - detail
** Dup - {_link("DEV-9")}
*** child dup - {_link("DEV-9")}
** Seven - {_link("DEV-7")}
** Proofs - {_link("DEV-10173")}
* Needs Refinement
* In Review
* Ready for QA
* In QA
* Accepted
* Closed
* Reopen
* Blocked (do not sync)
* Maybe (do not sync)
"""

MARKER = "worklog.org::*meetings (auto) 2026-10-22T06:31 · source: slack · attendees: Nick, Rob"


def _entry(locator, headline, text, *, kind="headline", jira=None, category="commitment", file="worklog.org", day="2026-10-22", done_at=None):
    return {"locator": locator, "key": f"k|action-items.org|{category}/{locator}", "file": file, "day": day, "kind": kind,
            "headline": headline, "text": text, "jira": jira, "jira_source": "digest" if jira else None,
            "category": category, "done_at": done_at}


def _row(text, target, done, jira=None, category="commitment"):
    return category, ledger.row_line(done, "", "@Nick", ledger.what_cell(text, jira, target))


def _age(path):
    old = time.time() - 3600
    os.utime(path, (old, old))


def _setup(org_dir, rows, entries, worklog=WORKLOG, tron=TRON, tron_path=None):
    (org_dir / "worklog.org").write_text(worklog)
    _age(org_dir / "worklog.org")
    tp = tron_path or (org_dir / "tron-tasks.org")
    tp.write_text(tron)
    _age(tp)
    by_cat = {}
    for cat, line in rows:
        by_cat.setdefault(cat, []).append(line)
    lines = list(ledger.PREAMBLE)
    for cat, heading in ledger.CATEGORIES:
        lines += [f"* {heading}", ledger.HEADER, ledger.RULE, *by_cat.get(cat, []), ""]
    (org_dir / "action-items.org").write_text("\n".join(lines) + "\n")
    _age(org_dir / "action-items.org")
    st = State.load(Paths(org_dir).state_file)
    for e in entries:
        st.ledger[e["locator"]] = e
    st.save()
    return Paths(org_dir)


SHIP = "worklog.org::*Ship it - @Nick"


def _ship(done="x", jira="DEV-5"):
    return [_row("Ship it", SHIP, done, jira)], [_entry(SHIP, "Ship it - @Nick", "Ship it", jira=jira)]


def _bucket_of(doc, idx):
    for j in range(idx, -1, -1):
        if doc.level_at(j) == 1:
            return doc.lines[j]
    return None


def _tron_idx(doc, key):
    return next(i for i, l in enumerate(doc.lines) if key in l and doc.level_at(i))


def test_x_flips_worklog_and_moves_task_to_in_review(org_dir):
    rows, entries = _ship()
    paths = _setup(org_dir, rows, entries)
    assert sync_done.main(ARGS) == 0
    wl = OrgDoc.load(paths.worklog)
    i = wl.lines.index("*** DONE Ship it - @Nick :commitment:auto:")
    assert wl.lines[i + 1] == "    CLOSED: [2026-10-28 Wed 07:12] DEADLINE: <2026-10-24 Sat>"
    tr = OrgDoc.load(paths.tron_tasks)
    t = _tron_idx(tr, "DEV-5")
    assert _bucket_of(tr, t) == "* In Review" and tr.lines[t + 1 : t + 3] == ["*** notes", "    - detail"]
    assert "* In Review" in tr.lines and tr.lines.count("** Ship it - @Nick - " + _link("DEV-5")) == 1
    assert State.load(paths.state_file).ledger[SHIP]["done_at"] == "2026-10-28T07:12"


def test_x_on_subtask_sets_in_review_tag(org_dir):
    loc = "worklog.org::*under csv - @Nick"
    paths = _setup(org_dir, [_row("under csv", loc, "x")], [_entry(loc, "under csv - @Nick", "under csv", jira="DEV-10718")])
    assert sync_done.main(ARGS) == 0
    tr = OrgDoc.load(paths.tron_tasks)
    assert headline_parts(tr.lines[_tron_idx(tr, "DEV-10718")])[3] == ["in_review"]


def test_subtask_without_status_tag_gets_one(org_dir):
    loc = "worklog.org::*under csv - @Nick"
    paths = _setup(org_dir, [_row("under csv", loc, "qa")], [_entry(loc, "under csv - @Nick", "under csv", jira="DEV-6")])
    assert sync_done.main(ARGS) == 0
    tr = OrgDoc.load(paths.tron_tasks)
    assert headline_parts(tr.lines[_tron_idx(tr, "DEV-6")])[3] == ["in_qa", "auto"]


@pytest.mark.parametrize("word,bucket", [(w, b) for w, (b, _) in sync_done.DONE_WORDS.items()])
def test_bucket_word_moves_task(org_dir, word, bucket):
    rows, entries = _ship(done=word)
    paths = _setup(org_dir, rows, entries)
    assert sync_done.main(ARGS) == 0
    tr = OrgDoc.load(paths.tron_tasks)
    assert _bucket_of(tr, _tron_idx(tr, "DEV-5")) == f"* {bucket}"
    assert "*** DONE Ship it - @Nick :commitment:auto:" in OrgDoc.load(paths.worklog).lines


def test_blocked_on_subtask_logs_and_keeps_tag(org_dir, capsys):
    loc = "worklog.org::*under csv - @Nick"
    paths = _setup(org_dir, [_row("under csv", loc, "blocked")], [_entry(loc, "under csv - @Nick", "under csv", jira="DEV-10718")])
    assert sync_done.main(ARGS) == 0
    assert "no sub-task tag" in capsys.readouterr().out
    tr = OrgDoc.load(paths.tron_tasks)
    assert tr.lines[_tron_idx(tr, "DEV-10718")].endswith(":in_progress:")
    assert "*** DONE under csv - @Nick :commitment:auto:" in OrgDoc.load(paths.worklog).lines


def test_unknown_word_leaves_tron(org_dir, capsys):
    rows, entries = _ship(done="someday")
    paths = _setup(org_dir, rows, entries)
    assert sync_done.main(ARGS) == 0
    assert "unknown DONE word" in capsys.readouterr().out
    assert OrgDoc.load(paths.tron_tasks).text == TRON
    assert "*** DONE Ship it - @Nick :commitment:auto:" in OrgDoc.load(paths.worklog).lines


def test_key_from_what_cell_and_from_headline(org_dir):
    loc2 = "worklog.org::*keyed - @Nick"
    rows = [("commitment", ledger.row_line("x", "", "@Nick", f"Ship it DEV-9 [[file:{SHIP}][↗]]")),
            _row("keyed", loc2, "x")]
    entries = [_entry(SHIP, "Ship it - @Nick", "Ship it"),
               _entry(loc2, "keyed - @Nick - " + _link("DEV-7"), "keyed")]
    paths = _setup(org_dir, rows, entries)
    assert sync_done.main(ARGS) == 0
    tr = OrgDoc.load(paths.tron_tasks)
    assert _bucket_of(tr, _tron_idx(tr, "DEV-9")) == "* In Review"
    assert _bucket_of(tr, _tron_idx(tr, "DEV-7")) == "* In Review"


def test_key_from_ancestor_heading(org_dir):
    loc = "worklog.org::*under csv - @Nick"
    paths = _setup(org_dir, [_row("under csv", loc, "x")], [_entry(loc, "under csv - @Nick", "under csv")])
    assert sync_done.main(ARGS) == 0
    tr = OrgDoc.load(paths.tron_tasks)
    assert _bucket_of(tr, _tron_idx(tr, "DEV-10173")) == "* In Review"


def test_open_question_bullet_resolved(org_dir):
    loc = MARKER + "::Open: why?"
    rows = [("open_question", ledger.row_line("x", "", "", ledger.what_cell("why?", None, MARKER)))]
    paths = _setup(org_dir, rows, [_entry(loc, MARKER.split("*", 1)[1], "why?", kind="bullet", category="open_question")])
    assert sync_done.main(ARGS) == 0
    wl = OrgDoc.load(paths.worklog)
    assert "   - Resolved [2026-10-28]: why?" in wl.lines and "   - Open: why?" not in wl.lines
    assert State.load(paths.state_file).ledger[loc]["done_at"] == "2026-10-28T07:12"


def test_oq_row_with_rewritten_text_is_untracked(org_dir):
    loc = MARKER + "::Open: why?"
    rows = [("open_question", ledger.row_line("x", "", "", ledger.what_cell("a completely different question", None, MARKER)))]
    paths = _setup(org_dir, rows, [_entry(loc, MARKER.split("*", 1)[1], "why?", kind="bullet", category="open_question")])
    assert sync_done.main(ARGS) == 2
    assert OrgDoc.load(paths.worklog).text == WORKLOG
    assert State.load(paths.state_file).ledger[loc]["done_at"] is None


def test_worklog_not_found_skips_tron_too(org_dir, capsys):
    rows, entries = _ship()
    paths = _setup(org_dir, rows, entries, worklog=WORKLOG.replace("Ship it - @Nick", "Ship it now - @Nick"))
    assert sync_done.main(ARGS) == 2
    assert "worklog item not found" in capsys.readouterr().out
    assert OrgDoc.load(paths.tron_tasks).text == TRON
    assert State.load(paths.state_file).ledger[SHIP]["done_at"] is None


def test_already_done_headline_only_gets_closed(org_dir):
    loc = "worklog.org::*already - @Nick"
    paths = _setup(org_dir, [_row("already", loc, "x")], [_entry(loc, "already - @Nick", "already")])
    assert sync_done.main(ARGS) == 0
    wl = OrgDoc.load(paths.worklog)
    i = wl.lines.index("*** DONE already - @Nick :commitment:auto:")
    assert wl.lines[i + 1] == "    CLOSED: [2026-10-28 Wed 07:12]"
    assert wl.lines.count("*** DONE already - @Nick :commitment:auto:") == 1


def test_duplicate_key_acts_on_first_match(org_dir, capsys):
    rows, entries = _ship(jira="DEV-9")
    paths = _setup(org_dir, rows, entries)
    assert sync_done.main(ARGS) == 0
    tr = OrgDoc.load(paths.tron_tasks)
    i = tr.lines.index("** Dup - " + _link("DEV-9"))
    assert _bucket_of(tr, i) == "* In Review" and tr.lines[i + 1] == "*** child dup - " + _link("DEV-9")
    assert "also on tron-tasks.org" in capsys.readouterr().out


def test_second_run_is_noop(org_dir):
    rows, entries = _ship()
    paths = _setup(org_dir, rows, entries)
    assert sync_done.main(ARGS) == 0
    wl, tr = paths.worklog.read_bytes(), paths.tron_tasks.read_bytes()
    assert sync_done.main(ARGS) == 2
    assert (paths.worklog.read_bytes(), paths.tron_tasks.read_bytes()) == (wl, tr)


def test_guard_trips_on_tron_or_worklog(org_dir):
    rows, entries = _ship()
    paths = _setup(org_dir, rows, entries)
    paths.tron_tasks.touch()
    assert sync_done.main(ARGS) == 3
    assert OrgDoc.load(paths.worklog).text == WORKLOG and OrgDoc.load(paths.tron_tasks).text == TRON
    assert State.load(paths.state_file).ledger[SHIP]["done_at"] is None


def test_symlinked_tron_is_written_through(org_dir, tmp_path):
    real = tmp_path / "real.org"
    rows, entries = _ship()
    paths = _setup(org_dir, rows, entries, tron_path=real)
    (org_dir / "tron-tasks.org").symlink_to(real)
    assert sync_done.main(ARGS) == 0
    assert (org_dir / "tron-tasks.org").is_symlink()
    assert _bucket_of(OrgDoc.load(real), _tron_idx(OrgDoc.load(real), "DEV-5")) == "* In Review"
    assert str(real) in State.load(paths.state_file).own_saves


def test_dry_run_prints_edits_and_changes_nothing(org_dir, capsys):
    rows, entries = _ship()
    paths = _setup(org_dir, rows, entries)
    assert sync_done.main([*ARGS, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "-> *** DONE Ship it - @Nick :commitment:auto:" in out and "-> * In Review" in out
    assert OrgDoc.load(paths.worklog).text == WORKLOG and OrgDoc.load(paths.tron_tasks).text == TRON
    assert State.load(paths.state_file).ledger[SHIP]["done_at"] is None


def test_log_lines_name_file_and_line(org_dir, capsys):
    rows, entries = _ship()
    paths = _setup(org_dir, rows, entries)
    assert sync_done.main(ARGS) == 0
    out = capsys.readouterr().out.splitlines()
    assert "done-sync: worklog.org:7 *** TODO Ship it - @Nick :commitment:auto: -> *** DONE Ship it - @Nick :commitment:auto:" in out
    assert any(l.startswith("done-sync: tron-tasks.org:6 ** Ship it - @Nick - [[") and l.endswith("-> * In Review") for l in out)


def test_zero_edit_row_still_gets_done_at(org_dir):
    """Nick flipped the headline by hand (nvim wrote CLOSED too) and ticked the row: nothing to edit,
    but the entry must close or the row is re-examined every morning."""
    loc = "worklog.org::*already - @Nick"
    wl = WORKLOG.replace("*** DONE already - @Nick :commitment:auto:\n", "*** DONE already - @Nick :commitment:auto:\n    CLOSED: [2026-10-21 Wed 09:12]\n")
    paths = _setup(org_dir, [_row("already", loc, "x")], [_entry(loc, "already - @Nick", "already")], worklog=wl)
    assert sync_done.main(ARGS) == 0
    assert OrgDoc.load(paths.worklog).text == wl
    assert State.load(paths.state_file).ledger[loc]["done_at"] == "2026-10-28T07:12"
    assert sync_done.main(ARGS) == 2


def test_hand_added_key_on_headline_still_matches_and_feeds_tron(org_dir):
    wl = WORKLOG.replace("*** TODO Ship it - @Nick :commitment:auto:", f"*** TODO Ship it - @Nick - {_link('DEV-5')} :commitment:auto:")
    paths = _setup(org_dir, [_row("Ship it", SHIP, "x")], [_entry(SHIP, "Ship it - @Nick", "Ship it")], worklog=wl)
    assert sync_done.main(ARGS) == 0
    assert f"*** DONE Ship it - @Nick - {_link('DEV-5')} :commitment:auto:" in OrgDoc.load(paths.worklog).lines
    tr = OrgDoc.load(paths.tron_tasks)
    assert _bucket_of(tr, _tron_idx(tr, "DEV-5")) == "* In Review"
