from ledger import (
    HEADER,
    PREAMBLE,
    RULE,
    is_rule,
    last_link_target,
    normalize_done,
    realign,
    report,
    row_line,
    rows,
    split_cells,
    table_bounds,
    what_cell,
)
from config import Paths
from orgfile import OrgDoc
from state import State


def test_split_cells_tolerant():
    assert split_cells("| a | b |") == ["a", "b"] and split_cells("|a|b") == ["a", "b"]
    assert is_rule("|---+---|") and not is_rule("| - |")


def test_rows_and_bounds():
    doc = OrgDoc(PREAMBLE + ["* Commitment", HEADER, RULE, "| x | <2026-10-22 Wed> | @Nick | Ship it [[file:worklog.org::*Ship it - @Nick][↗]] |", "", "* Follow-up", HEADER, RULE])
    assert table_bounds(doc, 3) == (4, 7)
    r = rows(doc)
    assert len(r) == 1 and r[0].category == "commitment" and r[0].done == "x"
    assert last_link_target(r[0].what) == "worklog.org::*Ship it - @Nick"


def test_realign_pads_all_rows_whitespace_only():
    doc = OrgDoc(["* Decision", "| DONE | WHEN | WHO | WHAT |", "|---+---+---+---|", "||<2026-10-22 Wed>|@Mitch|Call|"])
    before = [split_cells(l) for l in doc.lines[1:] if not is_rule(l)]
    realign(doc, 0)
    assert doc.lines[3] == "|      | <2026-10-22 Wed> | @Mitch | Call |"
    assert doc.lines[2] == "|------+------------------+--------+------|"
    assert [split_cells(l) for l in doc.lines[1:] if not is_rule(l)] == before


def test_what_cell_and_pipe_escape():
    assert what_cell("a | b", "DEV-1", "worklog.org::*a ¦ b - @Nick") == "a ¦ b [[https://rmt.atlassian.net/browse/DEV-1][DEV-1]] [[file:worklog.org::*a ¦ b - @Nick][↗]]"


def test_normalize_done():
    assert normalize_done("") is None and normalize_done(" [X] ") == "x" and normalize_done("Done") == "x" and normalize_done("QA") == "qa"


def test_report_counts(org_dir):
    doc = OrgDoc(PREAMBLE + ["* Commitment", HEADER, RULE,
        "| x | | @Nick | a [[file:worklog.org::*a - @Nick][↗]] |",
        "| | | @Nick | b [[file:worklog.org::*b - @Nick][↗]] |",
        "| | | @Nick | hand-written row |"])
    led = {"worklog.org::*a - @Nick": {"done_at": "2026-10-22T07:00"}, "worklog.org::*b - @Nick": {"done_at": None}}
    assert report(doc, led) == {"commitment": {"open": 1, "done": 1}, "untracked": 1}


def test_match_locator_open_question_by_link_and_text_prefix():
    from ledger import match_locator
    marker = "worklog.org::*meetings (auto) 2026-10-22T06:31 · source: slack · attendees: Nick, Rob"
    led = {
        marker + "::Open: Who owns the accuracy dashboard?": {"text": "Who owns the accuracy dashboard?", "done_at": None},
        marker + "::Open: Who owns the accuracy dashboard? (2)": {"text": "Who owns the accuracy dashboard? (2)", "done_at": None},
        "worklog.org::*a - @Nick": {"text": "a", "done_at": None},
    }
    cell = f"Who owns the accuracy dashboard? (2) [[file:{marker}][↗]]"
    assert match_locator(cell, led) == marker + "::Open: Who owns the accuracy dashboard? (2)"
    assert match_locator(f"a [[file:worklog.org::*a - @Nick][↗]]", led) == "worklog.org::*a - @Nick"
    assert match_locator("hand-written row", led) is None
    assert match_locator(f"rewritten text [[file:{marker}][↗]]", led) is None
    doc = OrgDoc(PREAMBLE + ["* Open question", HEADER, RULE, f"| x | | | {cell} |"])
    assert report(doc, led) == {"open_question": {"open": 1, "done": 0}, "untracked": 0}


def test_match_locator_prefers_exact_text_and_refuses_ambiguous_prefix():
    from ledger import match_locator
    marker = "worklog.org::*meetings (auto) 2026-10-22T06:31 · source: slack · attendees: Nick, Rob"
    a = "Should the accuracy dashboard be owned by platform or by data?"
    b = "Should the accuracy dashboard be owned by Rob instead?"
    led = {f"{marker}::Open: {a}": {"text": a}, f"{marker}::Open: {b}": {"text": b}}
    assert match_locator(f"{b} [[file:{marker}][↗]]", led) == f"{marker}::Open: {b}"
    assert match_locator(f"Should the accuracy dashboard be owned by someone [[file:{marker}][↗]]", led) is None
    assert match_locator(f"Should the accuracy dashboard be owned by platform or by data? (edited) [[file:{marker}][↗]]", led) is None
    led[f"{marker}::Open: {a}"]["text"] = a  # a lone prefix match still resolves
    assert match_locator(f"Should the accuracy dashboard be owned by Rob instead? (edited) [[file:{marker}][↗]]", {k: v for k, v in led.items() if v["text"] == b}) == f"{marker}::Open: {b}"



def test_header_puts_done_first_and_has_no_effort():
    assert HEADER == "| DONE | WHEN | WHO | WHAT |"
    assert RULE == "|------+------+-----+------|"
    assert row_line("x", "<2026-10-22 Wed>", "@Nick", "Ship it") == "| x | <2026-10-22 Wed> | @Nick | Ship it |"


def test_wrap_what_keeps_links_whole():
    from ledger import wrap_what
    link = "[[file:worklog.org::*Ship it - @Nick][↗]]"
    assert wrap_what("Ship it " + link, 60) == ["Ship it " + link]
    text = "one two three four five six seven eight nine ten " + link
    out = wrap_what(text, 20)
    assert out == ["one two three four", "five six seven eight", "nine ten", link]  # a link never splits, even past the width
    assert wrap_what("", 20) == [""]


def test_rows_join_continuation_rows():
    link = "[[file:worklog.org::*Ship it - @Nick][↗]]"
    doc = OrgDoc(PREAMBLE + ["* Commitment", HEADER, RULE,
        "| x | <2026-10-22 Wed> | @Nick | Ship it with a very long |",
        "|   |                  |       | explanation |",
        f"|   |                  |       | {link} |",
        "|   |                  | @Rob  | second |"])
    r = rows(doc)
    assert [x.what for x in r] == [f"Ship it with a very long explanation {link}", "second"]
    assert r[0].idx == 6 and r[0].end == 9 and r[1].idx == 9 and r[0].done == "x"
    assert last_link_target(r[0].what) == "worklog.org::*Ship it - @Nick"


def test_rows_keep_open_questions_with_blank_cells_apart():
    """An open-question row has blank EFFORT/DONE/WHEN/WHO like a continuation row: a row whose
    WHAT already ends with its link is complete, so the next blank-celled line is a new row."""
    m = "[[file:worklog.org::*meetings (auto) 2026-10-22T06:31 · source:][↗]]"
    doc = OrgDoc(PREAMBLE + ["* Open question", HEADER, RULE,
        f"|  |  |  | why? {m} |", f"|  |  |  | how? {m} |",
        "|  |  |  | and a long one that |", f"|  |  |  | wraps {m} |"])
    assert [x.what for x in rows(doc)] == [f"why? {m}", f"how? {m}", f"and a long one that wraps {m}"]


def test_reformat_wraps_every_row_to_the_sections_final_widths(org_dir):
    """A wide WHO on the last row must not push the first row's longer chunks past MAX_WIDTH."""
    from ledger import MAX_WIDTH, reformat
    st = State.load(Paths(org_dir).state_file)
    link = "[[file:worklog.org::*Ship it][↗]]"
    doc = OrgDoc(PREAMBLE + ["* Commitment", HEADER, RULE,
        f"| | | @Nick | {' '.join(['lorem'] * 40)} {link} |",
        f"| | <2026-10-22 Wed> | @Abhi, @David, @Mitch, @Jayson | tiny {link} |", ""])
    reformat(doc, st)
    assert all(len(l) <= MAX_WIDTH for l in doc.lines if l.startswith("|")), max(len(l) for l in doc.lines)
    assert [x.who for x in rows(doc)] == ["@Nick", "@Abhi, @David, @Mitch, @Jayson"]


def test_row_lines_wrap_to_table_width():
    from ledger import MAX_WIDTH, row_lines, section_index
    doc = OrgDoc(PREAMBLE + ["* Commitment", HEADER, RULE, "| | <2026-10-22 Wed> | @Abhi, @David, @Joseph | short |", ""])
    what = " ".join(f"word{i}" for i in range(40)) + " [[file:worklog.org::*x - @Nick][↗]]"
    lines = row_lines(doc, section_index(doc, "commitment"), "", "", "@Nick", what)
    assert len(lines) > 1 and lines[0].startswith("|  |  | @Nick | word0 ")
    assert all(split_cells(l)[:3] == ["", "", ""] for l in lines[1:])
    doc.insert(7, lines)
    realign(doc, section_index(doc, "commitment"))
    assert all(len(l) <= MAX_WIDTH for l in doc.lines[4:] if l.startswith("|"))
    assert [r.what for r in rows(doc)][1] == what


def test_short_target_truncates_at_word_boundary_and_extends_on_collision():
    from ledger import LOCATOR_MAX, short_target
    assert short_target("worklog.org", "Ship it - @Nick") == "worklog.org::*Ship it - @Nick"
    long = "build a proof-diff tool for CSV exports - @Nick"
    t = short_target("worklog.org", long)
    assert t == "worklog.org::*build a proof-diff tool for CSV exports" and len(t) <= LOCATOR_MAX
    assert short_target("worklog.org", long, {t}) == "worklog.org::*build a proof-diff tool for CSV exports - @Nick"
    assert short_target("worklog.org", long, {t, "worklog.org::*" + long}) == "worklog.org::*" + long  # identical headline: caller suffixes
    assert short_target("worklog.org", "x" * 70) == "worklog.org::*" + "x" * 70  # one word: nothing to cut


def test_migrate_locators_rewrites_links_state_and_processed(org_dir):
    from ledger import migrate_locators
    long = "build a proof-diff tool for CSV exports - @Nick"
    marker = "meetings (auto) 2026-10-22T06:31 · source: slack · attendees: Nick, Rob"
    old_t, old_m = f"worklog.org::*{long}", f"worklog.org::*{marker}"
    st = State.load(Paths(org_dir).state_file)
    st.ledger[old_t] = {"locator": old_t, "key": f"k1|action-items.org|commitment/{old_t}", "headline": long, "text": "b", "kind": "headline"}
    st.ledger[old_m + "::Open: why?"] = {"locator": old_m + "::Open: why?", "key": f"k1|action-items.org|open_question/{old_m}::Open: why?", "headline": marker, "text": "why?", "kind": "bullet"}
    st.ledger[old_m + "::Open: how?"] = {"locator": old_m + "::Open: how?", "key": f"k1|action-items.org|open_question/{old_m}::Open: how?", "headline": marker, "text": "how?", "kind": "bullet"}
    st.processed[f"k1|action-items.org|commitment/{old_t}"] = {"at": "x"}
    doc = OrgDoc(PREAMBLE + ["* Commitment", HEADER, RULE, f"|  |  | @Nick | b [[file:{old_t}][↗]] |", "",
                            "* Open question", HEADER, RULE, f"|  |  |  | why? [[file:{old_m}][↗]] |", f"|  |  |  | how? [[file:{old_m}][↗]] |"])
    assert migrate_locators(doc, st) == 2
    new_t, new_m = "worklog.org::*build a proof-diff tool for CSV exports", "worklog.org::*meetings (auto) 2026-10-22T06:31 · source:"
    assert last_link_target(rows(doc)[0].what) == new_t and [last_link_target(r.what) for r in rows(doc)[1:]] == [new_m, new_m]
    assert set(st.ledger) == {new_t, new_m + "::Open: why?", new_m + "::Open: how?"}
    assert st.ledger[new_t]["locator"] == new_t and st.ledger[new_t]["key"] == f"k1|action-items.org|commitment/{new_t}"
    assert f"k1|action-items.org|commitment/{new_t}" in st.processed and f"k1|action-items.org|commitment/{old_t}" not in st.processed
    assert migrate_locators(doc, st) == 0


def test_reformat_drops_effort_from_five_column_tables(org_dir):
    from ledger import reformat
    st = State.load(Paths(org_dir).state_file)
    doc = OrgDoc(PREAMBLE + ["* Commitment", "| EFFORT | DONE | WHEN | WHO | WHAT |", "|---+---+---+---+---|",
                             "| M | x | <2026-10-22 Wed> | @Nick | a [[file:worklog.org::*a][↗]] |",
                             "|   |   |                  |       | tail [[file:worklog.org::*b][↗]] |", ""])
    assert reformat(doc, st) == 2
    r = rows(doc)
    assert [(x.done, x.when, x.who, x.what) for x in r] == [
        ("x", "<2026-10-22 Wed>", "@Nick", "a [[file:worklog.org::*a][↗]]"), ("", "", "", "tail [[file:worklog.org::*b][↗]]")]
    assert doc.lines[4] == "| DONE | WHEN             | WHO   | WHAT                             |"


def test_reformat_reorders_old_tables_and_wraps(org_dir):
    from ledger import MAX_WIDTH, reformat
    long = "build a proof-diff tool for CSV exports with a fairly long description - @Nick"
    link = f"[[file:worklog.org::*{long}][↗]]"
    st = State.load(Paths(org_dir).state_file)
    st.ledger[f"worklog.org::*{long}"] = {"locator": f"worklog.org::*{long}", "key": f"k1|action-items.org|commitment/worklog.org::*{long}", "headline": long, "text": "b", "kind": "headline"}
    old = PREAMBLE + ["* Commitment", "| WHEN | WHO | WHAT | EFFORT | DONE |", "|---+---+---+---+---|",
                      f"| <2026-10-22 Wed> | @Nick | {' '.join(['lorem'] * 30)} {link} | M | x |",
                      "| | @Rob | tiny | | |", "", "* Decision", "| WHEN | WHO | WHAT | EFFORT | DONE |", "|---+---+---+---+---|", ""]
    doc = OrgDoc(list(old))
    assert reformat(doc, st) == 2
    r = rows(doc)
    assert [x.who for x in r] == ["@Nick", "@Rob"] and r[0].done == "x"
    assert not any("| M |" in l or l.startswith("| M ") for l in doc.lines)  # EFFORT dropped, not carried
    assert r[0].what.startswith(" ".join(["lorem"] * 30)) and r[0].end - r[0].idx >= 2
    assert last_link_target(r[0].what) == "worklog.org::*build a proof-diff tool for CSV exports"
    assert split_cells(doc.lines[4]) == ["DONE", "WHEN", "WHO", "WHAT"]
    assert all(len(l) <= MAX_WIDTH for l in doc.lines if l.startswith("|"))
    again = [x.what for x in r]
    assert reformat(doc, st) == 2 and [x.what for x in rows(doc)] == again  # idempotent
