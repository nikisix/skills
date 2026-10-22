"""Land a digest in the org files: meeting block under its day (merged into a matching hand-written
heading or as a new :auto: heading) plus one SCHEDULED item per dated follow-up under its target day.

Only additions are made. Every write carries a key `<digest key>|<file>|<heading path>` recorded in
state.json, so reruns are no-ops. Files saved within the last GUARD_MINUTES are not touched
(exit 3) unless --force: nvim does not reload a file that changes under it.

Usage: write_org.py <digest.json> --key <key> [--dry-run] [--force] [--now ISO] [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from config import Paths, add_org_dir_arg, paths_from_args
from orgfile import OrgDoc
from people import People
from render import followup_item, match_heading, meeting_block
from state import State

GUARD_MINUTES = 15
EXIT_GUARD = 3
EXIT_NOTHING = 2


class MtimeGuard(Exception):
    pass


@dataclass
class Write:
    file: Path
    insert_at: int  # 0-based line index in `file` as it stands when this write is applied, in order
    lines: list[str]
    write_key: str


def target_file(paths: Paths, d: date, today: date) -> Path:
    """Current month or later -> worklog.org; an earlier month -> that month's archive file."""
    if (d.year, d.month) >= (today.year, today.month):
        return paths.worklog
    return paths.archive_for(d)


def _append_point(doc: OrgDoc, idx: int) -> int:
    """Where to add children to the subtree at `idx`: its end, before any trailing blank lines."""
    end = doc.section_end(idx)
    while end - 1 > idx and doc.lines[end - 1] == "":
        end -= 1
    return end


class _Planner:
    def __init__(self, key: str, paths: Paths, done: frozenset[str]):
        self.key, self.paths, self.done = key, paths, done
        self.docs: dict[Path, OrgDoc] = {}
        self.writes: list[Write] = []

    def doc(self, file: Path) -> OrgDoc:
        if file not in self.docs:
            self.docs[file] = OrgDoc.load(file)
        return self.docs[file]

    def add(self, file: Path, at: int, lines: list[str], path: str) -> None:
        """Insert in the in-memory doc (so later positions are right) and record the write."""
        wk = f"{self.key}|{file.name}|{path}"
        if wk in self.done:
            return
        self.doc(file).insert(at, lines)
        self.writes.append(Write(file, at, list(lines), wk))

    def day(self, file: Path, d: date) -> int:
        doc = self.doc(file)
        idx = doc.find_day(d)
        if idx is not None:
            return idx
        idx = doc.ensure_day(d)  # inserts [header, ""] in memory
        header = doc.lines[idx : idx + 2]
        del doc.lines[idx : idx + 2]
        self.add(file, idx, header, f"{d.isoformat()}/day")
        return idx


def plan_writes(
    digest: dict,
    key: str,
    paths: Paths,
    people: People,
    now: datetime,
    today: date | None = None,
    done: frozenset[str] | set[str] = frozenset(),
) -> list[Write]:
    today = today or now.date()
    d = date.fromisoformat(digest["date"])
    p = _Planner(key, paths, frozenset(done))

    file = target_file(paths, d, today)
    doc = p.doc(file)
    day_idx = p.day(file, d)
    match = match_heading(digest["title"], digest.get("attendees") or [], doc.headings(day_idx, 2), people)
    if match:
        heading_title, at = match.title, _append_point(doc, match.idx)
    else:
        heading_title, at = digest["title"], _append_point(doc, day_idx)
    p.add(file, at, meeting_block(digest, people, now, new_heading=match is None), f"{d.isoformat()}/{heading_title}")

    link_file = str(file.relative_to(paths.org_dir))
    linked = {**digest, "title": heading_title}
    for i, fu in enumerate(digest.get("follow_ups") or []):
        if not fu.get("when"):
            continue
        when = date.fromisoformat(fu["when"])
        fu_file = target_file(paths, when, today)
        fu_day = p.day(fu_file, when)
        p.add(fu_file, _append_point(p.doc(fu_file), fu_day), followup_item(fu, linked, people, link_file),
              f"{when.isoformat()}/followup/{i}")
    return p.writes


def _recently_saved(file: Path) -> bool:
    """Wall-clock check (not --now): the question is whether an editor may have the file open."""
    if not file.exists():
        return False
    return time.time() - file.stat().st_mtime < GUARD_MINUTES * 60


def apply(writes: list[Write], state: State, dry_run: bool = False, *, force: bool = False, now: datetime | None = None) -> int:
    """Replay `writes` in order on freshly loaded files. Returns the number applied (or printed)."""
    now = now or datetime.now()
    todo = [w for w in writes if w.write_key not in state.processed]
    if not todo:
        return 0
    files = list(dict.fromkeys(w.file for w in todo))
    if not dry_run and not force:
        for f in files:
            if _recently_saved(f):
                raise MtimeGuard(f"{f} was saved less than {GUARD_MINUTES} min ago; retry later or --force")
    docs = {f: OrgDoc.load(f) for f in files}
    for w in todo:
        if dry_run:
            print(f"== {w.file}:{w.insert_at + 1}")
            print("\n".join(w.lines))
            continue
        docs[w.file].insert(w.insert_at, w.lines)
        state.processed[w.write_key] = {"file": str(w.file), "line": w.insert_at + 1, "at": now.isoformat(timespec="minutes")}
    if not dry_run:
        for f, doc in docs.items():
            doc.save_atomic(f)
        state.save()
    return len(todo)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("digest", type=Path)
    ap.add_argument("--key", required=True, help="digest key (sha256 of normalized body, or teams:<id>)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="ignore the recent-save guard")
    ap.add_argument("--now", type=datetime.fromisoformat, default=None)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    add_org_dir_arg(ap)
    args = ap.parse_args(argv)
    paths = paths_from_args(args)
    now = args.now or datetime.now()
    digest = json.loads(args.digest.read_text(encoding="utf-8"))
    people = People.load(paths.people_file)
    state = State.load(paths.state_file)
    writes = plan_writes(digest, args.key, paths, people, now, today=args.today, done=set(state.processed))
    try:
        n = apply(writes, state, dry_run=args.dry_run, force=args.force, now=now)
    except MtimeGuard as exc:
        print(f"skipped: {exc}", file=sys.stderr)
        return EXIT_GUARD
    print(f"{'would write' if args.dry_run else 'wrote'} {n} block(s)")
    return 0 if n else EXIT_NOTHING


if __name__ == "__main__":
    sys.exit(main())
