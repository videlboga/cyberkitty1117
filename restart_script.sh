#!/bin/bash
set -euo pipefail

DIR="/root/summary_bot"
cd "$DIR"

# Stop ONLY this bot instance, not any other "main.py" on the server.
pids="$(pgrep -f "^\\.venv/bin/python main\\.py$" || true)"
if [ -n "$pids" ]; then
  kill -TERM $pids || true
  sleep 1
  kill -KILL $pids || true
fi

nohup .venv/bin/python main.py > run.log 2>&1 & disown || true
echo "Started summary_bot in $DIR"
