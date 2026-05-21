#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "🚀 Запуск CyberKitty Summary Core-версии через vpnspace..."

# Проверяем наличие vpnspace
if ! sudo ip netns list | grep -q "^vpnspace"; then
    echo "❌ Ошибка: сетевое пространство 'vpnspace' не найдено."
    exit 1
fi

sudo ip netns exec vpnspace bash -c "source .venv/bin/activate && python main.py"
