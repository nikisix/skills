#!/usr/bin/env python3
"""Gate, describe, and open a merge request for the current branch.

Subcommands (run from inside the target repo):
  create_mr.py test [--label LABEL] [--dry-run]
      Run the configured suites in order (unit, golden, accuracy). Stops at the first
      failure, writes create-mr--failed-tests.md, and exits 1. On success, writes
      create-mr--test-results.md.
  create_mr.py describe --summary FILE --review FILE --decisions FILE [--tests FILE]
      Assemble the MR description from the pieces the calling session produced and
      write it to the configured description file. Does not touch the remote.
  create_mr.py open [--title TITLE] [--draft] [--dry-run]
      Push nothing and open the MR/PR for the current branch against the target branch,
      using the description file. Uses glab for GitLab remotes and gh for GitHub remotes.

Config: .create-mr.json at the repo root (see examples/tron.create-mr.json). Commands in
`suites` may contain {label}; the label is required when a suite uses it.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CONFIG_NAME = ".create-mr.json"
FAILED_FILE = "create-mr--failed-tests.md"
RESULTS_FILE = "create-mr--test-results.md"
DEFAULT_DESCRIPTION = "create-mr--description.md"
SUITE_ORDER = ["unit", "golden", "accuracy"]
OUTPUT_TAIL_LINES = 50


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def repo_root() -> Path:
    return Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()))


def load_config(root: Path) -> dict:
    path = root / CONFIG_NAME
    if not path.exists():
        sys.exit(f"Error: {CONFIG_NAME} not found at {path}. Copy examples/tron.create-mr.json or write one for this repo.")
    return json.loads(path.read_text())


def run_suite(name: str, command: str, cwd: Path, dry_run: bool) -> dict:
    """Run one suite through the shell (commands are repo config, not user input)."""
    if dry_run:
        print(f"[dry-run] {name}: {command}")
        return {"name": name, "command": command, "exit": None, "output": ""}
    print(f"[create-mr] running {name}: {command}", file=sys.stderr)
    proc = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)
    output = (proc.stdout + proc.stderr).rstrip()
    return {"name": name, "command": command, "exit": proc.returncode, "output": output}


def branch_name(root: Path) -> str:
    """Return the checked-out branch, or '(detached)' for a detached HEAD."""
    name = git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    return "(detached)" if name == "HEAD" else name


def write_failure(root: Path, head: str, result: dict, session_path: str) -> Path:
    tail = "\n".join(result["output"].splitlines()[-OUTPUT_TAIL_LINES:])
    body = f"""# Failed tests: {result['name']}

- **Suite:** {result['name']}
- **Command:** `{result['command']}`
- **Exit code:** {result['exit']}
- **Branch / HEAD:** `{branch_name(root)}` @ `{head}`
- **Active session:** {session_path or '(none)'}
- **Written:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

## What to do next

Fix the failing {result['name']} suite in this session, then run `/create-mr` again.
The tests run in order, so a fix in one suite is confirmed by re-running from the top.

## Last {OUTPUT_TAIL_LINES} lines of output

```
{tail}
```
"""
    path = root / FAILED_FILE
    path.write_text(body)
    return path


def cmd_test(args: argparse.Namespace) -> int:
    root = repo_root()
    config = load_config(root)
    suites = config.get("suites", {})
    head = git("rev-parse", "--short", "HEAD", cwd=root)
    results = []

    for name in SUITE_ORDER:
        if name not in suites:
            continue
        command = suites[name]
        if "{label}" in command and not args.label:
            sys.exit(f"Error: the {name} suite needs --label (its command uses {{label}}).")
        command = command.replace("{label}", args.label or "")
        result = run_suite(name, command, root, args.dry_run)
        results.append(result)
        if result["exit"] not in (None, 0):
            if not args.dry_run:
                failed = write_failure(root, head, result, args.session or "")
                print(f"[create-mr] {name} failed (exit {result['exit']}). Handoff written to {failed}", file=sys.stderr)
            return 1

    if args.dry_run:
        return 0
    lines = ["**Test results**", "", f"- **HEAD:** `{head}`", f"- **Run:** {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    lines += ["| Suite | Command | Result |", "|-------|---------|--------|"]
    lines += [f"| {r['name']} | `{r['command']}` | pass |" for r in results]
    (root / RESULTS_FILE).write_text("\n".join(lines) + "\n")
    print(f"[create-mr] all {len(results)} suites passed. Results: {root / RESULTS_FILE}")
    return 0


def read_optional(path: str | None, fallback: str) -> str:
    if not path:
        return fallback
    return Path(path).read_text().strip()


def cmd_describe(args: argparse.Namespace) -> int:
    root = repo_root()
    config = load_config(root)
    summary = read_optional(args.summary, "(no summary provided)")
    review = read_optional(args.review, "(code review not run)")
    decisions = read_optional(args.decisions, "(no decisions recorded)")
    tests = read_optional(args.tests or str(root / RESULTS_FILE), "(test results not recorded)")

    body = f"""## Summary

{summary}

## Decisions

Each decision records the question as posed, who answered it, the choices offered, and the
selection in bold. Review these for the reasoning behind the change, not the code.

{decisions}

## Code review

{review}

## Test results

{tests}
"""
    path = root / config.get("description_file", DEFAULT_DESCRIPTION)
    path.write_text(body)
    print(f"[create-mr] description written: {path}")
    return 0


def remote_host(root: Path) -> str:
    url = git("remote", "get-url", "origin", cwd=root)
    return "github" if "github.com" in url else "gitlab"


def cmd_open(args: argparse.Namespace) -> int:
    root = repo_root()
    config = load_config(root)
    target = config.get("target_branch", "main")
    description = root / config.get("description_file", DEFAULT_DESCRIPTION)
    if not description.exists():
        sys.exit(f"Error: {description} not found. Run `create_mr.py describe` first.")
    title = args.title or git("log", "-1", "--format=%s", cwd=root)
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)

    if remote_host(root) == "github":
        command = ["gh", "pr", "create", "--base", target, "--head", branch, "--title", title, "--body-file", str(description)]
        if args.draft:
            command.append("--draft")
    else:
        command = ["glab", "mr", "create", "--source-branch", branch, "--target-branch", target,
                   "--title", title, "--description", description.read_text(), "--yes"]
        if args.draft:
            command.append("--draft")

    if args.dry_run:
        printable = [c if len(c) < 120 else f"<{len(c)} chars from {description.name}>" for c in command]
        print("[dry-run]", " ".join(printable))
        return 0
    proc = subprocess.run(command, cwd=root)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_test = sub.add_parser("test")
    p_test.add_argument("--label", help="run label for suites that use {label} (for example the accuracy run)")
    p_test.add_argument("--session", help="path to the active session file, recorded in the failure handoff")
    p_test.add_argument("--dry-run", action="store_true", help="print the suite commands without running them")

    p_desc = sub.add_parser("describe")
    p_desc.add_argument("--summary", help="file with the MR summary")
    p_desc.add_argument("--review", help="file with the code-review findings")
    p_desc.add_argument("--decisions", help="file with `sessions.py decisions` output")
    p_desc.add_argument("--tests", help="file with test results (defaults to create-mr--test-results.md)")

    p_open = sub.add_parser("open")
    p_open.add_argument("--title")
    p_open.add_argument("--draft", action="store_true")
    p_open.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    return {"test": cmd_test, "describe": cmd_describe, "open": cmd_open}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
