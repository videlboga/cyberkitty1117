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


def test_write_summary_tab_creates_when_missing():
    from modules.gsheets import _write_summary_tab, SUMMARY_TAB_TITLE

    sh = _make_fake_sh(existing_titles=[])  # no existing tabs

    group_rows = [
        ['Group A', 10, 3, 5],
        ['Group B', 20, 4, 7],
    ]
    _write_summary_tab(sh, group_rows)

    sh.add_worksheet.assert_called_once()
    assert sh._last_added[0] == SUMMARY_TAB_TITLE
    assert sh._last_added[3] == 0  # index=0 (first tab)

    ws = sh._ws_by_title[SUMMARY_TAB_TITLE]
    assert ws._cleared is True
    expected = [
        ['Группа', 'Всего сообщений', 'Всего юзеров', 'Всего реакций'],
        ['Group A', 10, 3, 5],
        ['Group B', 20, 4, 7],
    ]
    assert ws._updated_with == expected


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
    _write_summary_tab(sh, group_rows)

    # Must NOT add a new tab when one exists.
    sh.add_worksheet.assert_not_called()
    assert existing._cleared is True
    assert existing._updated_with == [
        ['Группа', 'Всего сообщений', 'Всего юзеров', 'Всего реакций'],
        ['Only Group', 5, 2, 1],
    ]


def test_write_summary_tab_empty_rows():
    from modules.gsheets import _write_summary_tab, SUMMARY_TAB_TITLE

    sh = _make_fake_sh(existing_titles=[])
    _write_summary_tab(sh, [])

    ws = sh._ws_by_title[SUMMARY_TAB_TITLE]
    assert ws._updated_with == [
        ['Группа', 'Всего сообщений', 'Всего юзеров', 'Всего реакций'],
    ]


def test_write_summary_tab_does_not_touch_other_tabs():
    from modules.gsheets import _write_summary_tab, SUMMARY_TAB_TITLE

    other = MagicMock()
    other.title = 'Other Tab'

    summary = MagicMock()
    summary.title = SUMMARY_TAB_TITLE

    sh = _make_fake_sh()
    sh._ws_by_title = {SUMMARY_TAB_TITLE: summary, 'Other Tab': other}
    sh.worksheets.side_effect = lambda: [other, summary]

    _write_summary_tab(sh, [['G', 1, 1, 0]])

    other.clear.assert_not_called()
    other.update.assert_not_called()
    summary.clear.assert_called_once()
    summary.update.assert_called_once()


if __name__ == '__main__':
    test_write_summary_tab_creates_when_missing()
    test_write_summary_tab_clears_existing()
    test_write_summary_tab_empty_rows()
    test_write_summary_tab_does_not_touch_other_tabs()
    print('ok')