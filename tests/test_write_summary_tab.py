import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from unittest.mock import MagicMock


def _make_fake_sh(existing_titles=None):
    """Build a fake spreadsheet object capturing calls for assertions."""
    sh = MagicMock()
    sh._ws_by_title = {}

    def _worksheets():
        return [sh._ws_by_title[t] for t in (existing_titles or [])]

    def _add_worksheet(title, rows=100, cols=4, index=None):
        ws = MagicMock()
        ws.title = title
        ws._cleared = False
        ws._updated_with = None

        def _clear():
            ws._cleared = True

        def _update(values):
            ws._updated_with = values

        ws.clear.side_effect = _clear
        ws.update.side_effect = _update
        sh._ws_by_title[title] = ws
        sh._last_added = (title, rows, cols, index)
        return ws

    sh.worksheets.side_effect = _worksheets
    sh.add_worksheet.side_effect = _add_worksheet
    return sh


def _build_chat_data():
    """Minimal chat_data matching DB schema (history + reactions)."""
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
            ],
        },
        'reactions': {
            '2026-01-01': [
                {'reactor_user_id': '200', 'message_id': 10, 'delta': 1},
            ],
        },
    }


def _build_chat_data_with_membership():
    base = _build_chat_data()
    base['membership_events'] = [
        {'user_id': '100', 'action': 'joined', 'date': '2026-01-01T08:00:00'},
        {'user_id': '200', 'action': 'left', 'date': '2026-01-01T09:30:00'},
    ]
    return base


def _find_block(rows, title):
    """Return (title_idx, header_idx, data_rows) for the block titled *title*."""
    title_idx = None
    for i, r in enumerate(rows):
        if r and r[0] == title:
            title_idx = i
            break
    assert title_idx is not None, f"block title {title!r} not found"
    header_idx = title_idx + 1
    data = []
    for r in rows[header_idx + 1:]:
        if not r:
            break
        data.append(r)
    return title_idx, header_idx, data


def test_write_summary_tab_creates_when_missing():
    from modules.gsheets import _write_summary_tab, SUMMARY_TAB_TITLE

    sh = _make_fake_sh(existing_titles=[])

    group_rows = [
        ['Group A', 10, 3, 5],
        ['Group B', 20, 4, 7],
    ]
    groups = {'-100123': 'Group A', '-100456': 'Group B'}
    db = {'chats': {}, 'users': {}}
    _write_summary_tab(sh, group_rows, groups, db)

    sh.add_worksheet.assert_called_once()
    assert sh._last_added[0] == SUMMARY_TAB_TITLE
    assert sh._last_added[3] == 0  # index=0 (first tab)

    ws = sh._ws_by_title[SUMMARY_TAB_TITLE]
    assert ws._cleared is True
    rows = ws._updated_with
    # Block 0 header + group rows
    assert rows[0] == ['Группа', 'Всего сообщений', 'Всего юзеров', 'Всего реакций']
    assert rows[1] == ['Group A', 10, 3, 5]
    assert rows[2] == ['Group B', 20, 4, 7]
    # Two empty separator rows
    assert rows[3] == []
    assert rows[4] == []
    # Block 1 title present
    assert rows[5][0] == 'СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ ПО ЧАТАМ'


def test_write_summary_tab_clears_existing():
    from modules.gsheets import _write_summary_tab, SUMMARY_TAB_TITLE

    existing = MagicMock()
    existing.title = SUMMARY_TAB_TITLE
    existing._cleared = False
    existing._updated_with = None

    def _clear():
        existing._cleared = True

    def _update(values):
        existing._updated_with = values

    existing.clear.side_effect = _clear
    existing.update.side_effect = _update

    sh = _make_fake_sh()
    sh._ws_by_title[SUMMARY_TAB_TITLE] = existing
    sh.worksheets.side_effect = lambda: [existing]

    group_rows = [['Only Group', 5, 2, 1]]
    groups = {'-100': 'Only Group'}
    db = {'chats': {}, 'users': {}}
    _write_summary_tab(sh, group_rows, groups, db)

    # Must NOT add a new tab when one exists.
    sh.add_worksheet.assert_not_called()
    assert existing._cleared is True
    rows = existing._updated_with
    assert rows[0] == ['Группа', 'Всего сообщений', 'Всего юзеров', 'Всего реакций']
    assert rows[1] == ['Only Group', 5, 2, 1]


def test_write_summary_tab_empty_rows():
    from modules.gsheets import _write_summary_tab, SUMMARY_TAB_TITLE

    sh = _make_fake_sh(existing_titles=[])
    _write_summary_tab(sh, [], {}, {'chats': {}, 'users': {}})

    ws = sh._ws_by_title[SUMMARY_TAB_TITLE]
    rows = ws._updated_with
    # Block 0 header only (no group rows), then empty separators, then blocks.
    assert rows[0] == ['Группа', 'Всего сообщений', 'Всего юзеров', 'Всего реакций']
    # Two empty separator rows after header (no group rows).
    assert rows[1] == []
    assert rows[2] == []
    # Block 1 title follows.
    assert rows[3][0] == 'СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ ПО ЧАТАМ'


def test_write_summary_tab_does_not_touch_other_tabs():
    from modules.gsheets import _write_summary_tab, SUMMARY_TAB_TITLE

    other = MagicMock()
    other.title = 'Other Tab'

    summary = MagicMock()
    summary.title = SUMMARY_TAB_TITLE

    sh = _make_fake_sh()
    sh._ws_by_title = {SUMMARY_TAB_TITLE: summary, 'Other Tab': other}
    sh.worksheets.side_effect = lambda: [other, summary]

    _write_summary_tab(sh, [['G', 1, 1, 0]], {'-100': 'G'},
                       {'chats': {}, 'users': {}})

    other.clear.assert_not_called()
    other.update.assert_not_called()
    summary.clear.assert_called_once()
    summary.update.assert_called_once()


def test_write_summary_tab_full_data_with_messages_and_membership():
    """Summary tab includes full message list and membership events across chats."""
    from modules.gsheets import _write_summary_tab, SUMMARY_TAB_TITLE

    sh = _make_fake_sh(existing_titles=[])

    chat_data = _build_chat_data_with_membership()
    groups = {'-100123': 'Group A'}
    db = {
        'chats': {'-100123': chat_data},
        'users': {'100': {'username': 'alice'}, '200': {'username': 'bob'}},
    }
    group_rows = [['Group A', 2, 2, 1]]

    _write_summary_tab(sh, group_rows, groups, db)

    ws = sh._ws_by_title[SUMMARY_TAB_TITLE]
    rows = ws._updated_with

    # Block 1: user stats per chat
    _, h1, d1 = _find_block(rows, 'СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ ПО ЧАТАМ')
    assert rows[h1] == ['Чат', 'Пользователь', 'Сообщений',
                        'Реакций поставлено', 'Реакций получено']
    assert len(d1) == 2
    # Both users present with correct stats.
    usernames = {r[1] for r in d1}
    assert usernames == {'alice', 'bob'}

    # Block 2: all messages
    _, h2, d2 = _find_block(rows, 'СПИСОК СООБЩЕНИЙ ПО ВСЕМ ЧАТАМ')
    assert rows[h2] == ['Чат', 'Пользователь', 'Дата и время',
                         'Текст сообщения', 'Ссылка на сообщение']
    assert len(d2) == 2
    assert d2[0][0] == 'Group A'  # chat column
    assert d2[0][1] == 'alice'
    assert d2[0][2] == '2026-01-01T10:00:00'

    # Block 3: membership events
    _, h3, d3 = _find_block(rows, 'ИСТОРИЯ ПОДПИСОК/ОТПИСОК ПО ВСЕМ ЧАТАМ')
    assert rows[h3] == ['Чат', 'Пользователь', 'Отписка/Подписка', 'Дата']
    assert len(d3) == 2
    assert d3[0][0] == 'Group A'
    assert d3[0][1] == 'alice'
    assert d3[0][2] == 'Подписка'


if __name__ == '__main__':
    test_write_summary_tab_creates_when_missing()
    test_write_summary_tab_clears_existing()
    test_write_summary_tab_empty_rows()
    test_write_summary_tab_does_not_touch_other_tabs()
    test_write_summary_tab_full_data_with_messages_and_membership()
    print('ok')