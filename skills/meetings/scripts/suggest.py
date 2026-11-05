"""Append ticket-worthy action items (no Jira key yet) to suggested-tron-tasks.org under `* Suggested`.

Headlines mirror tron-tasks.org (`** <text> - @Owner`) so accepting one is a cut/paste. An item whose
normalized headline already exists in tron-tasks.org or suggested-tron-tasks.org is skipped.

Usage: suggest.py <digest.json> [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from config import Paths, add_org_dir_arg, parse_args_or_none, paths_from_args
from orgfile import Heading, OrgDoc, org_text
from people import People

EXIT_NOTHING = 2
TEMPLATE = ["* Suggested", ""]
_WS = re.compile(r"\s+")


def normalize_headline(title: str) -> str:
    return _WS.sub(" ", title).strip().lower()


def existing_headlines(paths: Paths) -> set[str]:
    out: set[str] = set()
    for f in (paths.tron_tasks, paths.suggestions):
        if not f.exists():
            continue
        for i, line in enumerate(OrgDoc.load(f).lines):
            h = Heading.parse(i, line)
            if h and h.level == 2:
                out.add(normalize_headline(h.title))
    return out


def candidates(digest: dict) -> list[dict]:
    return [a for a in digest.get("action_items") or [] if a.get("ticket_worthy") and not a.get("jira")]


def render(item: dict, digest: dict, people: People | None = None) -> list[str]:
    owner = (people.resolve(item.get("owner")) if people else None) or item.get("owner") or (people.me if people else "Nick")
    why = re.split(r"(?<=[.!?])\s", org_text(digest["summary"]), maxsplit=1)[0]
    landed = digest.get("landed") or {}
    link_file, heading = landed.get("file", "worklog.org"), org_text(landed.get("heading", digest["title"]))
    return [
        f"** {org_text(item['text'])} - @{org_text(owner)} :auto:",
        f"   - source: [[file:{link_file}::*{heading}][{digest['date']} {heading}]]",
        f"   - why: {why}",
    ]


def _suggested_section(doc: OrgDoc) -> int:
    for i, line in enumerate(doc.lines):
        if line == "* Suggested":
            return i
    doc.insert(0, TEMPLATE)
    return 0


def _append_point(doc: OrgDoc, idx: int) -> int:
    end = doc.section_end(idx)
    while end - 1 > idx and doc.lines[end - 1] == "":
        end -= 1
    return end


def suggest(digest: dict, paths: Paths, people: People, dry_run: bool = False) -> int:
    """Returns the number of suggestions written (or printed)."""
    seen = existing_headlines(paths)
    doc = OrgDoc.load(paths.suggestions) if paths.suggestions.exists() else OrgDoc(list(TEMPLATE))
    sec = _suggested_section(doc)
    n = 0
    for item in candidates(digest):
        if normalize_headline(org_text(item["text"])) in seen:
            continue
        lines = render(item, digest, people)
        seen.add(normalize_headline(org_text(item["text"])))
        at = _append_point(doc, sec)
        if dry_run:
            print(f"== {paths.suggestions}:{at + 1}")
            print("\n".join(lines))
        else:
            doc.insert(at, lines)
        n += 1
    if not dry_run and (n or not paths.suggestions.exists()):
        doc.save_atomic(paths.suggestions)  # template is created even when nothing was suggested
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("digest", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    add_org_dir_arg(ap)
    args = parse_args_or_none(ap, argv)
    if args is None:
        return 1
    paths = paths_from_args(args)
    digest = json.loads(args.digest.read_text(encoding="utf-8"))
    n = suggest(digest, paths, People.load(paths.people_file), dry_run=args.dry_run)
    print(f"{'would suggest' if args.dry_run else 'suggested'} {n} ticket(s)")
    return 0 if n else EXIT_NOTHING


if __name__ == "__main__":
    sys.exit(main())
