#!/bin/bash
# STONEAGE Scheduler Setup
# Usage: ./set_stoneage_schedule.sh HOURS="9 14" MIN="1 31" SEC=0

# Default values (9:01 and 14:31)
HOURS="${HOURS:-9 14}"
MIN="${MIN:-1 31}"
SEC="${SEC:-0}"

PROJECT_DIR="/Users/vadimkasse/Projects/stoneage"
SCRIPT_PATH="$PROJECT_DIR/run_stoneage.sh"
PLIST_PATH="$HOME/Library/LaunchAgents/com.stoneage.daily.plist"

# 1. Clean existing crontab entries for stoneage
crontab -l | grep -v "stoneage" > mycron

# 2. Add new entries
for h in $HOURS; do
    for m in $MIN; do
        # We only add specific pairs if they are provided, 
        # but to keep it simple like your lumen example:
        echo "$m $h * * * /bin/bash $SCRIPT_PATH $SEC >> $PROJECT_DIR/cron.log 2>&1" >> mycron
    done
done

# Special case for your request: 9:01 and 14:31
# If you run without arguments, we'll just set these two specifically:
if [ "$#" -eq 0 ]; then
    echo "1 9 * * * /bin/bash $SCRIPT_PATH $SEC >> $PROJECT_DIR/cron.log 2>&1" > mycron
    echo "31 14 * * * /bin/bash $SCRIPT_PATH $SEC >> $PROJECT_DIR/cron.log 2>&1" >> mycron
fi

crontab mycron
rm mycron

echo "✓ StoneAge schedule updated in crontab."
crontab -l | grep "stoneage"
