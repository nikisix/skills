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
    last_arxiv_run: str | None = None
    arxiv_seen: set[str] = field(default_factory=set)
    arxiv_queries: dict[str, list[str]] = field(default_factory=dict)

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
            last_arxiv_run=data.get("last_arxiv_run"),
            arxiv_seen=set(data.get("arxiv_seen", [])),
            arxiv_queries=data.get("arxiv_queries", {}),
        )

    def save(self) -> None:
        data = {
            "processed": self.processed,
            "fetched": self.fetched,
            "last_teams_poll": self.last_teams_poll,
            "last_arxiv_run": self.last_arxiv_run,
            "arxiv_seen": sorted(self.arxiv_seen),
            "arxiv_queries": self.arxiv_queries,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, self.path)
