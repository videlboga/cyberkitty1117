"""Google Sheets integration for admin dashboards.

gspread is imported lazily inside `_get_client()` so that importing this
module never fails — even when gspread / google-auth are not installed or the
service-account JSON is missing. Bot startup must succeed regardless of the
Sheets environment.

The public spreadsheet functions (create_admin_spreadsheet,
update_admin_spreadsheet, get_or_create_admin_spreadsheet) are added in
subsequent tasks; this file currently provides only the lazy client factory.
"""

import os
import logging
import asyncio

from modules.roles import get_admin_groups
from modules.db import save_database


# Module-level cache for the gspread client. Populated on first successful
# `_get_client()` call; reset to None only on import-time so tests can patch it.
_gc = None


def _get_client():
    """Lazily build and cache a gspread.service_account client.

    Returns the cached gspread client on success, or None if gspread is not
    importable, the credentials file is missing, or auth fails. Never raises
    on the expected failure paths — logs a warning and returns None so callers
    can skip the Sheets sync gracefully.
    """
    global _gc
    if _gc is not None:
        return _gc

    try:
        import gspread
    except Exception as e:  # ImportError, ModuleNotFoundError, etc.
        logging.warning(
            "modules.gsheets: gspread not available, Sheets sync disabled: %s", e
        )
        return None

    creds_path = os.environ.get(
        'GOOGLE_APPLICATION_CREDENTIALS',
        '/home/cyberkitty/Загрузки/overproject-455420-a75ed4f4592e.json',
    )

    if not creds_path or not os.path.exists(creds_path):
        logging.warning(
            "modules.gsheets: credentials file not found at %s, "
            "Sheets sync disabled",
            creds_path,
        )
        return None

    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ]

    try:
        _gc = gspread.service_account(filename=creds_path, scopes=scopes)
    except Exception as e:
        logging.warning(
            "modules.gsheets: failed to init gspread client from %s: %s",
            creds_path, e, exc_info=True,
        )
        _gc = None
        return None

    logging.info("modules.gsheets: gspread client initialized from %s", creds_path)
    return _gc


def compute_user_stats(chat_data: dict, args: list = None, db: dict = None) -> dict:
    """Aggregate per-user statistics for a single chat.

    Reproduces the aggregation logic of ``modules/export.py::process_export``
    for the ``len(args) == 0`` branch (i.e. "за всё время" — all dates in
    history), and additionally tracks each user's last message text.

    NOTE: Per RESEARCH.md, the aggregation helper could be factored out of
    ``export.py`` so that both the CSV exporter and the Sheets exporter share
    one implementation (option (a)). This task explicitly chooses option (b)
    — copying the logic into ``gsheets.py`` — to avoid touching ``export.py``
    and risking changes to the existing CSV behaviour. The two implementations
    must be kept consistent; if ``export.py`` aggregation changes, mirror it
    here.

    Args:
        chat_data: ``db['chats'][cid]`` dict with ``history`` and
            ``reactions`` sub-dicts keyed by date.
        args: period filter. When ``None`` or ``[]`` the full history is used,
            matching ``process_export``'s all-time branch. Only the empty-args
            branch is used by the Sheets worker today, but the signature keeps
            ``args`` for parity with ``process_export`` and future reuse.
        db: database dict (unused for aggregation itself, present for API
            symmetry with ``process_export``).

    Returns:
        ``{uid_str: {messages, reactions_given, reactions_received, last_text}}``.
        ``last_text`` is the text of the message with the maximum ``timestamp``
        for that user, resolved as
        ``msg.get('text_in_msg', '') or msg.get('text', '') or '[Медиа/Без текста]'``.
        Users that only appear in reactions (never sent a message) have
        ``last_text = ''``.
    """
    if args is None:
        args = []
    if db is None:
        db = {}

    history = chat_data.get('history', {})
    reactions_db = chat_data.get('reactions', {})

    # All-time branch (mirrors process_export when len(args) == 0)
    export_history = history if len(args) == 0 else {}
    export_reactions = reactions_db if len(args) == 0 else {}

    user_stats = {}
    # message_id -> author uid, used to credit received reactions
    msg_author_map = {}
    # uid -> (max_timestamp, text) of the most recent message for last_text
    last_msg_by_uid = {}

    # 1. Walk all messages
    for date_key, messages in export_history.items():
        for msg in messages:
            uid = str(msg.get('user_id'))
            link = msg.get('link_to_message', '')

            # Extract message_id from the link's last path segment
            msg_id = None
            if link:
                parts = link.split('/')
                if len(parts) > 0 and parts[-1].isdigit():
                    msg_id = int(parts[-1])

            if uid not in user_stats:
                user_stats[uid] = {
                    'messages': 0,
                    'reactions_given': 0,
                    'reactions_received': 0,
                    'last_text': '',
                }

            user_stats[uid]['messages'] += 1
            if msg_id:
                msg_author_map[msg_id] = uid

            # Resolve message text with the same fallback as export.py
            msg_text = msg.get('text_in_msg', '') or msg.get('text', '')
            if not msg_text:
                msg_text = '[Медиа/Без текста]'

            # Track the most recent message per user by timestamp
            ts = msg.get('timestamp', date_key)
            prev = last_msg_by_uid.get(uid)
            if prev is None or ts >= prev[0]:
                last_msg_by_uid[uid] = (ts, msg_text)

    # Apply last_text to each user that sent at least one message
    for uid, (_ts, text) in last_msg_by_uid.items():
        user_stats[uid]['last_text'] = text

    # 2. Walk all reactions (who reacted to whom)
    for _date_key, reactions in export_reactions.items():
        for rxn in reactions:
            reactor = str(rxn.get('reactor_user_id'))
            delta = rxn.get('delta', 0)
            msg_id = rxn.get('message_id')

            if delta > 0:
                # reactor gave a reaction
                if reactor not in user_stats:
                    user_stats[reactor] = {
                        'messages': 0,
                        'reactions_given': 0,
                        'reactions_received': 0,
                        'last_text': '',
                    }
                user_stats[reactor]['reactions_given'] += delta

                # message author received a reaction
                author = msg_author_map.get(msg_id)
                if author:
                    if author not in user_stats:
                        user_stats[author] = {
                            'messages': 0,
                            'reactions_given': 0,
                            'reactions_received': 0,
                            'last_text': '',
                        }
                    user_stats[author]['reactions_received'] += delta

    return user_stats


# Characters forbidden in Google Sheets tab names. Google rejects ':' outright
# and the others (per RESEARCH.md) are reserved/unsafe in the Sheets UI.
_FORBIDDEN_CHARS = (':', '/', '\\', '?', '*', '[', ']')


def sanitize_sheet_title(title: str) -> str:
    """Sanitize a group title for use as a Google Sheets tab name.

    Replaces every forbidden character (``:`` ``/`` ``\\`` ``?`` ``*`` ``[`` ``]``)
    with a space, truncates the result to the 100-character limit imposed by the
    Sheets API, and strips leading/trailing whitespace.

    Pure function — no side effects, no I/O. Callers are responsible for
    de-duplicating the returned title within a spreadsheet.
    """
    for ch in _FORBIDDEN_CHARS:
        title = title.replace(ch, ' ')
    return title[:100].strip()


SUMMARY_TAB_TITLE = 'Общая статистика'


def _write_summary_tab(sh, group_rows: list):
    """Write the ``Общая статистика`` summary tab into spreadsheet ``sh``.

    Finds an existing ``Общая статистика`` worksheet (clearing it in place,
    per the idempotent-update policy in RESEARCH.md) or creates it as the
    first sheet, then writes the header row followed by one row per group.

    Purely synchronous — meant to run inside ``asyncio.to_thread`` by the
    async public callers.

    Args:
        sh: an open gspread ``Spreadsheet``.
        group_rows: list of row lists shaped
            ``[[group_title, total_messages, total_users, total_reactions], ...]``.
    """
    summary_ws = None
    for ws in sh.worksheets():
        if ws.title == SUMMARY_TAB_TITLE:
            summary_ws = ws
            break

    if summary_ws is None:
        summary_ws = sh.add_worksheet(
            SUMMARY_TAB_TITLE, rows=100, cols=4, index=0
        )

    summary_ws.clear()

    header = ['Группа', 'Всего сообщений', 'Всего юзеров', 'Всего реакций']
    summary_ws.update([header] + list(group_rows))


def _write_group_tab(sh, tab_title, chat_data, db):
    """Write a per-group tab into spreadsheet ``sh`` with full event history.

    Finds an existing worksheet named ``tab_title`` (clearing it in place for
    idempotent updates, per RESEARCH.md) or creates it via ``sh.add_worksheet``
    (after scanning ``sh.worksheets()`` to avoid creating a duplicate tab),
    then writes three blocks mirroring ``modules/export.py::process_export``:

    Block 1 — Статистика пользователей (aggregate, one row per user):
        ``['Чат', 'Пользователь', 'Сообщений', 'Реакций поставлено',
        'Реакций получено']``, sorted by message count descending.

    Block 2 — Все сообщения (one row per message, with date/time):
        ``['Пользователь', 'Дата и время', 'Текст сообщения',
        'Ссылка на сообщение']``, sorted by timestamp.

    Block 3 — История подписок/отписок (one row per membership event):
        ``['Пользователь', 'Отписка/Подписка', 'Дата']``, sorted by date.

    Each block is preceded by a title row (e.g. ``['СПИСОК СООБЩЕНИЙ']``)
    and blocks are separated by two empty rows, matching the CSV export
    layout.

    Purely synchronous — meant to run inside ``asyncio.to_thread`` by the async
    public caller (``update_admin_spreadsheet``). Does not call
    ``asyncio.to_thread`` itself.

    Args:
        sh: an open gspread ``Spreadsheet``.
        tab_title: sanitized, unique tab title for this group.
        chat_data: ``db['chats'][cid]`` dict with ``history`` and
            ``reactions`` sub-dicts keyed by date, plus optional
            ``membership_events`` list.
        db: the in-memory database dict (used for username resolution via
            ``db['users'][uid]['username']``).
    """
    ws = None
    for existing in sh.worksheets():
        if existing.title == tab_title:
            ws = existing
            break

    if ws is None:
        ws = sh.add_worksheet(tab_title, rows=100, cols=6)

    ws.clear()

    history = chat_data.get('history', {})
    users_db = db.get('users', {})

    def _username(uid):
        return users_db.get(str(uid), {}).get('username', f'ID:{uid}')

    rows = []

    # --- Block 1: User statistics (aggregate) ---
    stats = compute_user_stats(chat_data, [], db)
    rows.append(['СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ'])
    rows.append(['Чат', 'Пользователь', 'Сообщений',
                 'Реакций поставлено', 'Реакций получено'])
    for uid, s in sorted(stats.items(),
                         key=lambda kv: kv[1]['messages'], reverse=True):
        rows.append([tab_title, _username(uid), s['messages'],
                     s['reactions_given'], s['reactions_received']])
    rows.append([])
    rows.append([])

    # --- Block 2: All messages (row by row, with date/time) ---
    all_messages = []
    for date_key, messages in history.items():
        for msg in messages:
            uid = str(msg.get('user_id'))
            ts = msg.get('timestamp', date_key)
            text = msg.get('text_in_msg', '') or msg.get('text', '')
            if not text:
                text = '[Медиа/Без текста]'
            link = msg.get('link_to_message', '')
            all_messages.append((ts, uid, text, link))
    all_messages.sort(key=lambda x: x[0])

    rows.append(['СПИСОК СООБЩЕНИЙ'])
    rows.append(['Пользователь', 'Дата и время',
                 'Текст сообщения', 'Ссылка на сообщение'])
    for ts, uid, text, link in all_messages:
        rows.append([_username(uid), ts, text, link])
    rows.append([])
    rows.append([])

    # --- Block 3: Membership events (join/leave history) ---
    membership = chat_data.get('membership_events', [])
    rows.append(['ИСТОРИЯ ПОДПИСОК/ОТПИСОК'])
    rows.append(['Пользователь', 'Отписка/Подписка', 'Дата'])
    for event in sorted(membership, key=lambda e: e.get('date', '')):
        uid = str(event.get('user_id'))
        action = 'Подписка' if event.get('action') == 'joined' else 'Отписка'
        rows.append([_username(uid), action, event.get('date', '')])

    ws.update(rows)


async def update_admin_spreadsheet(admin_user_id, spreadsheet_id, db):
    """Refresh an admin's spreadsheet in place (idempotent, ~30-min safe).

    Opens the spreadsheet by key, reconciles the set of tabs with the admin's
    current groups (deleting tabs for groups the admin no longer manages, per
    the idempotent-update policy in RESEARCH.md), rewrites each group tab with
    fresh per-user stats via ``_write_group_tab``, and finally rewrites the
    ``Общая статистика`` summary tab via ``_write_summary_tab``.

    All blocking gspread calls are wrapped in ``asyncio.to_thread`` so the bot
    event loop is not blocked.

    Args:
        admin_user_id: Telegram user id (int or str) of the admin.
        spreadsheet_id: the spreadsheet id (str) previously returned by
            ``create_admin_spreadsheet``.
        db: the in-memory database dict (same shape as ``load_database()``).

    Returns:
        The ``spreadsheet_id`` on success, or ``None`` when the gspread client
        is unavailable (missing credentials / gspread not installed).
    """
    gc = _get_client()
    if gc is None:
        return None

    sh = await asyncio.to_thread(gc.open_by_key, spreadsheet_id)

    groups = get_admin_groups(admin_user_id, db)
    desired = {sanitize_sheet_title(t) for t in groups.values()} | {SUMMARY_TAB_TITLE}

    # Delete tabs for groups the admin no longer manages. ``worksheets()``
    # returns a fresh list snapshot, so iterating while deleting is safe.
    # Google Sheets forbids removing ALL sheets from a document, so we
    # skip deletion when only one non-desired sheet remains — it will be
    # removed later once a desired tab has been created.
    current_sheets = sh.worksheets()
    for ws in current_sheets:
        if ws.title not in desired and len(current_sheets) > 1:
            sh.del_worksheet(ws)
            current_sheets = [w for w in current_sheets if w.id != ws.id]

    group_rows = []
    chats = db.get('chats', {})
    for cid, title in groups.items():
        tab = sanitize_sheet_title(title)
        chat_data = chats.get(cid, {})
        await asyncio.to_thread(_write_group_tab, sh, tab, chat_data, db)

        # Aggregate group-level totals for the summary tab. ``compute_user_stats``
        # is pure/in-memory so it's safe to run on the event loop thread; it is
        # also invoked inside ``_write_group_tab``, but we recompute here rather
        # than changing ``_write_group_tab``'s signature (which existing tests
        # pin).
        stats = compute_user_stats(chat_data, [], db)
        total_msgs = sum(s['messages'] for s in stats.values())
        total_users = len(stats)
        total_rxns = sum(s['reactions_given'] for s in stats.values())
        group_rows.append([title, total_msgs, total_users, total_rxns])

    await asyncio.to_thread(_write_summary_tab, sh, group_rows)

    logging.info(
        "Sheets sync: admin=%s spreadsheet=%s updated (%d groups)",
        admin_user_id, spreadsheet_id, len(group_rows),
    )
    return spreadsheet_id


async def create_admin_spreadsheet(admin_user_id, admin_username, db):
    """Create a per-admin Google Spreadsheet and persist its id in the DB.

    Creates a new spreadsheet titled ``Summary Bot — {admin_username}`` via the
    gspread client, stores the resulting ``spreadsheet_id`` into
    ``db['users'][str(admin_user_id)]['spreadsheet_id']`` (creating the user
    record lazily if it does not yet exist), and persists the database with
    ``await save_database(db)``.

    gspread is synchronous, so the blocking ``gc.create`` call is wrapped in
    ``asyncio.to_thread`` to avoid blocking the bot's event loop.

    Args:
        admin_user_id: Telegram user id (int or str) of the admin.
        admin_username: Telegram username (str) used in the sheet title.
        db: the in-memory database dict (same shape as ``load_database()``).

    Returns:
        The new spreadsheet id (str) on success, or ``None`` when the gspread
        client is unavailable (missing credentials / gspread not installed).
    """
    gc = _get_client()
    if gc is None:
        return None

    title = f'Summary Bot — {admin_username}'
    sh = await asyncio.to_thread(gc.create, title)
    sid = sh.id

    uid_str = str(admin_user_id)
    users = db.setdefault('users', {})
    if uid_str not in users or not isinstance(users.get(uid_str), dict):
        users[uid_str] = {}
    users[uid_str]['spreadsheet_id'] = sid

    await save_database(db)

    logging.info("Sheets: created spreadsheet %s for admin %s (%s)", sid, admin_user_id, admin_username)
    return sid


async def get_or_create_admin_spreadsheet(admin_user_id, db):
    """Return a usable spreadsheet id for ``admin_user_id``, creating if needed.

    If the admin's record in ``db['users'][str(admin_user_id)]`` already has a
    truthy ``spreadsheet_id``, the existing spreadsheet is refreshed in place
    via ``update_admin_spreadsheet`` and its id returned. Otherwise a new
    spreadsheet is created with ``create_admin_spreadsheet`` (using the admin's
    stored username, falling back to ``ID:{uid}`` when no username is set), and
    — only when creation succeeds — immediately updated via
    ``update_admin_spreadsheet`` so the caller always gets a populated sheet.

    Per RESEARCH.md acceptance criterion 4. Returns the spreadsheet id (str)
    on success, or ``None`` when the gspread client is unavailable or creation
    fails (``create_admin_spreadsheet`` returned ``None``).

    Args:
        admin_user_id: Telegram user id (int or str) of the admin.
        db: the in-memory database dict (same shape as ``load_database()``).

    Returns:
        The spreadsheet id (str), or ``None``.
    """
    uid = str(admin_user_id)
    user_record = db.get('users', {}).get(uid, {})
    sid = user_record.get('spreadsheet_id')

    if sid:
        await update_admin_spreadsheet(admin_user_id, sid, db)
        return sid

    username = user_record.get('username', f'ID:{uid}')
    sid = await create_admin_spreadsheet(admin_user_id, username, db)
    if sid:
        await update_admin_spreadsheet(admin_user_id, sid, db)
    return sid