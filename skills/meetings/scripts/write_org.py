"""Land a digest in the org files: meeting block under its day (merged into a matching hand-written
heading or as a new :auto: heading) plus one SCHEDULED item per dated follow-up under its target day.

Every landed item (action item, follow-up, open question) also lands as a row in action-items.org,
with a ledger entry in state.json keyed by the row's locator link (see ledger.py).

Only additions are made. Every write carries a key `<digest key>|<file>|<heading path>` recorded in
state.json, so reruns are no-ops. Files saved by something other than this writer within the last
GUARD_MINUTES are not touched (exit 3) unless --force: nvim does not reload a file that changes under
it. Our own saves are recognized by mtime (state.own_saves), so several digests can land in one run.

Usage: write_org.py <digest.json> --key <key> [--dry-run] [--force] [--now ISO] [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from config import Paths, add_org_dir_arg, parse_args_or_none, paths_from_args
from digest import normalize_digest
from ledger import (
    CATEGORIES,
    HEADER,
    HEADING,
    PREAMBLE,
    RULE,
    link_targets_in_use,
    own_entry,
    realign,
    row_lines,
    section_index,
    short_target,
    table_bounds,
    what_cell,
)
from orgfile import plain_title, OrgDoc
from people import People
from render import (
    followup_headline,
    followup_item,
    item_headline,
    match_heading,
    meeting_block,
    meeting_body,
    meeting_children,
    org_date,
)
from state import State

CHAT_GROUP = "Slack"
JIRA_KEY_RE = re.compile(r"[A-Z][A-Z0-9]+-\d+")

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
    ledger_entry: dict | None = None  # set on an action-items.org row write; recorded in state.ledger


def target_file(paths: Paths, d: date, today: date) -> Path:
    """Current month or later -> worklog.org. An earlier month -> worklog.org while that month is still
    in it (early-month runs land late transcripts), else that month's archive file."""
    if (d.year, d.month) >= (today.year, today.month):
        return paths.worklog
    if paths.worklog.exists():
        for _, dd in OrgDoc.load(paths.worklog).day_headers():
            if (dd.year, dd.month) == (d.year, d.month):
                return paths.worklog
    return paths.archive_for(d)


def _append_point(doc: OrgDoc, idx: int) -> int:
    """Where to add children to the subtree at `idx`: its end, before any trailing blank lines."""
    end = doc.section_end(idx)
    while end - 1 > idx and doc.lines[end - 1] == "":
        end -= 1
    return end


def _body_end(doc: OrgDoc, idx: int) -> int:
    """End of the heading's own body: just before its first child headline (or the subtree end)."""
    end = doc.section_end(idx)
    for j in range(idx + 1, end):
        if doc.level_at(j):
            end = j
            break
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

    def add(self, file: Path, at: int, lines: list[str], path: str, entry: dict | None = None) -> None:
        """Insert in the in-memory doc (so later positions are right) and record the write."""
        wk = f"{self.key}|{file.name}|{path}"
        if wk in self.done:
            return
        self.doc(file).insert(at, lines)
        self.writes.append(Write(file, at, list(lines), wk, entry))

    def ledger_row(self, category: str, when: str, who: str, text: str, jira: str | None,
                   target: str, entry: dict, done: str = "") -> None:
        """Append a row to the category's table in action-items.org. A missing file gets the preamble
        and all five sections in order; a missing section is appended at the end; a section without a
        table gets a header."""
        file = self.paths.ledger
        doc = self.doc(file)
        if not doc.lines:
            skeleton = list(PREAMBLE)
            for _, heading in CATEGORIES:
                skeleton += [f"* {heading}", HEADER, RULE, ""]
            self.add(file, 0, skeleton, "ledger/skeleton")
        sec = section_index(doc, category)
        if sec is None:
            sec = len(doc.lines)
            self.add(file, sec, [f"* {HEADING[category]}", HEADER, RULE, ""], f"ledger/{category}/section")
        bounds = table_bounds(doc, sec)
        if bounds is None:
            self.add(file, sec + 1, [HEADER, RULE], f"ledger/{category}/header")
            bounds = (sec + 1, sec + 3)
        lines = row_lines(doc, sec, done, when, who, what_cell(text, jira, target))
        self.add(file, bounds[1], lines, f"{category}/{entry['locator']}", entry=entry)

    def group(self, file: Path, day_idx: int, d: date, name: str = CHAT_GROUP) -> int:
        """Find or create the day's `** <name> :chat:auto:` heading that chat blocks nest under."""
        doc = self.doc(file)
        for h in doc.headings(day_idx, 2):
            if plain_title(h.title) == name:
                return h.idx
        at = _append_point(doc, day_idx)
        self.add(file, at, [f"** {name} :chat:auto:"], f"{d.isoformat()}/{name}/group")
        return at

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
    ledger: dict | None = None,
) -> list[Write]:
    """`ledger` is state.ledger: existing locators, so a repeated item gets a ` (2)` suffix."""
    today = today or now.date()
    ledger = ledger or {}
    d = date.fromisoformat(digest["date"])
    p = _Planner(key, paths, frozenset(done))

    file = target_file(paths, d, today)
    link_file = str(file.relative_to(paths.org_dir))
    taken = link_targets_in_use(ledger, exclude_key=key)  # other digests' targets; my own are recomputed
    planned: set[str] = set()

    def unique(obj: dict, locator_of) -> str:
        """Suffix obj['text'] with ` (n)` until its locator is unused (or is this digest's own)."""
        base, n = obj["text"], 1
        while True:
            loc = locator_of(taken | planned)
            prior = ledger.get(loc)
            if loc not in planned and (prior is None or str(prior.get("key", "")).split("|")[0] == key):
                planned.add(loc)
                return loc
            n += 1
            obj["text"] = f"{base} ({n})"

    def target_for(rel: str, headline: str, tk: set[str], title: str | None = None) -> str:
        """A rerun keeps the locator its earlier row already carries (looked up by the stored headline);
        a new item gets a short target from `title` (the headline minus its Jira link) or the headline."""
        mine = own_entry(ledger, key, rel, headline)
        return mine["locator"] if mine else short_target(rel, title or headline, tk)

    marker_headline = meeting_body(digest, people, now)[0].split(" ", 1)[1]
    marker_target = short_target(link_file, marker_headline, taken)
    item_targets = [unique(it, lambda tk: target_for(link_file, item_headline(it, people), tk, _locator_title(it, people)))
                    for it in digest.get("action_items") or []]
    fu_files = [target_file(paths, date.fromisoformat(fu["when"]), today) if fu.get("when") else file for fu in digest.get("follow_ups") or []]
    fu_targets = [unique(fu, lambda tk: target_for(str(ff.relative_to(paths.org_dir)), followup_headline(fu, people), tk))
                  for fu, ff in zip(digest.get("follow_ups") or [], fu_files)]
    oq_locators = [unique(q, lambda tk: f"{marker_target}::Open: {q['text']}") for q in digest.get("open_questions") or []]

    doc = p.doc(file)
    day_idx = p.day(file, d)
    # a chat day never merges into a hand-written heading: a DM with Rob is not the "Rob 1-1" notes
    match = None if digest.get("kind") == "chat" else match_heading(
        digest["title"], digest.get("attendees") or [], doc.headings(day_idx, 2), people)
    if match:
        # bullets go in the heading's own body (before any *** children I already wrote);
        # the *** items go at the end of the subtree
        heading_title = match.title
        p.add(file, _body_end(doc, match.idx), meeting_body(digest, people, now), f"{d.isoformat()}/{heading_title}")
        children = meeting_children(digest, people)
        if children:
            p.add(file, _append_point(doc, match.idx), children, f"{d.isoformat()}/{heading_title}/items")
    elif digest.get("kind") == "chat":
        # every conversation of the day sits one level down inside a single `** Slack` group
        heading_title = digest["title"]
        group_idx = p.group(file, day_idx, d)
        p.add(file, _append_point(doc, group_idx), meeting_block(digest, people, now, new_heading=True, level=3),
              f"{d.isoformat()}/{heading_title}")
    else:
        heading_title = digest["title"]
        p.add(file, _append_point(doc, day_idx), meeting_block(digest, people, now, new_heading=True), f"{d.isoformat()}/{heading_title}")

    digest["landed"] = {"file": link_file, "heading": heading_title}  # for suggest.py's backlink
    linked = {**digest, "title": heading_title}
    for i, fu in enumerate(digest.get("follow_ups") or []):
        if not fu.get("when"):
            continue
        when = date.fromisoformat(fu["when"])
        fu_file = fu_files[i]
        fu_day = p.day(fu_file, when)
        p.add(fu_file, _append_point(p.doc(fu_file), fu_day), followup_item(fu, linked, people, link_file),
              f"{when.isoformat()}/followup/{i}")

    # --- ledger rows, one per item, after the worklog writes
    heading_key = match.link if match and match.link and JIRA_KEY_RE.fullmatch(match.link) else None

    def entry(locator: str, kind: str, file_rel: str, day: date, headline: str, text: str,
              jira: str | None, jira_source: str | None, category: str) -> dict:
        return {"locator": locator, "key": f"{key}|{paths.ledger.name}|{category}/{locator}", "file": file_rel,
                "day": day.isoformat(), "kind": kind, "headline": headline, "text": text, "jira": jira,
                "jira_source": jira_source, "category": category, "done_at": None}

    for it, target in zip(digest.get("action_items") or [], item_targets):
        jira, source = (it.get("jira"), "digest") if it.get("jira") else (heading_key, "heading" if heading_key else None)
        cat = it.get("category") or ("commitment" if people.is_me(it.get("owner")) else "waiting_on")
        who = f"@{people.resolve(it.get('owner')) or it.get('owner') or '?'}"
        when = org_date(date.fromisoformat(it["due"])) if it.get("due") else ""
        p.ledger_row(cat, when, who, it["text"], jira, target,
                     entry(target, "headline", link_file, d, item_headline(it, people), it["text"], jira, source, cat))
    for fu, ff, target in zip(digest.get("follow_ups") or [], fu_files, fu_targets):
        cat = fu.get("category") or "follow_up"
        who = ", ".join(f"@{people.resolve(w) or w}" for w in fu.get("with") or []) or "@?"
        when_d = date.fromisoformat(fu["when"]) if fu.get("when") else None
        p.ledger_row(cat, org_date(when_d) if when_d else "", who, fu["text"], heading_key, target,
                     entry(target, "headline", str(ff.relative_to(paths.org_dir)), when_d or d, followup_headline(fu, people),
                           fu["text"], heading_key, "heading" if heading_key else None, cat))
    for q, locator in zip(digest.get("open_questions") or [], oq_locators):
        cat = q.get("category") or "open_question"
        p.ledger_row(cat, "", "", q["text"], heading_key, marker_target,
                     entry(locator, "bullet", link_file, d, marker_headline, q["text"], heading_key,
                           "heading" if heading_key else None, cat))
    return p.writes


def _locator_title(item: dict, people: People) -> str:
    """`<text> - @Owner`: the headline minus its Jira link, which would nest brackets inside the row's
    link. nvim-orgmode resolves `::*` by prefix, so the shorter target still finds the headline."""
    return item_headline({**item, "jira": None}, people)


def _recently_saved(file: Path, state: State) -> bool:
    """Wall-clock check (not --now): the question is whether an editor may have the file open.
    A file exactly as our last write left it (same mtime) was not saved by an editor since."""
    if not file.exists():
        return False
    st = file.stat()
    if state.own_saves.get(str(file)) == st.st_mtime_ns:
        return False
    return time.time() - st.st_mtime < GUARD_MINUTES * 60


def apply(writes: list[Write], state: State, dry_run: bool = False, *, force: bool = False, now: datetime | None = None) -> int:
    """Replay `writes` in order on freshly loaded files. Returns the number applied (or printed)."""
    now = now or datetime.now()
    todo = [w for w in writes if w.write_key not in state.processed]
    if not todo:
        return 0
    files = list(dict.fromkeys(w.file for w in todo))
    if not dry_run and not force:
        for f in files:
            if _recently_saved(f, state):
                raise MtimeGuard(f"{f} was saved less than {GUARD_MINUTES} min ago; retry later or --force")
    docs = {f: OrgDoc.load(f) for f in files}
    touched: set[tuple[Path, str]] = set()
    for w in todo:
        if dry_run:
            print(f"== {w.file}:{w.insert_at + 1}")
            print("\n".join(w.lines))
            continue
        docs[w.file].insert(w.insert_at, w.lines)
        state.processed[w.write_key] = {"file": str(w.file), "line": w.insert_at + 1, "at": now.isoformat(timespec="minutes")}
        if w.ledger_entry:
            state.ledger[w.ledger_entry["locator"]] = w.ledger_entry
            touched.add((w.file, w.ledger_entry["category"]))
    if not dry_run:
        for f, category in touched:
            sec = section_index(docs[f], category)
            if sec is not None:
                realign(docs[f], sec)
        for f, doc in docs.items():
            doc.save_atomic(f)
            state.own_saves[str(f)] = f.stat().st_mtime_ns
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
    args = parse_args_or_none(ap, argv)
    if args is None:
        return 1
    paths = paths_from_args(args)
    now = args.now or datetime.now()
    digest = json.loads(args.digest.read_text(encoding="utf-8"))
    people = People.load(paths.people_file)
    state = State.load(paths.state_file)
    normalize_digest(digest, people)
    writes = plan_writes(digest, args.key, paths, people, now, today=args.today, done=set(state.processed), ledger=state.ledger)
    if not args.dry_run:
        args.digest.write_text(json.dumps(digest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        n = apply(writes, state, dry_run=args.dry_run, force=args.force, now=now)
    except MtimeGuard as exc:
        print(f"skipped: {exc}", file=sys.stderr)
        return EXIT_GUARD
    print(f"{'would write' if args.dry_run else 'wrote'} {n} block(s)")
    return 0 if n else EXIT_NOTHING


if __name__ == "__main__":
    sys.exit(main())
