"""Pull transcripts of Teams meetings I organized into meetings/inbox via the PnP `m365` CLI.

Window = state.last_teams_poll (or now - 14 days on first run) .. now. Each transcript is keyed
`teams:<meetingId>:<transcriptId>` in state.fetched so it is downloaded once. Files are named
YYYY-MM-DD-HHMM-<slug>.vtt in America/Los_Angeles so normalize.py reads date/time/title from them.

Requires: `npm i -g @pnp/cli-microsoft365` plus your own Entra app (CLI v10+ has no default one):
delegated OnlineMeetings.Read + OnlineMeetingTranscript.Read.All (admin consent), `m365 cli config set`
clientId/tenantId, then `m365 login` (device code). Steps: ~/org/ringmaster/CLAUDE-meetings.md.

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


def list_meetings(start: datetime, end: datetime) -> list[dict]:
    out = m365(["teams", "meeting", "list", "--isOrganizer", "--startDateTime", graph_time(start), "--endDateTime", graph_time(end)])
    return list(out or [])


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


def inbox_name(meeting: dict) -> str:
    raw = meeting["startDateTime"]
    raw = re.sub(r"(\.\d{1,6})\d*(?=Z|[+-]\d{2}:\d{2}$)", r"\1", raw)  # Graph gives 7 fractional digits
    start = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(ZoneInfo(TIMEZONE))
    return f"{start:%Y-%m-%d-%H%M}-{slug(meeting.get('subject') or '')}.vtt"


def fetch(paths: Paths, state: State, now: datetime, since: datetime | None = None, dry_run: bool = False) -> list[Path]:
    """Download new transcripts into paths.inbox; returns the files written (none on dry run)."""
    if since is None:
        since = (datetime.fromisoformat(state.last_teams_poll) - timedelta(days=OVERLAP_DAYS)) if state.last_teams_poll else now - timedelta(days=FIRST_RUN_DAYS)
    written: list[Path] = []
    for meeting in list_meetings(since, now):
        for i, t in enumerate(list_transcripts(meeting["id"])):
            key = f"teams:{meeting['id']}:{t['id']}"
            if key in state.fetched:
                continue
            name = inbox_name(meeting)
            if i:
                name = name.replace(".vtt", f"-{i + 1}.vtt")
            out = paths.inbox / name
            if dry_run:
                print(f"would fetch {out}")
                continue
            download(meeting["id"], t["id"], out)
            state.fetched[key] = {"file": out.name, "subject": meeting.get("subject") or ""}
            written.append(out)
            print(out)
    if not dry_run:
        state.last_teams_poll = now.isoformat()
        state.save()
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
