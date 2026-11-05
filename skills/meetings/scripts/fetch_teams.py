"""Pull transcripts of Teams meetings into meetings/inbox via the PnP `m365` CLI.

Two routes, both keyed `teams:<meetingId>:<transcriptId>` in state.fetched so a transcript is
downloaded once whichever route finds it:
  calendar  `teams meeting list --isOrganizer` over the window: meetings I organized, named from the
            meeting's own start time.
  chats     `teams chat list --type meeting`: every meeting I attended has a meeting chat; the chats
            touched inside the window are resolved to their online meeting by join URL (works for
            attendees, not only organizers) and their transcripts fetched. A recurring series shares one
            meeting whose startDateTime is the series start, so these files are named from the
            transcript's createdDateTime (the end of that occurrence) instead.
Window = state.last_teams_poll (or now - 14 days on first run) .. now. Files are named
YYYY-MM-DD-HHMM-<slug>.vtt in America/Los_Angeles so normalize.py reads date/time/title from them.

Requires: `npm i -g @pnp/cli-microsoft365` plus your own Entra app (CLI v10+ has no default one):
delegated Calendars.Read (meeting list walks the calendar) + Chat.ReadBasic (chat list) +
OnlineMeetings.Read + OnlineMeetingTranscript.Read.All (admin consent), `m365 cli config set`
clientId/tenantId/authType=browser, then `m365 login`. Steps: ~/org/ringmaster/CLAUDE-meetings.md.

Usage: fetch_teams.py [--since ISO] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config import TIMEZONE, Paths, add_org_dir_arg, parse_args_or_none, paths_from_args
from state import State

M365_BIN = "m365"
FIRST_RUN_DAYS = 14
OVERLAP_DAYS = 2  # a meeting still running at the last poll had no transcript yet; fetched keys dedup
EXIT_NOTHING = 2
SCOPE_HINT = ("listing meeting chats needs the delegated Chat.ReadBasic scope on the app: add it, have it consented, "
              "then `m365 logout && m365 login` so the token carries it")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def m365(args: list[str]) -> Any:
    """Run `m365 <args> -o json` and parse the output. Raises RuntimeError with stderr on failure."""
    proc = subprocess.run([M365_BIN, *args, "-o", "json"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"m365 {' '.join(args)} failed: {proc.stderr.strip()[:500]}")
    return json.loads(proc.stdout or "null")


def graph_time(dt: datetime) -> str:
    """m365 validates ISO strings strictly: UTC, whole seconds, trailing Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def graph_datetime(raw: str) -> datetime:
    """Graph gives 7 fractional digits and a Z; fromisoformat wants at most 6 and an offset."""
    raw = re.sub(r"(\.\d{1,6})\d*(?=Z|[+-]\d{2}:\d{2}$)", r"\1", raw)
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def list_meetings(start: datetime, end: datetime) -> list[dict]:
    out = m365(["teams", "meeting", "list", "--isOrganizer", "--startDateTime", graph_time(start), "--endDateTime", graph_time(end)])
    return list(out or [])


def list_meeting_chats() -> list[dict]:
    """Every chat of type `meeting` I am a member of (the CLI pages through all of them)."""
    try:
        return list(m365(["teams", "chat", "list", "--type", "meeting"]) or [])
    except RuntimeError as exc:
        if re.search(r"scope|denied|forbidden|403|authoriz", str(exc), re.I):
            raise RuntimeError(f"{exc}\n{SCOPE_HINT}") from exc
        raise


def meeting_by_join_url(join_url: str) -> dict | None:
    """Resolve a meeting chat's join URL to its onlineMeeting; accepts an attendee's token, not only the organizer's."""
    out = m365(["teams", "meeting", "get", "--joinUrl", join_url])
    if isinstance(out, list):
        out = out[0] if out else None
    return out or None


def list_transcripts(meeting_id: str) -> list[dict]:
    return list(m365(["teams", "meeting", "transcript", "list", "-m", meeting_id]) or [])


def download(meeting_id: str, transcript_id: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [M365_BIN, "teams", "meeting", "transcript", "get", "-m", meeting_id, "-i", transcript_id, "-f", str(out)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(f"m365 transcript get {transcript_id} failed: {proc.stderr.strip()[:500]}")


def slug(subject: str) -> str:
    return _SLUG_RE.sub("-", subject.lower()).strip("-")[:60].strip("-") or "meeting"


def inbox_name(meeting: dict, when: str | None = None) -> str:
    """`when` (a Graph timestamp) overrides the meeting's startDateTime, for occurrences of a series."""
    start = graph_datetime(when or meeting["startDateTime"]).astimezone(ZoneInfo(TIMEZONE))
    return f"{start:%Y-%m-%d-%H%M}-{slug(meeting.get('subject') or '')}.vtt"


def _unique(name: str, inbox: Path, taken: set[str]) -> str:
    stem, ext = name.rsplit(".", 1)
    cand, n = name, 1
    while cand in taken or (inbox / cand).exists():
        n += 1
        cand = f"{stem}-{n}.{ext}"
    taken.add(cand)
    return cand


def fetch(paths: Paths, state: State, now: datetime, since: datetime | None = None, dry_run: bool = False) -> list[Path]:
    """Download new transcripts into paths.inbox; returns the files written (none on dry run)."""
    if since is None:
        since = (datetime.fromisoformat(state.last_teams_poll) - timedelta(days=OVERLAP_DAYS)) if state.last_teams_poll else now - timedelta(days=FIRST_RUN_DAYS)
    if since.tzinfo is None:  # `--since 2026-10-21` parses naive; read it as UTC like the Graph timestamps
        since = since.replace(tzinfo=timezone.utc)
    written: list[Path] = []
    taken: set[str] = set()

    def land(meeting: dict, t: dict, name: str) -> None:
        key = f"teams:{meeting['id']}:{t['id']}"
        if key in state.fetched:
            return
        out = paths.inbox / name
        if dry_run:
            print(f"would fetch {out}")
            return
        download(meeting["id"], t["id"], out)
        state.fetched[key] = {"file": out.name, "subject": meeting.get("subject") or ""}
        written.append(out)
        print(out)

    for meeting in list_meetings(since, now):
        for i, t in enumerate(list_transcripts(meeting["id"])):
            name = inbox_name(meeting)
            if i:
                name = name.replace(".vtt", f"-{i + 1}.vtt")
            taken.add(name)
            land(meeting, t, name)

    chats_error: RuntimeError | None = None
    try:
        chats = list_meeting_chats()
        if chats and not any((c.get("onlineMeetingInfo") or {}).get("joinWebUrl") for c in chats):
            print(f"teams: {len(chats)} meeting chats listed but none carries onlineMeetingInfo.joinWebUrl; "
                  "nothing can be resolved (inspect `m365 teams chat list --type meeting -o json`)", file=sys.stderr)
        for chat in chats:
            join_url = (chat.get("onlineMeetingInfo") or {}).get("joinWebUrl")
            touched = chat.get("lastUpdatedDateTime") or chat.get("createdDateTime")
            if not join_url or not touched or graph_datetime(touched) < since:
                continue
            try:
                meeting = meeting_by_join_url(join_url)
                transcripts = list_transcripts(meeting["id"]) if meeting else []
            except RuntimeError as exc:
                print(f"teams: skipping chat {chat.get('topic') or chat.get('id')}: {exc}", file=sys.stderr)
                continue
            for t in transcripts:
                if f"teams:{meeting['id']}:{t['id']}" in state.fetched:
                    continue
                land(meeting, t, _unique(inbox_name(meeting, when=t.get("createdDateTime")), paths.inbox, taken))
    except RuntimeError as exc:
        chats_error = exc  # keep what the calendar route landed; do not advance the window past what was missed

    if not dry_run:
        if chats_error is None:
            state.last_teams_poll = now.isoformat()
        state.save()
    if chats_error is not None:
        raise chats_error
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", type=datetime.fromisoformat, default=None)
    ap.add_argument("--dry-run", action="store_true")
    add_org_dir_arg(ap)
    args = parse_args_or_none(ap, argv)
    if args is None:
        return 1
    paths = paths_from_args(args)
    state = State.load(paths.state_file)
    try:
        files = fetch(paths, state, datetime.now(timezone.utc), since=args.since, dry_run=args.dry_run)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0 if files or args.dry_run else EXIT_NOTHING


if __name__ == "__main__":
    sys.exit(main())
