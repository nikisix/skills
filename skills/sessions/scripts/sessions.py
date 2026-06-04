#!/usr/bin/env python3
"""Session note management for Claude Code sessions.

Usage:
  sessions.py next-number          — print next session number
  sessions.py init <name>          — create session file, set as current
  sessions.py scan                 — print all session filenames + overviews
  sessions.py current              — print path to active session file
  sessions.py switch <n>           — switch current session to number n
  sessions.py resume <n>           — re-open an ended session, add Resumed timestamp
  sessions.py end                  — end current session (add footer, clear pointer)
  sessions.py flush                — process pending turn immediately (no stdin; used before switch/end)
  sessions.py stop-hook            — process pending turn (called by Stop hook)
  sessions.py detect-project       — print auto-detected project name and sessions dir
  sessions.py sessions-dir         — print the current sessions dir path
  sessions.py pending-path         — print the full path to .pending-turn.json
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PENDING_FILE = ".pending-turn.json"
CURRENT_SESSION_FILE = ".current-session"
CONFIG_PATH = Path.home() / ".claude/skills/sessions/config.yaml"


def load_config() -> dict:
    """Parse config.yaml without requiring PyYAML."""
    if not CONFIG_PATH.exists():
        return {}
    config = {}
    current_section = None
    for line in CONFIG_PATH.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1] in (" ", "\t"):
            # Indented — belongs to current section
            if current_section is not None and ":" in stripped:
                key, _, value = stripped.partition(":")
                if current_section not in config:
                    config[current_section] = {}
                config[current_section][key.strip()] = value.strip()
        else:
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key, value = key.strip(), value.strip()
                if value:
                    config[key] = value
                    current_section = None
                else:
                    current_section = key
    return config


def get_project_name(config: dict | None = None) -> str:
    """Detect project name from git repo; apply aliases from config."""
    if config is None:
        config = load_config()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        common_dir = result.stdout.strip()
        common_path = Path(common_dir)
        if not common_path.is_absolute():
            common_path = (Path.cwd() / common_path).resolve()
        # common_path is the .git dir; its parent is the repo root
        name = common_path.parent.name
    except Exception:
        name = Path.cwd().name

    aliases = config.get("project_aliases", {})
    if isinstance(aliases, dict):
        name = aliases.get(name, name)

    return name


def get_sessions_dir() -> Path:
    config = load_config()
    sessions_root_str = config.get("sessions_root", "~/code/sessions")
    sessions_root = Path(sessions_root_str).expanduser()
    project = get_project_name(config)
    sessions_dir = sessions_root / project
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def next_number(sessions_dir: Path) -> int:
    files = list(sessions_dir.glob("[0-9]*.md"))
    if not files:
        return 1
    nums = []
    for f in files:
        m = re.match(r"^(\d+)", f.name)
        if m:
            nums.append(int(m.group(1)))
    return max(nums) + 1 if nums else 1


def get_current_session(sessions_dir: Path) -> "Path | None":
    state_file = sessions_dir / CURRENT_SESSION_FILE
    if not state_file.exists():
        return None
    session_path = Path(state_file.read_text().strip())
    return session_path if session_path.exists() else None


def init_session(sessions_dir: Path, name: str) -> Path:
    num = next_number(sessions_dir)
    filename = f"{num}-{name}.md"
    session_path = sessions_dir / filename
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = name.replace("-", " ").title()

    session_path.write_text(
        f"# {title}\n\n"
        f"## Overview\n\n"
        f"*Session in progress...*\n\n"
        f"---\n\n"
        f"*Started: {now}*\n"
    )
    (sessions_dir / CURRENT_SESSION_FILE).write_text(str(session_path))
    return session_path


def end_session(session_path: Path, sessions_dir: Path):
    """Append ended timestamp and clear current session pointer."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = session_path.read_text()
    session_path.write_text(content.rstrip() + f"\n\n---\n\n*Ended: {now}*\n")
    (sessions_dir / CURRENT_SESSION_FILE).unlink(missing_ok=True)


def resume_session(sessions_dir: Path, target: str) -> Path:
    """Re-open an ended session: set as current and append a Resumed timestamp."""
    files = list(sessions_dir.glob("[0-9]*.md"))
    matched = None
    for f in files:
        if re.match(rf"^{re.escape(target)}[-.]", f.name) or f.name == target:
            matched = f
            break
    if not matched:
        for f in files:
            if target in f.name:
                matched = f
                break
    if not matched:
        raise ValueError(f"No session matching '{target}'")

    (sessions_dir / CURRENT_SESSION_FILE).write_text(str(matched))
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = matched.read_text()
    matched.write_text(content.rstrip() + f"\n\n---\n\n*Resumed: {now}*\n")
    return matched


def switch_session(sessions_dir: Path, target: str) -> Path:
    """Switch current session to the one matching target number or slug."""
    files = list(sessions_dir.glob("[0-9]*.md"))
    # Exact number prefix match first
    for f in files:
        if re.match(rf"^{re.escape(target)}[-.]", f.name) or f.name == target:
            (sessions_dir / CURRENT_SESSION_FILE).write_text(str(f))
            return f
    # Partial slug match
    for f in files:
        if target in f.name:
            (sessions_dir / CURRENT_SESSION_FILE).write_text(str(f))
            return f
    raise ValueError(f"No session matching '{target}'")


def get_turn_count(session_path: Path) -> int:
    content = session_path.read_text()
    return len(re.findall(r"^## Turn \d+", content, re.MULTILINE))


def scan_overviews(sessions_dir: Path) -> list:
    files = sorted(
        sessions_dir.glob("[0-9]*.md"),
        key=lambda f: int(re.match(r"^(\d+)", f.name).group(1))
        if re.match(r"^(\d+)", f.name)
        else 0,
    )
    results = []
    for f in files:
        content = f.read_text()
        m = re.search(r"## Overview\n+(.*?)(?:\n---|\n## |\Z)", content, re.DOTALL)
        overview = m.group(1).strip() if m else "(no overview)"
        results.append({"file": f.name, "overview": overview})
    return results


def format_turn_markdown(turn_data: dict, turn_num: int) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = f"\n## Turn {turn_num} — {ts}\n\n"

    if turn_data.get("prompt"):
        md += f"### Prompt\n\n{turn_data['prompt']}\n\n"

    if turn_data.get("summary"):
        md += f"### Summary\n\n{turn_data['summary']}\n\n"

    files = turn_data.get("files_changed", [])
    if files:
        md += "### Files Changed\n\n| File | Action |\n|------|--------|\n"
        for f in files:
            if isinstance(f, dict):
                md += f"| `{f['path']}` | {f.get('action', 'modified')} |\n"
            else:
                md += f"| `{f}` | modified |\n"
        md += "\n"

    decisions = turn_data.get("decisions", [])
    if decisions:
        md += "### Decisions\n\n"
        for d in decisions:
            md += f"- {d}\n"
        md += "\n"

    errors = turn_data.get("errors_blockers", [])
    if errors:
        md += "### Errors/Blockers\n\n"
        for e in errors:
            md += f"- {e}\n"
        md += "\n"

    return md


def append_turn(session_path: Path, turn_data: dict):
    content = session_path.read_text()
    turn_num = get_turn_count(session_path) + 1

    if turn_data.get("overview"):
        new_overview = turn_data["overview"]
        content = re.sub(
            r"(## Overview\n+).*?(\n---|\n## Turn|\Z)",
            lambda m: f"{m.group(1)}{new_overview}\n\n{m.group(2)}",
            content,
            flags=re.DOTALL,
            count=1,
        )

    turn_md = format_turn_markdown(turn_data, turn_num)
    session_path.write_text(content.rstrip() + "\n" + turn_md)


def flush_pending(sessions_dir: Path):
    """Process .pending-turn.json immediately without stdin (used before switch/end)."""
    pending_path = sessions_dir / PENDING_FILE
    if not pending_path.exists():
        return None
    session_path = get_current_session(sessions_dir)
    if not session_path:
        pending_path.unlink(missing_ok=True)
        return None
    try:
        turn_data = json.loads(pending_path.read_text())
        do_end = turn_data.pop("session_end", False)
        append_turn(session_path, turn_data)
        if do_end:
            end_session(session_path, sessions_dir)
        return session_path
    finally:
        pending_path.unlink(missing_ok=True)


def run_stop_hook():
    """Called by the Stop hook: process .pending-turn.json if present."""
    try:
        json.load(sys.stdin)
    except Exception:
        pass

    sessions_dir = get_sessions_dir()
    pending_path = sessions_dir / PENDING_FILE

    if not pending_path.exists():
        print(json.dumps({}))
        return

    session_path = get_current_session(sessions_dir)
    if not session_path:
        pending_path.unlink(missing_ok=True)
        print(json.dumps({}))
        return

    try:
        turn_data = json.loads(pending_path.read_text())
        do_end = turn_data.pop("session_end", False)
        append_turn(session_path, turn_data)
        if do_end:
            end_session(session_path, sessions_dir)
    except Exception as e:
        print(json.dumps({"systemMessage": f"sessions: failed to write turn — {e}"}))
        return
    finally:
        pending_path.unlink(missing_ok=True)

    print(json.dumps({}))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    sessions_dir = get_sessions_dir()

    if cmd == "next-number":
        print(next_number(sessions_dir))

    elif cmd == "init":
        if len(sys.argv) < 3:
            print("Error: init requires a session name (e.g. api-auth-refactor)")
            sys.exit(1)
        path = init_session(sessions_dir, sys.argv[2])
        print(f"Created: {path}")

    elif cmd == "scan":
        results = scan_overviews(sessions_dir)
        if not results:
            print("No prior sessions found.")
        else:
            for r in results:
                print(f"\n### {r['file']}\n{r['overview']}")

    elif cmd == "current":
        session = get_current_session(sessions_dir)
        if not session:
            print("No active session")
        else:
            content = session.read_text()
            m = re.search(r"## Overview\n+(.*?)(?:\n---|\n## |\Z)", content, re.DOTALL)
            overview = m.group(1).strip() if m else "(no overview)"
            print(f"File: {session}\n\n{overview}")

    elif cmd == "flush":
        result = flush_pending(sessions_dir)
        print(f"Flushed to: {result}" if result else "Nothing to flush.")

    elif cmd == "resume":
        if len(sys.argv) < 3:
            print("Error: resume requires a session number or slug")
            sys.exit(1)
        try:
            path = resume_session(sessions_dir, sys.argv[2])
            print(f"Resumed: {path}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "switch":
        if len(sys.argv) < 3:
            print("Error: switch requires a session number or slug")
            sys.exit(1)
        try:
            path = switch_session(sessions_dir, sys.argv[2])
            print(f"Switched to: {path}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "end":
        session = get_current_session(sessions_dir)
        if not session:
            print("No active session to end.")
            sys.exit(1)
        end_session(session, sessions_dir)
        print(f"Ended: {session}")

    elif cmd == "detect-project":
        config = load_config()
        project = get_project_name(config)
        sessions_root = Path(config.get("sessions_root", "~/code/sessions")).expanduser()
        print(f"Project: {project}")
        print(f"Sessions dir: {sessions_root / project}")

    elif cmd == "sessions-dir":
        print(sessions_dir)

    elif cmd == "pending-path":
        print(sessions_dir / PENDING_FILE)

    elif cmd == "stop-hook":
        run_stop_hook()

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
