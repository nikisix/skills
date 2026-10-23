from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import fetch_slack
from config import Paths
from state import State

LA = ZoneInfo("America/Los_Angeles")
DAY = date(2026, 10, 21)
TODAY = date(2026, 10, 22)
USERS = {"U1": "Nick Tomasino", "U2": "Rob Smith", "U3": "Lars Berg", "UB": "Jira Bot"}
CONVS = [
    {"id": "C1", "name": "tron", "is_channel": True, "is_im": False, "is_mpim": False},
    {"id": "C2", "name": "random", "is_channel": True, "is_im": False, "is_mpim": False},
    {"id": "D1", "is_im": True, "is_mpim": False, "user": "U2"},
    {"id": "G1", "is_im": False, "is_mpim": True, "name": "mpdm-nick--rob--lars-1"},
]


def ts(d: date, h: int, m: int) -> str:
    return f"{datetime(d.year, d.month, d.day, h, m, tzinfo=LA).timestamp():.6f}"


HISTORY = {
    "C1": [
        {"type": "message", "user": "U2", "text": "<@U1> can you look at the proof diff for <https://rmt.atlassian.net/browse/DEV-10173|DEV-10173>?", "ts": ts(DAY, 9, 0), "thread_ts": ts(DAY, 9, 0), "reply_count": 1},
        {"type": "message", "user": "UB", "subtype": "bot_message", "text": "DEV-1 transitioned", "ts": ts(DAY, 9, 1)},
        {"type": "message", "user": "U3", "subtype": "channel_join", "text": "<@U3> has joined", "ts": ts(DAY, 9, 2)},
        {"type": "message", "user": "U1", "text": "yes, by Friday. see <https://example.com/doc>", "ts": ts(DAY, 9, 5)},
        {"type": "message", "user": "U3", "text": "I'll send the sample file", "ts": ts(DAY, 9, 7)},
        {"type": "message", "user": "U3", "text": "yesterday's message", "ts": ts(date(2026, 10, 20), 9, 7)},
    ],
    "D1": [
        {"type": "message", "user": "U2", "text": "quick one", "ts": ts(DAY, 14, 0)},
        {"type": "message", "user": "U1", "text": "sure", "ts": ts(DAY, 14, 1)},
    ],
    "G1": [
        {"type": "message", "user": "U2", "text": "roadmap sync Friday?", "ts": ts(DAY, 15, 0)},
        {"type": "message", "user": "U3", "text": "works for me", "ts": ts(DAY, 15, 1)},
        {"type": "message", "user": "U1", "text": "booked", "ts": ts(DAY, 15, 2)},
    ],
}
REPLIES = {("C1", ts(DAY, 9, 0)): [
    HISTORY["C1"][0],
    {"type": "message", "user": "U2", "text": "thread reply here", "ts": ts(DAY, 9, 3), "thread_ts": ts(DAY, 9, 0)},
]}
MEMBERS = {"G1": ["U1", "U2", "U3"], "C1": ["U1", "U2", "U3", "UB"], "D1": ["U1", "U2"]}


class FakeClient:
    def __init__(self):
        self.calls = []

    def me(self):
        return "U1"

    def conversations(self):
        return CONVS

    def members(self, channel):
        return MEMBERS[channel]

    def history(self, channel, oldest, latest):
        self.calls.append(("history", channel, oldest, latest))
        return [m for m in HISTORY.get(channel, []) if oldest <= float(m["ts"]) < latest]

    def replies(self, channel, thread_ts):
        return REPLIES.get((channel, thread_ts), [])

    def user_name(self, uid):
        return USERS.get(uid, uid)


CFG = fetch_slack.SlackConfig(dms=True, group_dms=True, channels=["tron"], min_messages=3)


def test_day_window_la():
    oldest, latest = fetch_slack.day_window(DAY)
    assert datetime.fromtimestamp(oldest, LA).isoformat() == "2026-10-21T00:00:00-07:00"
    assert datetime.fromtimestamp(latest, LA).isoformat() == "2026-10-22T00:00:00-07:00"


def test_select_conversations():
    assert [c["id"] for c in fetch_slack.select_conversations(CONVS, CFG)] == ["C1", "D1", "G1"]
    assert [c["id"] for c in fetch_slack.select_conversations(CONVS, fetch_slack.SlackConfig(dms=False, group_dms=False, channels=[]))] == []


def test_titles():
    c = FakeClient()
    assert fetch_slack.conversation_title(CONVS[0], c) == "Slack #tron"
    assert fetch_slack.conversation_title(CONVS[2], c) == "Slack DM Rob Smith"
    assert fetch_slack.conversation_title(CONVS[3], c) == "Slack DM Rob Smith, Lars Berg"


def test_render_day_rewrites_and_skips_noise():
    c = FakeClient()
    msgs = c.history("C1", *fetch_slack.day_window(DAY))
    speakers, text = fetch_slack.render_day(msgs, "C1", c, fetch_slack.day_window(DAY))
    assert speakers == ["Rob Smith", "Nick Tomasino", "Lars Berg"]
    lines = text.splitlines()
    assert lines[0] == "Rob Smith: @Nick Tomasino can you look at the proof diff for DEV-10173?"
    assert lines[1] == "Rob Smith (thread): thread reply here"
    assert lines[2] == "Nick Tomasino: yes, by Friday. see https://example.com/doc"
    assert lines[3] == "Lars Berg: I'll send the sample file"
    assert "Jira Bot" not in text and "joined" not in text and "yesterday" not in text


def test_fetch_completed_days_only(org_dir):
    paths, state, c = Paths(org_dir), State.load(Paths(org_dir).state_file), FakeClient()
    files = fetch_slack.fetch(paths, state, CFG, c, TODAY)
    assert [f.name for f in files] == ["2026-10-21-slack-tron-c1.txt", "2026-10-21-slack-dm-rob-smith-lars-berg-g1.txt"]
    day_calls = [call for call in c.calls if call[0] == "history" and call[3] - call[2] <= 26 * 3600]
    assert day_calls and all(call[2] >= fetch_slack.day_window(DAY)[0] for call in day_calls)  # lookback calls excluded
    text = files[0].read_text()
    assert text.startswith("title: Slack #tron\ndate: 2026-10-21\ntime: 09:00\nsource: slack\nkind: chat\nattendees: Rob Smith, Nick Tomasino, Lars Berg\n\n")
    assert "Rob Smith: @Nick Tomasino" in text
    s = State.load(paths.state_file)
    assert s.fetched["slack:C1:2026-10-21"] == {"file": "2026-10-21-slack-tron-c1.txt", "name": "Slack #tron"}
    assert "slack:D1:2026-10-21" not in s.fetched  # below min_messages: not written, not recorded (last_slack_poll gates it)
    assert s.last_slack_poll == "2026-10-21"
    assert fetch_slack.fetch(paths, state, CFG, c, TODAY) == []  # retry the same morning: nothing new


def test_fetch_resumes_from_last_poll(org_dir):
    paths, state, c = Paths(org_dir), State.load(Paths(org_dir).state_file), FakeClient()
    state.last_slack_poll = "2026-10-18"
    fetch_slack.fetch(paths, state, CFG, c, TODAY)
    days = sorted({datetime.fromtimestamp(call[2], LA).date() for call in c.calls if call[0] == "history" and call[3] - call[2] <= 26 * 3600})
    assert days == [date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)]


def test_dry_run(org_dir, capsys):
    paths, state, c = Paths(org_dir), State.load(Paths(org_dir).state_file), FakeClient()
    assert fetch_slack.fetch(paths, state, CFG, c, TODAY, dry_run=True) == []
    assert "2026-10-21-slack-tron-c1.txt" in capsys.readouterr().out
    assert not paths.state_file.exists() and not list(paths.inbox.iterdir())


def test_client_retries_rate_limits():
    from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

    c = fetch_slack.SlackClient("xoxp-test")
    assert any(isinstance(h, RateLimitErrorRetryHandler) for h in c.c.retry_handlers)


def test_thread_reply_after_last_toplevel_is_kept():
    c = FakeClient()
    msgs = [
        {"type": "message", "user": "U2", "text": "can you review X?", "ts": ts(DAY, 9, 0), "thread_ts": ts(DAY, 9, 0), "reply_count": 1},
        {"type": "message", "user": "U3", "text": "other", "ts": ts(DAY, 9, 5)},
    ]
    REPLIES[("C9", ts(DAY, 9, 0))] = [msgs[0], {"type": "message", "user": "U1", "text": "will do by Friday", "ts": ts(DAY, 11, 0), "thread_ts": ts(DAY, 9, 0)}]
    _, text = fetch_slack.render_day(msgs, "C9", c, fetch_slack.day_window(DAY))
    assert "Nick Tomasino (thread): will do by Friday" in text


def test_reply_today_to_yesterdays_thread():
    yesterday = date(2026, 10, 20)
    parent = {"type": "message", "user": "U2", "text": "status on the extract job?", "ts": ts(yesterday, 16, 0),
              "thread_ts": ts(yesterday, 16, 0), "reply_count": 1, "latest_reply": ts(DAY, 10, 0)}
    HISTORY["C1"].append(parent)
    REPLIES[("C1", parent["ts"])] = [parent, {"type": "message", "user": "U1", "text": "done, deployed this morning", "ts": ts(DAY, 10, 0), "thread_ts": parent["ts"]}]
    try:
        c = FakeClient()
        win = fetch_slack.day_window(DAY)
        earlier = c.history("C1", win[0] - 7 * 86400, win[0])
        _, text = fetch_slack.render_day(c.history("C1", *win), "C1", c, win, earlier=earlier)
        assert "Nick Tomasino (thread, re: status on the extract job?): done, deployed this morning" in text
        assert "Rob Smith: status on the extract job?" not in text  # the parent itself was yesterday's
    finally:
        HISTORY["C1"].remove(parent)
        del REPLIES[("C1", parent["ts"])]


def test_failed_conversation_does_not_block_others(org_dir):
    class Flaky(FakeClient):
        def history(self, channel, oldest, latest):
            if channel == "C1":
                raise RuntimeError("missing_scope")
            return super().history(channel, oldest, latest)

    paths, state, c = Paths(org_dir), State.load(Paths(org_dir).state_file), Flaky()
    files = fetch_slack.fetch(paths, state, CFG, c, TODAY)
    assert [f.name for f in files] == ["2026-10-21-slack-dm-rob-smith-lars-berg-g1.txt"]  # G1 still landed
    s = State.load(paths.state_file)
    assert "slack:G1:2026-10-21" in s.fetched and "slack:C1:2026-10-21" not in s.fetched
    assert s.last_slack_poll is None  # a failed day is retried next run


def test_slackbot_dm_is_not_selected():
    """users.conversations lists the Slackbot DM, but conversations.history on it is channel_not_found."""
    convs = CONVS + [{"id": "D9", "is_im": True, "user": "USLACKBOT"}]
    assert "D9" not in [c["id"] for c in fetch_slack.select_conversations(convs, CFG)]


def test_app_posts_with_bot_id_are_not_human():
    """The Jira Cloud app posts with a `user` id *and* a `bot_id` and no subtype; it must not count toward min_messages."""
    jira = {"type": "message", "user": "UHJFH8G0G", "bot_id": "BHLSVAYHJ", "text": "Chris commented on ITSM-1133", "ts": "1.0"}
    assert not fetch_slack._human(jira)
    assert fetch_slack._human({"type": "message", "user": "U1", "text": "hi", "ts": "1.0"})
