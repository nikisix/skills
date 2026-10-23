import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import fetch_teams
from config import Paths
from state import State

FIX = Path(__file__).parent / "fixtures"
MEETINGS = json.loads((FIX / "m365-meetings.json").read_text())
TRANSCRIPTS = json.loads((FIX / "m365-transcripts.json").read_text())
NOW = datetime(2026, 10, 22, 6, 30, tzinfo=timezone.utc)


@pytest.fixture
def fake_m365(monkeypatch):
    calls: list[list[str]] = []

    def m365(args):
        calls.append(list(args))
        if args[:3] == ["teams", "meeting", "list"]:
            return MEETINGS
        if args[:4] == ["teams", "meeting", "transcript", "list"]:
            mid = args[args.index("-m") + 1]
            return [t for t in TRANSCRIPTS if t["meetingId"] == mid]
        raise AssertionError(f"unexpected m365 call: {args}")

    def download(meeting_id, transcript_id, out: Path):
        calls.append(["download", meeting_id, transcript_id, str(out)])
        out.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<v Nick>hi\n")

    monkeypatch.setattr(fetch_teams, "m365", m365)
    monkeypatch.setattr(fetch_teams, "download", download)
    return calls


def test_inbox_name_localtime_slug():
    assert fetch_teams.inbox_name(MEETINGS[0]) == "2026-10-21-1500-csv-proofs-sync.vtt"
    assert fetch_teams.inbox_name(MEETINGS[1]) == "2026-10-20-0930-rob-nick-1-1.vtt"


def test_first_run_window_14_days(org_dir, fake_m365):
    paths = Paths(org_dir)
    state = State.load(paths.state_file)
    fetch_teams.fetch(paths, state, NOW)
    listing = next(c for c in fake_m365 if c[:3] == ["teams", "meeting", "list"])
    assert "--isOrganizer" in listing
    # m365 rejects fractional seconds / +00:00 offsets: it wants 2026-10-08T06:30:00Z
    assert listing[listing.index("--startDateTime") + 1] == "2026-10-08T06:30:00Z"
    assert listing[listing.index("--endDateTime") + 1] == "2026-10-22T06:30:00Z"


def test_writes_state_after_download(org_dir, fake_m365):
    paths = Paths(org_dir)
    state = State.load(paths.state_file)
    files = fetch_teams.fetch(paths, state, NOW)
    assert files == [paths.inbox / "2026-10-21-1500-csv-proofs-sync.vtt"]
    assert files[0].read_text().startswith("WEBVTT")
    key = f"teams:{MEETINGS[0]['id']}:{TRANSCRIPTS[0]['id']}"
    assert State.load(paths.state_file).fetched[key] == {"file": files[0].name, "subject": "CSV Proofs Sync"}
    assert State.load(paths.state_file).last_teams_poll == NOW.isoformat()


def test_skips_fetched_keys(org_dir, fake_m365):
    paths = Paths(org_dir)
    state = State.load(paths.state_file)
    state.fetched[f"teams:{MEETINGS[0]['id']}:{TRANSCRIPTS[0]['id']}"] = {"file": "x.vtt", "subject": "CSV Proofs Sync"}
    assert fetch_teams.fetch(paths, state, NOW) == []
    assert not any(c[0] == "download" for c in fake_m365)


def test_second_run_window_starts_at_last_poll(org_dir, fake_m365):
    paths = Paths(org_dir)
    state = State.load(paths.state_file)
    state.last_teams_poll = (NOW - timedelta(days=1)).isoformat()
    fetch_teams.fetch(paths, state, NOW)
    listing = next(c for c in fake_m365 if c[:3] == ["teams", "meeting", "list"])
    # two-day overlap: a meeting still running at the last poll had no transcript yet
    assert listing[listing.index("--startDateTime") + 1] == "2026-10-19T06:30:00Z"


def test_dry_run_downloads_nothing(org_dir, fake_m365, capsys):
    paths = Paths(org_dir)
    state = State.load(paths.state_file)
    assert fetch_teams.fetch(paths, state, NOW, dry_run=True) == []
    assert not any(c[0] == "download" for c in fake_m365)
    assert "2026-10-21-1500-csv-proofs-sync.vtt" in capsys.readouterr().out
    assert not paths.state_file.exists()
