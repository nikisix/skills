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
CHATS = json.loads((FIX / "m365-chats.json").read_text())
RX_MEETING = {  # a recurring series Jeremy organizes: startDateTime is the series start, not this occurrence
    "id": "MSpqZXJlbXkqMCoqMTk6bWVldGluZ19VbmhVY205dQ",
    "subject": "Rx Tron Discussion",
    "startDateTime": "2026-09-01T18:00:00.0000000Z",
    "endDateTime": "2026-09-01T18:30:00.0000000Z",
    "joinWebUrl": "https://teams.microsoft.com/l/meetup-join/rx",
}
MEETING_BY_JOIN_URL = {RX_MEETING["joinWebUrl"]: RX_MEETING, MEETINGS[0]["joinWebUrl"]: MEETINGS[0]}
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
        if args[:3] == ["teams", "chat", "list"]:
            return CHATS
        if args[:3] == ["teams", "meeting", "get"]:
            url = args[args.index("--joinUrl") + 1]
            if url not in MEETING_BY_JOIN_URL:
                raise RuntimeError(f"m365 teams meeting get failed: no meeting for {url}")
            return MEETING_BY_JOIN_URL[url]
        raise AssertionError(f"unexpected m365 call: {args}")

    def download(meeting_id, transcript_id, out: Path):
        calls.append(["download", meeting_id, transcript_id, str(out)])
        out.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<v Nick>hi\n")

    monkeypatch.setattr(fetch_teams, "m365", m365)
    monkeypatch.setattr(fetch_teams, "download", download)
    return calls


@pytest.fixture
def no_chats(monkeypatch):
    monkeypatch.setattr(fetch_teams, "list_meeting_chats", lambda: [])


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


def test_writes_state_after_download(org_dir, fake_m365, no_chats):
    paths = Paths(org_dir)
    state = State.load(paths.state_file)
    files = fetch_teams.fetch(paths, state, NOW)
    assert files == [paths.inbox / "2026-10-21-1500-csv-proofs-sync.vtt"]
    assert files[0].read_text().startswith("WEBVTT")
    key = f"teams:{MEETINGS[0]['id']}:{TRANSCRIPTS[0]['id']}"
    assert State.load(paths.state_file).fetched[key] == {"file": files[0].name, "subject": "CSV Proofs Sync"}
    assert State.load(paths.state_file).last_teams_poll == NOW.isoformat()


def test_skips_fetched_keys(org_dir, fake_m365, no_chats):
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


@pytest.fixture
def empty_calendar(monkeypatch):
    monkeypatch.setattr(fetch_teams, "list_meetings", lambda start, end: [])


def test_chats_route_fetches_a_meeting_i_did_not_organize(org_dir, fake_m365, empty_calendar):
    paths = Paths(org_dir)
    state = State.load(paths.state_file)
    files = fetch_teams.fetch(paths, state, NOW)
    # every meeting chat touched in the window lands; the series occurrence is named from the
    # transcript's date (19:02 UTC = 12:02 Pacific), not from the series start in September
    assert sorted(f.name for f in files) == ["2026-10-21-1202-rx-tron-discussion.vtt", "2026-10-21-1531-csv-proofs-sync.vtt"]
    key = f"teams:{RX_MEETING['id']}:MSMjMCMjUlgtVFJBTlNDUklQVA"
    assert State.load(paths.state_file).fetched[key] == {"file": "2026-10-21-1202-rx-tron-discussion.vtt", "subject": "Rx Tron Discussion"}
    listing = next(c for c in fake_m365 if c[:3] == ["teams", "chat", "list"])
    assert listing[listing.index("--type") + 1] == "meeting"


def test_chats_route_skips_chats_outside_the_window(org_dir, fake_m365, empty_calendar):
    paths = Paths(org_dir)
    fetch_teams.fetch(paths, State.load(paths.state_file), NOW)
    resolved = [c[c.index("--joinUrl") + 1] for c in fake_m365 if c[:3] == ["teams", "meeting", "get"]]
    assert "https://teams.microsoft.com/l/meetup-join/old" not in resolved  # last updated 2026-09-01
    assert RX_MEETING["joinWebUrl"] in resolved


def test_chats_route_warns_and_continues_when_a_meeting_cannot_be_resolved(org_dir, fake_m365, empty_calendar, capsys):
    paths = Paths(org_dir)
    MEETING_BY_JOIN_URL.pop(MEETINGS[0]["joinWebUrl"])
    try:
        files = fetch_teams.fetch(paths, State.load(paths.state_file), NOW)
    finally:
        MEETING_BY_JOIN_URL[MEETINGS[0]["joinWebUrl"]] = MEETINGS[0]
    assert [f.name for f in files] == ["2026-10-21-1202-rx-tron-discussion.vtt"]
    assert "CSV Proofs Sync" in capsys.readouterr().err


def test_chats_route_dedups_against_the_calendar_route(org_dir, fake_m365):
    paths = Paths(org_dir)
    files = fetch_teams.fetch(paths, State.load(paths.state_file), NOW)
    # the CSV Proofs meeting is on the calendar and in a meeting chat: downloaded once, under its calendar name
    assert sorted(f.name for f in files) == ["2026-10-21-1202-rx-tron-discussion.vtt", "2026-10-21-1500-csv-proofs-sync.vtt"]
    assert sum(1 for c in fake_m365 if c[0] == "download") == 2


def test_chat_listing_failure_names_the_scope_and_keeps_fetched_keys(org_dir, fake_m365, monkeypatch):
    paths = Paths(org_dir)
    real = fetch_teams.m365

    def m365(args):
        if args[:3] == ["teams", "chat", "list"]:
            raise RuntimeError("m365 teams chat list failed: Error: Missing scope permissions on the request. API requires one of "
                               "'Chat.ReadBasic, Chat.Read, Chat.ReadWrite'. Scopes on the request 'Calendars.Read, OnlineMeetings.Read'")
        return real(args)

    monkeypatch.setattr(fetch_teams, "m365", m365)
    state = State.load(paths.state_file)
    with pytest.raises(RuntimeError, match="Chat.ReadBasic"):
        fetch_teams.fetch(paths, state, NOW)
    saved = State.load(paths.state_file)
    assert f"teams:{MEETINGS[0]['id']}:{TRANSCRIPTS[0]['id']}" in saved.fetched  # the calendar download is remembered
    assert saved.last_teams_poll is None  # the window is not advanced past the days the chats route missed


def test_naive_since_from_the_cli_flag_is_treated_as_utc(org_dir, fake_m365, empty_calendar):
    paths = Paths(org_dir)
    # argparse hands fetch a naive datetime for `--since 2026-10-21`; the chats window must still work
    files = fetch_teams.fetch(paths, State.load(paths.state_file), NOW, since=datetime(2026, 10, 21))
    assert "2026-10-21-1202-rx-tron-discussion.vtt" in [f.name for f in files]


def test_chats_without_join_urls_are_reported_not_silently_skipped(org_dir, fake_m365, empty_calendar, monkeypatch, capsys):
    paths = Paths(org_dir)
    bare = [{k: v for k, v in c.items() if k != "onlineMeetingInfo"} for c in CHATS]
    monkeypatch.setattr(fetch_teams, "list_meeting_chats", lambda: bare)
    assert fetch_teams.fetch(paths, State.load(paths.state_file), NOW) == []
    err = capsys.readouterr().err
    assert "onlineMeetingInfo.joinWebUrl" in err and str(len(bare)) in err
