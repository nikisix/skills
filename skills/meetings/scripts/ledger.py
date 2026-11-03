"""action-items.org: one table per category, rows appended by the writer, ticked by hand.

Row identity is the last `[[file:…][…]]` link in WHAT (the worklog locator). Realignment only
changes whitespace, so hand edits to any cell survive.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass

from config import JIRA_BROWSE, add_org_dir_arg, parse_args_or_none, paths_from_args
from orgfile import OrgDoc
from state import State

CATEGORIES: list[tuple[str, str]] = [
    ("decision", "Decision"),
    ("commitment", "Commitment"),
    ("waiting_on", "Waiting-on"),
    ("follow_up", "Follow-up"),
    ("open_question", "Open question"),
]
HEADING = dict(CATEGORIES)
PREAMBLE = ["#+TITLE: Action items", "#+STARTUP: showall", ""]
COLUMNS = ["WHEN", "WHO", "WHAT", "EFFORT", "DONE"]
HEADER = "| WHEN | WHO | WHAT | EFFORT | DONE |"
RULE = "|------+-----+------+--------+------|"

FILE_LINK_RE = re.compile(r"\[\[file:([^\]]+)\]\[[^\]]*\]\]")
DONE_X = {"x", "[x]", "done"}
BLANK_DONE = {"", "[]", "[ ]"}


@dataclass
class Row:
    category: str
    idx: int
    cells: list[str]


def split_cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip() for c in body.split("|")]


def is_rule(line: str) -> bool:
    s = line.strip()
    return s.startswith("|-") or s.startswith("|+")


def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def section_index(doc: OrgDoc, category: str) -> int | None:
    want = f"* {HEADING[category]}"
    for i, line in enumerate(doc.lines):
        if line.rstrip() == want:
            return i
    return None


def table_bounds(doc: OrgDoc, section_idx: int) -> tuple[int, int] | None:
    end = doc.section_end(section_idx)
    start = None
    for i in range(section_idx + 1, end):
        if _is_table_line(doc.lines[i]):
            start = i
            break
    if start is None:
        return None
    stop = start
    while stop < end and _is_table_line(doc.lines[stop]):
        stop += 1
    return start, stop


def _is_header(cells: list[str]) -> bool:
    return bool(cells) and cells[0].upper() == COLUMNS[0]


def rows(doc: OrgDoc) -> list[Row]:
    out: list[Row] = []
    for category, _ in CATEGORIES:
        sec = section_index(doc, category)
        if sec is None:
            continue
        bounds = table_bounds(doc, sec)
        if bounds is None:
            continue
        for i in range(*bounds):
            line = doc.lines[i]
            if is_rule(line):
                continue
            cells = split_cells(line)
            if _is_header(cells):
                continue
            while len(cells) < len(COLUMNS):
                cells.append("")
            out.append(Row(category, i, cells))
    return out


def realign(doc: OrgDoc, section_idx: int) -> None:
    bounds = table_bounds(doc, section_idx)
    if bounds is None:
        return
    start, stop = bounds
    parsed = {i: split_cells(doc.lines[i]) for i in range(start, stop) if not is_rule(doc.lines[i])}
    ncols = max([len(COLUMNS)] + [len(c) for c in parsed.values()])
    widths = [0] * ncols
    for cells in parsed.values():
        for k, c in enumerate(cells):
            widths[k] = max(widths[k], len(c))
    for i in range(start, stop):
        if is_rule(doc.lines[i]):
            doc.lines[i] = "|" + "+".join("-" * (w + 2) for w in widths) + "|"
        else:
            cells = parsed[i] + [""] * (ncols - len(parsed[i]))
            doc.lines[i] = "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths)) + " |"


def link_target(file_rel: str, headline: str) -> str:
    return f"{file_rel}::*{headline}"


def what_cell(text: str, jira: str | None, target: str) -> str:
    parts = [text]
    if jira:
        parts.append(f"[[{JIRA_BROWSE}{jira}][{jira}]]")
    parts.append(f"[[file:{target}][↗]]")
    return " ".join(parts).replace("|", "¦")


def last_link_target(cell: str) -> str | None:
    found = FILE_LINK_RE.findall(cell)
    return found[-1] if found else None


def row_line(when: str, who: str, what: str, effort: str, done: str = "") -> str:
    return f"| {when} | {who} | {what} | {effort} | {done} |"


def normalize_done(cell: str) -> str | None:
    s = cell.strip()
    if s in BLANK_DONE:
        return None
    low = s.lower()
    if low in DONE_X:
        return "x"
    return low


def report(doc: OrgDoc, ledger: dict) -> dict:
    out: dict = {}
    untracked = 0
    for row in rows(doc):
        bucket = out.setdefault(row.category, {"open": 0, "done": 0})
        entry = ledger.get(last_link_target(row.cells[2]) or "")
        if entry is None:
            untracked += 1
        elif entry.get("done_at"):
            bucket["done"] += 1
        else:
            bucket["open"] += 1
    out["untracked"] = untracked
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Summarize action-items.org against the ledger state.")
    add_org_dir_arg(parser)
    args = parse_args_or_none(parser, argv)
    if args is None:
        return 1
    paths = paths_from_args(args)
    doc = OrgDoc.load(paths.ledger)
    state = State.load(paths.state_file)
    rep = report(doc, state.ledger)
    for category, heading in CATEGORIES:
        if category in rep:
            print(f"{heading}: {rep[category]['open']} open, {rep[category]['done']} done")
    print(f"untracked rows: {rep['untracked']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
