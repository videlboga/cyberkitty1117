import json
from datetime import datetime, timedelta

with open('/home/cyberkitty/Projects/servertans/summary_bot/users_database.json', 'r', encoding='utf-8') as f:
    db = json.load(f)

all_dates = set()
for chat_id, chat_data in db.get('chats', {}).items():
    history = chat_data.get('history', {})
    for d in history.keys():
        # filter out any badly formatted date keys
        try:
            datetime.strptime(d, '%Y-%m-%d')
            all_dates.add(d)
        except ValueError:
            pass

    reactions = chat_data.get('reactions', {})
    for d in reactions.keys():
        try:
            datetime.strptime(d, '%Y-%m-%d')
            all_dates.add(d)
        except ValueError:
            pass

if not all_dates:
    print("В базе нет корректных дат активности.")
    exit(0)

sorted_dates = sorted(list(all_dates))
min_date_str = sorted_dates[0]
max_date_str = sorted_dates[-1]

min_date = datetime.strptime(min_date_str, '%Y-%m-%d').date()
max_date = datetime.strptime(max_date_str, '%Y-%m-%d').date()

current_date = min_date
expected_dates = set()
while current_date <= max_date:
    expected_dates.add(current_date.strftime('%Y-%m-%d'))
    current_date += timedelta(days=1)

missing_dates = sorted(list(expected_dates - all_dates))

print(f"Доступные даты ({len(sorted_dates)}):")
print(", ".join(sorted_dates))
print(f"\nПериод: с {min_date_str} по {max_date_str}")

if missing_dates:
    print(f"\nПропущенные даты ({len(missing_dates)}):")
    print(", ".join(missing_dates))
else:
    print("\nПропущенных дат в этом диапазоне нет.")
