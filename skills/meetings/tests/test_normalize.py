import hashlib
from datetime import date
from pathlib import Path

import docx

from normalize import normalize, parse_filename, parse_frontmatter, read_transcript

FIX = Path(__file__).parent / "fixtures"


def test_parse_filename_with_time():
    m = parse_filename("2026-10-21-1500-csv-proofs-sync.vtt")
    assert m.date == date(2026, 10, 21)
    assert m.time == "15:00"
    assert m.title == "Csv Proofs Sync"
    assert m.source == "teams"
    assert m.stem == "2026-10-21-1500-csv-proofs-sync"


def test_parse_filename_without_time():
    m = parse_filename("2026-10-20-rob-1-1.txt")
    assert m.date == date(2026, 10, 20)
    assert m.time is None
    assert m.title == "Rob 1-1"
    assert m.source == "manual"


def test_frontmatter_overrides_title():
    meta, body = normalize(FIX / "2026-10-20-rob-1-1.txt")
    assert meta.title == "Rob 1:1"
    assert meta.source == "slack"
    assert meta.attendees == ["Nick", "Rob"]
    assert meta.date == date(2026, 10, 20)
    assert body.startswith("Rob: How's the accuracy work going?")
    assert "\n\n\n" not in body  # >= 3 blank lines collapsed to one blank line


def test_parse_frontmatter_no_header():
    meta, body = parse_frontmatter("Rob: hi\nNick: hello\n")
    assert meta == {}
    assert body == "Rob: hi\nNick: hello\n"


def test_vtt_speakers_and_dedup():
    text = read_transcript(FIX / "2026-10-21-1500-csv-proofs-sync.vtt")
    lines = text.splitlines()
    assert lines[0] == "Nick Tomasino: Let's go over the CSV proofs status."
    assert lines[1] == "Rob: I'll send you the sample file by Friday."
    assert "-->" not in text
    assert text.count("Let's go over") == 1


def test_docx_paragraphs(tmp_path):
    p = tmp_path / "2026-10-19-standup.docx"
    d = docx.Document()
    d.add_paragraph("Nick: first")
    d.add_paragraph("Rob: second")
    d.save(p)
    assert read_transcript(p) == "Nick: first\nRob: second"


def test_key_is_stable_sha256():
    meta, body = normalize(FIX / "2026-10-20-rob-1-1.txt")
    assert meta.key == hashlib.sha256(body.encode()).hexdigest()
    meta2, _ = normalize(FIX / "2026-10-20-rob-1-1.txt")
    assert meta.key == meta2.key
