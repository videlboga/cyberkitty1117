#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
sudo ip netns exec vpnspace pkill -f "python main.py" || true
sudo killall python || true
pkill -f "main.py" || true
sleep 1
sudo ip netns exec vpnspace bash -c "cd $DIR && source .venv/bin/activate && PYTHONUNBUFFERED=1 python main.py > run.log 2>&1 &"
echo "Bot restarted in $DIR"
