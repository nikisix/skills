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


def test_parse_filename_accepts_unpadded_month_and_day():
    """Hand-named files come in as 2026-11-2-…; the date is the same day, the stem is kept as named."""
    m = parse_filename("2026-11-2-rfp-gen-epics.vtt")
    assert m.date == date(2026, 11, 2) and m.time is None and m.title == "Rfp Gen Epics" and m.source == "teams"
    assert m.stem == "2026-11-2-rfp-gen-epics"
    m = parse_filename("2026-1-3-1500-Rx-Tron-Discussion.docx")
    assert m.date == date(2026, 1, 3) and m.time == "15:00" and m.title == "Rx Tron Discussion"


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


def test_parse_filename_double_hyphen():
    m = parse_filename("2026-10-22--multi-loc-extracts.txt")
    assert m.date == date(2026, 10, 22)
    assert m.time is None
    assert m.title == "Multi Loc Extracts"
    assert m.stem == "2026-10-22--multi-loc-extracts"


def test_teams_copy_is_detected():
    meta, body = normalize(FIX / "2026-10-22--multi-loc-extracts.txt")
    assert meta.source == "teams"
    assert meta.attendees == ["Mara Stone", "Abhi Gurudwar", "Nick Tomasino", "Johnathan Neil"]


def test_teams_copy_keeps_only_speaker_utterances():
    _, body = normalize(FIX / "2026-10-22--multi-loc-extracts.txt")
    lines = body.splitlines()
    assert lines[0] == "Mara Stone: Hey, Abby."
    assert lines[1] == "Abhi Gurudwar: Good afternoon, everyone."
    # consecutive chunks from one speaker merge into one line
    assert lines[2] == "Mara Stone: I'll kick this off. We're going to go through the multi-line of coverage extracts."
    assert lines[-1] == "Mara Stone: All right. Talk to you guys later. One more thing after the hour."
    for noise in ("transcription", "AI-generated", "0:05", "minutes", "\nMS\n", "\u00ee"):
        assert noise not in body


def test_slack_huddle_copy_is_detected():
    """A Slack huddle transcript copied from the captions pane: the name on its own line, the
    utterance on the next, a blank line between turns. Speakers become attendees, consecutive turns
    from one speaker merge, and system notices ("started screen sharing.") are dropped."""
    meta, body = normalize(FIX / "2026-11-2-rx-planning-meeting.txt")
    assert meta.source == "slack"
    assert meta.attendees == ["Joseph Sakaya", "Nick", "David Reeder"]
    assert body.splitlines() == [
        "Joseph Sakaya: But quickly wrapping up what Uh-huh. So if Sonnet agrees with Haiku, then we keep the Haiku extraction.",
        "Nick: Outside",
        "Joseph Sakaya: so.",
        "Nick: of the retry budget, you have",
        "David Reeder: Yeah.",
        "Nick: to flag it for review, yeah.",
    ]


def test_slack_huddle_parse_rejects_prose_paragraphs():
    from normalize import parse_slack_huddle

    assert parse_slack_huddle("Agenda\nitem one\n\nNotes from the call, which ran long.\n") is None
    assert parse_slack_huddle("Rob: hi\nNick: hello\n") is None


TEAMS_RECORDING = [
    "Rx Tron Discussion-20261103_153041-Meeting Recording",
    "November 3, 2026, 9:30PM",
    "1h 17m 27s",
    "\nLars Hacking started transcription",
    "\nJeremy Theriault   0:23\nFiles.",
    "\nLars Hacking   0:26\nHey, Jeremy, how's it going?",
    "\nLars Hacking   0:42\nSounds good, yeah.\nI've simplified the deck.",
    "\nNick Tomasino   1:14:05\nHow is it going, Jeremy?",
    "\nLars Hacking stopped transcription",
]


def _recording_docx(tmp_path):
    d = docx.Document()
    for t in TEAMS_RECORDING:
        d.add_paragraph(t)
    f = tmp_path / "2026-11-3-Rx-Tron-Discussion.docx"
    d.save(f)
    return f


def test_teams_recording_docx_is_parsed(tmp_path):
    """A Teams 'Meeting Recording' transcript download: `Name   M:SS` (or H:MM:SS) stamp lines
    with the utterance on the lines that follow; the title, date, duration, and
    started/stopped notices are dropped; same-speaker runs merge."""
    meta, body = normalize(_recording_docx(tmp_path))
    assert meta.source == "teams" and meta.title == "Rx Tron Discussion"
    assert meta.attendees == ["Jeremy Theriault", "Lars Hacking", "Nick Tomasino"]
    assert body.splitlines() == [
        "Jeremy Theriault: Files.",
        "Lars Hacking: Hey, Jeremy, how's it going? Sounds good, yeah. I've simplified the deck.",
        "Nick Tomasino: How is it going, Jeremy?",
    ]


def test_teams_recording_pasted_as_txt_is_parsed(tmp_path):
    f = tmp_path / "2026-11-3-rx-tron-discussion.txt"
    f.write_text("\n".join(TEAMS_RECORDING) + "\n", encoding="utf-8")
    meta, body = normalize(f)
    assert meta.source == "teams" and meta.attendees == ["Jeremy Theriault", "Lars Hacking", "Nick Tomasino"]
    assert body.splitlines()[0] == "Jeremy Theriault: Files."


def test_teams_copy_parse_rejects_plain_text():
    from normalize import parse_teams_copy

    assert parse_teams_copy("Rob: hi\nNick: hello\n") is None


def test_plain_text_body_unchanged():
    meta, body = normalize(FIX / "2026-10-20-rob-1-1.txt")
    assert meta.source == "slack"
    assert body.startswith("Rob: How's the accuracy work going?")


def test_teams_stamp_with_hours():
    meta, body = normalize(FIX / "2026-10-22--multi-loc-extracts.txt")
    assert "Mara Stone 1 hour" not in meta.attendees and len(meta.attendees) == 4
    assert "One more thing after the hour." in body


def test_kind_chat_round_trips(tmp_path):
    p = tmp_path / "2026-10-21-slack-tron.txt"
    p.write_text("title: Slack #tron\nsource: slack\nkind: chat\nattendees: Nick, Rob\n\nRob: can you look at the proof diff?\n")
    meta, body = normalize(p)
    assert meta.kind == "chat" and meta.source == "slack"
    assert "kind: chat\n" in meta.header()
    meta2, _ = normalize(FIX / "2026-10-20-rob-1-1.txt")
    assert meta2.kind == "meeting" and "kind: meeting\n" in meta2.header()


def test_vtt_merges_consecutive_cues_and_internal_newlines(tmp_path):
    p = tmp_path / "2026-10-22-x.vtt"
    p.write_text(
        "WEBVTT\n\nid/1-0\n00:00:01.000 --> 00:00:02.000\n<v Mitch Slavens>See, I'll kick this off.\nWe're going to go through some design</v>\n\n"
        "id/1-1\n00:00:02.000 --> 00:00:03.000\n<v Mitch Slavens>stuff for the classifier.</v>\n\n"
        "id/2-0\n00:00:03.000 --> 00:00:04.000\n<v Nick Tomasino>Separate.</v>\n\n"
        "id/2-1\n00:00:04.000 --> 00:00:05.000\n<v Nick Tomasino>Separate.</v>\n")
    assert read_transcript(p).splitlines() == [
        "Mitch Slavens: See, I'll kick this off. We're going to go through some design stuff for the classifier.",
        "Nick Tomasino: Separate.",
    ]
