from datetime import date

from config import Paths
from people import People
from state import State


def test_resolve_alias_case_insensitive(org_dir):
    people = People.load(org_dir / "meetings" / "people.yaml")
    assert people.resolve("REEDER") == "David"
    assert people.resolve("Nick Tomasino") == "Nick"
    assert people.resolve("j.t.") == "Joseph"


def test_resolve_unknown_is_none(org_dir):
    people = People.load(org_dir / "meetings" / "people.yaml")
    assert people.resolve("Zelda") is None


def test_is_me(org_dir):
    people = People.load(org_dir / "meetings" / "people.yaml")
    assert people.me == "Nick"
    assert people.is_me("ntomasino")
    assert not people.is_me("Rob")
    assert "Rob" in people.canonical_names


def test_state_roundtrip(org_dir):
    path = org_dir / "meetings" / "state.json"
    s = State.load(path)
    s.processed["abc"] = {"file": "x.txt"}
    s.arxiv_seen.add("2510.01234")
    s.last_teams_poll = "2026-10-22T06:30:00-07:00"
    s.save()
    s2 = State.load(path)
    assert s2.processed == {"abc": {"file": "x.txt"}}
    assert s2.arxiv_seen == {"2510.01234"}
    assert s2.last_teams_poll == "2026-10-22T06:30:00-07:00"


def test_archive_for_path(org_dir):
    p = Paths(org_dir)
    assert p.archive_for(date(2026, 9, 3)) == org_dir / "2026" / "2026-09-worklog.org"
    assert p.worklog == org_dir / "worklog.org"
    assert p.people_file == org_dir / "meetings" / "people.yaml"
