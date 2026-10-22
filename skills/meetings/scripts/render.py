"""Render a digest into org lines, and match a digest against hand-written headings on its day."""

from __future__ import annotations

import re
from datetime import date, datetime

from config import JIRA_BROWSE
from orgfile import DOW, Heading
from people import People

STOPWORDS = {"meeting", "sync", "call", "with", "and", "the", "on", "re", "w", "a", "an", "of", "for"}
MATCH_THRESHOLD = 0.34
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[0-9]+)*")


def org_date(d: date) -> str:
    return f"<{d.isoformat()} {DOW[d.weekday()]}>"


def tokens(text: str) -> set[str]:
    """Lowercased word tokens; '-' survives only between digits ('1-1' stays one token)."""
    text = re.sub(r"(?<!\d)-|-(?!\d)", " ", text.lower())
    text = text.replace(":", "-") if re.search(r"\d:\d", text) else text
    return {t for t in _TOKEN_RE.findall(text) if t not in STOPWORDS}


def digest_tokens(title: str, attendees: list[str], people: People) -> set[str]:
    out = tokens(title)
    for name in attendees:
        canonical = people.resolve(name)
        if canonical and not people.is_me(canonical):
            out |= people.tokens_for(canonical)
        elif not canonical:
            out |= tokens(name)
    return out


def score_heading(digest_toks: set[str], heading_toks: set[str]) -> float:
    """Overlap coefficient |A∩B| / min(|A|,|B|): one strong shared token (an attendee alias)
    is enough to match a short hand-written heading; disjoint sets score 0."""
    if len(digest_toks) < 1 or len(heading_toks) < 1:
        return 0.0

    intersection = len(digest_toks.intersection(heading_toks))
    # union = len(digest_toks.union(heading_toks))
    return intersection/min([len(heading_toks), len(digest_toks)])


def match_heading(title: str, attendees: list[str], headings: list[Heading], people: People) -> Heading | None:
    dt = digest_tokens(title, attendees, people)
    best, best_score = None, 0.0
    for h in headings:
        if "auto" in h.tags:
            continue
        ht = tokens(h.title)
        if h.owner:
            ht |= tokens(h.owner)
        s = score_heading(dt, ht)
        if s > best_score:
            best, best_score = h, s
    return best if best_score >= MATCH_THRESHOLD else None


# --- rendering -----------------------------------------------------------


def _owner_suffix(owner: str | None, people: People) -> str:
    """@Roster name; an off-roster but named owner keeps the name as given; nobody named -> @?."""
    canonical = people.resolve(owner) if owner else None
    return f" - @{canonical or owner or '?'}"


def _jira_suffix(key: str | None) -> str:
    return f" - [[{JIRA_BROWSE}{key}][{key}]]" if key else ""


def _item_lines(item: dict, people: People) -> list[str]:
    mine = people.is_me(item.get("owner"))
    keyword = "TODO " if mine else ""
    head = f"*** {keyword}{item['text']}{_owner_suffix(item.get('owner'), people)}{_jira_suffix(item.get('jira'))} :auto:"
    lines = [head]
    if item.get("due"):
        lines.append(f"    DEADLINE: {org_date(date.fromisoformat(item['due']))}")
    return lines


def meeting_block(d: dict, people: People, now: datetime, new_heading: bool) -> list[str]:
    lines: list[str] = []
    if new_heading:
        lines.append(f"** {d['title']} :meeting:auto:")
    attendees = ", ".join(d.get("attendees") or [])
    lines.append(f"   - meetings (auto) {now.strftime('%Y-%m-%dT%H:%M')} · source: {d['source']} · attendees: {attendees}")
    lines.append(f"   - {d['summary'].strip()}")
    for dec in d.get("decisions") or []:
        by = f" — {people.resolve(dec.get('by')) or dec.get('by')}" if dec.get("by") else ""
        lines.append(f"   - Decided ({dec['firmness']}): {dec['text']}{by}")
    for q in d.get("open_questions") or []:
        lines.append(f"   - Open: {q}")
    for item in d.get("action_items") or []:
        lines.extend(_item_lines(item, people))
    for fu in d.get("follow_ups") or []:
        if fu.get("when"):
            continue  # dated follow-ups live under their target day (write_org)
        lines.append(f"*** TODO {fu['text']} - @{people.me} :auto:")
        lines.append("    - when: TBD")
    return lines


def followup_item(fu: dict, d: dict, people: People) -> list[str]:
    when = date.fromisoformat(fu["when"])
    return [
        f"** TODO {fu['text']} - @{people.me} :auto:",
        f"   SCHEDULED: {org_date(when)}",
        f"   - from: [[file:worklog.org::*{d['title']}][{d['date']} {d['title']}]]",
    ]
