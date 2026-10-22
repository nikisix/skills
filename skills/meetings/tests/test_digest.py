import json
from pathlib import Path

import pytest

import digest
from people import People

FIX = Path(__file__).parent / "fixtures"


def test_good_digest_validates():
    assert digest.validate(json.loads((FIX / "digest-good.json").read_text())) == []


def test_bad_digest_reports_errors():
    errors = digest.validate(json.loads((FIX / "digest-bad.json").read_text()))
    assert len(errors) == 2
    joined = " ".join(errors)
    assert "extra_key" in joined and "maybe" in joined


def test_extract_json_from_prose():
    text = 'Here is the digest:\n```json\n{"a": {"b": [1, 2]}, "c": "}"}\n```\nDone.'
    assert digest.extract_json(text) == {"a": {"b": [1, 2]}, "c": "}"}
    with pytest.raises(ValueError):
        digest.extract_json("no json here")


def test_build_prompt_fills_placeholders(org_dir):
    people = People.load(org_dir / "meetings" / "people.yaml")
    prompt = digest.build_prompt("title: X\ndate: 2026-10-20\n", "Rob: hi\n", people)
    assert "{{" not in prompt
    assert "Nick, Rob" in prompt or "Rob" in prompt
    assert "Rob: hi" in prompt


def _normalized(tmp_path):
    p = tmp_path / "2026-10-20-rob-1-1.txt"
    p.write_text("title: Rob 1:1\ndate: 2026-10-20\ntime: \nsource: slack\nattendees: Nick, Rob\nkey: abc\n\nRob: hi\n")
    return p


def test_cli_retries_then_fails(org_dir, tmp_path, monkeypatch):
    calls = []

    def fake(prompt, timeout=300):
        calls.append(prompt)
        return "not json at all"

    monkeypatch.setattr(digest, "run_claude", fake)
    out = tmp_path / "d.json"
    rc = digest.main([str(_normalized(tmp_path)), "-o", str(out)])
    assert rc == 1
    assert len(calls) == 2
    assert not out.exists()
    assert (tmp_path / "d.raw.txt").read_text() == "not json at all"


def test_cli_retry_succeeds(org_dir, tmp_path, monkeypatch):
    good = (FIX / "digest-good.json").read_text()
    answers = iter(['{"title": "only"}', "Sure! " + good])
    seen = []

    def fake(prompt, timeout=300):
        seen.append(prompt)
        return next(answers)

    monkeypatch.setattr(digest, "run_claude", fake)
    out = tmp_path / "d.json"
    rc = digest.main([str(_normalized(tmp_path)), "-o", str(out)])
    assert rc == 0
    assert json.loads(out.read_text())["title"] == "Rob 1:1"
    assert "required" in seen[1].lower()  # validation errors were fed back on retry


def test_validate_only_cli():
    assert digest.main(["--validate-only", str(FIX / "digest-good.json")]) == 0
    assert digest.main(["--validate-only", str(FIX / "digest-bad.json")]) == 1


def test_run_claude_parses_list_envelope(monkeypatch):
    import subprocess

    class Proc:
        returncode = 0
        stderr = ""
        stdout = '[{"type":"system","subtype":"init"},{"type":"assistant"},{"type":"result","subtype":"success","result":"{\\"ok\\": true}"}]'

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Proc())
    assert digest.run_claude("x") == '{"ok": true}'


def test_run_claude_parses_dict_envelope(monkeypatch):
    import subprocess

    class Proc:
        returncode = 0
        stderr = ""
        stdout = '{"type":"result","result":"hello"}'

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Proc())
    assert digest.run_claude("x") == "hello"


def test_landed_digest_still_validates():
    import digest as dg
    d = json.loads((FIX / "digest-good.json").read_text())
    d["landed"] = {"file": "worklog.org", "heading": "Rob 1-1"}
    assert dg.validate(d) == []


def test_schema_rejects_newlines_in_text():
    import digest as dg
    d = json.loads((FIX / "digest-good.json").read_text())
    d["summary"] = "one\n* two"
    assert any("summary" in e for e in dg.validate(d))


def test_digest_date_source_from_header(org_dir, tmp_path, monkeypatch):
    good = json.loads((FIX / "digest-good.json").read_text())
    good["date"], good["source"] = "2026-10-19", "manual"  # model drifted from the header
    good["follow_ups"].append({"text": "earlier than the meeting", "with": ["Rob"], "when": "2025-01-01"})
    monkeypatch.setattr(digest, "run_claude", lambda prompt, timeout=300: json.dumps(good))
    out = tmp_path / "d.json"
    assert digest.main([str(_normalized(tmp_path)), "-o", str(out)]) == 0
    d = json.loads(out.read_text())
    assert d["date"] == "2026-10-20" and d["source"] == "slack" and d["key"] == "abc"
    assert d["follow_ups"][-1]["when"] is None  # a follow-up cannot precede the meeting


def test_cli_claude_crash_returns_1(org_dir, tmp_path, monkeypatch):
    def boom(prompt, timeout=300):
        raise RuntimeError("claude exited 1: boom")

    monkeypatch.setattr(digest, "run_claude", boom)
    out = tmp_path / "d.json"
    assert digest.main([str(_normalized(tmp_path)), "-o", str(out)]) == 1
    assert "boom" in (tmp_path / "d.raw.txt").read_text()


def test_cli_usage_error_exits_1():
    assert digest.main(["--bogus"]) == 1


def test_chat_prompt_lists_open_items(org_dir):
    people = People.load(org_dir / "meetings" / "people.yaml")
    header = "title: Slack #tron\ndate: 2026-10-21\ntime: \nsource: slack\nkind: chat\nattendees: Nick, Rob\nkey: k\n"
    prompt = digest.build_prompt(header, "Rob: can you fix the proof diff?\n", people, open_items=["Align on Jira buckets"])
    assert "Align on Jira buckets" in prompt and "{{" not in prompt
    assert "already tracked" in prompt.lower()
    meeting = digest.build_prompt(header.replace("kind: chat", "kind: meeting"), "x", people, open_items=["Align on Jira buckets"])
    assert "already tracked" not in meeting.lower()


def test_pin_to_header_sets_kind():
    d = json.loads((FIX / "digest-good.json").read_text())
    out = digest.pin_to_header(d, "title: X\ndate: 2026-10-20\nsource: slack\nkind: chat\nkey: k\n")
    assert out["kind"] == "chat" and digest.validate(out) == []


def test_open_items_include_landed_auto_todos(org_dir):
    (org_dir / "worklog.org").write_text(
        "* <2026-10-21 Wed>\n\n** Slack #tron :chat:auto:\n   - meetings (auto) x\n"
        "*** TODO Send Rob the DMP access creds - @Nick :auto:\n*** DONE old thing - @Nick :auto:\n"
        "** TODO Follow up\n\n* TODO\n** Align on Jira buckets\n")
    from config import Paths
    items = digest.open_work_items(Paths(org_dir))
    assert "Send Rob the DMP access creds" in items and "Follow up" in items and "Align on Jira buckets" in items
    assert "old thing" not in items
