#!/usr/bin/env bash
# Install (or `install.sh uninstall`) the DeepSports launchd agents for this user.
# Optional agent names after the action limit it to those, e.g.
#   tools/launchd/install.sh install com.deepsports.odds
#   tools/launchd/install.sh uninstall com.deepsports.odds
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$HOME/Library/LaunchAgents"
UID_=$(id -u)
ACTION="${1:-install}"
[ $# -gt 0 ] && shift
NAMES=("$@")
[ ${#NAMES[@]} -eq 0 ] && NAMES=(com.deepsports.serve com.deepsports.sync com.deepsports.odds)
mkdir -p "$DEST" "$HOME/Library/Logs/DeepSports"
for name in "${NAMES[@]}"; do
  launchctl bootout "gui/$UID_/$name" 2>/dev/null || true
  rm -f "$DEST/$name.plist"
  if [ "$ACTION" != "uninstall" ]; then
    sed -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" "$REPO/tools/launchd/$name.plist" > "$DEST/$name.plist"
    plutil -lint "$DEST/$name.plist" >/dev/null
    launchctl bootstrap "gui/$UID_" "$DEST/$name.plist"
    echo "installed $name"
  else
    echo "removed $name"
  fi
done
