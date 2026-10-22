#!/bin/bash
# Render the two plists with absolute paths and load them as user agents (gui domain, so claude and
# m365 can reach the login keychain). Re-run to update. `--uninstall` removes them.
set -eu
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ORG_DIR="${MEETINGS_ORG_DIR:-$HOME/org/ringmaster}"
CLAUDE="$(command -v claude || true)"; [ -n "$CLAUDE" ] || { echo "claude not on PATH" >&2; exit 1; }
BIN_PATH="$(dirname "$CLAUDE"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin"
DEST="$HOME/Library/LaunchAgents"
mkdir -p "$DEST" "$ORG_DIR/meetings/logs"
for name in daily arxiv; do
  label="com.ntomasino.meetings.$name"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  if [ "${1:-}" = "--uninstall" ]; then rm -f "$DEST/$label.plist"; echo "removed $label"; continue; fi
  sed -e "s|@SKILL_DIR@|$SKILL_DIR|g" -e "s|@PATH@|$BIN_PATH|g" -e "s|@HOME@|$HOME|g" -e "s|@ORG_DIR@|$ORG_DIR|g" \
    "$SKILL_DIR/launchd/$label.plist" > "$DEST/$label.plist"
  plutil -lint "$DEST/$label.plist" >/dev/null
  launchctl bootstrap "gui/$(id -u)" "$DEST/$label.plist"
  echo "loaded $label  (kick: launchctl kickstart -k gui/$(id -u)/$label)"
done
