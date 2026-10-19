#!/bin/bash
# STONEAGE Scheduler Setup (LaunchAgent version)
# Usage: ./set_stoneage_schedule.sh HOURS="9 14" MIN=1 SEC=30

# 1. Parse arguments like KEY=VALUE
for arg in "$@"; do
    case "$arg" in
        HOURS=*) HOURS="${arg#*=}" ;;
        MIN=*)   MIN="${arg#*=}" ;;
        SEC=*)   SEC="${arg#*=}" ;;
    esac
done

# 2. Defaults if not provided via args or env
HOURS="${HOURS:-9 14}"
MIN="${MIN:-1}"
SEC="${SEC:-0}"

PROJECT_DIR="/Users/vadimkasse/Projects/stoneage"
SCRIPT_PATH="$PROJECT_DIR/run_stoneage.sh"
LABEL="com.stoneage.daily"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

# Unload existing agent
launchctl unload "$PLIST_PATH" 2>/dev/null

# Build PLIST XML
echo '<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>'$LABEL'</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>'$SCRIPT_PATH'</string>
        <string>'$SEC'</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>' > "$PLIST_PATH"

for h in $HOURS; do
    echo "        <dict>
            <key>Hour</key>
            <integer>$h</integer>
            <key>Minute</key>
            <integer>$MIN</integer>
        </dict>" >> "$PLIST_PATH"
done

echo '    </array>
    <key>StandardOutPath</key>
    <string>'$HOME'/Library/Logs/stoneage.log</string>
    <key>StandardErrorPath</key>
    <string>'$HOME'/Library/Logs/stoneage.error.log</string>
</dict>
</plist>' >> "$PLIST_PATH"

# Load the agent
launchctl load "$PLIST_PATH"

echo "✓ StoneAge schedule updated: $PLIST_PATH"
echo "Times: $HOURS:$MIN (Delay: $SEC seconds)"
