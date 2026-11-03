"""Propagate a filled DONE cell in action-items.org to the worklog item and the tron task.

For every ledger row whose DONE cell is non-blank and whose entry has no `done_at` yet: flip the
worklog headline to DONE with a CLOSED stamp (or rewrite an `- Open:` bullet to `- Resolved`), then
move the tron task to the bucket the DONE word names (a sub-task gets the bucket's child tag). The
DONE cell itself is never touched. Every edit is printed as `done-sync: <file>:<line> <before> ->
<after>` so the day's log is the undo list.

Usage: sync_done.py [--dry-run] [--now ISO]   exit 0 edited · 2 nothing to do · 3 mtime guard
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from config import Paths, add_org_dir_arg, parse_args_or_none, paths_from_args
from ledger import Row, match_locator, normalize_done, rows
from orgfile import OrgDoc, headline_parts
from state import State
from write_org import EXIT_GUARD, EXIT_NOTHING, _recently_saved

DONE_WORDS: dict[str, tuple[str, str | None]] = {
    "x": ("In Review", "in_review"),
    "review": ("In Review", "in_review"),
    "ready": ("Ready for QA", "ready_for_qa"),
    "qa": ("In QA", "in_qa"),
    "accepted": ("Accepted", "accepted"),
    "closed": ("Closed", "closed"),
    "reopen": ("Reopen", "reopen"),
    "blocked": ("Blocked (do not sync)", None),
    "maybe": ("Maybe (do not sync)", None),
    "todo": ("To Do", "to_do"),
    "progress": ("In Progress", "in_progress"),
    "refine": ("Needs Refinement", "needs_refinement"),
}
STATUS_TAGS = {"needs_refinement", "to_do", "reopen", "in_progress", "in_review", "ready_for_qa", "in_qa", "accepted", "closed"}
KEY_RE = re.compile(r"DEV-\d+")
PLANNING_RE = re.compile(r"^\s*(DEADLINE|SCHEDULED|CLOSED):")
OPEN_BULLET = "- Open: "


@dataclass
class Edit:
    file: Path  # real path (symlink resolved)
    idx: int  # 0-based line index when the edit is applied, in order
    before: str
    after: str
    kind: str = "replace"  # replace | insert | move
    to: int | None = None  # move: index of the target bucket heading


def _apply(doc: OrgDoc, e: Edit) -> None:
    if e.kind == "replace":
        doc.replace_line(e.idx, e.after)
    elif e.kind == "insert":
        doc.insert(e.idx, [e.after])
    elif e.kind == "move":
        doc.move_section(e.idx, e.to)
    else:  # pragma: no cover
        raise ValueError(e.kind)


def match_entry(row: Row, ledger: dict) -> tuple[str, dict] | None:
    locator = match_locator(row.cells[2], ledger)
    return (locator, ledger[locator]) if locator else None


def _day_range(doc: OrgDoc, day: str) -> tuple[int, int] | None:
    try:
        idx = doc.find_day(date.fromisoformat(day))
    except ValueError:
        idx = None
    return (idx, doc.section_end(idx)) if idx is not None else None


def _find_headline(doc: OrgDoc, entry: dict) -> int | None:
    rng = _day_range(doc, entry.get("day", ""))
    if rng and (i := doc.find_headline(entry["headline"], *rng)) is not None:
        return i
    return doc.find_headline(entry["headline"])


def _find_bullet(doc: OrgDoc, entry: dict) -> int | None:
    want = OPEN_BULLET + entry["text"]
    rng = _day_range(doc, entry.get("day", "")) or (0, len(doc.lines))
    for start, end in (rng, (0, len(doc.lines))):
        for i in range(start, end):
            if doc.lines[i].strip() == want:
                return i
    return None


def _anchor(doc: OrgDoc, idx: int) -> int | None:
    """The headline at `idx` or the nearest one above it."""
    for j in range(idx, -1, -1):
        if doc.level_at(j):
            return j
    return None


def resolve_key(entry: dict, row: Row, doc: OrgDoc, hidx: int | None) -> str | None:
    """Entry's jira, then DEV-N typed in WHAT, then in the worklog headline, then in its ancestors."""
    if entry.get("jira"):
        return entry["jira"]
    if m := KEY_RE.search(row.cells[2]):
        return m.group(0)
    if hidx is None:
        return None
    if m := KEY_RE.search(doc.lines[hidx]):
        return m.group(0)
    level = doc.level_at(hidx)
    for j in range(hidx - 1, -1, -1):
        lj = doc.level_at(j)
        if lj and lj < level:
            if m := KEY_RE.search(doc.lines[j]):
                return m.group(0)
            level = lj
            if level == 1:
                break
    return None


class _Sync:
    def __init__(self, paths: Paths, now: datetime):
        self.paths, self.now = paths, now
        self.docs: dict[Path, OrgDoc] = {}
        self.edits: list[Edit] = []
        self.logs: list[str] = []

    def real(self, file: Path) -> Path:
        return file.resolve() if file.is_symlink() else file

    def doc(self, file: Path) -> OrgDoc:
        real = self.real(file)
        if real not in self.docs:
            self.docs[real] = OrgDoc.load(real)
        return self.docs[real]

    def rel(self, file: Path) -> str:
        try:
            return str(file.relative_to(self.paths.org_dir))
        except ValueError:
            return file.name

    def edit(self, file: Path, e: Edit) -> None:
        _apply(self.doc(file), e)
        self.edits.append(e)
        self.logs.append(f"done-sync: {self.rel(file)}:{e.idx + 1} {e.before} -> {e.after}")

    # --- worklog ---------------------------------------------------------------

    def worklog(self, entry: dict, locator: str) -> tuple[OrgDoc, int] | None:
        """Flip the item; return (doc, anchor headline index) or None when the item is not there."""
        file = self.paths.org_dir / entry["file"]
        doc = self.doc(file)
        if entry.get("kind") == "bullet":
            b = _find_bullet(doc, entry)
            if b is None:
                self.logs.append(f"done-sync: {locator}: worklog item not found, skipped")
                return None
            before = doc.lines[b]
            after = before.replace(OPEN_BULLET, f"- Resolved [{self.now:%Y-%m-%d}]: ", 1)
            self.edit(file, Edit(self.real(file), b, before, after))
            return doc, _anchor(doc, b)
        h = _find_headline(doc, entry)
        if h is None:
            self.logs.append(f"done-sync: {locator}: worklog item not found, skipped")
            return None
        level, keyword, _, _ = headline_parts(doc.lines[h])
        if keyword != "DONE":
            before = doc.lines[h]
            after = doc.set_keyword(h, "DONE")
            doc.lines[h] = before  # edit() applies it
            self.edit(file, Edit(self.real(file), h, before, after))
        stamp = f"CLOSED: [{self.now:%Y-%m-%d %a %H:%M}]"
        nxt = doc.lines[h + 1] if h + 1 < len(doc.lines) else ""
        if nxt.strip().startswith("CLOSED:"):
            return doc, h
        indent = " " * (level + 1)
        if PLANNING_RE.match(nxt):
            self.edit(file, Edit(self.real(file), h + 1, nxt, f"{indent}{stamp} {nxt.strip()}"))
        else:
            self.edit(file, Edit(self.real(file), h + 1, "", f"{indent}{stamp}", kind="insert"))
        return doc, h

    # --- tron ------------------------------------------------------------------

    def tron(self, key: str, word: str) -> None:
        if word not in DONE_WORDS:
            self.logs.append(f"done-sync: {key}: unknown DONE word '{word}', tron untouched")
            return
        bucket, tag = DONE_WORDS[word]
        file = self.paths.tron_tasks
        doc = self.doc(file)
        hits = [i for i, l in enumerate(doc.lines) if doc.level_at(i) and key in l]
        if not hits:
            self.logs.append(f"done-sync: {key}: not found in tron-tasks.org, tron untouched")
            return
        t = hits[0]
        for extra in hits[1:]:
            self.logs.append(f"done-sync: {key}: also on tron-tasks.org:{extra + 1}, left alone")
        if doc.level_at(t) == 2:
            target = next((i for i, l in enumerate(doc.lines) if l.rstrip() == f"* {bucket}"), None)
            if target is None:
                self.logs.append(f"done-sync: {key}: bucket '* {bucket}' not in tron-tasks.org, tron untouched")
                return
            if _anchor_level1(doc, t) == target:
                self.logs.append(f"done-sync: {key}: already under * {bucket}")
                return
            self.edit(file, Edit(self.real(file), t, doc.lines[t], f"* {bucket}", kind="move", to=target))
            return
        if tag is None:
            self.logs.append(f"done-sync: {key}: '{word}' has no sub-task tag, unchanged")
            return
        _, _, _, tags = headline_parts(doc.lines[t])
        new = [tag] + [x for x in tags if x not in STATUS_TAGS]
        if new == tags:
            self.logs.append(f"done-sync: {key}: already :{tag}:")
            return
        before = doc.lines[t]
        after = doc.set_tags(t, new)
        doc.lines[t] = before
        self.edit(file, Edit(self.real(file), t, before, after))


def _anchor_level1(doc: OrgDoc, idx: int) -> int | None:
    for j in range(idx, -1, -1):
        if doc.level_at(j) == 1:
            return j
    return None


def plan(paths: Paths, state: State, now: datetime) -> tuple[list[Edit], list[str], dict[str, str]]:
    """Simulate every edit on in-memory copies (so later indexes are right) and return them with the
    log lines and the {locator: done_at} map to record once the edits are saved."""
    s = _Sync(paths, now)
    done: dict[str, str] = {}
    if not paths.ledger.exists():
        return [], [], {}
    for row in rows(OrgDoc.load(paths.ledger)):
        word = normalize_done(row.cells[4])
        if word is None:
            continue
        m = match_entry(row, state.ledger)
        if m is None:
            continue
        locator, entry = m
        if entry.get("done_at"):
            continue
        hit = s.worklog(entry, locator)
        if hit is None:
            continue
        doc, hidx = hit
        key = resolve_key(entry, row, doc, hidx)
        if key:
            s.tron(key, word)
        done[locator] = now.isoformat(timespec="minutes")
    return s.edits, s.logs, done


def apply(edits: list[Edit], done: dict[str, str], state: State, *, dry_run: bool) -> None:
    files = list(dict.fromkeys(e.file for e in edits))
    if dry_run:
        return
    for f in files:
        if _recently_saved(f, state):
            raise MtimeGuard(f"{f} was saved recently; retry later")
    docs = {f: OrgDoc.load(f) for f in files}
    for e in edits:
        _apply(docs[e.file], e)
    for f, doc in docs.items():
        doc.save_atomic(f)
        state.own_saves[str(f)] = f.stat().st_mtime_ns
    for locator, at in done.items():
        state.ledger[locator]["done_at"] = at
    state.save()


class MtimeGuard(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", type=datetime.fromisoformat, default=None)
    add_org_dir_arg(ap)
    args = parse_args_or_none(ap, argv)
    if args is None:
        return 1
    paths = paths_from_args(args)
    now = args.now or datetime.now()
    state = State.load(paths.state_file)
    edits, logs, done = plan(paths, state, now)
    for line in logs:
        print(line)
    if not edits:
        print("done-sync: nothing to do")
        return EXIT_NOTHING
    try:
        apply(edits, done, state, dry_run=args.dry_run)
    except MtimeGuard as exc:
        print(f"done-sync: skipped: {exc}", file=sys.stderr)
        return EXIT_GUARD
    print(f"done-sync: {'would apply' if args.dry_run else 'applied'} {len(edits)} edit(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
