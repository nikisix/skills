"""action-items.org: one table per category, rows appended by the writer, ticked by hand.

Columns: EFFORT, DONE, WHEN, WHO, WHAT. A table is at most MAX_WIDTH characters wide: a long WHAT is
wrapped onto continuation rows whose other four cells are blank, and `rows()` joins them back into
one logical row. Row identity is the last `[[file:…][…]]` link in WHAT (the worklog locator).
Realignment only changes whitespace, so hand edits to any cell survive.
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
COLUMNS = ["EFFORT", "DONE", "WHEN", "WHO", "WHAT"]
WHAT = COLUMNS.index("WHAT")
HEADER = "| EFFORT | DONE | WHEN | WHO | WHAT |"
RULE = "|--------+------+------+-----+------|"
MAX_WIDTH = 140
LOCATOR_MAX = 56  # link target length; `[[file:…][↗]]` adds 12, which must fit the WHAT column
TOKEN_RE = re.compile(r"\[\[.*?\]\]|\S+")

FILE_LINK_RE = re.compile(r"\[\[file:([^\]]+)\]\[[^\]]*\]\]")
DONE_X = {"x", "[x]", "done"}
BLANK_DONE = {"", "[]", "[ ]"}


@dataclass
class Row:
    """One logical row: `idx` is its first physical line, `end` one past its last (continuation
    rows included); `cells` are in COLUMNS order with WHAT joined."""
    category: str
    idx: int
    cells: list[str]
    end: int = 0

    def __post_init__(self):
        self.end = self.end or self.idx + 1

    @property
    def effort(self) -> str:
        return self.cells[0]

    @property
    def done(self) -> str:
        return self.cells[1]

    @property
    def when(self) -> str:
        return self.cells[2]

    @property
    def who(self) -> str:
        return self.cells[3]

    @property
    def what(self) -> str:
        return self.cells[WHAT]


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
    return bool(cells) and cells[0].upper() in COLUMNS


def _is_continuation(cells: list[str]) -> bool:
    return len(cells) >= len(COLUMNS) and not any(c for i, c in enumerate(cells) if i != WHAT)


def _complete(row: "Row") -> bool:
    """A row's WHAT ends with its `[[file:…][↗]]` link, which wrap_what never splits off; until the
    link has arrived, blank-celled lines that follow are its continuation."""
    return row.what.endswith("][↗]]")


def rows(doc: OrgDoc) -> list[Row]:
    out: list[Row] = []
    for category, _ in CATEGORIES:
        sec = section_index(doc, category)
        if sec is None:
            continue
        bounds = table_bounds(doc, sec)
        if bounds is None:
            continue
        last: Row | None = None
        for i in range(*bounds):
            line = doc.lines[i]
            if is_rule(line):
                last = None
                continue
            cells = split_cells(line)
            if _is_header(cells):
                last = None
                continue
            while len(cells) < len(COLUMNS):
                cells.append("")
            if last is not None and last.end == i and _is_continuation(cells) and not _complete(last):
                last.cells[WHAT] = f"{last.what} {cells[WHAT]}".strip()
                last.end = i + 1
                continue
            last = Row(category, i, cells)
            out.append(last)
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


def short_target(file_rel: str, headline: str, taken: set[str] | frozenset[str] = frozenset()) -> str:
    """`file::*<prefix of headline>`: the longest word-boundary prefix that keeps the target within
    LOCATOR_MAX (nvim-orgmode resolves `::*` by prefix). A prefix already in `taken` grows word by
    word until it is free; two identical headlines end up with the same full target, which the
    caller resolves with a ` (2)` suffix on the text."""
    words = headline.split(" ")
    n = 1
    while n < len(words) and len(link_target(file_rel, " ".join(words[: n + 1]))) <= LOCATOR_MAX:
        n += 1
    while True:
        prefix = " ".join(words[:n]) if n >= len(words) else " ".join(words[:n]).rstrip(" -·")
        cand = link_target(file_rel, prefix)
        if cand not in taken or n >= len(words):
            return cand
        n += 1


def link_targets_in_use(ledger: dict, exclude_key: str | None = None) -> set[str]:
    """Every link target the ledger knows (open-question locators share their block's target),
    optionally without the entries one digest key owns."""
    return {loc.split(OPEN_SEP, 1)[0] for loc, e in ledger.items()
            if exclude_key is None or str(e.get("key", "")).split("|")[0] != exclude_key}


def own_entry(ledger: dict, key: str, file_rel: str, headline: str, text: str | None = None) -> dict | None:
    """The entry this digest key already holds for an item (by file and headline, for an open
    question also by text), whatever its locator looks like now."""
    for e in ledger.values():
        if str(e.get("key", "")).split("|")[0] != key or e.get("file") != file_rel or e.get("headline") != headline:
            continue
        if text is None or e.get("text") == text:
            return e
    return None


def what_cell(text: str, jira: str | None, target: str) -> str:
    parts = [text]
    if jira:
        parts.append(f"[[{JIRA_BROWSE}{jira}][{jira}]]")
    parts.append(f"[[file:{target}][↗]]")
    return " ".join(parts).replace("|", "¦")


def last_link_target(cell: str) -> str | None:
    found = FILE_LINK_RE.findall(cell)
    return found[-1] if found else None


OPEN_SEP = "::Open: "
TEXT_PREFIX = 40


def what_text(cell: str) -> str:
    """The item text of a WHAT cell: everything before its first org link."""
    return cell.split(" [[", 1)[0].strip()


def match_locator(cell: str, ledger: dict) -> str | None:
    """The ledger key a WHAT cell belongs to: its last link target, or for an open question (several
    rows share the block's marker link) the entry whose text equals the cell's text, else the one
    entry whose text starts like it. Ambiguous -> None (untracked), never a guess."""
    target = last_link_target(cell)
    if target is None:
        return None
    if target in ledger:
        return target
    text = what_text(cell)
    shared = {loc: str(e.get("text", "")) for loc, e in ledger.items() if loc.startswith(target + OPEN_SEP)}
    exact = [loc for loc, t in shared.items() if t == text]
    if len(exact) == 1:
        return exact[0]
    prefix = text[:TEXT_PREFIX]
    close = [loc for loc, t in shared.items() if t[:TEXT_PREFIX] == prefix]
    return close[0] if len(close) == 1 else None


def row_line(effort: str, done: str, when: str, who: str, what: str) -> str:
    return f"| {effort} | {done} | {when} | {who} | {what} |"


def wrap_what(text: str, width: int) -> list[str]:
    """Greedy word wrap; an org link `[[…]]` is one token and is never split, even past `width`."""
    lines: list[str] = []
    cur = ""
    for tok in TOKEN_RE.findall(text):
        if cur and len(cur) + 1 + len(tok) > width:
            lines.append(cur)
            cur = tok
        else:
            cur = f"{cur} {tok}" if cur else tok
    lines.append(cur)
    return lines


def _fixed_widths(doc: OrgDoc, section_idx: int, extra: list[str] | None = None) -> list[int]:
    """Width of every column but WHAT, over the table's current content plus `extra` cells."""
    widths = [len(c) for c in COLUMNS]
    bounds = table_bounds(doc, section_idx)
    rows_cells = [split_cells(doc.lines[i]) for i in range(*bounds) if not is_rule(doc.lines[i])] if bounds else []
    for cells in ([extra] if extra else []) + rows_cells:
        for k, c in enumerate(cells[: len(COLUMNS)]):
            if k != WHAT:
                widths[k] = max(widths[k], len(c))
    return [w for k, w in enumerate(widths) if k != WHAT]


def _what_width_for(fixed: list[int]) -> int:
    """Characters left for WHAT in a MAX_WIDTH-wide table: `| a | b | c | d | e |` costs 3 per column + 1."""
    return max(20, MAX_WIDTH - 1 - 3 * len(COLUMNS) - sum(fixed))


def what_width(doc: OrgDoc, section_idx: int, extra: list[str] | None = None) -> int:
    return _what_width_for(_fixed_widths(doc, section_idx, extra))


def _lines_for(effort: str, done: str, when: str, who: str, what: str, width: int) -> list[str]:
    chunks = wrap_what(what, width)
    return [row_line(effort, done, when, who, chunks[0])] + [row_line("", "", "", "", c) for c in chunks[1:]]


def row_lines(doc: OrgDoc, section_idx: int, effort: str, done: str, when: str, who: str, what: str) -> list[str]:
    """The physical lines for one logical row: the first carries every cell, continuation rows only WHAT.
    Wrapped to the width the table's current content leaves (a wider fixed cell later pushes earlier
    rows past MAX_WIDTH; `--reformat` re-wraps the whole table)."""
    return _lines_for(effort, done, when, who, what, what_width(doc, section_idx, [effort, done, when, who, ""]))


def migrate_locators(doc: OrgDoc, state) -> int:
    """Shorten every full-headline link target in the file to its `short_target` form and rename the
    matching state.ledger keys, entry locators, entry write keys, and processed keys. Returns the
    number of targets changed. Rows the state does not know are left alone."""
    by_target: dict[str, list[str]] = {}
    for loc in state.ledger:
        by_target.setdefault(loc.split(OPEN_SEP, 1)[0], []).append(loc)
    renames: dict[str, str] = {}
    taken: set[str] = set()
    for old in (t for line in doc.lines if line.startswith("|") for t in re.findall(r"\[\[file:([^\]]+)\]\[", line)):
        if old not in by_target or old in renames:
            continue
        file_rel, _, headline = old.partition("::*")
        new = short_target(file_rel, headline, taken)
        taken.add(new)
        renames[old] = new
    changed = 0
    for old, new in renames.items():
        if new == old:
            continue
        changed += 1
        for loc in by_target[old]:
            e = state.ledger.pop(loc)
            new_loc = new + loc[len(old):]
            e["locator"] = new_loc
            if e.get("key"):
                new_key = str(e["key"]).replace(loc, new_loc)
                if e["key"] in state.processed:
                    state.processed[new_key] = state.processed.pop(e["key"])
                e["key"] = new_key
            state.ledger[new_loc] = e
        for i, line in enumerate(doc.lines):
            if f"[[file:{old}]" in line:
                doc.lines[i] = line.replace(f"[[file:{old}]", f"[[file:{new}]")
    return changed


def reformat(doc: OrgDoc, state=None) -> int:
    """Rebuild every category table in COLUMNS order with wrapped WHAT cells. Cells are mapped by the
    table's own header names, so a file in the old WHEN/WHO/WHAT/EFFORT/DONE order converts. With
    `state`, link targets are shortened first (migrate_locators). Returns the number of logical
    rows. Idempotent."""
    if state is not None:
        migrate_locators(doc, state)
    total = 0
    for category, _ in CATEGORIES:
        sec = section_index(doc, category)
        bounds = table_bounds(doc, sec) if sec is not None else None
        if bounds is None:
            continue
        start, stop = bounds
        names = None
        logical: list[dict[str, str]] = []
        for i in range(start, stop):
            if is_rule(doc.lines[i]):
                continue
            cells = split_cells(doc.lines[i])
            if _is_header(cells):
                names = [c.upper() for c in cells]
                continue
            names = names or COLUMNS
            by = {n: (cells[k] if k < len(cells) else "") for k, n in enumerate(names)}
            if logical and not any(v for n, v in by.items() if n != "WHAT") and not logical[-1]["WHAT"].endswith("][↗]]"):
                logical[-1]["WHAT"] = f"{logical[-1]['WHAT']} {by.get('WHAT', '')}".strip()
            else:
                logical.append({n: by.get(n, "") for n in COLUMNS})
        # one width for the whole table: the widest fixed cell of any row decides what WHAT gets
        fixed = [max([len(n)] + [len(r[n]) for r in logical]) for n in COLUMNS if n != "WHAT"]
        width = _what_width_for(fixed)
        doc.lines[start:stop] = [HEADER, RULE] + [
            line for r in logical for line in _lines_for(r["EFFORT"], r["DONE"], r["WHEN"], r["WHO"], r["WHAT"], width)]
        realign(doc, sec)
        total += len(logical)
    return total


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
        locator = match_locator(row.what, ledger)
        entry = ledger.get(locator) if locator else None
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
    parser.add_argument("--reformat", action="store_true", help="rewrite every table in EFFORT/DONE/WHEN/WHO/WHAT order, wrapped to the width")
    add_org_dir_arg(parser)
    args = parse_args_or_none(parser, argv)
    if args is None:
        return 1
    paths = paths_from_args(args)
    doc = OrgDoc.load(paths.ledger)
    state = State.load(paths.state_file)
    if args.reformat:
        n = reformat(doc, state)
        doc.save_atomic(paths.ledger)
        state.own_saves[str(paths.ledger)] = paths.ledger.stat().st_mtime_ns
        state.save(replace=True)
        print(f"reformatted {n} row(s)")
    rep = report(doc, state.ledger)
    for category, heading in CATEGORIES:
        if category in rep:
            print(f"{heading}: {rep[category]['open']} open, {rep[category]['done']} done")
    print(f"untracked rows: {rep['untracked']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
