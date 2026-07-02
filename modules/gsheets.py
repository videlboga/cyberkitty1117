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