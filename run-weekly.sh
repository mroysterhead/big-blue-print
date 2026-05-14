#!/bin/zsh
# Weekly homework sync. Invoked by launchd every Monday.
# Logs to ~/git/tj_app/weekly.log

set -e
cd "$(dirname "$0")"

# Ensure Homebrew binaries are on PATH (launchd jobs start with a minimal PATH)
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

echo "===== $(date) ====="
python3 hw_to_ics.py
gcalcli --default-calendar "Family" import homework.ics
echo
