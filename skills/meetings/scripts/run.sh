#!/bin/bash
# Orchestrator for the meetings pipeline. Invoked by launchd (absolute paths, no shell profile).
#
#   run.sh daily              fetch Teams transcripts, then digest + land every file in inbox/
#   run.sh arxiv              weekly arXiv scan against open work items
#   run.sh digest-one <file>  normalize -> digest -> write_org -> suggest -> archive, for one file
#   run.sh status             what is pending, last runs, tail of today's log
#
# Exit: 0 ok · 2 nothing to do · 3 a write was skipped (worklog saved < 15 min ago; retried hourly)
set -u
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
UV="${UV:-/opt/homebrew/bin/uv}"
ORG_DIR="${MEETINGS_ORG_DIR:-$HOME/org/ringmaster}"
MEET="$ORG_DIR/meetings"
LOG="$MEET/logs/$(date +%F).log"
LOCK="$MEET/logs/.lock"
export MEETINGS_ORG_DIR="$ORG_DIR"
mkdir -p "$MEET/inbox" "$MEET/digests" "$MEET/archive" "$MEET/logs"

log() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "$LOG" >&2; }
py()  { "$UV" run --project "$SKILL_DIR" --quiet python "$SKILL_DIR/scripts/$@"; }

digest_one() {
  local src="$1" stem name norm dig key rc
  name="$(basename "$src")"; stem="${name%.*}"
  norm="$MEET/digests/$stem.normalized.txt"; dig="$MEET/digests/$stem.json"
  log "normalize $name"
  if ! py normalize.py "$src" -o "$norm" >>"$LOG" 2>&1; then log "  normalize failed; left in inbox"; return 1; fi
  key="$(sed -n 's/^key: //p' "$norm" | head -1)"
  if [ -s "$dig" ] && [ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("key",""))' "$dig")" != "$key" ]; then
    log "  digest on disk is for a different transcript; re-digesting"
    rm -f "$dig"
  fi
  if [ ! -s "$dig" ]; then
    log "  digest via claude -p"
    if ! py digest.py "$norm" -o "$dig" >>"$LOG" 2>&1; then log "  digest failed; left in inbox (see $MEET/digests/$stem.raw.txt)"; return 1; fi
  fi
  py write_org.py "$dig" --key "$key" >>"$LOG" 2>&1; rc=$?
  case $rc in
    0) log "  worklog: wrote";;
    2) log "  worklog: already landed";;
    3) log "  worklog: skipped (saved < 15 min ago); will retry"; return 3;;
    *) log "  worklog: error $rc; left in inbox"; return 1;;
  esac
  py suggest.py "$dig" >>"$LOG" 2>&1; rc=$?
  [ $rc -eq 0 ] && log "  suggestions: wrote"
  [ $rc -gt 2 ] && log "  suggestions: error $rc"
  local dest="$MEET/archive/$name"
  [ -e "$dest" ] && dest="$MEET/archive/$stem.$(date +%H%M%S).${name##*.}"
  mv "$src" "$dest" && log "  archived -> $(basename "$dest")"
  return 0
}

cmd_daily() {
  if ! mkdir "$LOCK" 2>/dev/null; then log "another run holds $LOCK; exiting"; exit 0; fi
  trap 'rmdir "$LOCK"' EXIT
  log "daily run start"
  if command -v m365 >/dev/null 2>&1; then
    py fetch_teams.py >>"$LOG" 2>&1; rc=$?
    case $rc in 0) log "teams: fetched new transcripts";; 2) log "teams: nothing new";; *) log "teams: fetch failed ($rc), continuing (run 'm365 status')";; esac
  else
    log "teams: m365 not installed, skipping fetch"
  fi
  local any=0 skipped=0 f
  shopt -s nullglob
  for f in "$MEET"/inbox/*.txt "$MEET"/inbox/*.vtt "$MEET"/inbox/*.docx; do
    any=1
    digest_one "$f"; rc=$?
    [ $rc -eq 3 ] && skipped=1
  done
  [ $any -eq 0 ] && log "inbox empty: nothing to do"
  log "daily run end"
  [ $skipped -eq 1 ] && exit 3
  [ $any -eq 0 ] && exit 2
  exit 0
}

cmd_arxiv() {
  log "arxiv scan start"
  py arxiv_scan.py "$@" >>"$LOG" 2>&1; rc=$?
  log "arxiv scan end (exit $rc)"
  exit $rc
}

cmd_status() {
  echo "org dir:   $ORG_DIR"
  echo "inbox:     $(ls "$MEET/inbox" 2>/dev/null | wc -l | tr -d ' ') file(s)"; ls "$MEET/inbox" 2>/dev/null | sed 's/^/           /'
  echo "archived:  $(ls "$MEET/archive" 2>/dev/null | wc -l | tr -d ' ') file(s)"
  if [ -f "$MEET/state.json" ]; then
    python3 -c "import json,sys; s=json.load(open(sys.argv[1])); print('last poll: ', s.get('last_teams_poll')); print('last arxiv:', s.get('last_arxiv_run')); print('writes:    ', len(s.get('processed',{})))" "$MEET/state.json"
  fi
  echo "auto lines:$(grep -c ':auto:' "$ORG_DIR/worklog.org" 2>/dev/null || echo 0) in worklog.org"
  [ -f "$LOG" ] && { echo "--- $LOG"; tail -n 15 "$LOG"; }
}

case "${1:-}" in
  daily) cmd_daily;;
  arxiv) shift; cmd_arxiv "$@";;
  digest-one) [ -n "${2:-}" ] || { echo "usage: run.sh digest-one <file>" >&2; exit 1; }; digest_one "$2"; exit $?;;
  status) cmd_status;;
  *) sed -n '2,10p' "$0"; exit 1;;
esac
