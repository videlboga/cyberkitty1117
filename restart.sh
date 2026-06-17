#!/bin/bash
set -euo pipefail

DIR="/root/summary_bot"
cd "$DIR"

wait_for_death() {
  local pids="$1" max_wait="${2:-10}"
  local waited=0
  while [ "$waited" -lt "$max_wait" ]; do
    local alive=""
    for pid in $pids; do
      if kill -0 "$pid" 2>/dev/null; then alive="$alive $pid"; fi
    done
    if [ -z "$alive" ]; then return 0; fi
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}

stop_matching() {
  local pattern="$1"
  local pids="$(pgrep -f "$pattern" || true)"
  if [ -n "$pids" ]; then
    echo "Stopping $pattern (PIDs: $pids)"
    kill -TERM $pids || true
    if ! wait_for_death "$pids" 10; then
      echo "Force-killing $pattern"
      kill -KILL $pids || true
      wait_for_death "$pids" 5 || true
    fi
  fi
}

# Stop only this bot and userbot, never all python processes.
stop_matching "\.venv/bin/python main\.py"
stop_matching "\.venv/bin/python modules/userbot_sync\.py"

# Start bot
.venv/bin/python main.py > run.log 2>&1 &
echo "$!" > /tmp/summary_bot_main.pid

# Start userbot synchronizer
.venv/bin/python modules/userbot_sync.py > userbot.log 2>&1 &
echo "$!" > /tmp/summary_bot_userbot.pid

sleep 1
if kill -0 "$(cat /tmp/summary_bot_main.pid)" 2>/dev/null; then
  echo "summary_bot main.py started (PID $(cat /tmp/summary_bot_main.pid))"
else
  echo "ERROR: main.py failed to start; see run.log"
  exit 1
fi

if kill -0 "$(cat /tmp/summary_bot_userbot.pid)" 2>/dev/null; then
  echo "summary_bot userbot_sync.py started (PID $(cat /tmp/summary_bot_userbot.pid))"
else
  echo "WARNING: userbot_sync.py failed to start; see userbot.log"
fi
