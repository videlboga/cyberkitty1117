"""Main entry for the Telegram bot, managing lifecycle and user roles via DM menu."""

import asyncio
import logging
from datetime import datetime as dt, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    MessageReactionUpdated
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from modules.config import API_TOKEN as BOT_TOKEN
from modules.db import load_database, save_database
from modules.summary import save_message_to_database, get_summary_data
from modules.export import process_export

ADMIN_ID = 648981358
PAGE_SIZE = 5

logging.basicConfig(level=logging.INFO)

# Initializing aiogram 3 components
dp = Dispatcher()


async def safe_answer_callback(callback_query: CallbackQuery, text: str | None = None, show_alert: bool = False):
    """Try to answer a callback_query but ignore invalid/expired query errors."""
    try:
        if text is None:
            await callback_query.answer()
        else:
            await callback_query.answer(text, show_alert=show_alert)
    except Exception as e:
        logging.warning(f"Ignored callback answer error: {e}")

def is_superadmin(user_id, db):
    return str(user_id) in db.get('superadmins', [str(ADMIN_ID)])

def is_admin(user_id, chat_id_str, db):
    if is_superadmin(user_id, db): return True
    return str(user_id) in db.get('chats', {}).get(chat_id_str, {}).get('admins', [])

def get_admin_groups(user_id, db):
    """Список групп, в которых юзер админ или суперадмин."""
    is_sa = is_superadmin(user_id, db)
    groups = {}
    for cid, cdata in db.get('chats', {}).items():
        if str(user_id) in cdata.get('admins', []) or is_sa:
            title = cdata.get('title', f"Группа {cid}")
            if title == cid or str(title).startswith('-'):
                title = f"Чат {cid}"
            groups[cid] = title
    return groups

def _build_group_page_kb(groups: dict, page: int):
    """Build paginated inline keyboard for group list."""
    group_items = list(groups.items())
    total = len(group_items)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    page_items = group_items[start:end]
    
    keyboard_rows = []
    for cid, title in page_items:
        keyboard_rows.append([InlineKeyboardButton(text=f"📁 {title}", callback_data=f"manage:{cid}")])
    
    if total > 0:
        keyboard_rows.append([InlineKeyboardButton(text="🌍 Глобальный сбор", callback_data="global_summary")])
        
    nav_row = []
    if total_pages > 1:
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"main_menu_page:{page - 1}"))
        nav_row.append(InlineKeyboardButton(text=f" 📄 {page + 1}/{total_pages}", callback_data="nav_info"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"main_menu_page:{page + 1}"))
            
    if nav_row:
        keyboard_rows.append(nav_row)
        
    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows), total_pages

@dp.message(Command(commands=['start', 'menu']))
async def cmd_start(message: Message):
    if message.chat.type != 'private':
        return await message.reply("Управление ботом перенесено в личные сообщения. Напишите мне /start в ЛС.")
    
    db = load_database()
    user_id = str(message.from_user.id)
    groups = get_admin_groups(user_id, db)
    
    if not groups:
        return await message.answer("Привет! Я бот-суммаризатор.\nВы пока не привязали ни одной группы.\n\nПросто добавьте меня в вашу группу (и любые сообщения в ней), и она автоматически появится здесь в меню управления (для всех администраторов этой группы).")
    
    kb, _ = _build_group_page_kb(groups, 0)
    await message.answer("🎛 Главное меню управления группами:\nВыберите группу для действий:", reply_markup=kb)

@dp.callback_query(F.data.startswith('main_menu_page:'))
async def cb_main_menu_page(callback_query: CallbackQuery):
    await callback_query.answer()
    db = load_database()
    user_id = str(callback_query.from_user.id)
    groups = get_admin_groups(user_id, db)
    if not groups:
        await callback_query.message.edit_text("Привет! Я бот-суммаризатор.\nВы пока не привязали ни одной группы.")
        return
    page = int(callback_query.data.split(':')[1])
    kb, _ = _build_group_page_kb(groups, page)
    await callback_query.message.edit_text("🎛 Главное меню управления группами:\nВыберите группу для действий:", reply_markup=kb)

@dp.callback_query(F.data == 'nav_info')
async def cb_nav_info(callback_query: CallbackQuery):
    await callback_query.answer("Используйте ◀️▶️ для переключения страниц", show_alert=False)

@dp.callback_query(F.data.startswith('manage:'))
async def cb_manage_group(callback_query: CallbackQuery, bot: Bot):
    await safe_answer_callback(callback_query)
    db = load_database()
    user_id = str(callback_query.from_user.id)
    chat_id_str = callback_query.data.split(':')[1]
    
    if not is_admin(user_id, chat_id_str, db):
        return await callback_query.answer("Нет прав!", show_alert=True)
        
    title = db.get('chats', {}).get(chat_id_str, {}).get('title', chat_id_str)
    if title == chat_id_str or str(title).startswith('-'):
        try:
            chat_info = await bot.get_chat(chat_id_str)
            if chat_info.title:
                title = chat_info.title
                db['chats'][chat_id_str]['title'] = title
                await save_database(db)
        except Exception:
            pass
            
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Собрать сводку", callback_data=f"sum_period:{chat_id_str}")
    builder.button(text="📦 Выгрузить CSV", callback_data=f"export:{chat_id_str}")
    builder.button(text="⚙️ Настройки", callback_data=f"settings:{chat_id_str}")
    builder.button(text="🔙 Назад", callback_data="main_menu")
    builder.adjust(2, 1, 1)

    await bot.edit_message_text(
        text=f"⚙️ Управление: <b>{title}</b>",
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == 'main_menu')
async def cb_main_menu(callback_query: CallbackQuery, bot: Bot):
    await callback_query.answer()
    db = load_database()
    user_id = str(callback_query.from_user.id)
    groups = get_admin_groups(user_id, db)
    if not groups:
        await callback_query.message.edit_text("Привет! Я бот-суммаризатор.\nВы пока не привязали ни одной группы.")
        return
    kb, _ = _build_group_page_kb(groups, 0)
    await callback_query.message.edit_text("🎛 Главное меню управления группами:\nВыберите группу для действий:", reply_markup=kb)

@dp.callback_query(F.data.startswith('sum_period:'))
async def cb_sum_period(callback_query: CallbackQuery, bot: Bot):
    await safe_answer_callback(callback_query)
    db = load_database()
    chat_id_str = callback_query.data.split(':')[1]
    user_id = str(callback_query.from_user.id)
    if not is_admin(user_id, chat_id_str, db):
        return await callback_query.answer("Нет прав!", show_alert=True)
        
    today = dt.now().date()
    yesterday = today - timedelta(days=1)
    
    builder = InlineKeyboardBuilder()
    
    history = db.get('chats', {}).get(chat_id_str, {}).get('history', {})
    dates = list(set([str(today), str(yesterday)] + list(history.keys())))
    dates.sort(reverse=True)
    dates = dates[:7]
    for d in dates:
        if d == str(today): label = "📅 Сегодня"
        elif d == str(yesterday): label = "🔙 Вчера"
        else: label = f"📆 {d}"
        builder.button(text=label, callback_data=f"summary:{chat_id_str}:{d}")
        
    builder.button(text="🔙 Назад", callback_data=f"manage:{chat_id_str}")
    builder.adjust(1)
    
    await bot.edit_message_text("Выберите период для сводки:", callback_query.message.chat.id, callback_query.message.message_id, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith('summary:'))
async def cb_summary_group(callback_query: CallbackQuery, bot: Bot):
    await callback_query.answer("Собираю данные, это займет время...")
    db = load_database()
    parts = callback_query.data.split(':')
    chat_id_str = parts[1]
    date_str = parts[2] if len(parts) > 2 else str(dt.now().date())
    user_id = str(callback_query.from_user.id)
    
    if not is_admin(user_id, chat_id_str, db): return
    
    summary = await get_summary_data(chat_id_str, date_str, db)
    if summary:
        await bot.send_message(callback_query.message.chat.id, f"✅ Сводка за {date_str} собрана:")
        await bot.send_message(callback_query.message.chat.id, summary)
    else:
        await bot.send_message(callback_query.message.chat.id, f"ℹ️ В группе за {date_str} сообщений нет.")

@dp.callback_query(F.data.startswith('export:'))
async def cb_export_group(callback_query: CallbackQuery):
    await callback_query.answer("Формирую данные...")
    db = load_database()
    chat_id_str = callback_query.data.split(':')[1]
    user_id = str(callback_query.from_user.id)
    
    if not is_admin(user_id, chat_id_str, db): return
    chat_data = db.get('chats', {}).get(chat_id_str, {})
    await process_export(callback_query.message, chat_data, chat_id_str, args=[], db=db)

@dp.callback_query(F.data == 'global_summary')
async def cb_global_summary_menu(callback_query: CallbackQuery, bot: Bot):
    await safe_answer_callback(callback_query)
    db = load_database()
    user_groups = get_admin_groups(callback_query.from_user.id, db)
    if not user_groups: return await callback_query.answer("Нет групп для сбора", show_alert=True)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Собрать сводки", callback_data="global_action:summary")
    builder.button(text="📦 Выгрузить CSV", callback_data="global_action:export")
    builder.button(text="�� Назад", callback_data="main_menu")
    builder.adjust(1)
    
    await bot.edit_message_text(
        "🌍 <b>Глобальный сбор</b>\nВыберите действие:",
        callback_query.message.chat.id,
        callback_query.message.message_id,
        reply_markup=builder.as_markup(),
    )

@dp.callback_query(F.data.startswith('global_action:'))
async def cb_global_action_choose_period(callback_query: CallbackQuery, bot: Bot):
    await safe_answer_callback(callback_query)
    db = load_database()
    user_groups = get_admin_groups(callback_query.from_user.id, db)
    if not user_groups:
        return await callback_query.answer("Нет групп", show_alert=True)

    action = callback_query.data.split(":")[1]
    
    today = dt.now().date()
    yesterday = today - timedelta(days=1)
    
    dates = {str(today), str(yesterday)}
    for chat_id in user_groups.keys():
        history = db.get("chats", {}).get(chat_id, {}).get("history", {}) or {}
        dates.update(history.keys())
        
    sorted_dates = sorted(dates, reverse=True)[:7]
    
    builder = InlineKeyboardBuilder()
    if action == "export":
        builder.button(text="🗂 Всё время", callback_data="global_run:export:all")
        
    for d in sorted_dates:
        if d == str(today):
            label = "📅 Сегодня"
        elif d == str(yesterday):
            label = "🔙 Вчера"
        else:
            label = f"�� {d}"
        builder.button(text=label, callback_data=f"global_run:{action}:{d}")
        
    builder.button(text="🔙 Назад", callback_data="global_summary")
    builder.adjust(1)

    title = "сводок" if action == "summary" else "выгрузки CSV"
    await bot.edit_message_text(
        f"Выберите период для {title}:",
        callback_query.message.chat.id,
        callback_query.message.message_id,
        reply_markup=builder.as_markup(),
    )

@dp.callback_query(F.data.startswith("global_run:"))
async def cb_global_run(callback_query: CallbackQuery, bot: Bot):
    db = load_database()
    user_id = str(callback_query.from_user.id)
    user_groups = get_admin_groups(user_id, db)
    if not user_groups:
        return await callback_query.answer("Нет групп", show_alert=True)
        
    _prefix, action, period = callback_query.data.split(":", 2)
    
    if action == "summary":
        await callback_query.answer("Обхожу чаты...")
        await bot.send_message(
            callback_query.message.chat.id, f"🔄 Обход чатов за {period}..."
        )
        
        success_count = 0
        for c_id, title in user_groups.items():
            summary = await get_summary_data(c_id, period, db)
            if summary:
                await bot.send_message(
                    callback_query.message.chat.id, f"📁 <b>{title}</b>:\n{summary}"
                )
                success_count += 1
                
        if success_count > 0:
            await bot.send_message(
                callback_query.message.chat.id,
                f"✅ Глобальный сбор завершен. Собрано сводок: {success_count}.",
            )
        else:
            await bot.send_message(callback_query.message.chat.id, "ℹ️ Нет сообщений за эту дату.")
        return

    if action == "export":
        await callback_query.answer("Формирую CSV...")
        args = []
        if period != "all":
            args = [period]
            
        chats = []
        for c_id, title in user_groups.items():
            chat_data = db.get("chats", {}).get(c_id, {})
            chats.append((c_id, title, chat_data))
            
        csv_bytes, period_str, err = build_global_export_csv_bytes(chats, args=args, db=db)
        if err:
            return await bot.send_message(callback_query.message.chat.id, err)
            
        filename_period = period if period != "all" else "all"
        await bot.send_message(
            callback_query.message.chat.id,
            f"📦 Глобальная выгрузка {period_str}.",
        )
        await bot.send_document(
            callback_query.message.chat.id,
            document=BufferedInputFile(csv_bytes, filename=f"export_global_{filename_period}_new.csv"),
        )
        return

    await callback_query.answer("Неизвестное действие", show_alert=True)

@dp.callback_query(F.data.startswith("global_act:"))
async def cb_global_summary_act_legacy(callback_query: CallbackQuery, bot: Bot):
    # Backward-compatible handler for old buttons: treat as "summary for date"
    callback_query.data = callback_query.data.replace("global_act:", "global_run:summary:", 1)
    await cb_global_run(callback_query, bot)

@dp.callback_query(F.data.startswith('settings:'))
async def cb_settings(callback_query: CallbackQuery, bot: Bot):
    await safe_answer_callback(callback_query)
    db = load_database()
    chat_id_str = callback_query.data.split(':')[1]
    if not is_admin(str(callback_query.from_user.id), chat_id_str, db): return
    
    settings = db.get('chats', {}).get(chat_id_str, {}).get('settings', {})
    time_hour = settings.get('summary_time', 21)
    topic_id = settings.get('summary_topic_id')
    topic_text = f"ID {topic_id}" if topic_id else "Не задана (общий чат)"
    
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🕒 Время отправки: {time_hour}:00", callback_data=f"set_time_menu:{chat_id_str}")
    builder.button(text=f"📂 Тема: {topic_text}", callback_data=f"set_topic_info:{chat_id_str}")
    builder.button(text="🔙 Назад", callback_data=f"manage:{chat_id_str}")
    builder.adjust(1)
    
    await bot.edit_message_text("⚙️ <b>Настройки группы</b>", callback_query.message.chat.id, callback_query.message.message_id, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith('set_time_menu:'))
async def cb_set_time_menu(callback_query: CallbackQuery, bot: Bot):
    await safe_answer_callback(callback_query)
    chat_id_str = callback_query.data.split(':')[1]
    builder = InlineKeyboardBuilder()
    
    for i in range(24):
        builder.button(text=f"{i}:00", callback_data=f"save_time:{chat_id_str}:{i}")
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"settings:{chat_id_str}"))
    
    await bot.edit_message_text("Выберите час для отправки автоматической сводки (по серверному времени):", callback_query.message.chat.id, callback_query.message.message_id, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith('save_time:'))
async def cb_save_time(callback_query: CallbackQuery, bot: Bot):
    _, chat_id_str, hour_str = callback_query.data.split(':')
    db = load_database()
    if 'settings' not in db['chats'][chat_id_str]: db['chats'][chat_id_str]['settings'] = {}
    db['chats'][chat_id_str]['settings']['summary_time'] = int(hour_str)
    await save_database(db)
    
    callback_query.data = f"settings:{chat_id_str}"
    await safe_answer_callback(callback_query)
    await cb_settings(callback_query, bot)

@dp.callback_query(F.data.startswith('set_topic_info:'))
async def cb_set_topic_info(callback_query: CallbackQuery, bot: Bot):
    await safe_answer_callback(callback_query)
    chat_id_str = callback_query.data.split(':')[1]
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Сбросить (отправлять в общий)", callback_data=f"reset_topic:{chat_id_str}")
    builder.button(text="🔙 Назад", callback_data=f"settings:{chat_id_str}")
    builder.adjust(1)
    
    text = ("Для отправки автоматической сводки в определенную подтему (топик), перейдите в этот топик в самой группе и отправьте команду:\n\n"
            "<code>/set_summary_topic</code>\n\n"
            "Бот запомнит этот топик и будет отправлять туда ежедневную сводку.")
    await bot.edit_message_text(text, callback_query.message.chat.id, callback_query.message.message_id, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith('reset_topic:'))
async def cb_reset_topic(callback_query: CallbackQuery, bot: Bot):
    chat_id_str = callback_query.data.split(':')[1]
    db = load_database()
    if 'settings' in db['chats'][chat_id_str] and 'summary_topic_id' in db['chats'][chat_id_str]['settings']:
        del db['chats'][chat_id_str]['settings']['summary_topic_id']
        await save_database(db)
        
    callback_query.data = f"settings:{chat_id_str}"
    await safe_answer_callback(callback_query)
    await cb_settings(callback_query, bot)

@dp.message(Command(commands=['set_summary_topic']))
async def cmd_set_summary_topic(message: Message):
    if message.chat.type == 'private': return
    db = load_database()
    chat_id_str = str(message.chat.id)
    if not is_admin(str(message.from_user.id), chat_id_str, db): return
    
    if not message.is_topic_message and not message.message_thread_id:
        return await message.reply("Эту команду нужно писать только внутри нужной подтемы (топика)!")
        
    if 'settings' not in db['chats'][chat_id_str]: db['chats'][chat_id_str]['settings'] = {}
    db['chats'][chat_id_str]['settings']['summary_topic_id'] = message.message_thread_id
    await save_database(db)
    await message.reply("✅ Автоматическая сводка теперь будет приходить в этот топик.")

@dp.message(Command(commands=['sa']))
async def cmd_superadmin_menu(message: Message):
    if message.chat.type != 'private': return
    db = load_database()
    user_id = str(message.from_user.id)
    if not is_superadmin(user_id, db):
        return await message.reply("У вас нет прав суперадмина.")
        
    text = "�� <b>Меню суперадмина</b>\n\nСписок администраторов и их каналы:\n\n"
    admins_map = {}
    
    for cid, cdata in db.get('chats', {}).items():
        title = cdata.get('title', cid)
        for admin in cdata.get('admins', []):
            if admin not in admins_map:
                admins_map[admin] = []
            admins_map[admin].append(title)
            
    if not admins_map:
        text += "<i>Нет подключенных администраторов.</i>"
    else:
        users = db.get('users', {})
        for admin, titles in admins_map.items():
            username = users.get(admin, {}).get('username', f"ID: {admin}")
            text += f"👤 <b>{username}</b> (<code>{admin}</code>):\n"
            for t in titles:
                text += f"  ➖ {t}\n"
    
    await message.answer(text)

@dp.message(Command(commands=['summary', 'export']))
async def cmd_ignore_public(message: Message):
    if message.chat.type != 'private':
        await message.reply("Пожалуйста, управляйте ботом через личные сообщения: напишите мне в ЛС /start")

@dp.message_reaction()
async def process_reactions(event: MessageReactionUpdated):
    """Сбор реакций: кто кому и что поставил."""
    if event.chat.type == 'private': return
    
    db = load_database()
    chat_id_str = str(event.chat.id)
    
    if 'chats' not in db: db['chats'] = {}
    if chat_id_str not in db['chats']:
        db['chats'][chat_id_str] = {'admins': [], 'settings': {}, 'history': {}, 'reactions': {}}
        
    if 'reactions' not in db['chats'][chat_id_str]:
        db['chats'][chat_id_str]['reactions'] = {}
        
    reactor_user_id = str(event.user.id) if event.user else None
    if not reactor_user_id: return
    
    delta = len(event.new_reaction) - len(event.old_reaction)
    if delta != 0:
        # Для простоты пока просто трекаем факты простановки/убирания реакций
        # В идеале нужно подтянуть автора сообщения, но Telegram не передает author_id в MessageReactionUpdated (в базовом варианте)
        # Сохраним сам факт: пользователь `reactor_user_id` сделал на сообщении `event.message_id` действие
        today = str(dt.now().date())
        if today not in db['chats'][chat_id_str]['reactions']:
            db['chats'][chat_id_str]['reactions'][today] = []
            
        db['chats'][chat_id_str]['reactions'][today].append({
            "reactor_user_id": reactor_user_id,
            "message_id": event.message_id,
            "delta": delta,
            "timestamp": dt.now().isoformat()
        })
        await save_database(db)

@dp.message()
async def process_messages(message: Message, bot: Bot):
    if message.chat.type == 'private': return
    if not message.text and not message.caption and not message.new_chat_members: return
    
    db = load_database()
    if 'superadmins' not in db: db['superadmins'] = [str(ADMIN_ID)]
    if 'chats' not in db: db['chats'] = {}
    chat_id_str = str(message.chat.id)
    
    if chat_id_str not in db['chats']:
        db['chats'][chat_id_str] = {'admins': [], 'settings': {}, 'history': {}, 'admins_updated_at': 0, 'reactions': {}}
        
    # Save/Update Title
    if message.chat.title:
        db['chats'][chat_id_str]['title'] = message.chat.title
        
    # Update admins cache periodically
    chat_data = db['chats'][chat_id_str]
    now_ts = dt.now().timestamp()
    if now_ts - chat_data.get('admins_updated_at', 0) > 3600 or not chat_data.get('admins'):
        try:
            admins = await bot.get_chat_administrators(message.chat.id)
            chat_data['admins'] = [str(a.user.id) for a in admins if not a.user.is_bot]
            chat_data['admins_updated_at'] = now_ts
        except Exception:
            pass

    if message.new_chat_members:
        await save_database(db)
        return

    await save_message_to_database(message, db, chat_id_str)
    await save_database(db)


async def daily_summary_job(bot: Bot):
    await asyncio.sleep(10)
    logging.info("Фоновый воркер запущен.")
    while True:
        try:
            now = dt.now()
            today = str(now.date())
            db = load_database()
            chats = db.get("chats", {})
            changed = False
            for c_id, c_data in chats.items():
                settings = c_data.get("settings", {})
                target_hour = settings.get("summary_time", 21)
                target_topic_id = settings.get("summary_topic_id")
                
                if now.hour == target_hour and c_data.get("last_summary_date") != today:
                    summary = await get_summary_data(c_id, today, db)
                    if summary:
                        try:
                            if target_topic_id:
                                await bot.send_message(c_id, summary, message_thread_id=target_topic_id)
                            else:
                                await bot.send_message(c_id, summary)
                            c_data["last_summary_date"] = today
                            changed = True
                        except Exception as e:
                            logging.error(e)
            if changed: await save_database(db)
        except Exception as e:
            logging.error(e)
        await asyncio.sleep(60)


async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    logging.info("Бот переведен на управление через ЛС.")
    asyncio.create_task(daily_summary_job(bot))
    
    # Polling limits can be added via allowed_updates.
    # To receive reactions updates, we must enable message_reaction in allowed_updates.
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "message_reaction"])

if __name__ == '__main__':
    asyncio.run(main())
