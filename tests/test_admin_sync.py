"""Тесты admin_sync_job из main.py.

Покрывает:
(a) обновление admins строковыми ID (исключая ботов) + admins_updated_at;
(b) продолжение работы при ошибке API для одного чата;
(c) пустой список admins от API.

Паттерн тестирования — mock sys.modules['aiogram'] как в test_export.py / test_llm_client.py.
Patch main.asyncio.sleep с side_effect RuntimeError('stop') для прерывания бесконечного цикла.
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

# Гарантируем, что корень проекта доступен в sys.path (как в test_export.py)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _import_main():
    """Импортирует main с замоканным aiogram, чтобы избежать реального API."""
    # Сохраняем оригинал, чтобы не ломать другие тесты
    saved = {}
    aiogram_modules = [
        'aiogram',
        'aiogram.types',
        'aiogram.filters',
        'aiogram.utils',
        'aiogram.utils.keyboard',
        'aiogram.client',
        'aiogram.client.default',
        'aiogram.client.session',
        'aiogram.client.session.aiohttp',
        'aiogram.client.telegram',
        'aiogram.enums',
    ]
    for mod in aiogram_modules:
        if mod in sys.modules:
            saved[mod] = sys.modules[mod]
        sys.modules[mod] = MagicMock()

    # Принудительно перезагружаем main
    if 'main' in sys.modules:
        del sys.modules['main']
    import main
    return main


def _make_admin(user_id, is_bot=False):
    """Создаёт фейковый объект ChatMember с .user.id и .user.is_bot."""
    return types.SimpleNamespace(
        user=types.SimpleNamespace(id=user_id, is_bot=is_bot)
    )


# ---------------------------------------------------------------------------
# (a) Обновление admins строковыми ID (исключая ботов) + admins_updated_at
# ---------------------------------------------------------------------------
def test_admin_sync_updates_admins():
    main = _import_main()

    chats = {
        "-100123": {
            'admins': [],
            'admins_updated_at': 0,
            'title': 'Chat A',
            'settings': {},
            'history': {},
            'reactions': {},
        },
    }
    db = {'chats': chats, 'users': {}}

    bot = MagicMock()
    bot.get_chat_administrators = AsyncMock(
        return_value=[
            _make_admin(111, is_bot=False),
            _make_admin(222, is_bot=False),
            _make_admin(333, is_bot=True),  # бот — должен быть исключён
        ]
    )

    save_mock = AsyncMock(return_value=None)

    call_count = {'n': 0}

    async def fake_sleep(seconds):
        call_count['n'] += 1
        if call_count['n'] >= 2:
            raise RuntimeError('stop')

    with patch.object(main, 'load_database', return_value=db), \
         patch.object(main, 'save_database', save_mock), \
         patch.object(main.asyncio, 'sleep', side_effect=fake_sleep):
        # Первый sleep(30) проходит, второй sleep(3600) — RuntimeError('stop')
        try:
            asyncio.run(main.admin_sync_job(bot))
        except RuntimeError as e:
            assert str(e) == 'stop'

    chat_data = chats['-100123']
    assert chat_data['admins'] == ['111', '222'], \
        f"Ожидалось ['111','222'], получилось {chat_data['admins']}"
    assert chat_data['admins_updated_at'] > 0, \
        "admins_updated_at должен быть установлен"
    save_mock.assert_called_once_with(db)


# ---------------------------------------------------------------------------
# (b) Ошибка API для одного чата — воркер продолжает и обновляет следующий
# ---------------------------------------------------------------------------
def test_admin_sync_continues_after_error():
    main = _import_main()

    chats = {
        "-100999": {
            'admins': ['old'],
            'admins_updated_at': 0,
            'title': 'Broken Chat',
            'settings': {},
            'history': {},
            'reactions': {},
        },
        "-100888": {
            'admins': [],
            'admins_updated_at': 0,
            'title': 'Good Chat',
            'settings': {},
            'history': {},
            'reactions': {},
        },
    }
    db = {'chats': chats, 'users': {}}

    bot = MagicMock()

    async def get_admins(chat_id):
        if chat_id == int("-100999"):
            raise Exception("Telegram API error")
        return [_make_admin(555, is_bot=False)]

    bot.get_chat_administrators = AsyncMock(side_effect=get_admins)

    save_mock = AsyncMock(return_value=None)

    call_count = {'n': 0}

    async def fake_sleep(seconds):
        call_count['n'] += 1
        if call_count['n'] >= 2:
            raise RuntimeError('stop')

    with patch.object(main, 'load_database', return_value=db), \
         patch.object(main, 'save_database', save_mock), \
         patch.object(main.asyncio, 'sleep', side_effect=fake_sleep):
        try:
            asyncio.run(main.admin_sync_job(bot))
        except RuntimeError as e:
            assert str(e) == 'stop'

    # Первый чат не обновился (ошибка), второй — обновился
    assert chats['-100999']['admins'] == ['old'], \
        "Сломанный чат не должен был обновиться"
    assert chats['-100888']['admins'] == ['555'], \
        f"Хороший чат должен был обновиться, получилось {chats['-100888']['admins']}"
    assert chats['-100888']['admins_updated_at'] > 0


# ---------------------------------------------------------------------------
# (c) Пустой список admins от API
# ---------------------------------------------------------------------------
def test_admin_sync_empty_admins():
    main = _import_main()

    chats = {
        "-100000": {
            'admins': ['should_be_cleared'],
            'admins_updated_at': 0,
            'title': 'Empty Admins',
            'settings': {},
            'history': {},
            'reactions': {},
        },
    }
    db = {'chats': chats, 'users': {}}

    bot = MagicMock()
    bot.get_chat_administrators = AsyncMock(return_value=[])

    save_mock = AsyncMock(return_value=None)

    call_count = {'n': 0}

    async def fake_sleep(seconds):
        call_count['n'] += 1
        if call_count['n'] >= 2:
            raise RuntimeError('stop')

    with patch.object(main, 'load_database', return_value=db), \
         patch.object(main, 'save_database', save_mock), \
         patch.object(main.asyncio, 'sleep', side_effect=fake_sleep):
        try:
            asyncio.run(main.admin_sync_job(bot))
        except RuntimeError as e:
            assert str(e) == 'stop'

    assert chats['-100000']['admins'] == [], \
        f"Ожидался пустой список, получилось {chats['-100000']['admins']}"
    assert chats['-100000']['admins_updated_at'] > 0


if __name__ == '__main__':
    test_admin_sync_updates_admins()
    test_admin_sync_continues_after_error()
    test_admin_sync_empty_admins()
    print("All admin_sync tests passed.")