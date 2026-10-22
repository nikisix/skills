import json
from datetime import date, datetime
from pathlib import Path

import render
from orgfile import Heading, OrgDoc
from people import People

FIX = Path(__file__).parent / "fixtures"


def people(org_dir):
    return People.load(org_dir / "meetings" / "people.yaml")


def day_headings(d):
    doc = OrgDoc.load(FIX / "worklog-sample.org")
    return doc.headings(doc.find_day(d), level=2)


def test_match_exact_title(org_dir):
    hs = day_headings(date(2026, 10, 20))
    h = render.match_heading("Rob 1:1", ["Nick", "Rob"], hs, people(org_dir))
    assert h is not None and h.title == "Rob 1-1"


def test_match_by_attendee_alias(org_dir):
    # digest title shares no word with "Reeder MR"; attendee David resolves via alias "reeder"
    hs = day_headings(date(2026, 10, 21))
    h = render.match_heading("Weekly catch-up", ["Nick", "David"], hs, people(org_dir))
    assert h is not None and h.title == "Reeder MR"


def test_match_excludes_auto_headings(org_dir):
    hs = [Heading(5, 2, None, "Rob 1-1", ["meeting", "auto"], None, None)]
    assert render.match_heading("Rob 1-1", ["Rob"], hs, people(org_dir)) is None


def test_no_match_below_threshold(org_dir):
    hs = day_headings(date(2026, 10, 21))
    assert render.match_heading("Platform Weekly Sync", ["Nick", "Lars"], hs, people(org_dir)) is None


def test_block_new_heading_shape(org_dir):
    d = json.loads((FIX / "digest-good.json").read_text())
    lines = render.meeting_block(d, people(org_dir), datetime(2026, 10, 22, 6, 31), new_heading=True)
    assert lines[0] == "** Rob 1:1 :meeting:auto:"
    assert lines[1] == "   - meetings (auto) 2026-10-22T06:31 · source: slack · attendees: Nick, Rob"
    assert lines[2].startswith("   - Status on accuracy work")
    assert "   - Decided (committed): Align Jira buckets with David this week — Nick" in lines
    assert "   - Open: Who owns the accuracy dashboard?" in lines


def test_block_merged_has_no_heading_line(org_dir):
    d = json.loads((FIX / "digest-good.json").read_text())
    lines = render.meeting_block(d, people(org_dir), datetime(2026, 10, 22, 6, 31), new_heading=False)
    assert lines[0].startswith("   - meetings (auto)")
    assert not any(l.startswith("** ") for l in lines)


def test_mine_vs_others_keyword(org_dir):
    d = json.loads((FIX / "digest-good.json").read_text())
    lines = render.meeting_block(d, people(org_dir), datetime(2026, 10, 22, 6, 31), new_heading=True)
    assert "*** send the sample CSV file - @Rob :auto:" in lines
    assert "*** TODO build a proof-diff tool for CSV exports - @Nick :auto:" in lines
    # dated follow-up is NOT in the block; undated one is, with a TBD bullet
    assert not any("sync with Rob on the roadmap" in l for l in lines)
    i = lines.index("*** TODO revisit accuracy targets - @Nick :auto:")
    assert lines[i + 1] == "    - when: TBD"


def test_jira_link_placement(org_dir):
    d = json.loads((FIX / "digest-good.json").read_text())
    lines = render.meeting_block(d, people(org_dir), datetime(2026, 10, 22, 6, 31), new_heading=True)
    i = lines.index(
        "*** TODO draft the CSV proofs runbook - @Nick - [[https://rmt.atlassian.net/browse/DEV-10173][DEV-10173]] :auto:"
    )
    assert lines[i + 1] == "    DEADLINE: <2026-10-23 Fri>"


def test_unresolved_owner(org_dir):
    d = json.loads((FIX / "digest-good.json").read_text())
    d["action_items"] = [
        {"text": "ping legal", "owner": "Mitch Slavens", "due": None, "jira": None, "ticket_worthy": False},
        {"text": "find an owner", "owner": None, "due": None, "jira": None, "ticket_worthy": False},
    ]
    lines = render.meeting_block(d, people(org_dir), datetime(2026, 10, 22, 6, 31), new_heading=True)
    assert "*** ping legal - @Mitch Slavens :auto:" in lines  # named but off-roster: keep the name
    assert "*** find an owner - @? :auto:" in lines  # nobody named: a finding


def test_followup_item_shape(org_dir):
    d = json.loads((FIX / "digest-good.json").read_text())
    lines = render.followup_item(d["follow_ups"][0], d, people(org_dir))
    assert lines == [
        "** TODO sync with Rob on the roadmap - @Nick :auto:",
        "   SCHEDULED: <2026-10-28 Wed>",
        "   - from: [[file:worklog.org::*Rob 1:1][2026-10-20 Rob 1:1]]",
    ]


def test_org_date():
    assert render.org_date(date(2026, 10, 28)) == "<2026-10-28 Wed>"


def real_headings():
    doc = OrgDoc.load(FIX / "real-headings.org")
    return doc.headings(doc.find_day(date(2026, 10, 21)), level=2)


def test_no_match_on_url_tokens(org_dir):
    # "dev" must not match the Jira URL tokens of a linked heading
    assert render.match_heading("Dev standup", ["Nick"], real_headings(), people(org_dir)) is None


def test_no_match_on_single_generic_word(org_dir):
    assert render.match_heading("MR review", ["Nick", "Lars"], real_headings(), people(org_dir)) is None


def test_match_two_title_tokens(org_dir):
    h = render.match_heading("RFP generation sync", ["Nick"], real_headings(), people(org_dir))
    assert h is not None and h.title == "meet with Johnathan about RFP generation"


def test_real_heading_shapes(org_dir):
    hs, p = real_headings(), people(org_dir)
    assert render.match_heading("Rob 1:1", ["Nick", "Rob"], hs, p).title == "Rob 1-1"
    assert render.match_heading("Abhi MR walkthrough", ["Nick", "Abhi"], hs, p).title == "Abhi's MR"
    for title, who in [("Ontology 2.0 planning", ["Nick"]), ("Weekly catch-up", ["Nick", "Lars"]),
                       ("Design review", ["Nick"]), ("Skill planning", ["Nick"])]:
        assert render.match_heading(title, who, hs, p) is None, title


def test_tokens_drop_single_chars():
    assert "j" not in render.tokens("J.T. can't make it") and "jt" not in render.tokens("J.T.")


def test_render_sanitizes_multiline_strings(org_dir):
    d = json.loads((FIX / "digest-good.json").read_text())
    d["title"] = "Bad\ntitle"
    d["summary"] = "Line one.\n* TODO injected top-level\n- bullet"
    d["action_items"][0]["text"] = "* do\nthe thing"
    lines = render.meeting_block(d, people(org_dir), datetime(2026, 10, 22, 6, 31), new_heading=True)
    assert lines[0] == "** Bad title :meeting:auto:"
    assert "   - Line one. * TODO injected top-level - bullet" in lines
    assert any(l.startswith("*** TODO do the thing - @Nick") for l in lines)
    assert not any(l.startswith("* ") or l == "- bullet" for l in lines)


def test_chat_block_tag(org_dir):
    d = json.loads((FIX / "digest-good.json").read_text())
    d["kind"], d["title"] = "chat", "Slack #tron"
    lines = render.meeting_block(d, people(org_dir), datetime(2026, 10, 22, 6, 31), new_heading=True)
    assert lines[0] == "** Slack #tron :chat:auto:"
