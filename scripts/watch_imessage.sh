#!/bin/bash
#
# Watch for incoming iMessages and route them to the Flowers bot.
# Polls 'imsg history' every 2 seconds instead of using 'imsg watch'
# (which requires Full Disk Access for filesystem monitoring).
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
exec python3 scripts/poll_imessage.py
