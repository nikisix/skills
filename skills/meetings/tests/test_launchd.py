"""The daily job must not run on weekends; Monday's run catches up on Friday through Sunday."""

import plistlib
from pathlib import Path

PLIST = Path(__file__).resolve().parent.parent / "launchd" / "com.ntomasino.meetings.daily.plist"


def test_daily_job_runs_weekdays_only_at_three_morning_slots():
    entries = plistlib.loads(PLIST.read_bytes())["StartCalendarInterval"]
    assert all(1 <= e.get("Weekday", 0) <= 5 for e in entries), "every slot must name a weekday (1=Mon..5=Fri)"
    assert {e["Weekday"] for e in entries} == {1, 2, 3, 4, 5}
    assert {(e["Hour"], e["Minute"]) for e in entries} == {(6, 30), (7, 30), (8, 30)}
    assert len(entries) == 15
