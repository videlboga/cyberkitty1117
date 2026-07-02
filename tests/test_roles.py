"""Tests for modules/roles.py: is_superadmin / is_admin / get_admin_groups.

These functions were extracted verbatim from main.py; behavior must be
identical (superadmin sees all chats; per-chat admin sees only their chats).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.roles import is_superadmin, is_admin, get_admin_groups, ADMIN_ID


def _db(superadmins=None, chats=None):
    return {
        'superadmins': superadmins if superadmins is not None else ['648981358'],
        'chats': chats or {},
    }


def test_admin_id_constant_unchanged():
    assert ADMIN_ID == 648981358


def test_is_superadmin_matches_string_in_db():
    db = _db(superadmins=['111'])
    assert is_superadmin(111, db) is True
    assert is_superadmin('111', db) is True
    assert is_superadmin(222, db) is False


def test_is_superadmin_falls_back_to_admin_id_when_key_missing():
    db = {'chats': {}}  # no 'superadmins' key at all
    assert is_superadmin(ADMIN_ID, db) is True
    assert is_superadmin(str(ADMIN_ID), db) is True
    assert is_superadmin(999, db) is False


def test_is_admin_true_for_superadmin_even_if_not_in_chat_admins():
    db = _db(superadmins=['111'], chats={'-100': {'admins': ['222']}})
    assert is_admin(111, '-100', db) is True


def test_is_admin_true_for_per_chat_admin():
    db = _db(superadmins=['111'], chats={'-100': {'admins': ['222']}})
    assert is_admin(222, '-100', db) is True
    assert is_admin('222', '-100', db) is True


def test_is_admin_false_for_non_admin():
    db = _db(superadmins=['111'], chats={'-100': {'admins': ['222']}})
    assert is_admin(333, '-100', db) is False


def test_is_admin_false_for_missing_chat():
    db = _db(superadmins=['111'], chats={'-100': {'admins': ['222']}})
    assert is_admin(222, '-999', db) is False


def test_is_admin_handles_missing_admins_key_in_chat():
    db = _db(superadmins=['111'], chats={'-100': {}})
    assert is_admin(222, '-100', db) is False


def test_get_admin_groups_superadmin_sees_all_chats():
    db = _db(superadmins=['111'], chats={
        '-100': {'admins': ['222'], 'title': 'Chat A'},
        '-200': {'admins': [], 'title': 'Chat B'},
    })
    groups = get_admin_groups(111, db)
    assert groups == {'-100': 'Chat A', '-200': 'Chat B'}


def test_get_admin_groups_per_chat_admin_sees_only_own_chats():
    db = _db(superadmins=['111'], chats={
        '-100': {'admins': ['222'], 'title': 'Chat A'},
        '-200': {'admins': ['333'], 'title': 'Chat B'},
    })
    groups = get_admin_groups(222, db)
    assert groups == {'-100': 'Chat A'}


def test_get_admin_groups_no_admin_sees_nothing():
    db = _db(superadmins=['111'], chats={
        '-100': {'admins': ['222'], 'title': 'Chat A'},
    })
    groups = get_admin_groups(999, db)
    assert groups == {}


def test_get_admin_groups_title_fallback_for_missing_title():
    db = _db(superadmins=['111'], chats={
        '-100': {'admins': []},
    })
    groups = get_admin_groups(111, db)
    assert groups == {'-100': 'Группа -100'}


def test_get_admin_groups_title_fallback_for_numeric_string_title():
    # title == cid → fallback to "Чат {cid}"
    db = _db(superadmins=['111'], chats={
        '-100': {'admins': [], 'title': '-100'},
    })
    groups = get_admin_groups(111, db)
    assert groups == {'-100': 'Чат -100'}


def test_get_admin_groups_title_fallback_for_dash_prefixed_title():
    db = _db(superadmins=['111'], chats={
        '-100': {'admins': [], 'title': '-group'},
    })
    groups = get_admin_groups(111, db)
    assert groups == {'-100': 'Чат -100'}


def test_get_admin_groups_no_chats_key():
    db = {'superadmins': ['111']}
    assert get_admin_groups(111, db) == {}