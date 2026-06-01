import csv
import io
from aiogram.types import BufferedInputFile

async def process_export(target_message, chat_data: dict, chat_id: str, args: list = None, db: dict = None):
    """Шлюз для выгрузки данных в CSV-формате (юзеры + сообщения)."""
    if args is None:
        args = []
    if db is None:
        db = {}
        
    history = chat_data.get('history', {})
    reactions_db = chat_data.get('reactions', {})
    membership_db = chat_data.get('membership_events', [])
    users_db = db.get('users', {})
    
    if not history and not reactions_db and not membership_db:
        return await target_message.answer(f"В базе пока нет записей для группы {chat_id}.")
        
    export_history = {}
    export_reactions = {}
    export_membership = []
    
    membership_db = chat_data.get('membership_events', [])
    
    if len(args) == 0:
        export_history = history
        export_reactions = reactions_db
        export_membership = membership_db
        period_str = "за всё время"
    elif len(args) == 1:
        date_target = args[0]
        if date_target in history or date_target in reactions_db or any(m.get("date", "").startswith(date_target) for m in membership_db):
            if date_target in history: export_history[date_target] = history[date_target]
            if date_target in reactions_db: export_reactions[date_target] = reactions_db[date_target]
            export_membership = [m for m in membership_db if m.get("date", "").startswith(date_target)]
            period_str = f"за {date_target}"
        else:
            return await target_message.answer(f"Нет данных за {date_target}. Формат: YYYY-MM-DD")
    elif len(args) >= 2:
        start_date, end_date = args[0], args[1]
        for date_key in history.keys():
            if start_date <= date_key <= end_date:
                export_history[date_key] = history[date_key]
        for date_key in reactions_db.keys():
            if start_date <= date_key <= end_date:
                export_reactions[date_key] = reactions_db[date_key]
        export_membership = [m for m in membership_db if start_date <= m.get("date", "")[:10] <= end_date]
        period_str = f"с {start_date} по {end_date}"
        
        if not export_history and not export_reactions and not export_membership:
            return await target_message.answer("В указанном диапазоне нет данных.")
            
    # Собираем статистику
    user_stats = {}
    # str(user_id): {"messages": 0, "reactions_given": 0, "reactions_received": 0}
    
    # Карта message_id -> author_id для подсчета полученных реакций
    msg_author_map = {}
    
    all_messages = []
    
    # 1. Проход по истории сообщений
    for date_key, messages in export_history.items():
        for msg in messages:
            uid = str(msg.get("user_id"))
            link = msg.get("link_to_message", "")
            
            # Извлекаем message_id из ссылки: https://t.me/c/chat_id/msg_id
            msg_id = None
            if link:
                parts = link.split("/")
                if len(parts) > 0 and parts[-1].isdigit():
                    msg_id = int(parts[-1])
            
            if uid not in user_stats:
                user_stats[uid] = {"messages": 0, "reactions_given": 0, "reactions_received": 0}
                
            user_stats[uid]["messages"] += 1
            if msg_id:
                msg_author_map[msg_id] = uid
                
            msg_text = msg.get("text_in_msg", "") or msg.get("text", "")
            if not msg_text:
                msg_text = "[Медиа/Без текста]"

            all_messages.append({
                "user_id": uid,
                "link": link,
                "date": msg.get("timestamp", date_key),
                "text": msg_text
            })

    # 2. Проход по реакциям (кто кому поставил)
    for date_key, reactions in export_reactions.items():
        for rxn in reactions:
            reactor = str(rxn.get("reactor_user_id"))
            delta = rxn.get("delta", 0)
            msg_id = rxn.get("message_id")
            
            if delta > 0:
                # Поставил реакцию
                if reactor not in user_stats:
                    user_stats[reactor] = {"messages": 0, "reactions_given": 0, "reactions_received": 0}
                user_stats[reactor]["reactions_given"] += delta
                
                # Получил реакцию
                author = msg_author_map.get(msg_id)
                if author:
                    if author not in user_stats:
                        user_stats[author] = {"messages": 0, "reactions_given": 0, "reactions_received": 0}
                    user_stats[author]["reactions_received"] += delta

    # Генерация CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Блок 1: Статистика пользователей
    writer.writerow(["СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ"])
    writer.writerow(["Пользователь", "Отправлено сообщений", "Поставлено реакций", "Получено реакций"])
    
    for uid, stats in sorted(user_stats.items(), key=lambda x: x[1]["messages"], reverse=True):
        username = users_db.get(uid, {}).get("username", f"ID:{uid}")
        writer.writerow([
            username, 
            stats["messages"], 
            stats["reactions_given"], 
            stats["reactions_received"]
        ])
        
    writer.writerow([])
    writer.writerow([])
    
    # Блок 2: Все сообщения
    writer.writerow(["СПИСОК СООБЩЕНИЙ"])
    writer.writerow(["Пользователь", "Дата и время", "Текст сообщения", "Ссылка на сообщение"])
    
    for msg in sorted(all_messages, key=lambda x: x["date"]):
        uid = msg["user_id"]
        username = users_db.get(uid, {}).get("username", f"ID:{uid}")
        writer.writerow([
            username,
            msg["date"],
            msg["text"],
            msg["link"]
        ])
        
    writer.writerow([])
    writer.writerow([])
    
    # Блок 3: Подписки и отписки
    writer.writerow(["ИСТОРИЯ ПОДПИСОК/ОТПИСОК"])
    writer.writerow(["Чат", "Пользователь", "Отписка/Подписка", "Дата"])
    
    for event in sorted(export_membership, key=lambda x: x["date"]):
        uid = str(event["user_id"])
        username = users_db.get(uid, {}).get("username", f"ID:{uid}")
        action_ru = "Подписка" if event["action"] == "joined" else "Отписка"
        writer.writerow([
            chat_id,
            username,
            action_ru,
            event["date"]
        ])
        
    csv_bytes = output.getvalue().encode('utf-8')
    caption = f"📦 Выгрузка данных для группы {chat_id} {period_str}."
    
    await target_message.answer_document(
        document=BufferedInputFile(csv_bytes, filename=f"export_{chat_id}.csv"),
        caption=caption
    )

import csv
import io

def build_global_export_csv_bytes(chats, args=None, db=None) -> tuple[bytes, str, str]:
    if args is None: args = []
    if db is None: db = {}
    users_db = db.get('users', {})
    
    period_str = "за всё время"
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # 1. Сбор всей истории
    all_events = []
    
    for c_id, title, chat_data in chats:
        membership_db = chat_data.get('membership_events', [])
        history = chat_data.get('history', {})
        reactions_db = chat_data.get('reactions', {})
        
        export_history = {}
        export_reactions = {}
        export_membership = []
        
        if len(args) == 0:
            export_history = history
            export_reactions = reactions_db
            export_membership = membership_db
            period_str = "за всё время"
        elif len(args) == 1:
            date_target = args[0]
            if date_target in history: export_history[date_target] = history[date_target]
            if date_target in reactions_db: export_reactions[date_target] = reactions_db[date_target]
            export_membership = [m for m in membership_db if m.get("date", "").startswith(date_target)]
            period_str = f"за {date_target}"
        elif len(args) >= 2:
            start_date, end_date = args[0], args[1]
            for date_key, msgs in history.items():
                if start_date <= date_key <= end_date:
                    export_history[date_key] = msgs
            for date_key, rxns in reactions_db.items():
                if start_date <= date_key <= end_date:
                    export_reactions[date_key] = rxns
            export_membership = [m for m in membership_db if start_date <= m.get("date", "")[:10] <= end_date]
            period_str = f"с {start_date} по {end_date}"
            
        # Collect for this chat
        for event in export_membership:
            e_copy = dict(event)
            e_copy['chat_title'] = title
            all_events.append(e_copy)
            
    # Write only membership events for simplicity? Or user stats too?
    # Let's just output membership events for the global export
    
    # --- ADDED CODE: Gather stats and messages for all chats ---
    user_stats = {}
    msg_author_map = {}
    all_messages = []
    
    for c_id, title, chat_data in chats:
        history = chat_data.get('history', {})
        reactions_db = chat_data.get('reactions', {})
        
        export_history = {}
        export_reactions = {}
        
        if len(args) == 0:
            export_history = history
            export_reactions = reactions_db
        elif len(args) == 1:
            date_target = args[0]
            if date_target in history: export_history[date_target] = history[date_target]
            if date_target in reactions_db: export_reactions[date_target] = reactions_db[date_target]
        elif len(args) >= 2:
            start_date, end_date = args[0], args[1]
            for date_key, msgs in history.items():
                if start_date <= date_key <= end_date:
                    export_history[date_key] = msgs
            for date_key, rxns in reactions_db.items():
                if start_date <= date_key <= end_date:
                    export_reactions[date_key] = rxns
                    
        for date_key, messages in export_history.items():
            for msg in messages:
                uid = str(msg.get("user_id"))
                link = msg.get("link_to_message", "")
                
                msg_id = None
                if link:
                    parts = link.split("/")
                    if len(parts) > 0 and parts[-1].isdigit():
                    msg_id = int(parts[-1])
                            
                uid_chat_key = f"{uid}_{c_id}"
                if uid_chat_key not in user_stats:
                    user_stats[uid_chat_key] = {"uid": uid, "chat_title": title, "messages": 0, "reactions_given": 0, "reactions_received": 0}
                
                user_stats[uid_chat_key]["messages"] += 1
                if msg_id:
                    msg_author_map[f"{c_id}_{msg_id}"] = uid_chat_key
                
                # Use "text_in_msg" fallback to "text" inside the JSON or a placeholder.
                msg_text = msg.get("text_in_msg", "") or msg.get("text", "")
                if not msg_text:
                    msg_text = "[Медиа/Без текста]"

                all_messages.append({
                    "chat_title": title,
                    "user_id": uid,
                    "link": link,
                    "date": msg.get("timestamp", date_key),
                    "text": msg_text
                })        for date_key, reactions in export_reactions.items():
            for rxn in reactions:
                reactor = str(rxn.get("reactor_user_id"))
                delta = rxn.get("delta", 0)
                msg_id = rxn.get("message_id")
                
                reactor_chat_key = f"{reactor}_{c_id}"
                if delta > 0:
                    if reactor_chat_key not in user_stats:
                        user_stats[reactor_chat_key] = {"uid": reactor, "chat_title": title, "messages": 0, "reactions_given": 0, "reactions_received": 0}
                    user_stats[reactor_chat_key]["reactions_given"] += delta
                    
                    author_chat_key = msg_author_map.get(f"{c_id}_{msg_id}")
                    if author_chat_key:
                        if author_chat_key not in user_stats:
                            user_stats[author_chat_key] = {"uid": author_chat_key.split('_')[0], "chat_title": title, "messages": 0, "reactions_given": 0, "reactions_received": 0}
                        user_stats[author_chat_key]["reactions_received"] += delta

    writer.writerow(["СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ ПО ЧАТАМ"])
    writer.writerow(["Чат", "Пользователь", "Отправлено сообщений", "Поставлено реакций", "Получено реакций"])
    for stat_key, stats in sorted(user_stats.items(), key=lambda x: x[1]["messages"], reverse=True):
        username = users_db.get(stats["uid"], {}).get("username", f"ID:{stats['uid']}")
        writer.writerow([
            stats["chat_title"],
            username, 
            stats["messages"], 
            stats["reactions_given"],
            stats["reactions_received"]
        ])
        
    writer.writerow([])
    writer.writerow([])

    writer.writerow(["СПИСОК СООБЩЕНИЙ ПО ВСЕМ ЧАТАМ"])
    writer.writerow(["Чат", "Пользователь", "Дата и время", "Текст сообщения", "Ссылка на сообщение"])
    for msg in sorted(all_messages, key=lambda x: x["date"]):
        uid = msg["user_id"]
        username = users_db.get(uid, {}).get("username", f"ID:{uid}")
        writer.writerow([
            msg["chat_title"],
            username,
            msg["date"],
            msg["text"],
            msg["link"]
        ])
        
    writer.writerow([])
    writer.writerow([])
    # --- END ADDED CODE ---

    writer.writerow(["ИСТОРИЯ ПОДПИСОК/ОТПИСОК ПО ВСЕМ ЧАТАМ"])
    writer.writerow(["Чат", "Пользователь", "Отписка/Подписка", "Дата"])
    
    for event in sorted(all_events, key=lambda x: x.get("date", "")):
        uid = str(event["user_id"])
        username = users_db.get(uid, {}).get("username", f"ID:{uid}")
        action_ru = "Подписка" if event["action"] == "joined" else "Отписка"
        writer.writerow([
            event["chat_title"],
            username,
            action_ru,
            event["date"]
        ])
        
    return output.getvalue().encode('utf-8'), period_str, ""

