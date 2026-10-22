import json
import shutil
from pathlib import Path

import suggest
from config import Paths

FIX = Path(__file__).parent / "fixtures"


def _digest(**over):
    d = json.loads((FIX / "digest-good.json").read_text())
    d.update(over)
    return d


def _dj(tmp_path, d):
    p = tmp_path / "d.json"
    p.write_text(json.dumps(d))
    return p


def test_candidates_are_ticket_worthy_without_jira():
    d = _digest(action_items=[
        {"text": "a", "owner": "Nick", "due": None, "jira": "DEV-1", "ticket_worthy": True},
        {"text": "b", "owner": "Rob", "due": None, "jira": None, "ticket_worthy": True},
        {"text": "c", "owner": None, "due": None, "jira": None, "ticket_worthy": False},
    ])
    assert [c["text"] for c in suggest.candidates(d)] == ["b"]


def test_creates_file_with_sections(org_dir, tmp_path):
    rc = suggest.main([str(_dj(tmp_path, _digest()))])
    assert rc == 0
    text = (org_dir / "suggested-tron-tasks.org").read_text()
    lines = text.splitlines()
    assert lines[0] == "* Suggested"
    assert "* arXiv" in lines
    i = lines.index("** build a proof-diff tool for CSV exports - @Nick :auto:")
    assert lines[i + 1] == "   - source: [[file:worklog.org::*Rob 1:1][2026-10-20 Rob 1:1]]"
    assert lines[i + 2] == "   - why: Status on accuracy work; Rob wants the CSV proofs runbook by Friday."
    assert i < lines.index("* arXiv")


def test_appends_under_suggested_not_arxiv(org_dir, tmp_path):
    f = org_dir / "suggested-tron-tasks.org"
    f.write_text("* Suggested\n\n** existing idea - @Nick\n\n* arXiv\n\n** some paper\n")
    suggest.main([str(_dj(tmp_path, _digest()))])
    lines = f.read_text().splitlines()
    new = lines.index("** build a proof-diff tool for CSV exports - @Nick :auto:")
    assert lines.index("** existing idea - @Nick") < new < lines.index("* arXiv") < lines.index("** some paper")


def test_dedup_against_tron_tasks(org_dir, tmp_path):
    shutil.copy(FIX / "tron-tasks-sample.org", org_dir / "tron-tasks.org")
    assert "build a proof-diff tool for csv exports" in suggest.existing_headlines(Paths(org_dir))
    rc = suggest.main([str(_dj(tmp_path, _digest()))])
    assert rc == 2
    assert "proof-diff" not in (org_dir / "suggested-tron-tasks.org").read_text()


def test_skips_items_with_jira_key(org_dir, tmp_path):
    d = _digest(action_items=[
        {"text": "already ticketed", "owner": "Nick", "due": None, "jira": "DEV-5", "ticket_worthy": True}])
    assert suggest.main([str(_dj(tmp_path, d))]) == 2
    assert "already ticketed" not in (org_dir / "suggested-tron-tasks.org").read_text()


def test_owner_defaults_to_me():
    d = _digest()
    item = {"text": "Do the thing", "owner": None, "due": None, "jira": None, "ticket_worthy": True}
    assert suggest.render(item, d)[0] == "** Do the thing - @Nick :auto:"


def test_rerun_noop(org_dir, tmp_path):
    dj = _dj(tmp_path, _digest())
    assert suggest.main([str(dj)]) == 0
    before = (org_dir / "suggested-tron-tasks.org").read_bytes()
    assert suggest.main([str(dj)]) == 2
    assert (org_dir / "suggested-tron-tasks.org").read_bytes() == before


def test_dry_run_writes_nothing(org_dir, tmp_path, capsys):
    assert suggest.main([str(_dj(tmp_path, _digest())), "--dry-run"]) == 0
    assert "** build a proof-diff tool" in capsys.readouterr().out
    assert not (org_dir / "suggested-tron-tasks.org").exists()


def test_source_link_uses_landed_heading():
    d = _digest(landed={"file": "2026/2026-09-worklog.org", "heading": "Rob 1-1"})
    item = {"text": "x", "owner": "Nick", "due": None, "jira": None, "ticket_worthy": True}
    assert suggest.render(item, d)[1] == "   - source: [[file:2026/2026-09-worklog.org::*Rob 1-1][2026-10-20 Rob 1-1]]"


def test_render_sanitizes_newlines():
    d = _digest(summary="First.\n* second")
    item = {"text": "* fix\nthis", "owner": "Nick", "due": None, "jira": None, "ticket_worthy": True}
    out = suggest.render(item, d)
    assert out[0] == "** fix this - @Nick :auto:" and out[2] == "   - why: First."
