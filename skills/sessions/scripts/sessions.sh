#!/bin/bash
# Session management CLI wrapper
# Usage: sessions <command> [args...]
# Commands: init, scan, current, end, switch, resume, detect-project, flush, help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="/Users/six/.claude/skills/sessions/scripts/sessions.py"

usage() {
    cat <<EOF
Sessions CLI — manage Claude Code session notes

Usage: sessions <command> [args...]

Commands:
  init <name>           Create new session with kebab-case name (active project)
  scan                  List all sessions with overviews (active project)
  current               Show active session file and overview
  end                   End the active session (flushes pending turn first)
  switch <n>            Switch to session n or slug fragment (flushes first)
  resume <n>            Re-open ended session n (flushes first)
  flush                 Process pending turn immediately
  detect-project        Show auto-detected project and sessions directory
  list-projects         List all projects in sessions root
  capture-path <proj> <name>       Return target session file path without creating it
  read-transcript [<session-id>]   Dump current session transcript as JSON
  capture <proj> <name> <overview> Create session in <proj> with given overview (manual)
  help                  Show this message

Config file: ~/.claude/skills/sessions/config.yaml (optional)
Sessions root: ~/code/sessions/<project> (default)

Examples:
  sessions init api-auth-refactor
  sessions scan
  sessions current
  sessions switch 2
  sessions list-projects
  sessions capture myproj feature-x "Added dashboard with real-time stats"
EOF
}

if [[ $# -eq 0 ]]; then
    usage
    exit 1
fi

cmd="$1"
shift

case "$cmd" in
    init|scan|current|end|flush|resume|switch|detect-project|sessions-dir|pending-path|stop-hook|list-projects|capture|capture-path|read-transcript)
        python3 "$PYTHON_SCRIPT" "$cmd" "$@"
        ;;
    help|--help|-h)
        usage
        ;;
    *)
        echo "Error: Unknown command '$cmd'" >&2
        echo "Run 'sessions help' for usage" >&2
        exit 1
        ;;
esac