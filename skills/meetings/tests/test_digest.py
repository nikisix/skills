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
