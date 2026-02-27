#!/bin/bash
# Installs the launchd daemon so the AI agent auto-starts at login.
# Run once: bash scripts/install_daemon.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(which python3)"
PLIST_DST="$HOME/Library/LaunchAgents/com.personalai.agent.plist"

echo "Installing Personal AI Agent daemon..."
echo "  Project: $PROJECT_DIR"
echo "  Python:  $PYTHON"

cat > "$PLIST_DST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.personalai.agent</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$PROJECT_DIR/src/menubar_app.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/logs/launchd.log</string>

    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/logs/launchd.log</string>
</dict>
</plist>
PLIST

mkdir -p "$PROJECT_DIR/logs"
launchctl load "$PLIST_DST"
echo "Done. The agent will now start automatically at login."
echo "To stop:  launchctl unload $PLIST_DST"
echo "To start: launchctl load $PLIST_DST"
