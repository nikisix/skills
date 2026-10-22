"""Minimal org-mode file model: day headers, headings, subtree bounds, ordered insertion, atomic save.

Only additions are ever made to a document; existing lines are never rewritten.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DAY_RE = re.compile(r"^\* <(\d{4}-\d{2}-\d{2}) [A-Z][a-z]{2}>(.*)$")
HEADLINE_RE = re.compile(r"^(\*+) (.*)$")
KEYWORD_RE = re.compile(r"^(TODO|INPROGRESS|DONE) (.*)$")
TAGS_RE = re.compile(r"^(.*?)\s+:([\w:]+):\s*$")
LINK_RE = re.compile(r"\s*-\s*\[\[[^\]]+\]\[([^\]]+)\]\]\s*$")
OWNER_RE = re.compile(r"^(.*?)\s+-\s+@(\S+)\s*$")
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def day_header(d: date) -> str:
    return f"* <{d.isoformat()} {DOW[d.weekday()]}>"


@dataclass
class Heading:
    idx: int
    level: int
    keyword: str | None
    title: str
    tags: list[str] = field(default_factory=list)
    owner: str | None = None
    link: str | None = None

    @classmethod
    def parse(cls, idx: int, line: str) -> "Heading | None":
        m = HEADLINE_RE.match(line)
        if not m:
            return None
        stars, rest = m.groups()
        tags: list[str] = []
        if tm := TAGS_RE.match(rest):
            rest, tags = tm.group(1), [t for t in tm.group(2).split(":") if t]
        keyword = None
        if km := KEYWORD_RE.match(rest):
            keyword, rest = km.groups()
        link = None
        if lm := LINK_RE.search(rest):
            link, rest = lm.group(1), rest[: lm.start()]
        owner = None
        if om := OWNER_RE.match(rest):
            rest, owner = om.groups()
        return cls(idx, len(stars), keyword, rest.strip(), tags, owner, link)


@dataclass
class OrgDoc:
    lines: list[str]

    @classmethod
    def load(cls, path: Path) -> "OrgDoc":
        text = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
        return cls(text.split("\n")[:-1] if text.endswith("\n") else text.split("\n") if text else [])

    @property
    def text(self) -> str:
        return "\n".join(self.lines) + ("\n" if self.lines else "")

    def save_atomic(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp~")
        tmp.write_text(self.text, encoding="utf-8")
        os.replace(tmp, path)

    # --- structure -------------------------------------------------------

    def level_at(self, idx: int) -> int:
        m = HEADLINE_RE.match(self.lines[idx])
        return len(m.group(1)) if m else 0

    def section_end(self, idx: int) -> int:
        """Index just past the subtree rooted at `idx` (next headline of level <= this one, or EOF)."""
        level = self.level_at(idx)
        for j in range(idx + 1, len(self.lines)):
            lj = self.level_at(j)
            if lj and lj <= level:
                return j
        return len(self.lines)

    def day_headers(self) -> list[tuple[int, date]]:
        out = []
        for i, line in enumerate(self.lines):
            if m := DAY_RE.match(line):
                out.append((i, date.fromisoformat(m.group(1))))
        return out

    def find_day(self, d: date) -> int | None:
        for i, dd in self.day_headers():
            if dd == d:
                return i
        return None

    def ensure_day(self, d: date) -> int:
        """Return the header index for `d`, inserting `* <d Dow>` in chronological order if needed.
        A new day later than all existing days goes before the first non-day top-level section."""
        existing = self.find_day(d)
        if existing is not None:
            return existing
        days = self.day_headers()
        at = None
        for i, dd in days:
            if dd > d:
                at = i
                break
        if at is None:
            if days:
                at = self.section_end(days[-1][0])
            else:
                at = 0
        self.insert(at, [day_header(d), ""])
        return at

    def headings(self, parent_idx: int, level: int) -> list[Heading]:
        """Direct headings of `level` inside the subtree rooted at `parent_idx`."""
        end = self.section_end(parent_idx)
        out = []
        for j in range(parent_idx + 1, end):
            if self.level_at(j) == level:
                h = Heading.parse(j, self.lines[j])
                if h:
                    out.append(h)
        return out

    def contains_marker(self, start: int, end: int, needle: str) -> bool:
        return any(needle in line for line in self.lines[start:end])

    def insert(self, at: int, new_lines: list[str]) -> None:
        self.lines[at:at] = list(new_lines)
