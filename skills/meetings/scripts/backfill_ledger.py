"""One-time ledger backfill: classify every digest on disk that predates `category`/`effort`, persist
the fields into the digest file, and append one action-items.org row per item that was landed (its
worklog write key is in state.processed and its headline is still in the file). A headline already
marked DONE gets `x` in the row and `done_at` now. Worklog lines are not retro-tagged.

Usage: backfill_ledger.py [--since YYYY-MM-DD] [--dry-run] [--now ISO]
exit 0 rows appended · 2 nothing to do · 3 mtime guard
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from config import Paths, add_org_dir_arg, parse_args_or_none, paths_from_args
from digest import CATEGORIES, EFFORTS, SKILL_DIR, extract_json, run_claude, ticket_candidates, validate
from ledger import link_target
from orgfile import OrgDoc, headline_parts, plain_title
from people import People
from render import followup_headline, item_headline, org_date
from state import State
from write_org import EXIT_GUARD, EXIT_NOTHING, MtimeGuard, _Planner, _locator_title, apply

CLASSIFY_PROMPT_PATH = SKILL_DIR / "references" / "classify-prompt.md"
KEY_RE = re.compile(r"[A-Z][A-Z0-9]+-\d+")
MARKER_PREFIX = "meetings (auto) "


# --- classification ----------------------------------------------------------


def needs_classification(d: dict) -> bool:
    items = list(d.get("action_items") or []) + list(d.get("follow_ups") or [])
    if any("category" not in it for it in items):
        return True
    return any(not isinstance(q, dict) or "category" not in q for q in d.get("open_questions") or [])


def _items_block(d: dict) -> str:
    def q_text(q):
        return q.get("text") if isinstance(q, dict) else str(q)

    payload = {
        "action_items": [{"text": it.get("text"), "owner": it.get("owner"), "due": it.get("due"), "jira": it.get("jira")}
                         for it in d.get("action_items") or []],
        "follow_ups": [{"text": fu.get("text"), "with": fu.get("with"), "when": fu.get("when")} for fu in d.get("follow_ups") or []],
        "open_questions": [{"text": q_text(q)} for q in d.get("open_questions") or []],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def build_classify_prompt(d: dict, tickets: list[str], people: People) -> str:
    tmpl = CLASSIFY_PROMPT_PATH.read_text(encoding="utf-8")
    ticket_lines = "\n".join(f"  - {t}" for t in tickets) or "  - (none)"
    return (
        tmpl.replace("{{ME}}", people.me)
        .replace("{{TICKETS}}", ticket_lines)
        .replace("{{TITLE}}", str(d.get("title", "")))
        .replace("{{DATE}}", str(d.get("date", "")))
        .replace("{{SOURCE}}", str(d.get("source", "")))
        .replace("{{ATTENDEES}}", ", ".join(d.get("attendees") or []))
        .replace("{{SUMMARY}}", str(d.get("summary", "")))
        .replace("{{ITEMS}}", _items_block(d))
    )


def _check_answer(answer: dict, d: dict) -> list[str]:
    errors: list[str] = []
    for name in ("action_items", "follow_ups", "open_questions"):
        got = answer.get(name)
        want = len(d.get(name) or [])
        if not isinstance(got, list) or len(got) != want:
            errors.append(f"{name}: expected a list of {want} entries")
            continue
        for i, e in enumerate(got):
            if not isinstance(e, dict) or e.get("category") not in CATEGORIES:
                errors.append(f"{name}/{i}: category must be one of {', '.join(CATEGORIES)}")
            if isinstance(e, dict) and e.get("effort") not in (*EFFORTS, None):
                errors.append(f"{name}/{i}: effort must be S, M, L, or null")
    return errors


def classify(d: dict, tickets: list[str], run: Callable[[str], str] = run_claude, people: People | None = None) -> dict:
    """Fill category/effort (and a jira key from the tickets in play) into `d` in place. One retry
    with the validation errors appended, then ValueError."""
    people = people or People(me="Nick", aliases={})
    prompt = build_classify_prompt(d, tickets, people)
    allowed = {m.group(0) for t in tickets if (m := KEY_RE.match(t))}
    errors: list[str] = []
    for _ in range(2):
        raw = run(prompt)
        try:
            answer = extract_json(raw)
            errors = _check_answer(answer, d)
        except ValueError as exc:
            errors = [str(exc)]
        if not errors:
            break
        prompt += "\n\nYour previous output did not validate:\n- " + "\n- ".join(errors) + "\nReturn the corrected JSON object only."
    if errors:
        raise ValueError("classification did not validate: " + "; ".join(errors[:3]))
    for it, a in zip(d.get("action_items") or [], answer["action_items"]):
        it["category"], it["effort"] = a["category"], a.get("effort")
        if not it.get("jira") and a.get("jira") in allowed:
            it["jira"] = a["jira"]
    for fu, a in zip(d.get("follow_ups") or [], answer["follow_ups"]):
        fu["category"], fu["effort"] = a["category"], a.get("effort")
    qs = []
    for q, a in zip(d.get("open_questions") or [], answer["open_questions"]):
        text = q.get("text") if isinstance(q, dict) else str(q)
        qs.append({"text": text, "category": a["category"], "effort": a.get("effort")})
    d["open_questions"] = qs
    if schema_errors := validate({k: v for k, v in d.items() if k not in ("landed", "key")}):
        raise ValueError("classified digest does not validate: " + "; ".join(schema_errors[:3]))
    return d


# --- row planning for landed items --------------------------------------------


def landed_key(d: dict, state: State) -> str | None:
    """The digest key its worklog writes were recorded under: the digest's own `key`, else the
    processed key whose path is `<date>/<landed heading>` in the landed file."""
    landed = d.get("landed") or {}
    if not landed:
        return None
    want = f"|{Path(landed['file']).name}|{d['date']}/{landed['heading']}"
    for k in (d.get("key"), *state.processed):
        if k and k.endswith(want) and k.split("|")[0]:
            return k.split("|")[0]
    return None


def _block_bounds(doc: OrgDoc, d: dict) -> tuple[int, int] | None:
    """The landed heading's subtree under the digest's day."""
    day_idx = doc.find_day(date.fromisoformat(d["date"]))
    if day_idx is None:
        return None
    end = doc.section_end(day_idx)
    want = d["landed"]["heading"]
    for i in range(day_idx + 1, end):
        parts = headline_parts(doc.lines[i])
        if parts and plain_title(parts[2]) == plain_title(want):
            return i, doc.section_end(i)
    return None


def _marker(doc: OrgDoc, start: int, end: int, d: dict) -> int | None:
    tail = f"· source: {d.get('source')} · attendees: {', '.join(d.get('attendees') or [])}"
    first = None
    for i in range(start, end):
        parts = headline_parts(doc.lines[i])
        if parts and parts[2].startswith(MARKER_PREFIX):
            first = first if first is not None else i
            if parts[2].endswith(tail):
                return i
    return first


def plan_rows(d: dict, key: str, paths: Paths, people: People, state: State, now: datetime, log,
              landed_jira: list[str | None] | None = None) -> list:
    """Ledger writes for a landed digest: every item still present in its file gets a row. `landed_jira`
    is each action item's key at landing time (the classifier may have linked one since); the worklog
    headline is located and recorded in that form."""
    p = _Planner(key, paths, frozenset(state.processed))
    landed_file = paths.org_dir / d["landed"]["file"]
    link_file = d["landed"]["file"]
    doc = OrgDoc.load(landed_file)
    bounds = _block_bounds(doc, d)
    if bounds is None:
        log(f"backfill: {key}: landed heading not found in {link_file}, skipped")
        return []
    start, end = bounds
    day = d["date"]

    def entry(locator, kind, file_rel, day_s, headline, text, jira, category, done_at, jira_source="digest"):
        return {"locator": locator, "key": f"{key}|{paths.ledger.name}|{category}/{locator}", "file": file_rel, "day": day_s,
                "kind": kind, "headline": headline, "text": text, "jira": jira,
                "jira_source": jira_source if jira else None, "category": category, "done_at": done_at}

    def done_of(hdoc: OrgDoc, idx: int) -> tuple[str, str | None]:
        return ("x", now.isoformat(timespec="minutes")) if headline_parts(hdoc.lines[idx])[1] == "DONE" else ("", None)

    items = d.get("action_items") or []
    landed_jira = landed_jira if landed_jira is not None else [it.get("jira") for it in items]
    for it, was in zip(items, landed_jira):
        headline = item_headline({**it, "jira": was}, people)
        target = link_target(link_file, _locator_title(it, people))
        if target in state.ledger:
            continue
        h = doc.find_headline(headline, start, end)
        if h is None:
            log(f"backfill: {key}: '{headline}' not found in {link_file}, skipped")
            continue
        done, done_at = done_of(doc, h)
        cat = it.get("category") or ("commitment" if people.is_me(it.get("owner")) else "waiting_on")
        who = f"@{people.resolve(it.get('owner')) or it.get('owner') or '?'}"
        when = org_date(date.fromisoformat(it["due"])) if it.get("due") else ""
        p.ledger_row(cat, when, who, it["text"], it.get("jira"), it.get("effort") or "", target,
                     entry(target, "headline", link_file, day, headline, it["text"], it.get("jira"), cat, done_at,
                           "digest" if it.get("jira") == was else "classify"), done)
    for i, fu in enumerate(d.get("follow_ups") or []):
        headline = followup_headline(fu, people)
        cat = fu.get("category") or "follow_up"
        who = ", ".join(f"@{people.resolve(w) or w}" for w in fu.get("with") or []) or "@?"
        if fu.get("when"):
            when = date.fromisoformat(fu["when"])
            fdoc, frel = _file_with_day(paths, when)
            if fdoc is None or f"{key}|{Path(frel).name}|{when.isoformat()}/followup/{i}" not in state.processed:
                continue
            fday = fdoc.find_day(when)
            h = fdoc.find_headline(headline, fday, fdoc.section_end(fday))
            target = link_target(frel, headline)
            day_s, when_s, hdoc = when.isoformat(), org_date(when), fdoc
        else:
            h = doc.find_headline(headline, start, end)
            target = link_target(link_file, headline)
            day_s, when_s, hdoc, frel = day, "", doc, link_file
        if target in state.ledger:
            continue
        if h is None:
            log(f"backfill: {key}: '{headline}' not found in {frel}, skipped")
            continue
        done, done_at = done_of(hdoc, h)
        p.ledger_row(cat, when_s, who, fu["text"], None, fu.get("effort") or "", target,
                     entry(target, "headline", frel, day_s, headline, fu["text"], None, cat, done_at), done)
    qs = d.get("open_questions") or []
    if qs:
        m = _marker(doc, start, end, d)
        if m is None:
            log(f"backfill: {key}: no meetings (auto) marker under '{d['landed']['heading']}', open questions skipped")
        else:
            marker_headline = headline_parts(doc.lines[m])[2]
            marker_target = link_target(link_file, marker_headline)
            for q in qs:
                text = q.get("text") if isinstance(q, dict) else str(q)
                locator = f"{marker_target}::Open: {text}"
                if locator in state.ledger:
                    continue
                if not any(doc.lines[j].strip() == f"- Open: {text}" for j in range(m, doc.section_end(m))):
                    log(f"backfill: {key}: open question '{text}' not found under the marker, skipped")
                    continue
                cat = q.get("category", "open_question") if isinstance(q, dict) else "open_question"
                effort = (q.get("effort") if isinstance(q, dict) else None) or ""
                p.ledger_row(cat, "", "", text, None, effort, marker_target,
                             entry(locator, "bullet", link_file, day, marker_headline, text, None, cat, None))
    return p.writes


def _file_with_day(paths: Paths, when: date) -> tuple[OrgDoc | None, str]:
    """The worklog file that holds `when`'s day header: worklog.org, else that month's archive."""
    for f in (paths.worklog, paths.archive_for(when)):
        if f.exists():
            doc = OrgDoc.load(f)
            if doc.find_day(when) is not None:
                return doc, str(f.relative_to(paths.org_dir))
    return None, ""


# --- driver --------------------------------------------------------------------


def backfill(paths: Paths, state: State, people: People, since: date | None, dry_run: bool,
             run: Callable[[str], str] = run_claude, now: datetime | None = None) -> int:
    """Classify and row every landed digest on disk. Returns the number of rows appended (or that would
    be). Raises MtimeGuard when action-items.org was saved by hand in the last GUARD_MINUTES."""
    now = now or datetime.now()
    total = 0
    for dj in sorted(paths.digests.glob("*.json")):
        d = json.loads(dj.read_text(encoding="utf-8"))
        if not d.get("date") or (since and date.fromisoformat(d["date"]) < since):
            continue
        key = landed_key(d, state)
        if key is None:
            continue
        landed_jira = [it.get("jira") for it in d.get("action_items") or []]
        if needs_classification(d):
            classify(d, ticket_candidates(paths, date.fromisoformat(d["date"])), run=run, people=people)
            if not dry_run:
                dj.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        writes = plan_rows(d, key, paths, people, state, now, print, landed_jira)
        rows = [w for w in writes if w.ledger_entry]
        if not rows:
            continue
        apply(writes, state, dry_run=dry_run, now=now)
        total += len(rows)
    return total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", type=date.fromisoformat, default=None, help="only digests dated on/after this day")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", type=datetime.fromisoformat, default=None)
    add_org_dir_arg(ap)
    args = parse_args_or_none(ap, argv)
    if args is None:
        return 1
    paths = paths_from_args(args)
    people = People.load(paths.people_file)
    state = State.load(paths.state_file)
    try:
        n = backfill(paths, state, people, args.since, args.dry_run, run=run_claude, now=args.now)
    except MtimeGuard as exc:
        print(f"backfill: skipped: {exc}", file=sys.stderr)
        return EXIT_GUARD
    print(f"backfill: {'would append' if args.dry_run else 'appended'} {n} row(s)")
    return 0 if n else EXIT_NOTHING


if __name__ == "__main__":
    sys.exit(main())
