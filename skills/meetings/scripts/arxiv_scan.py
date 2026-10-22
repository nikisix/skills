"""Weekly arXiv scan: open work items -> queries (claude -p, cached) -> arxiv search -> relevance gate
(claude -p) -> `* arXiv` section of suggested-tron-tasks.org. Seen ids live in state.arxiv_seen.

Usage: arxiv_scan.py [--since YYYY-MM-DD] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from config import Paths, add_org_dir_arg, paths_from_args
from digest import SKILL_DIR, extract_json, run_claude
from orgfile import Heading, OrgDoc
from state import State
from suggest import TEMPLATE

QUERIES_PROMPT = SKILL_DIR / "references" / "arxiv-queries-prompt.md"
GATE_PROMPT = SKILL_DIR / "references" / "arxiv-gate-prompt.md"
TRON_SECTIONS = ("In Progress", "To Do")
OPEN_KEYWORDS = ("TODO", "INPROGRESS")
FIRST_RUN_DAYS = 30
CS_CATEGORIES = ("cs.CL", "cs.AI", "cs.IR", "cs.LG", "cs.CV", "cs.SE", "cs.DB", "cs.HC")
EXIT_NOTHING = 2
_ORG_LINK = re.compile(r"\[\[([^\]]+?)\](?:\[([^\]]+)\])?\]")


@dataclass(frozen=True)
class Paper:
    id: str
    title: str
    abstract: str
    url: str
    published: date


@dataclass(frozen=True)
class Hit:
    paper: Paper
    item: str
    why: str


def _clean_title(title: str) -> str:
    return _ORG_LINK.sub(lambda m: m.group(2) or m.group(1), title).strip()


def _top_sections(doc: OrgDoc) -> list[tuple[int, str]]:
    return [(i, line[2:].strip()) for i, line in enumerate(doc.lines) if line.startswith("* ")]


def collect_work_items(paths: Paths) -> list[str]:
    """`**` titles under tron-tasks In Progress / To Do, plus worklog TODO/INPROGRESS day items and
    everything under the worklog's `* TODO` section. Owners and links are stripped; order kept."""
    items: list[str] = []

    def take(doc: OrgDoc, sec_idx: int, keywords: tuple[str, ...] | None) -> None:
        for h in doc.headings(sec_idx, 2):
            if keywords is None or h.keyword in keywords:
                t = _clean_title(h.title)
                if t and t not in items:
                    items.append(t)

    if paths.tron_tasks.exists():
        doc = OrgDoc.load(paths.tron_tasks)
        for idx, name in _top_sections(doc):
            if name in TRON_SECTIONS:
                take(doc, idx, None)
    if paths.worklog.exists():
        doc = OrgDoc.load(paths.worklog)
        for idx, _ in doc.day_headers():
            take(doc, idx, OPEN_KEYWORDS)
        for idx, name in _top_sections(doc):
            if name == "TODO":
                take(doc, idx, None)
    return items


def item_hash(item: str) -> str:
    return hashlib.sha256(item.encode("utf-8")).hexdigest()[:16]


def queries_for(items: list[str], state: State, run: Callable[[str], str] = run_claude) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    missing = []
    for item in items:
        cached = state.arxiv_queries.get(item_hash(item))
        if cached:
            out[item] = cached
        else:
            missing.append(item)
    if missing:
        prompt = QUERIES_PROMPT.read_text().replace("{{ITEMS}}", "\n".join(f"- {m}" for m in missing))
        data = extract_json(run(prompt))
        for item in missing:
            qs = [str(q) for q in (data.get(item) or [])][:2] or [item]
            state.arxiv_queries[item_hash(item)] = qs
            out[item] = qs
    return out


def build_query(query: str) -> str:
    """A bare multi-word query sorted by date matches any one word; AND the terms and stay in cs.*."""
    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    cats = " OR ".join(f"cat:{c}" for c in CS_CATEGORIES)
    return " AND ".join(f"all:{t}" for t in terms) + f" AND ({cats})"


def search(query: str, since: date, max_results: int = 20) -> list[Paper]:
    import arxiv

    client = arxiv.Client()
    s = arxiv.Search(query=build_query(query), max_results=max_results, sort_by=arxiv.SortCriterion.SubmittedDate)
    out = []
    for r in client.results(s):
        if r.published.date() < since:
            continue
        pid = re.sub(r"v\d+$", "", r.get_short_id())
        out.append(Paper(pid, r.title.strip(), r.summary.strip(), f"https://arxiv.org/abs/{pid}", r.published.date()))
    return out


def gate(items: list[str], papers: list[Paper], run: Callable[[str], str] = run_claude) -> list[Hit]:
    if not papers or not items:
        return []
    by_id = {p.id: p for p in papers}
    listing = "\n\n".join(f"[{p.id}] {p.title}\n{p.abstract[:1200]}" for p in papers)
    prompt = (
        GATE_PROMPT.read_text()
        .replace("{{ITEMS}}", "\n".join(f"- {i}" for i in items))
        .replace("{{PAPERS}}", listing)
    )
    data = extract_json(run(prompt))
    hits = []
    for h in data.get("hits") or []:
        p = by_id.get(str(h.get("id", "")).strip())
        if p and h.get("item") in items:
            hits.append(Hit(p, h["item"], str(h.get("why", "")).strip()))
    return hits


def _arxiv_section(doc: OrgDoc) -> int:
    for i, line in enumerate(doc.lines):
        if line == "* arXiv":
            return i
    doc.lines.extend(["* arXiv", ""] if doc.lines else TEMPLATE)
    return _arxiv_section(doc)


def _append_point(doc: OrgDoc, idx: int) -> int:
    end = doc.section_end(idx)
    while end - 1 > idx and doc.lines[end - 1] == "":
        end -= 1
    return end


def render_hit(h: Hit) -> list[str]:
    return [
        f"** {h.paper.title} — relevant to: {h.item} :auto:",
        f"   - [[{h.paper.url}][arXiv:{h.paper.id}]] · {h.paper.published.isoformat()} · {h.why}",
    ]


def append_hits(paths: Paths, hits: list[Hit], state: State, dry_run: bool = False) -> int:
    doc = OrgDoc.load(paths.suggestions) if paths.suggestions.exists() else OrgDoc(list(TEMPLATE))
    sec = _arxiv_section(doc)
    n = 0
    for h in hits:
        if h.paper.id in state.arxiv_seen:
            continue
        lines = render_hit(h)
        at = _append_point(doc, sec)
        if dry_run:
            print(f"== {paths.suggestions}:{at + 1}")
            print("\n".join(lines))
        else:
            doc.insert(at, lines)
            state.arxiv_seen.add(h.paper.id)
        n += 1
    if n and not dry_run:
        doc.save_atomic(paths.suggestions)
        state.save()
    return n


def scan(paths: Paths, state: State, since: date, today: date, dry_run: bool = False) -> int:
    items = collect_work_items(paths)
    if not items:
        print("no open work items", file=sys.stderr)
        return 0
    queries = queries_for(items, state)
    papers: dict[str, Paper] = {}
    for item, qs in queries.items():
        for q in qs:
            for p in search(q, since):
                if p.id not in state.arxiv_seen:
                    papers.setdefault(p.id, p)
    print(f"{len(items)} items, {sum(len(q) for q in queries.values())} queries, {len(papers)} new papers since {since}", file=sys.stderr)
    hits = gate(items, list(papers.values()))
    n = append_hits(paths, hits, state, dry_run=dry_run)
    if not dry_run:
        state.last_arxiv_run = today.isoformat()
        state.save()
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", type=date.fromisoformat, default=None)
    ap.add_argument("--dry-run", action="store_true")
    add_org_dir_arg(ap)
    args = ap.parse_args(argv)
    paths = paths_from_args(args)
    state = State.load(paths.state_file)
    today = date.today()
    since = args.since or (date.fromisoformat(state.last_arxiv_run) if state.last_arxiv_run else today - timedelta(days=FIRST_RUN_DAYS))
    n = scan(paths, state, since, today, dry_run=args.dry_run)
    print(f"{'would add' if args.dry_run else 'added'} {n} paper(s)")
    return 0 if n else EXIT_NOTHING


if __name__ == "__main__":
    sys.exit(main())
