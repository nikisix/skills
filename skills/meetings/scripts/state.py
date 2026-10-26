"""Pipeline state: processed/fetched keys, poll times, arXiv memory. One JSON file, atomic saves."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class State:
    path: Path
    processed: dict[str, dict] = field(default_factory=dict)
    fetched: dict[str, dict] = field(default_factory=dict)
    last_teams_poll: str | None = None
    last_slack_poll: str | None = None  # last fully fetched local day, YYYY-MM-DD
    last_arxiv_run: str | None = None
    arxiv_seen: set[str] = field(default_factory=set)
    arxiv_queries: dict[str, list[str]] = field(default_factory=dict)
    own_saves: dict[str, int] = field(default_factory=dict)  # org file -> st_mtime_ns after our last write

    @classmethod
    def load(cls, path: Path) -> "State":
        path = Path(path)
        if not path.exists():
            return cls(path=path)
        data = json.loads(path.read_text() or "{}")
        return cls(
            path=path,
            processed=data.get("processed", {}),
            fetched=data.get("fetched", {}),
            last_teams_poll=data.get("last_teams_poll"),
            last_slack_poll=data.get("last_slack_poll"),
            last_arxiv_run=data.get("last_arxiv_run"),
            arxiv_seen=set(data.get("arxiv_seen", [])),
            arxiv_queries=data.get("arxiv_queries", {}),
            own_saves=data.get("own_saves", {}),
        )

    def save(self) -> None:
        """Merge with whatever is on disk now: two jobs (daily, arXiv) may hold the file at once.
        Dicts and sets union (mine wins on a key), scalars take mine when set."""
        if self.path.exists():
            other = State.load(self.path)
            self.processed = {**other.processed, **self.processed}
            self.fetched = {**other.fetched, **self.fetched}
            self.arxiv_seen |= other.arxiv_seen
            self.arxiv_queries = {**other.arxiv_queries, **self.arxiv_queries}
            self.own_saves = {**other.own_saves, **self.own_saves}
            self.last_teams_poll = self.last_teams_poll or other.last_teams_poll
            self.last_slack_poll = max(filter(None, [self.last_slack_poll, other.last_slack_poll]), default=None)
            self.last_arxiv_run = self.last_arxiv_run or other.last_arxiv_run
        data = {
            "processed": self.processed,
            "fetched": self.fetched,
            "last_teams_poll": self.last_teams_poll,
            "last_slack_poll": self.last_slack_poll,
            "last_arxiv_run": self.last_arxiv_run,
            "arxiv_seen": sorted(self.arxiv_seen),
            "arxiv_queries": self.arxiv_queries,
            "own_saves": self.own_saves,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, self.path)
