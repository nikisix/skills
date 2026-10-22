from datetime import date
from pathlib import Path

from orgfile import OrgDoc, day_header

FIX = Path(__file__).parent / "fixtures" / "worklog-sample.org"


def load():
    return OrgDoc.load(FIX)


def test_find_day_existing():
    doc = load()
    idx = doc.find_day(date(2026, 10, 20))
    assert doc.lines[idx] == "* <2026-10-20 Tue>"
    assert doc.find_day(date(2026, 10, 13)) is None


def test_find_day_pto_suffix():
    doc = load()
    assert doc.lines[doc.find_day(date(2026, 10, 12))] == "* <2026-10-12 Mon> PTO"


def test_day_header_format():
    assert day_header(date(2026, 10, 28)) == "* <2026-10-28 Wed>"


def test_ensure_day_inserts_between():
    doc = load()
    idx = doc.ensure_day(date(2026, 10, 16))
    assert doc.lines[idx] == "* <2026-10-16 Fri>"
    assert doc.lines[idx + 1] == ""
    days = [l for l in doc.lines if l.startswith("* <")]
    assert days == [
        "* <2026-10-12 Mon> PTO",
        "* <2026-10-14 Wed>",
        "* <2026-10-16 Fri>",
        "* <2026-10-20 Tue>",
        "* <2026-10-21 Wed>",
    ]


def test_ensure_day_after_last_day_before_todo():
    doc = load()
    idx = doc.ensure_day(date(2026, 10, 28))
    assert doc.lines[idx] == "* <2026-10-28 Wed>"
    todo = doc.lines.index("* TODO")
    assert idx < todo
    # the previous day's content is still before the new header
    assert doc.lines.index("** CSV Proofs - @Nick - [[https://rmt.atlassian.net/browse/DEV-10173][DEV-10173]]") < idx


def test_ensure_day_idempotent():
    doc = load()
    a = doc.ensure_day(date(2026, 10, 20))
    before = list(doc.lines)
    b = doc.ensure_day(date(2026, 10, 20))
    assert a == b and doc.lines == before


def test_ensure_day_on_empty_doc():
    doc = OrgDoc([])
    idx = doc.ensure_day(date(2026, 11, 2))
    assert doc.lines[idx] == "* <2026-11-02 Mon>"


def test_headings_parse_keyword_owner_tags():
    doc = load()
    day = doc.find_day(date(2026, 10, 21))
    hs = doc.headings(day, level=2)
    assert [h.title for h in hs] == ["Reeder MR", "CSV Proofs"]
    assert hs[0].tags == ["meeting"] and hs[0].keyword is None and hs[0].owner is None
    assert hs[1].owner == "Nick" and hs[1].link == "DEV-10173"
    day20 = doc.find_day(date(2026, 10, 20))
    hs20 = doc.headings(day20, level=2)
    assert hs20[1].keyword == "INPROGRESS" and hs20[1].title == "Ontology 2.0 - RX Skeleton"
    kids = doc.headings(hs[1].idx, level=3)
    assert kids[0].keyword == "DONE" and kids[0].title == "incorporate Marcus' ontology edits"


def test_section_end_last_day():
    doc = load()
    day = doc.find_day(date(2026, 10, 21))
    assert doc.lines[doc.section_end(day)] == "* TODO"
    h = doc.headings(day, level=2)[0]
    assert doc.lines[doc.section_end(h.idx)].startswith("** CSV Proofs")


def test_contains_marker():
    doc = load()
    day = doc.find_day(date(2026, 10, 21))
    assert doc.contains_marker(day, doc.section_end(day), "synonyms MR")
    assert not doc.contains_marker(day, doc.section_end(day), "accuracy")


def test_insert_and_save_atomic_roundtrip(tmp_path):
    doc = load()
    doc.insert(2, ["** inserted", "   - body"])
    out = tmp_path / "w.org"
    doc.save_atomic(out)
    again = OrgDoc.load(out)
    assert again.lines == doc.lines
    assert out.read_text().endswith("\n")
    assert not list(tmp_path.glob("*.tmp"))
