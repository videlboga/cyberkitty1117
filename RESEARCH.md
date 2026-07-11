# RESEARCH.md

## Stack
- **Language/runtime:** Python 3 (system CPython 3.11+; project uses its own env). aiogram 3.4.1 pinned in `requirements.txt`.
- **Bot framework:** aiogram 3.x — async Telegram bot, `Bot` / `Dispatcher` from `aiogram`.
- **Storage:** flat JSON file `users_database.json`, cached in-process by `modules/db.py` (`load_database()` returns the cached dict, `await save_database(db)` writes it to disk and updates the cache).
- **Frontend approach:** N/A — no web UI. This task is a backend background worker only.
- **Build/test commands:**
  - Tests: `pytest tests/test_admin_sync.py -q` (and full suite `pytest tests/ -q`).
  - No build step. Run bot: `python main.py`.
  - Tests must mock `bot.get_chat_administrators` (AsyncMock) and `save_database` / `load_database` so no real Telegram API or filesystem is touched.

## Architecture
- **Directory layout (relevant files):**
  - `main.py` — Dispatcher, all handlers, background workers (`daily_summary_job`, `sheets_sync_job`), and `main()` which launches them via `asyncio.create_task`. The new `admin_sync_job` goes here alongside the other workers.
  - `modules/db.py` — `load_database()` (sync, returns cached dict) and `async save_database(data=None)` (writes JSON to disk, updates `_database_cache`).
  - `modules/roles.py` — `is_superadmin`, `is_admin`, `get_admin_groups`, `ADMIN_ID`. Already extracted from main.py; main.py imports `get_admin_groups`, `is_admin`, `is_superadmin`, `ADMIN_ID` from here.
  - `tests/` — pytest tests. Existing patterns: `sys.path.insert(0, ...)` at top of test files, `unittest.mock.MagicMock` / `AsyncMock` for mocking.
- **Existing admin-cache logic (main.py:558-567, inside `process_messages`):**
  ```python
  chat_data = db['chats'][chat_id_str]
  now_ts = dt.now().timestamp()
  if now_ts - chat_data.get('admins_updated_at', 0) > 3600 or not chat_data.get('admins'):
      try:
          admins = await bot.get_chat_administrators(message.chat.id)
          chat_data['admins'] = [str(a.user.id) for a in admins if not a.user.is_bot]
          chat_data['admins_updated_at'] = now_ts
      except Exception:
          pass
  ```
  This is the exact transformation the new worker must apply to ALL chats, not just the one that received a message.
- **DB chat schema (verified from live DB + code):** `db['chats'][cid_str]` = `{admins: [str], admins_updated_at: float, title: str, settings: {summary_time, summary_topic_id}, history: {date: [msgs]}, reactions: {date: [rxns]}, generating_lock, last_summary_date}`. Some chats lack `admins_updated_at` — code uses `.get('admins_updated_at', 0)`.
- **Worker launch pattern (main.py:659-680):** `main()` creates `Bot`, then `asyncio.create_task(daily_summary_job(bot))` and `asyncio.create_task(sheets_sync_job(bot))`, then `await dp.start_polling(bot, ...)`. The new `admin_sync_job` is launched identically after `sheets_sync_job`.
- **Bot API call:** `bot.get_chat_administrators(chat_id)` — aiogram 3.x async method. Returns a list of `ChatMember` objects; each has `.user.id` (int) and `.user.is_bot` (bool). The cid stored in db is a string (`str(message.chat.id)`), so the worker must call `bot.get_chat_administrators(int(cid))` to convert back to int.

## Acceptance Criteria
1. `async def admin_sync_job(bot: Bot)` exists in `main.py`. On startup it sleeps 30 seconds (`await asyncio.sleep(30)`), then enters an infinite loop.
2. Each loop iteration: calls `db = load_database()`, iterates every `cid, chat_data` in `db.get('chats', {}).items()`. For each chat, calls `admins = await bot.get_chat_administrators(int(cid))` and sets `chat_data['admins'] = [str(a.user.id) for a in admins if not a.user.is_bot]` and `chat_data['admins_updated_at'] = dt.now().timestamp()` (using the already-imported `dt` = `datetime`). After processing all chats, calls `await save_database(db)`.
3. If `bot.get_chat_administrators` raises for a specific chat, the error is logged (`logging.error` or `logging.warning`) and the worker continues to the next chat — the worker must NOT die on a per-chat API error.
4. After a full sweep, the worker sleeps 3600 seconds (`await asyncio.sleep(3600)`) before the next cycle.
5. The worker is launched in `main()` via `asyncio.create_task(admin_sync_job(bot))` placed AFTER the `asyncio.create_task(sheets_sync_job(bot))` line.
6. The outer loop is wrapped in a try/except so that an unexpected exception in the sweep is logged and the worker sleeps and retries rather than dying.
7. `tests/test_admin_sync.py` exists and passes with `pytest tests/test_admin_sync.py -q`. It must cover:
   - (a) Mock `bot.get_chat_administrators` with `AsyncMock` returning fake admin objects; verify `chat_data['admins']` is updated with correct string IDs (excluding bots) and `admins_updated_at` is set.
   - (b) Mock one chat's `get_chat_administrators` to raise an exception; verify the worker logs and continues to the next chat, which gets updated successfully.
   - (c) Mock `get_chat_administrators` returning an empty list; verify `admins` is set to `[]` and the worker does not crash.
   - Tests must mock `load_database`, `save_database`, and `asyncio.sleep` to avoid real DB I/O and infinite loops (e.g. patch `asyncio.sleep` to raise after N calls or use a side_effect that counts calls).
8. Existing tests still pass: `pytest tests/ -q` has no new failures from the change.
9. `admin_sync_job` is documented in this RESEARCH.md's Architecture section (done here).

## Engineering Notes
- **Import context:** `main.py` already imports `asyncio`, `logging`, `dt` (from `datetime`), `Bot`, `load_database`, `save_database`. No new top-level imports needed. `dt.now().timestamp()` is the existing pattern for `admins_updated_at` (see main.py:560).
- **Do NOT call `save_database` per-chat inside the loop** — accumulate changes in the in-memory `db` dict and call `await save_database(db)` once after the full sweep, matching the task description ("обновляет ... сохраняет через save_database(db)"). This minimizes disk I/O.
- **The `db` dict returned by `load_database()` is the cached `_database_cache`** — mutating it in-place and calling `save_database(db)` is the established pattern (see `process_messages`, `daily_summary_job`). The worker should follow this: get `db` once per sweep, mutate `chat_data` dicts in place, save once.
- **Chat ID conversion:** db keys are strings (`str(message.chat.id)`); `bot.get_chat_administrators` expects an int. Use `int(cid)`.
- **Empty `db['chats']`:** if there are no chats, the loop body simply doesn't execute and the worker sleeps 3600s — no crash.
- **Test isolation:** tests must NOT import `main.py` at module top-level (it constructs `Dispatcher` and imports aiogram/`modules.config`). Use `sys.path.insert` + import `main` inside the test function with aiogram mocked, OR better: import `admin_sync_job` by importing the `main` module with `aiogram` mocked via `sys.modules` (same pattern as `tests/test_export.py` and `tests/test_llm_client.py` which do `sys.modules['aiogram'] = MagicMock()`). Alternative: use `importlib` to load `main` after injecting mock modules. The simplest robust approach matching existing tests: at top of test file, `sys.path.insert(0, repo_root)`, then set `sys.modules['aiogram']` and `sys.modules['aiogram.*']` to `MagicMock()` before `import main`.
- **Mocking `asyncio.sleep`:** patch `main.asyncio.sleep` (or `asyncio.sleep`) with a side_effect that raises `RuntimeError('stop')` after the first call, and wrap the `admin_sync_job(bot)` call in `pytest.raises(RuntimeError)` to break the infinite loop. Alternatively, use a counter side_effect. This is the standard pattern for testing infinite-loop workers.
- **Mock `bot`:** use `MagicMock()` with `bot.get_chat_administrators = AsyncMock(side_effect=...)`. For the "one chat fails" test, use `side_effect` as a list/function: first call raises, second succeeds.
- **Fake admin objects:** simple `types.SimpleNamespace(user=types.SimpleNamespace(id=123, is_bot=False))` — matches the `.user.id` / `.user.is_bot` access pattern.
- **Do not modify `modules/db.py`, `modules/roles.py`, or any handler.** This task is purely additive: one new async function in `main.py`, one `asyncio.create_task` line in `main()`, one new test file.
- **Logging:** use the module-level `logging` already configured in main.py (`logging.basicConfig(level=logging.INFO)`). Log per-chat errors as `logging.error(f"admin_sync: chat {cid} failed: {e}")` or similar; log sweep start/finish with `logging.info`.
- **No new dependencies.** This task uses only aiogram (already installed) and stdlib. No requirements.txt changes.
- **Backward compatibility:** the existing `process_messages` admin-cache logic (main.py:558-567) stays as-is — it provides fast updates for active chats. The new worker is a safety net for inactive chats. Both can coexist; if both run within the same hour, the worker's `admins_updated_at` timestamp will be more recent, which is fine.