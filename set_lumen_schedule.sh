#!/bin/bash

for arg in "$@"; do
  case $arg in
    HOURS=*) HOURS="${arg#HOURS=}" ;;
    MIN=*) MIN="${arg#MIN=}" ;;
    SEC=*) SEC="${arg#SEC=}" ;;
  esac
done

HOURS=$(echo "$HOURS" | xargs)
MIN=$(echo "$MIN" | xargs)
SEC=$(echo "$SEC" | xargs)

PLIST="$HOME/Library/LaunchAgents/com.lumen.daily.plist"

launchctl unload "$PLIST" 2>/dev/null

{
echo '<?xml version="1.0" encoding="UTF-8"?>'
echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
echo '<plist version="1.0"><dict>'

echo '<key>Label</key><string>com.lumen.daily</string>'

echo '<key>ProgramArguments</key>'
echo '<array>'
echo '<string>/bin/bash</string>'
echo '<string>-c</string>'
echo "<string>sleep $SEC; /opt/miniconda3/bin/python3 /Users/vadimkasse/Projects/lumen/lumen_generator.py</string>"
echo '</array>'

echo '<key>WorkingDirectory</key><string>/Users/vadimkasse/Projects/lumen</string>'

echo '<key>StartCalendarInterval</key>'
echo '<array>'
for h in $HOURS; do
  echo "<dict><key>Hour</key><integer>$h</integer><key>Minute</key><integer>$MIN</integer></dict>"
done
echo '</array>'

echo '<key>StandardOutPath</key><string>/Users/vadimkasse/Library/Logs/lumen.log</string>'
echo '<key>StandardErrorPath</key><string>/Users/vadimkasse/Library/Logs/lumen.error.log</string>'

echo '<key>KeepAlive</key><false/>'
echo '<key>RunAtLoad</key><false/>'

echo '<key>EnvironmentVariables</key>'
echo '<dict>'
echo '<key>PATH</key>'
echo '<string>/opt/homebrew/bin:/opt/homebrew/sbin:/opt/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>'
echo '<key>HOME</key>'
echo "<string>/Users/vadimkasse</string>"
echo '</dict>'

echo '</dict></plist>'
} > "$PLIST"

plutil -lint "$PLIST" || exit 1
launchctl load "$PLIST"
plutil -p "$PLIST"