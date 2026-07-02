# RESEARCH.md

## Stack
- Python 3.9+, aiogram 3.4.1 (async Telegram bot), aiohttp, httpx.
- LLM через OpenAI SDK (openai>=1.x), направляется на OpenRouter (`base_url=https://openrouter.ai/api/v1`) при ключе `sk-or-`.
- Хранилище: JSON-файл (`users_database.json`), in-memory dict в рантайме.
- Конфиг: `config.cfg` (configparser) + `.env` (python-dotenv), env-переменные перезаписывают секцию `Settings`.
- Тесты: pytest 9.0.3 (установлен в окружении). Способа запуска по умолчанию нет — используется `python -m pytest tests/`.
- Frontend: отсутствует (Telegram-бот, HTML-сообщения с `<a href>`).

## Architecture
- `main.py` — точка входа, aiogram-роутеры, планировщик сводок.
- `modules/summary.py` — `get_summary_data(chat_id, data_needed, database)`: собирает `forming_data` (список dict-сообщений) и `only_text`, формирует промпт, вызывает `ask_llm`, парсит ответ через `ast.literal_eval`, рендерит итоговое HTML-сообщение. `save_message_to_database` пишет сообщения в историю.
- `modules/llm_client.py` — `ask_llm(condition_text, channel_text_data)`: отправляет `openai.chat.completions.create(model, messages, stream=True)`, склеивает stream-чанки, до 3 ретраев. Сейчас возвращает `""` (строка 60) при всех неудачах, хотя docstring обещает `None`.
- `modules/config.py` — `load_cfg`, `init_openai_client`, загрузка `.env` поверх `config.cfg`, env-overrides в секцию `Settings`. Экспортирует `openai` (клиент) и `config` (_cfg).
- `tests/` — только `test_export.py`, `test_aiohttp.py`. `test_summary.py` / `test_llm_client.py` отсутствуют — создавать с нуля.

### Структура сообщения в истории (message_data)
`{"user_id", "link_to_message", "text_in_msg", "timestamp"}` — см. `summary.py:136-141`.

### Корневые проблемы (подтверждено кодом)
1. Промпт `summary.py:38-44` содержит `Выдели КАЖДУЮ уникальную тему или идею, даже если она упоминалась мельком` → одна тема на сообщение.
2. Дефолт модели — `llm_client.py:28` (НЕ `config.py:28`, как в описании задачи): `config['Settings'].get('text_model', 'gpt-3.5-turbo')`.
3. `llm_client.py:23` — `str(channel_text_data)` передаёт сырой `list[dict]` в LLM.
4. `summary.py:63,72` — `ast.literal_eval(llm_answer)`: падает на markdown-обёртках, пустой строке, не-python-dict.
5. `llm_client.py:32-36` — `max_tokens`/`temperature` из config не передаются в `create`.
6. `llm_client.py:60` — возвращает `""`, docstring обещает `None`; `ast.literal_eval("")` → `SyntaxError` в `summary.py:63`.

### Модель DeepSeek на OpenRouter (проверено live-запросом `/api/v1/models`)
Доступные релевантные идентификаторы и цена (per token, USD):
- `deepseek/deepseek-v4-flash` — ctx 1 048 576, prompt $0.000000089, completion $0.00000018. ← рекомендуемый дефолт (быстрый, дешёвый, длинный контекст).
- `deepseek/deepseek-v4-pro` — ctx 1 048 576, prompt $0.000000435, completion $0.00000087 (качественнее, дороже).
- `deepseek/deepseek-chat` — ctx 131 072, prompt $0.0000002002, completion $0.0000008001.
- `deepseek/deepseek-v3.2` — ctx 131 072, prompt $0.0000002288, completion $0.0000003432.

Идентификатор из описания `deepseek/deepseek-chat-v4-flash` НЕ существует на OpenRouter. Правильный — `deepseek/deepseek-v4-flash` (проверено: есть в выдаче `/api/v1/models`). Инженер обязан использовать именно `deepseek/deepseek-v4-flash`.

## Acceptance Criteria
1. В `modules/config.py` (или `llm_client.py` — где живёт `.get('text_model', ...)`) дефолт модели изменён с `gpt-3.5-turbo` на `deepseek/deepseek-v4-flash`.
2. При ключе `sk-or-` клиент уже использует `base_url=https://openrouter.ai/api/v1` — это не должно сломаться (инженер проверяет, что путь ключа сохранён).
3. `.env.example` (новый файл, т.к. `.env` в `.gitignore` и `.env.example` отсутствует) содержит пример `TEXT_MODEL=deepseek/deepseek-v4-flash`. README обновлён упоминанием DeepSeek как дефолта.
4. Промпт в `summary.py` НЕ содержит подстроки `КАЖДУЮ` (точнее `Выдели КАЖДУЮ`). Новая инструкция: группировать сообщения по темам, объединять похожее, выделять 3–8 ключевых тем за день. Лимит тем берётся из `settings.get('summary_max_topics', 8)` (новая настройка per-chat, дефолт 8). Добавлена инструкция: `Если сообщение не вписывается в основную тему — отнеси к теме «Прочее»`. В промпт встроен явный пример ожидаемого вывода (dict).
5. Per-chat override `settings.prompt_summary` сохранён — если задан, используется вместо дефолтного промпта (но лимит тем и инструкция про «Прочее» применяются всегда, поверх override, либо override полностью заменяет — инженер решает, но custom-промпт должен работать). Рекомендация: override заменяет только пользовательскую часть, служебные инструкции (`condition_main2` формат + лимит) остаются.
6. `forming_data` передаётся в LLM в читаемом текстовом виде: `[1] username: text (link)\n[2] ...` — форматирование реализовано новой функцией (например `_format_messages_for_llm`). В LLM идут только `text_in_msg` + `link_to_message` (username если есть в `database['users']`), без `user_id`/`timestamp`. Для links-запроса `only_text` форматируется аналогично или остаётся списком текстов — инженер сохраняет рабочую логику links.
7. Парсинг ответа LLM: `ast.literal_eval` заменён на безопасный JSON-парсинг (`json.loads`) с очисткой ответа от markdown-обёрток (```json ... ```, ```python ... ```) и извлечением dict регуляркой (например `re.search(r'\{.*\}', text, re.DOTALL)`) как fallback. Если парсинг не удался — `dict_info = None` (не падает).
8. `ask_llm` при неудаче (все ретраи исчерпаны / пустой ответ) возвращает `None`, а не `""`. Это согласовано с docstring функции и предотвращает `SyntaxError`/`ValueError` в вызывающем коде.
9. `ask_llm` передаёт `max_tokens` и `temperature` в `openai.chat.completions.create`, если они заданы в `config['Settings']` (читаются через `.get` с дефолтом-None → не передаются, если не заданы). Параметры добавляются только при наличии (не передавать `None` в API).
10. `get_summary_data` корректно обрабатывает `None` от `ask_llm`: не падает, возвращает итоговое сообщение с темами (если распарсились) или `None`, если тем нет.
11. `tests/test_summary.py` (новый) покрывает: (а) промпт не содержит `КАЖДУЮ`; (б) парсинг валидного JSON; (в) парсинг JSON в markdown-обёртке ```json ... ```; (г) парсинг невалидного ответа → `None`, без исключения; (д) `_format_messages_for_llm` возвращает строки вида `[1] username: text (link)`; (е) при моке `ask_llm` → `None` `get_summary_data` не падает.
12. `tests/test_llm_client.py` (новый или обновлённый) покрывает: `ask_llm` возвращает `None` после 3 неудач; `ask_llm` передаёт `max_tokens`/`temperature` в `create`, когда они заданы в config; склейка stream-чанков.
13. `python -m pytest tests/` проходит без ошибок.

## Engineering Notes
- Дефолт модели правится в `llm_client.py:28` (`config['Settings'].get('text_model', 'gpt-3.5-turbo')`) — именно тут живёт `.get`, а не в `config.py`. `config.py` только проксирует env `TEXT_MODEL` в `_cfg['Settings']['text_model']`. Дублирующего дефолта в `config.py` нет — инженер правит едиственное место в `llm_client.py`. (Описание задачи ссылалось на `config.py:28` — неточно; источник истины — код.)
- Идентификатор модели: использовать `deepseek/deepseek-v4-flash` (подтверждён live-запросом к `https://openrouter.ai/api/v1/models`). Идентификатор `deepseek/deepseek-chat-v4-flash` из описания НЕ существует — его использовать нельзя.
- `max_tokens`/`temperature` из env приходят как строки (`os.getenv` в `config.py:78-79`). В `ask_llm` нужно приводить к int/float и только затем передавать; передавать строки в OpenAI-клиент нельзя. Если значение невалидно/отсутствует — параметр не передаётся вовсе (собирать kwargs условно).
- OpenRouter принимает стандартные `max_tokens`/`temperature` в `chat.completions.create` — совместимо с OpenAI SDK. Доп. заголовки (`HTTP-Referer`, `X-Title`) опциональны, можно не добавлять.
- Парсинг: ответ LLM может содержать одинарные кавычки (python-dict) ИЛИ двойные (JSON). Стратегия: strip → убрать ```…``` обёртки → `json.loads` → если падает, попытаться заменить одинарные кавычки на двойные и повторить `json.loads` → fallback regex `\{.*\}` → `json.loads` найденного → иначе `None`. Не использовать `ast.literal_eval` (eval-семантика, хрупко).
- `only_text` (для links-запроса) сейчас — список строк; логика links в `summary.py:69-75` отдельная. Инженер не должен сломать links-парсинг; формат `only_text` можно оставить списком строк, т.к. links-промпт ожидает текст для поиска ссылок. Менять формат только для основного (themes) запроса.
- Тесты мокают `ask_llm` (патч `modules.summary.ask_llm`) и `openai.chat.completions.create` (для `test_llm_client`). Не делать реальных сетевых вызовов. В `test_summary.py` мок `database` с историей на тестовую дату.
- `config.cfg` отсутствует в worktree (только `.gitignore` + env-механизм) — тесты не должны зависеть от реального конфига; мокать `config`/`openai` через `unittest.mock` или monkeypatch.
- `.env.example` — НОВЫЙ файл (в репо отсутствует, `.env` в `.gitignore`). Создать с примерами всех env-переменных из `config.py:72-80`: `TG_BOT_TOKEN`, `OPENAI_API_KEY` (sk-or-…), `TEXT_MODEL=deepseek/deepseek-v4-flash`, `MAX_TOKENS`, `TEMPERATURE`, `DATABASE_URL`, опционально `PROXY_*`, `CONFIG_FILE`.
- Не трогать `save_message_to_database`, `main.py`, экспорт-модули — область задачи ограничена summary/llm_client/config/тестами.
- Бэкап: worktree уже на отдельной ветке `agent/run_074c04a4` от чистого коммита `e9938ad` — отдельный бэкап не нужен, изменения изолированы.

### Подходы, которые попробованы (research)
1. Live-запрос `GET https://openrouter.ai/api/v1/models` — успешно, без авторизации. Получены реальные идентификаторы и цены DeepSeek-моделей. Подтверждено: `deepseek/deepseek-v4-flash` существует, `deepseek/deepseek-chat-v4-flash` — нет.
2. Чтение `config.py` — подтверждено, что `text_model` проксируется через env `TEXT_MODEL`, дефолт живёт в `llm_client.py:28`, а не в `config.py`.
3. Поиск `tests/test_summary.py`, `test_llm_client.py` — не найдены, создаются с нуля.
4. Поиск `.env.example` / `config.cfg` в worktree — отсутствуют; `.env` в `.gitignore`. Создаётся `.env.example`.