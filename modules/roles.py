"""Role helpers: superadmin / per-chat admin checks and admin-group discovery.

Extracted verbatim from main.py so that both main.py and modules/gsheets.py
can import them without pulling in aiogram/Dispatcher at import time.
Behavior is identical to the previous in-main.py definitions.
"""

# Hardcoded fallback superadmin id (kept here so the fallback lives next to
# the function that uses it; main.py re-imports this constant to stay
# backward compatible with code that still references ADMIN_ID).
ADMIN_ID = 648981358


def is_superadmin(user_id, db):
    return str(user_id) in db.get('superadmins', [str(ADMIN_ID)])


def is_admin(user_id, chat_id_str, db):
    if is_superadmin(user_id, db):
        return True
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