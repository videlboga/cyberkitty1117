import json
from pathlib import Path
import asyncio

DB_PATH = Path("../database/users_database.json")

# Кэш в памяти
_database_cache = None

def load_database():
    """Загружает базу данных из JSON файла."""
    global _database_cache
    
    if _database_cache is not None:
        return _database_cache

    if not DB_PATH.exists():
        _database_cache = {}
        return _database_cache

    try:
        with open(DB_PATH, 'r', encoding='utf-8') as f:
            _database_cache = json.load(f)
    except Exception as e:
        print(f"Ошибка при загрузке БД: {e}")
        _database_cache = {}
        
    return _database_cache


async def save_database(data=None):
    """Сохраняет текущее состояние базы в JSON файл."""
    global _database_cache
    if data is not None:
        _database_cache = data
        
    if _database_cache is None:
        return
        
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        # В реальной среде лучше использовать aiofiles, но для ядра v1 подойдет и синхронная запись
        with open(DB_PATH, 'w', encoding='utf-8') as f:
            json.dump(_database_cache, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Ошибка при сохранении БД: {e}")

