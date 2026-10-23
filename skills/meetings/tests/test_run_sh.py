"""run.sh end to end with a fake `claude` (CLAUDE_BIN) so no model is called."""
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

SKILL = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures"
FAKE_CLAUDE = '''#!/usr/bin/env python3
import json, sys
prompt = sys.stdin.read()
d = json.load(open(%r))
d["title"] = "Second" if "SECOND" in prompt else d["title"]
d["attendees"] = ["Nick"]
print(json.dumps([{"type": "result", "result": json.dumps(d)}]))
'''


@pytest.fixture
def org(org_dir, tmp_path):
    shutil.copy(FIX / "worklog-sample.org", org_dir / "worklog.org")
    old = time.time() - 3600
    os.utime(org_dir / "worklog.org", (old, old))
    fake = tmp_path / "claude"
    fake.write_text(FAKE_CLAUDE % str(FIX / "digest-good.json"))
    fake.chmod(0o755)
    return org_dir, fake


def run(org_dir, fake, *args):
    env = {**os.environ, "MEETINGS_ORG_DIR": str(org_dir), "CLAUDE_BIN": str(fake)}
    return subprocess.run(["bash", str(SKILL / "scripts" / "run.sh"), *args], env=env, capture_output=True, text=True)


def test_reused_filename_is_redigested(org):
    org_dir, fake = org
    inbox = org_dir / "meetings" / "inbox"
    shutil.copy(FIX / "2026-10-20-rob-1-1.txt", inbox / "2026-10-20-rob-1-1.txt")
    assert run(org_dir, fake, "daily").returncode == 0
    (inbox / "2026-10-20-rob-1-1.txt").write_text("title: Rob 1:1\ndate: 2026-10-20\n\nRob: SECOND transcript\n")
    old = time.time() - 3600
    os.utime(org_dir / "worklog.org", (old, old))  # otherwise the mtime guard (rightly) skips
    assert run(org_dir, fake, "daily").returncode == 0
    text = (org_dir / "worklog.org").read_text()
    assert text.count("*** meetings (auto)") == 2
    assert "** Second :meeting:auto:" in text  # the new transcript was digested, not the stale JSON reused
    assert run(org_dir, fake, "daily").returncode == 2  # inbox empty


def test_arxiv_usage_error_is_not_nothing_to_do(org):
    org_dir, fake = org
    assert run(org_dir, fake, "arxiv", "--", "--dry-run").returncode == 1


def test_chat_file_lands_as_chat_block(org):
    org_dir, fake = org
    (org_dir / "meetings" / "inbox" / "2026-10-21-slack-tron.txt").write_text(
        "title: Slack #tron\ndate: 2026-10-21\ntime: 09:00\nsource: slack\nkind: chat\nattendees: Rob Smith, Nick Tomasino\n\n"
        "Rob Smith: @Nick Tomasino can you look at the proof diff?\nNick Tomasino: yes, by Friday.\n")
    r = run(org_dir, fake, "daily")
    assert r.returncode == 0, r.stdout + r.stderr
    text = (org_dir / "worklog.org").read_text()
    assert "** Slack :chat:auto:\n*** Rob 1:1 :chat:auto:" in text  # fake claude keeps the fixture title; kind from the header
    assert text.count(":chat:auto:") == 2  # the day's group + the one conversation
