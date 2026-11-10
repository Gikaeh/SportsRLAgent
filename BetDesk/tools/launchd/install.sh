#!/usr/bin/env bash
# Install (or `install.sh uninstall`) the BetDesk pusher launchd agent for this user.
# The owner runs this; agent sessions don't create login items.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$HOME/Library/LaunchAgents"
NAME=com.betdesk.pusher
UID_=$(id -u)
NODE_BIN="$(command -v node)" || { echo "node not found on PATH" >&2; exit 1; }
mkdir -p "$DEST" "$HOME/Library/Logs/BetDesk"
launchctl bootout "gui/$UID_/$NAME" 2>/dev/null || true
rm -f "$DEST/$NAME.plist"
if [ "${1:-install}" = "uninstall" ]; then echo "removed $NAME"; exit 0; fi
sed -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" -e "s|__NODE__|$NODE_BIN|g" \
  "$REPO/tools/launchd/$NAME.plist" > "$DEST/$NAME.plist"
plutil -lint "$DEST/$NAME.plist" >/dev/null
launchctl bootstrap "gui/$UID_" "$DEST/$NAME.plist"
echo "installed $NAME (node: $NODE_BIN); log: ~/Library/Logs/BetDesk/pusher.log"
