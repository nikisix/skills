"""Paths for the meetings pipeline. Everything hangs off one org dir."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DEFAULT_ORG_DIR = Path.home() / "org" / "ringmaster"
JIRA_BROWSE = "https://rmt.atlassian.net/browse/"
TIMEZONE = "America/Los_Angeles"


@dataclass(frozen=True)
class Paths:
    org_dir: Path

    @property
    def worklog(self) -> Path:
        return self.org_dir / "worklog.org"

    @property
    def suggestions(self) -> Path:
        return self.org_dir / "suggested-tron-tasks.org"

    @property
    def tron_tasks(self) -> Path:
        return self.org_dir / "tron-tasks.org"

    @property
    def meetings_dir(self) -> Path:
        return self.org_dir / "meetings"

    @property
    def inbox(self) -> Path:
        return self.meetings_dir / "inbox"

    @property
    def digests(self) -> Path:
        return self.meetings_dir / "digests"

    @property
    def archive(self) -> Path:
        return self.meetings_dir / "archive"

    @property
    def logs(self) -> Path:
        return self.meetings_dir / "logs"

    @property
    def state_file(self) -> Path:
        return self.meetings_dir / "state.json"

    @property
    def people_file(self) -> Path:
        return self.meetings_dir / "people.yaml"

    @property
    def slack_file(self) -> Path:
        return self.meetings_dir / "slack.yaml"

    def archive_for(self, d: date) -> Path:
        """Monthly archive file for a past month: 2026/2026-09-worklog.org."""
        return self.org_dir / f"{d.year}" / f"{d.year}-{d.month:02d}-worklog.org"


def resolve_org_dir(explicit: str | None = None) -> Path:
    raw = explicit or os.environ.get("MEETINGS_ORG_DIR") or str(DEFAULT_ORG_DIR)
    return Path(raw).expanduser()


def paths_from_args(args) -> Paths:
    """`args` is an argparse namespace with an optional `org_dir` attribute."""
    return Paths(resolve_org_dir(getattr(args, "org_dir", None)))


def add_org_dir_arg(parser) -> None:
    parser.add_argument(
        "--org-dir",
        dest="org_dir",
        default=None,
        help="org root (default: $MEETINGS_ORG_DIR or ~/org/ringmaster)",
    )


def parse_args_or_none(parser, argv):
    """argparse exits 2 on a usage error, which the orchestrator reads as 'nothing to do'.
    Return None instead so main() can return 1. --help (exit 0) still exits."""
    try:
        return parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code == 0:
            raise
        return None
