from ledger import (
    HEADER,
    PREAMBLE,
    RULE,
    is_rule,
    last_link_target,
    normalize_done,
    realign,
    report,
    rows,
    split_cells,
    table_bounds,
    what_cell,
)
from orgfile import OrgDoc


def test_split_cells_tolerant():
    assert split_cells("| a | b |") == ["a", "b"] and split_cells("|a|b") == ["a", "b"]
    assert is_rule("|---+---|") and not is_rule("| - |")


def test_rows_and_bounds():
    doc = OrgDoc(PREAMBLE + ["* Commitment", HEADER, RULE, "| <2026-10-22 Wed> | @Nick | Ship it [[file:worklog.org::*Ship it - @Nick][↗]] | S | x |", "", "* Follow-up", HEADER, RULE])
    assert table_bounds(doc, 3) == (4, 7)
    r = rows(doc)
    assert len(r) == 1 and r[0].category == "commitment" and r[0].cells[4] == "x"
    assert last_link_target(r[0].cells[2]) == "worklog.org::*Ship it - @Nick"


def test_realign_pads_all_rows_whitespace_only():
    doc = OrgDoc(["* Decision", "| WHEN | WHO | WHAT | EFFORT | DONE |", "|---+---+---+---+---|", "|<2026-10-22 Wed>|@Mitch|Call|M||"])
    before = [split_cells(l) for l in doc.lines[1:] if not is_rule(l)]
    realign(doc, 0)
    assert doc.lines[3] == "| <2026-10-22 Wed> | @Mitch | Call | M      |      |"
    assert doc.lines[2] == "|------------------+--------+------+--------+------|"
    assert [split_cells(l) for l in doc.lines[1:] if not is_rule(l)] == before


def test_what_cell_and_pipe_escape():
    assert what_cell("a | b", "DEV-1", "worklog.org::*a ¦ b - @Nick") == "a ¦ b [[https://rmt.atlassian.net/browse/DEV-1][DEV-1]] [[file:worklog.org::*a ¦ b - @Nick][↗]]"


def test_normalize_done():
    assert normalize_done("") is None and normalize_done(" [X] ") == "x" and normalize_done("Done") == "x" and normalize_done("QA") == "qa"


def test_report_counts(org_dir):
    doc = OrgDoc(PREAMBLE + ["* Commitment", HEADER, RULE,
        "| | @Nick | a [[file:worklog.org::*a - @Nick][↗]] | | x |",
        "| | @Nick | b [[file:worklog.org::*b - @Nick][↗]] | | |",
        "| | @Nick | hand-written row | | |"])
    led = {"worklog.org::*a - @Nick": {"done_at": "2026-10-22T07:00"}, "worklog.org::*b - @Nick": {"done_at": None}}
    assert report(doc, led) == {"commitment": {"open": 1, "done": 1}, "untracked": 1}
