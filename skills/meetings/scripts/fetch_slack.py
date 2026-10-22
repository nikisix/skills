"""Pull one completed local day of Slack messages per conversation into meetings/inbox as a
`kind: chat` text file, so the normal digest -> worklog pipeline lands the action items.

Completed days only: the 06:30 run fetches every full local day after state.last_slack_poll up to
yesterday (first run: yesterday). The hourly retries then find nothing new, which keeps them
idempotent. Each conversation-day is keyed `slack:<channel_id>:<YYYY-MM-DD>` in state.fetched.

Config meetings/slack.yaml: dms, group_dms, channels (names without '#'), min_messages.
Token: $SLACK_USER_TOKEN, else the login keychain item `meetings-slack`
(`security add-generic-password -a "$USER" -s meetings-slack -w 'xoxp-…'`). User scopes:
channels:history groups:history im:history mpim:history channels:read groups:read im:read mpim:read users:read

Usage: fetch_slack.py [--dry-run] [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from config import TIMEZONE, Paths, add_org_dir_arg, parse_args_or_none, paths_from_args
from state import State

EXIT_NOTHING = 2
KEYCHAIN_SERVICE = "meetings-slack"
SKIP_SUBTYPES = {"bot_message", "channel_join", "channel_leave", "group_join", "group_leave", "channel_topic",
                 "channel_purpose", "channel_name", "pinned_item", "reminder_add", "tombstone", "joiner_notification"}
_MENTION = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]*)?>")
_LINK = re.compile(r"<(https?://[^|>]+)\|([^>]+)>")
_BARE = re.compile(r"<(https?://[^>]+)>")
_CHAN = re.compile(r"<#[A-Z0-9]+\|([^>]+)>")
_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass
class SlackConfig:
    dms: bool = True
    group_dms: bool = True
    channels: list[str] = field(default_factory=list)
    min_messages: int = 3

    @classmethod
    def load(cls, path: Path) -> "SlackConfig | None":
        if not Path(path).exists():
            return None
        d = yaml.safe_load(Path(path).read_text()) or {}
        return cls(bool(d.get("dms", True)), bool(d.get("group_dms", True)),
                   [str(c).lstrip("#") for c in d.get("channels") or []], int(d.get("min_messages", 3)))


def token() -> str | None:
    t = os.environ.get("SLACK_USER_TOKEN")
    if t:
        return t
    proc = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True)
    return proc.stdout.strip() or None


class SlackClient:
    """Thin paging wrapper over slack_sdk; tests substitute an object with the same methods."""

    def __init__(self, tok: str):
        from slack_sdk import WebClient
        from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

        self.c = WebClient(token=tok)
        # Tier 3 methods allow ~50/min; the first run bursts one history call per conversation-day.
        self.c.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
        self._names: dict[str, str] = {}

    def me(self) -> str:
        return self.c.auth_test()["user_id"]

    def conversations(self) -> list[dict]:
        out, cursor = [], None
        while True:
            r = self.c.users_conversations(types="im,mpim,public_channel,private_channel", exclude_archived=True, limit=200, cursor=cursor)
            out.extend(r["channels"])
            cursor = (r.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return out

    def members(self, channel: str) -> list[str]:
        return list(self.c.conversations_members(channel=channel, limit=200)["members"])

    def history(self, channel: str, oldest: float, latest: float) -> list[dict]:
        out, cursor = [], None
        while True:
            r = self.c.conversations_history(channel=channel, oldest=f"{oldest:.6f}", latest=f"{latest:.6f}", limit=200, cursor=cursor)
            out.extend(r["messages"])
            cursor = (r.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return out

    def replies(self, channel: str, thread_ts: str) -> list[dict]:
        return list(self.c.conversations_replies(channel=channel, ts=thread_ts, limit=200)["messages"])

    def user_name(self, uid: str) -> str:
        if uid not in self._names:
            u = self.c.users_info(user=uid)["user"]
            prof = u.get("profile") or {}
            self._names[uid] = u.get("real_name") or prof.get("display_name") or u.get("name") or uid
        return self._names[uid]


def day_window(d: date) -> tuple[float, float]:
    tz = ZoneInfo(TIMEZONE)
    start = datetime(d.year, d.month, d.day, tzinfo=tz)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def select_conversations(convs: list[dict], cfg: SlackConfig) -> list[dict]:
    wanted = {c.lower() for c in cfg.channels}
    out = []
    for c in convs:
        if c.get("is_im"):
            if cfg.dms:
                out.append(c)
        elif c.get("is_mpim"):
            if cfg.group_dms:
                out.append(c)
        elif (c.get("name") or "").lower() in wanted:
            out.append(c)
    return out


def conversation_title(conv: dict, client) -> str:
    if conv.get("is_im"):
        return f"Slack DM {client.user_name(conv['user'])}"
    if conv.get("is_mpim"):
        me = client.me()
        others = [client.user_name(u) for u in client.members(conv["id"]) if u != me]
        return "Slack DM " + ", ".join(others)
    return f"Slack #{conv.get('name', conv['id'])}"


def clean_text(text: str, client) -> str:
    text = _MENTION.sub(lambda m: "@" + client.user_name(m.group(1)), text)
    text = _LINK.sub(lambda m: m.group(2), text)
    text = _BARE.sub(lambda m: m.group(1), text)
    text = _CHAN.sub(lambda m: "#" + m.group(1), text)
    return re.sub(r"\s+", " ", text.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")).strip()


def _human(m: dict) -> bool:
    return m.get("type") == "message" and m.get("subtype") not in SKIP_SUBTYPES and bool(m.get("user")) and bool(m.get("text", "").strip())


THREAD_LOOKBACK_DAYS = 7


def _in(window: tuple[float, float], m: dict) -> bool:
    return window[0] <= float(m["ts"]) < window[1]


def render_day(messages: list[dict], channel: str, client, window: tuple[float, float],
               earlier: list[dict] | None = None) -> tuple[list[str], str]:
    """(speakers in order of first appearance, 'Name: text' lines) for one local day.

    Replies anywhere inside the day's window follow their parent as 'Name (thread): text'. Replies
    today to a thread whose parent is in `earlier` (a lookback of history before the window) are
    emitted as 'Name (thread, re: <parent>): text' so long-running threads are not lost."""
    speakers: list[str] = []
    lines: list[str] = []

    def emit(m: dict, suffix: str = "") -> None:
        name = client.user_name(m["user"])
        if name not in speakers:
            speakers.append(name)
        lines.append(f"{name}{suffix}: {clean_text(m['text'], client)}")

    def thread_replies(parent: dict):
        for r in client.replies(channel, parent["ts"]):
            if r["ts"] != parent["ts"] and _human(r) and _in(window, r):
                yield r

    for m in sorted(messages, key=lambda x: float(x["ts"])):
        if not _human(m):
            continue
        if m.get("thread_ts") and m["thread_ts"] != m["ts"]:
            continue  # a broadcast reply: emitted under its parent (today's or an earlier day's)
        emit(m)
        if m.get("reply_count") and m.get("thread_ts") == m["ts"]:
            for r in thread_replies(m):
                emit(r, " (thread)")
    for parent in sorted(earlier or [], key=lambda x: float(x["ts"])):
        if not (_human(parent) and parent.get("reply_count") and parent.get("latest_reply")):
            continue
        if float(parent["latest_reply"]) < window[0]:
            continue
        topic = clean_text(parent["text"], client)[:60]
        for r in thread_replies(parent):
            emit(r, f" (thread, re: {topic})")
    return speakers, "\n".join(lines) + ("\n" if lines else "")


def slug(title: str) -> str:
    return _SLUG.sub("-", title.lower().replace("#", "")).strip("-")[:50].strip("-")


def fetch(paths: Paths, state: State, cfg: SlackConfig, client, today: date, dry_run: bool = False) -> list[Path]:
    first = date.fromisoformat(state.last_slack_poll) + timedelta(days=1) if state.last_slack_poll else today - timedelta(days=1)
    last = today - timedelta(days=1)
    written: list[Path] = []
    if first > last:
        return written
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    failed_days: list[date] = []
    for conv in select_conversations(client.conversations(), cfg):
        title: str | None = None
        for d in days:
            key = f"slack:{conv['id']}:{d.isoformat()}"
            if key in state.fetched:
                continue
            try:
                window = day_window(d)
                msgs = client.history(conv["id"], *window)
                earlier = client.history(conv["id"], window[0] - THREAD_LOOKBACK_DAYS * 86400, window[0])
                speakers, body = render_day(msgs, conv["id"], client, window, earlier=earlier)
                n = body.count("\n")
                if n < cfg.min_messages:
                    continue  # not recorded: last_slack_poll gates the day once the run completes
                title = title or conversation_title(conv, client)
                name = f"{d.isoformat()}-{slug(title)}-{conv['id'].lower()}.txt"
                stamps = [float(m["ts"]) for m in msgs if _human(m)]
                hhmm = datetime.fromtimestamp(min(stamps), ZoneInfo(TIMEZONE)).strftime("%H:%M") if stamps else ""
                out = paths.inbox / name
                text = (f"title: {title}\ndate: {d.isoformat()}\ntime: {hhmm}\nsource: slack\nkind: chat\n"
                        f"attendees: {', '.join(speakers)}\n\n{body}")
                if dry_run:
                    print(f"would write {out} ({n} messages)")
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
                state.fetched[key] = {"file": name, "name": title}
                state.save()  # per file: a later failure keeps what already landed
                written.append(out)
                print(out)
            except Exception as exc:  # one bad conversation-day must not wedge the rest
                print(f"slack {conv['id']} {d}: {exc}", file=sys.stderr)
                failed_days.append(d)
    if not dry_run:
        done_through = min(failed_days) - timedelta(days=1) if failed_days else last
        if done_through >= first:
            state.last_slack_poll = done_through.isoformat()
        state.save()
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    add_org_dir_arg(ap)
    args = parse_args_or_none(ap, argv)
    if args is None:
        return 1
    paths = paths_from_args(args)
    cfg = SlackConfig.load(paths.slack_file)
    if cfg is None:
        print(f"no {paths.slack_file}; skipping Slack", file=sys.stderr)
        return EXIT_NOTHING
    tok = token()
    if not tok:
        print("no Slack token ($SLACK_USER_TOKEN or keychain item meetings-slack)", file=sys.stderr)
        return 1
    state = State.load(paths.state_file)
    try:
        files = fetch(paths, state, cfg, SlackClient(tok), args.today or date.today(), dry_run=args.dry_run)
    except Exception as exc:  # slack_sdk raises SlackApiError and friends
        print(f"slack fetch failed: {exc}", file=sys.stderr)
        return 1
    return 0 if files or args.dry_run else EXIT_NOTHING


if __name__ == "__main__":
    sys.exit(main())
