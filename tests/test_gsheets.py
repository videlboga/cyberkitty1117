"""Tests for modules/gsheets.py lazy client factory.

These tests do not require gspread/google-auth to be installed: they patch the
gspread import surface and the filesystem check so no real network or credentials
are touched.
"""

import importlib
import os
import sys
import types

import modules.gsheets as gsheets


def test_import_never_fails_without_gspread(monkeypatch):
    # Simulate gspread not installed by hiding it from sys.modules.
    for name in list(sys.modules):
        if name == 'gspread' or name.startswith('gspread.'):
            monkeypatch.delitem(sys.modules, name, raising=False)

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'gspread':
            raise ModuleNotFoundError("No module named 'gspread'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    # Reset the cache so we re-run the import path.
    gsheets._gc = None
    assert gsheets._get_client() is None
    gsheets._gc = None


def test_get_client_returns_none_when_creds_missing(monkeypatch):
    # Inject a fake gspread module that would succeed, but point creds path
    # at a nonexistent file.
    fake_gspread = types.ModuleType('gspread')
    fake_gspread.service_account = lambda **kw: object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'gspread', fake_gspread)

    monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS', '/nonexistent/creds.json')
    gsheets._gc = None
    assert gsheets._get_client() is None
    gsheets._gc = None


def test_get_client_caches_success(monkeypatch, tmp_path):
    creds_file = tmp_path / 'svc.json'
    creds_file.write_text('{}')

    captured = {}

    fake_gspread = types.ModuleType('gspread')

    def service_account(filename, scopes):
        captured['filename'] = filename
        captured['scopes'] = scopes
        return ('fake-client', filename)

    fake_gspread.service_account = service_account  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'gspread', fake_gspread)
    monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS', str(creds_file))

    gsheets._gc = None
    c1 = gsheets._get_client()
    assert c1 is not None
    assert captured['filename'] == str(creds_file)
    assert any('spreadsheets' in s for s in captured['scopes'])
    assert any('drive' in s for s in captured['scopes'])

    # Second call should reuse the cached client (service_account not called again).
    c2 = gsheets._get_client()
    assert c1 is c2

    gsheets._gc = None


def test_get_client_falls_back_to_hardcoded_path(monkeypatch, tmp_path):
    creds_file = tmp_path / 'overproject-455420-a75ed4f4592e.json'
    creds_file.write_text('{}')

    fake_gspread = types.ModuleType('gspread')
    fake_gspread.service_account = lambda **kw: 'ok'  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'gspread', fake_gspread)

    # Unset env → must fall back to the hardcoded path.
    monkeypatch.delenv('GOOGLE_APPLICATION_CREDENTIALS', raising=False)

    # Monkeypatch os.path.exists so the hardcoded fallback resolves to our tmp file.
    real_exists = os.path.exists

    def fake_exists(p):
        if p.endswith('overproject-455420-a75ed4f4592e.json'):
            return True
        return real_exists(p)

    monkeypatch.setattr(os.path, 'exists', fake_exists)

    gsheets._gc = None
    client = gsheets._get_client()
    assert client is not None
    gsheets._gc = None


def test_get_client_returns_none_on_service_account_error(monkeypatch, tmp_path):
    creds_file = tmp_path / 'svc.json'
    creds_file.write_text('{}')

    fake_gspread = types.ModuleType('gspread')

    def boom(**kw):
        raise RuntimeError('auth failed')

    fake_gspread.service_account = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'gspread', fake_gspread)
    monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS', str(creds_file))

    gsheets._gc = None
    assert gsheets._get_client() is None
    gsheets._gc = None


def test_sanitize_sheet_title_replaces_forbidden_chars():
    raw = 'a:b/c\\d?e*f[g]h'
    assert gsheets.sanitize_sheet_title(raw) == 'a b c d e f g h'


def test_sanitize_sheet_title_strips_whitespace():
    assert gsheets.sanitize_sheet_title('  hello  ') == 'hello'
    # Leading/trailing forbidden chars become spaces then are stripped.
    assert gsheets.sanitize_sheet_title(':::title:::') == 'title'


def test_sanitize_sheet_title_truncates_to_100():
    raw = 'x' * 150
    result = gsheets.sanitize_sheet_title(raw)
    assert len(result) == 100
    assert result == 'x' * 100


def test_sanitize_sheet_title_truncates_after_replacement():
    # 100 'a' plus a trailing ':' — replacement yields 101 chars, truncate to 100.
    raw = 'a' * 100 + ':'
    assert gsheets.sanitize_sheet_title(raw) == 'a' * 100


def test_sanitize_sheet_title_empty_after_strip():
    assert gsheets.sanitize_sheet_title('///') == ''


def test_sanitize_sheet_title_no_forbidden_chars():
    assert gsheets.sanitize_sheet_title('Общая статистика') == 'Общая статистика'


def test_update_admin_spreadsheet_none_when_no_client(monkeypatch):
    import asyncio

    monkeypatch.setattr(gsheets, '_gc', None)

    db = {'chats': {}, 'users': {}}
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            gsheets.update_admin_spreadsheet(1, 'SID', db)
        )
    finally:
        loop.close()

    assert result is None


def test_update_admin_spreadsheet_creates_tabs_and_summary(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    group_ws = MagicMock()
    summary_ws = MagicMock()

    fake_sh = MagicMock()
    fake_sh.worksheets.return_value = []  # no existing tabs

    # Distinct worksheet mock per add_worksheet call (group, then summary).
    def _add_worksheet(title, rows=10, cols=10, index=None):
        if title == gsheets.SUMMARY_TAB_TITLE:
            return summary_ws
        return group_ws

    fake_sh.add_worksheet.side_effect = _add_worksheet

    fake_gc = MagicMock()
    fake_gc.open_by_key.return_value = fake_sh

    monkeypatch.setattr(gsheets, '_gc', fake_gc)

    chat_data = _build_chat_data()
    db = {
        'superadmins': ['648981358'],
        'chats': {
            '-100123': {
                'title': 'Group A',
                'admins': [],
                **chat_data,
            },
        },
        'users': {
            '100': {'username': 'alice'},
            '200': {'username': 'bob'},
        },
    }

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            gsheets.update_admin_spreadsheet(648981358, 'SID_X', db)
        )
    finally:
        loop.close()

    assert result == 'SID_X'
    fake_gc.open_by_key.assert_called_once_with('SID_X')

    # Should create one group tab and one summary tab.
    assert fake_sh.add_worksheet.call_count == 2
    created_titles = [c.kwargs.get('title') or c.args[0]
                      for c in fake_sh.add_worksheet.call_args_list]
    assert 'Group A' in created_titles
    assert gsheets.SUMMARY_TAB_TITLE in created_titles

    # No stray tabs to delete (worksheets was empty).
    assert fake_sh.del_worksheet.call_count == 0

    summary_ws.clear.assert_called_once()
    summary_rows = summary_ws.update.call_args.args[0]
    assert summary_rows[0] == ['Группа', 'Всего сообщений', 'Всего юзеров', 'Всего реакций']
    assert len(summary_rows) == 2
    row = summary_rows[1]
    assert row[0] == 'Group A'
    assert row[1] == 3  # 3 messages in _build_chat_data
    assert row[2] == 2  # 2 users
    # 3 reactions given total (delta 1 from bob + delta 2 from alice).
    assert row[3] == 3

    # Group tab also written.
    group_ws.clear.assert_called_once()
    group_rows_written = group_ws.update.call_args.args[0]
    assert group_rows_written[0][2] == 'Сообщений'


def test_update_admin_spreadsheet_deletes_stray_tabs(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    stray = MagicMock()
    stray.title = 'Old Group'
    keep_group = MagicMock()
    keep_group.title = 'Group A'
    keep_summary = MagicMock()
    keep_summary.title = gsheets.SUMMARY_TAB_TITLE

    fake_sh = MagicMock()
    fake_sh.worksheets.return_value = [stray, keep_group, keep_summary]

    fake_gc = MagicMock()
    fake_gc.open_by_key.return_value = fake_sh

    monkeypatch.setattr(gsheets, '_gc', fake_gc)

    db = {
        'superadmins': ['648981358'],
        'chats': {
            '-100123': {'title': 'Group A', 'admins': [],
                        'history': {}, 'reactions': {}},
        },
        'users': {},
    }

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            gsheets.update_admin_spreadsheet(648981358, 'SID_X', db)
        )
    finally:
        loop.close()

    assert result == 'SID_X'
    # Only the stray tab should be deleted; the kept tabs stay.
    fake_sh.del_worksheet.assert_called_once_with(stray)
    # Existing tabs should be cleared+rewritten, not re-created.
    fake_sh.add_worksheet.assert_not_called()
    keep_group.clear.assert_called_once()
    keep_summary.clear.assert_called_once()
    assert keep_group.update.called
    assert keep_summary.update.called


def test_create_admin_spreadsheet_returns_id_and_persists(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    fake_sh = MagicMock()
    fake_sh.id = 'SPREADSHEET_ID_123'
    fake_gc = MagicMock()
    fake_gc.create.return_value = fake_sh

    monkeypatch.setattr(gsheets, '_gc', fake_gc)

    saved = {}

    async def fake_save(data=None):
        saved['data'] = data

    monkeypatch.setattr(gsheets, 'save_database', fake_save)

    db = {'users': {}}

    loop = asyncio.new_event_loop()
    try:
        sid = loop.run_until_complete(
            gsheets.create_admin_spreadsheet(648981358, 'andrey', db)
        )
    finally:
        loop.close()

    assert sid == 'SPREADSHEET_ID_123'
    fake_gc.create.assert_called_once_with('Summary Bot — andrey')
    assert db['users']['648981358']['spreadsheet_id'] == 'SPREADSHEET_ID_123'
    assert saved.get('data') is db


def test_create_admin_spreadsheet_creates_user_record(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    fake_sh = MagicMock()
    fake_sh.id = 'SID_2'
    fake_gc = MagicMock()
    fake_gc.create.return_value = fake_sh

    monkeypatch.setattr(gsheets, '_gc', fake_gc)

    async def fake_save(data=None):
        pass

    monkeypatch.setattr(gsheets, 'save_database', fake_save)

    # No 'users' key at all — function must create it lazily.
    db = {}

    loop = asyncio.new_event_loop()
    try:
        sid = loop.run_until_complete(
            gsheets.create_admin_spreadsheet(42, 'neo', db)
        )
    finally:
        loop.close()

    assert sid == 'SID_2'
    assert db['users']['42']['spreadsheet_id'] == 'SID_2'


def test_create_admin_spreadsheet_none_when_no_client(monkeypatch):
    import asyncio

    monkeypatch.setattr(gsheets, '_gc', None)

    async def fake_save(data=None):
        raise AssertionError('save_database must not be called without a client')

    monkeypatch.setattr(gsheets, 'save_database', fake_save)

    db = {'users': {}}
    loop = asyncio.new_event_loop()
    try:
        sid = loop.run_until_complete(
            gsheets.create_admin_spreadsheet(1, 'x', db)
        )
    finally:
        loop.close()

    assert sid is None
    assert db['users'] == {}


def _build_chat_data():
    """Return a minimal chat_data with history + reactions matching DB schema."""
    return {
        'history': {
            '2026-01-01': [
                {
                    'user_id': '100',
                    'link_to_message': 'https://t.me/c/1/10',
                    'text_in_msg': 'hello',
                    'timestamp': '2026-01-01T10:00:00',
                },
                {
                    'user_id': '200',
                    'link_to_message': 'https://t.me/c/1/11',
                    'text': 'world',
                    'timestamp': '2026-01-01T11:00:00',
                },
                {
                    'user_id': '100',
                    'link_to_message': 'https://t.me/c/1/12',
                    'text_in_msg': '',
                    'timestamp': '2026-01-01T12:00:00',
                },
            ],
        },
        'reactions': {
            '2026-01-01': [
                {'reactor_user_id': '200', 'message_id': 10, 'delta': 1},
                {'reactor_user_id': '100', 'message_id': 11, 'delta': 2},
            ],
        },
    }


def test_write_group_tab_creates_worksheet_and_writes_rows():
    from unittest.mock import MagicMock

    sh = MagicMock()
    existing = MagicMock()
    existing.title = 'Other Tab'
    sh.worksheets.return_value = [existing]
    new_ws = MagicMock()
    sh.add_worksheet.return_value = new_ws

    db = {
        'users': {
            '100': {'username': 'alice'},
            '200': {'username': 'bob'},
        },
        'chats': {},
    }

    gsheets._write_group_tab(sh, 'Group A', _build_chat_data(), db)

    # Should have scanned existing tabs and created a new one.
    sh.add_worksheet.assert_called_once_with('Group A', rows=100, cols=6)
    new_ws.clear.assert_called_once()

    # Inspect the rows written via ws.update.
    assert new_ws.update.called
    rows = new_ws.update.call_args.args[0]
    header = rows[0]
    assert header == [
        'Дата',
        'Пользователь',
        'Сообщений',
        'Реакций поставлено',
        'Реакций получено',
        'Текст последнего сообщения',
    ]

    # Two data rows, sorted by messages desc.
    data_rows = rows[1:]
    assert len(data_rows) == 2
    # alice (100): 2 messages, 2 reactions given, 1 received, last text '[Медиа/Без текста]'
    # bob   (200): 1 message,  1 reaction given,  2 received, last text 'world'
    by_user = {r[1]: r for r in data_rows}
    alice = by_user['alice']
    assert alice[0] == ''  # Дата placeholder
    assert alice[2] == 2
    assert alice[3] == 2
    assert alice[4] == 1
    assert alice[5] == '[Медиа/Без текста]'

    bob = by_user['bob']
    assert bob[2] == 1
    assert bob[3] == 1
    assert bob[4] == 2
    assert bob[5] == 'world'

    # Sorted by messages desc → alice (2) before bob (1).
    assert data_rows[0][1] == 'alice'
    assert data_rows[1][1] == 'bob'


def test_write_group_tab_reuses_existing_worksheet():
    from unittest.mock import MagicMock

    existing = MagicMock()
    existing.title = 'Group A'
    sh = MagicMock()
    sh.worksheets.return_value = [existing]

    db = {'users': {}, 'chats': {}}

    gsheets._write_group_tab(sh, 'Group A', _build_chat_data(), db)

    # Must NOT add a new worksheet — reuse the existing one.
    sh.add_worksheet.assert_not_called()
    existing.clear.assert_called_once()
    assert existing.update.called


def test_write_group_tab_username_fallback_to_id():
    from unittest.mock import MagicMock

    sh = MagicMock()
    new_ws = MagicMock()
    sh.worksheets.return_value = []
    sh.add_worksheet.return_value = new_ws

    # No users record for uid '100' → fallback to 'ID:100'.
    db = {'users': {}, 'chats': {}}

    gsheets._write_group_tab(sh, 'Group X', _build_chat_data(), db)

    rows = new_ws.update.call_args.args[0]
    data_rows = rows[1:]
    usernames = {r[1] for r in data_rows}
    assert 'ID:100' in usernames
    assert 'ID:200' in usernames


def test_write_group_tab_empty_chat():
    from unittest.mock import MagicMock

    sh = MagicMock()
    new_ws = MagicMock()
    sh.worksheets.return_value = []
    sh.add_worksheet.return_value = new_ws

    db = {'users': {}, 'chats': {}}

    gsheets._write_group_tab(sh, 'Empty', {'history': {}, 'reactions': {}}, db)

    rows = new_ws.update.call_args.args[0]
    # Only the header row, no data rows.
    assert len(rows) == 1
    assert rows[0][2] == 'Сообщений'