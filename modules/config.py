"""
Модуль конфигурации бота.
Содержит загрузку настроек, инициализацию клиентов OpenAI и основные константы.
"""

import configparser
import httpx
import openai as op
from datetime import datetime as dt
import os
from dotenv import load_dotenv  # NEW: для чтения .env


def load_cfg(file_path):
    """Загружает конфигурационный файл."""
    config = configparser.ConfigParser()
    config.read(file_path, encoding='utf8')
    return config


def init_openai_client(config):
    """Инициализирует клиент OpenAI с настройками прокси."""
    # Установка прокси для клиента OpenAI
    proxy_yes = config['Settings'].getboolean('proxy_yes', False)
    http_client = None
    
    if proxy_yes:
        # Получение настроек прокси
        proxy_http = config['Settings'].get('proxy_http', 'def_value_none')
        proxy_https = config['Settings'].get('proxy_https', 'def_value_none')

        # Настройка прокси для новых версий httpx
        if proxy_http != 'def_value_none' and proxy_https != 'def_value_none':
            # В новых версиях httpx используется параметр proxies
            http_client = httpx.Client(proxies={"http://": proxy_http, "https://": proxy_https})
    
    api_key_chatgpt = config['Settings'].get('api_key_chatgpt', 'def_value_none')
    
    # Проверяем, используем ли OpenRouter или обычный OpenAI
    if api_key_chatgpt.startswith('sk-or-'):
        # Используем OpenRouter
        openai_client = op.OpenAI(
            api_key=api_key_chatgpt, 
            base_url="https://openrouter.ai/api/v1",
            http_client=http_client
        )
        print('Инициализирован OpenRouter клиент')
    else:
        # Используем обычный OpenAI
        openai_client = op.OpenAI(api_key=api_key_chatgpt, http_client=http_client)
        print('Инициализирован OpenAI клиент')
    
    return openai_client


# NEW: загружаем переменные окружения из .env, если он существует
load_dotenv()

# NEW: путь к конфигу можно переопределить через переменную окружения
CONFIG_PATH = os.getenv("CONFIG_FILE", "./config.cfg")

# Загружаем конфигурацию в переменную _cfg (чтобы не конфликтовать с именем модуля)
_cfg = load_cfg(CONFIG_PATH)
print(f'Конфиг загружен из {CONFIG_PATH}')

# Гарантируем наличие секции Settings, чтобы не было KeyError
if 'Settings' not in _cfg:
    _cfg['Settings'] = {}

# Записываем переменные окружения в секцию Settings (не перезаписываем, если уже есть значение)
env_overrides = {
    'tg_bot_token': os.getenv('TG_BOT_TOKEN') or os.getenv('CYBERKITTY_TG_BOT_TOKEN'),
    'api_key_chatgpt': os.getenv('OPENAI_API_KEY') or os.getenv('API_KEY_CHATGPT'),
    'proxy_yes': os.getenv('PROXY_YES'),
    'proxy_http': os.getenv('PROXY_HTTP'),
    'proxy_https': os.getenv('PROXY_HTTPS'),
    'text_model': os.getenv('TEXT_MODEL'),
    'max_tokens': os.getenv('MAX_TOKENS'),
    'temperature': os.getenv('TEMPERATURE'),
    'database_url': os.getenv('DATABASE_URL') or os.getenv('CYBERKITTY_DATABASE_URL'),
}

for key, value in env_overrides.items():
    if value is not None:
        _cfg['Settings'][key] = value

# Инициализируем OpenAI клиент
openai = init_openai_client(_cfg)

# Основные константы
API_TOKEN = _cfg['Settings'].get('tg_bot_token', 'def_value_none')
ADMINS = ['tomjeferson', 'Like_a_duck']
FOLDER_PATH = './database/users_database.json'
TEST_PATH = './database/test_database.json'

print(f'Сегодня {dt.now().date()} и я запущен')

# Экспортируем _cfg под старым именем для совместимости с кодом/тестами
config = _cfg  # noqa: N816  (оставляем в __all__ как ожидалось) 