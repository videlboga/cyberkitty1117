# RESEARCH.md

## Stack
- **Language/runtime:** Python 3 (Manjaro Linux, system CPython; externally-managed — installs must use a venv or `--break-system-packages`, but the project runs from its own env; deps declared in `requirements.txt`).
- **Bot framework:** aiogram 3.4.1 (async Telegram bot), pinned in `requirements.txt`.
- **Storage:** flat JSON file `users_database.json`, cached in-process by `modules/db.py` (`load_database()` / `async save_database()`). No SQL.
- **Existing deps:** aiogram, aiohttp, openai, python-dotenv, httpx, asgiref.
- **New deps to add:** `gspread` (latest 6.2.1 confirmed available on PyPI), `google-auth` (provides `google.oauth2.service_account`). gspread 6.x uses the v4 Sheets API via `gspread.service_account(filename=...)`.
- **Frontend approach:** N/A — no web UI. Google Sheets is the "report frontend"; written via gspread.
- **Build/test commands:**
  - Tests run with pytest: `pytest tests/ -q` (or `python tests/test_gsheets.py` directly, matching existing `tests/test_export.py` style).
  - No build step. Run bot: `python main.py`.
  - Env for tests: `GOOGLE_APPLICATION_CREDENTIALS` may be unset; tests must mock gspread and not touch the network.

## Architecture
- **Directory layout (current, minimal):**
  - `main.py` — Dispatcher, handlers, `get_admin_groups()`, `daily_summary_job`, `main()`.
  - `modules/db.py` — JSON load/save + in-memory `_database_cache`.
  - `modules/config.py` — loads `config.cfg` + `.env` via `load_dotenv()`, exports `API_TOKEN`, `openai`, `config`.
  - `modules/summary.py` — `save_message_to_database`, `get_summary_data`.
  - `modules/export.py` — `process_export` (per-chat CSV) and `build_global_export_csv_bytes` (multi-chat CSV). Contains the exact aggregation logic to reuse for Sheets.
  - `tests/test_export.py`, `tests/test_aiohttp.py` — existing pytest-style tests.
  - `users_database.json` — the live DB (7 chats, 222 users, superadmins=['648981358']).
- **New file:** `modules/gsheets.py` — all Google Sheets logic.
- **New test file:** `tests/test_gsheets.py`.
- **DB schema (verified from `users_database.json`):**
  - `db['superadmins']` : list[str] (default `['648981358']`).
  - `db['users'][uid_str]` : `{username, first_seen}` — **no `spreadsheet_id` field yet**; engineer adds it lazily on admin users only.
  - `db['chats'][cid_str]` : `{admins[], settings{}, history{date: [msg]}, reactions{date: [rxn]}, membership_events[], title, admins_updated_at, generating_lock, last_summary_date}`. Note: in the live DB several chats lack `title`, `reactions`, and `membership_events` keys — code must `.get(...)` defensively (the rest of the codebase already does).
- **Msg record shape:** `{user_id, link_to_message, text_in_msg, timestamp}` (user_id is a str).
- **Reaction record shape:** `{reactor_user_id, message_id, delta, timestamp}`.
- **Admin discovery (reuse, do NOT reimplement):** `get_admin_groups(user_id, db)` in `main.py` returns `{chat_id: title}` for superadmins + per-chat admins. The sheets worker must collect all admins by scanning `db['chats'][*]['admins']` + `db['superadmins']`, then call `get_admin_groups` per admin. Because `get_admin_groups` lives in `main.py` (which imports heavy aiogram stuff), prefer either (a) importing `get_admin_groups` lazily inside the worker, or (b) extracting/replicating the admin-collection in `gsheets.py`. Decision: the worker should import `get_admin_groups` from `main` lazily to avoid coupling; if that causes import cycles, replicate the small scan. The admin-list scan itself is: union of all `cdata['admins']` plus `db['superadmins']`.
- **Aggregation logic to mirror:** `modules/export.py::process_export` builds per-user stats `{messages, reactions_given, reactions_received}` plus a `msg_author_map` (message_id -> author_id derived from `link_to_message` last path segment) to credit received reactions. The Sheets per-group tab must reproduce this exact aggregation. A reusable helper (e.g. `compute_user_stats(chat_data, args=[])`) should be added, ideally factored out of `export.py` so both CSV and Sheets share it — but to avoid breaking existing CSV behavior, engineer may copy the logic into `gsheets.py` and keep them consistent. Mark which approach was chosen in code comments.
- **Service account (verified):** `/home/cyberkitty/Загрузки/overproject-455420-a75ed4f4592e.json` exists (2362 bytes), `type=service_account`, `project_id=overproject-455420`, `client_email=sammory@overproject-455420.iam.gserviceaccount.com`, contains `private_key`. This file is OUTSIDE the repo and must NOT be committed. Path via env `GOOGLE_APPLICATION_CREDENTIALS`, hardcoded fallback to that absolute path.
- **gspread usage (from API, confirmed available v6.2.1):**
  - Auth: `gc = gspread.service_account(filename=<json_path>, scopes=[...])`.
  - Create: `sh = gc.create('Summary Bot — {username}')` → returns Spreadsheet with `.id`.
  - Open existing: `sh = gc.open_by_key(spreadsheet_id)`.
  - Tabs: `ws = sh.get_worksheet(index)` / `sh.add_worksheet(title, rows, cols)` / `sh.del_worksheet(ws)`. Clear: `ws.clear()` then `ws.update([row, ...])` or `ws.append_row`.
  - Share (optional per task): `sh.share(email, perm_type='user', role='reader')` — only if admin email is known; admins in DB only have `username`, not email, so skip sharing for now (task says "пока просто создаём").
  - Sheet titles have a 100-char limit and cannot contain `:` — sanitize group titles for tab names (replace `:`/`/`/`[`,`]`,`*`,`?` with space; truncate to ~100 chars; dedupe names if collision).

## Acceptance Criteria
1. `modules/gsheets.py` exists and exposes `create_admin_spreadsheet(admin_user_id, admin_username)`, `update_admin_spreadsheet(admin_user_id, spreadsheet_id, db)`, and `get_or_create_admin_spreadsheet(admin_user_id, db)`.
2. `create_admin_spreadsheet` creates a spreadsheet titled exactly `Summary Bot — {username}`, returns its `spreadsheet_id` (str), and persists it into `db['users'][str(admin_user_id)]['spreadsheet_id']` via `save_database(db)`.
3. `update_admin_spreadsheet(admin_user_id, spreadsheet_id, db)`:
   - Opens the spreadsheet by key.
   - For each group returned by `get_admin_groups(admin_user_id, db)` (or equivalent scan), creates/replaces a tab named after the group title (sanitized to valid sheet-title constraints, unique within the spreadsheet).
   - Each group tab contains a header row `["Дата", "Пользователь", "Сообщений", "Реакций поставлено", "Реакций получено", "Текст последнего сообщения"]` followed by one row per user with the same per-user aggregation as `modules/export.py process_export` (messages count, reactions given, reactions received, plus the user's last message text — a new column not in CSV, derived from the most recent message by that user in that chat).
   - Contains a dedicated tab `Общая статистика` with columns `["Группа", "Всего сообщений", "Всего юзеров", "Всего реакций"]` and one row per group.
   - Aggregation must cover "за всё время" (all dates in history) when no period args are given, consistent with export.py's `len(args)==0` branch.
4. `get_or_create_admin_spreadsheet(admin_user_id, db)`: if `db['users'][str(admin_user_id)].get('spreadsheet_id')` exists and is truthy → reuse it (call update); otherwise call `create_admin_spreadsheet` then update. Returns the spreadsheet_id.
5. gspread client is initialized **lazily** (on first call), not at import time. If the JSON file is missing/unreadable, the module logs an error and returns `None`/raises a caught exception — importing `modules.gsheets` must NEVER raise and must NEVER block bot startup. `main()` startup must succeed even with no credentials file.
6. `main.py` gains `async def sheets_sync_job(bot)` launched via `asyncio.create_task` in `main()`. It loops forever, sleeping ~30 min between full sweeps; on each sweep it iterates all admins (union of `db['superadmins']` and every `db['chats'][*]['admins']`), calls `get_or_create_admin_spreadsheet` + `update_admin_spreadsheet` for each, and logs per-admin success/failure. Any exception per admin is logged and the loop continues — the worker must not die.
7. `requirements.txt` includes `gspread` and `google-auth` (pinned or `>=` reasonable minimum; `gspread>=6.0`).
8. The service account JSON path is read from `GOOGLE_APPLICATION_CREDENTIALS` env var with a hardcoded fallback to `/home/cyberkitty/Загрузки/overproject-455420-a75ed4f4592e.json`. The JSON file itself is not added to the repo and must be in `.gitignore`-safe location (it is outside the repo tree).
9. `tests/test_gsheets.py` exists, uses a mock gspread client (e.g. `unittest.mock.MagicMock` patched into `modules.gsheets`), asserts: (a) `create_admin_spreadsheet` calls `gc.create(...)` with the expected title and returns a non-None id and stores it in the mock db; (b) `update_admin_spreadsheet` calls `open_by_key`, creates a tab per group, writes the header row, writes at least one data row for a group with history, and creates the `Общая статистика` tab; (c) `get_or_create_admin_spreadsheet` reuses an existing id when present and creates when absent. No real network/API calls are made.
10. Existing behavior is unchanged: `pytest tests/test_export.py tests/test_aiohttp.py` still pass, and `main.py` imports/starts without the Sheets env present.

## Engineering Notes
- **Do not break `modules/db.py` shape.** `users` entries currently only have `{username, first_seen}`. Adding `spreadsheet_id` to admin users is additive and safe; do not restructure other keys. `save_database` is async — the sheets module must call `await save_database(db)` when persisting the id, not sync write the file directly.
- **Lazy gspread init pattern:** keep a module-level `_gc = None` and a `_get_client()` that imports gspread lazily, reads `os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '/home/cyberkitty/Загрузки/overproject-455420-a75ed4f4592e.json')`, checks the file exists, and returns the client; caches on success; raises/returns None on failure with a logged warning. All three public functions must tolerate `_get_client()` returning None by logging and returning None (worker then skips that admin).
- **Async/sync boundary:** gspread is synchronous (uses `requests`/`google-auth` under the hood). Because the Sheets worker runs in an asyncio task alongside the bot, wrap each blocking gspread call in `await asyncio.to_thread(...)` (or `loop.run_in_executor`) so the event loop is not blocked. This is mandatory — calling gspread directly inside the async worker will freeze polling.
- **gspread not yet installed** in the current interpreter (verified: `ModuleNotFoundError`). The engineer must ensure `gspread` + `google-auth` are importable in the runtime env (add to requirements and install in the bot's venv). Tests mock gspread so they pass without it installed, but `main.py` import must not hard-fail if gspread is absent — import gspread lazily inside `_get_client` and guard the import with try/except, logging that Sheets sync is disabled when the lib is missing.
- **Sheet title sanitization:** Google Sheets tab names cannot contain `:` and must be ≤ 100 chars; also avoid `/ \ ? * [ ]`. Implement a `sanitize_sheet_title(title)` used for all group tabs. Ensure uniqueness within a spreadsheet (append ` (2)` etc. on collision). The `Общая статистика` tab name is fixed and must be created exactly once (delete a pre-existing one before re-adding, or clear it in place).
- **Idempotent updates:** `update_admin_spreadsheet` must be safe to call repeatedly every 30 min. Prefer clearing tab contents (`ws.clear()`) and rewriting over deleting/recreating tabs, to preserve tab order and avoid leaking orphan tabs; but also remove tabs for groups the admin no longer manages. A robust approach: build the set of desired tab names, delete tabs not in the set, clear+rewrite tabs in the set. Keep `Общая статистика` as the first tab.
- **Admin iteration in worker:** collect `all_admins = set(db.get('superadmins', [])) | {a for c in db.get('chats', {}).values() for a in c.get('admins', [])}`. Skip empty/None ids. Reload db at the start of each sweep (call `load_database()`) to get fresh admin lists; pass the same db snapshot into get_or_create/update for that sweep.
- **`get_admin_groups` reuse:** it lives in `main.py`. To avoid importing `main` (which constructs a Dispatcher at import), either (a) move `get_admin_groups`/`is_superadmin`/`is_admin` into a small `modules/roles.py` and import from both `main` and `gsheets`, or (b) replicate the admin-groups scan inside `gsheets.py`. Preferred: option (a) reduces duplication, but it touches `main.py` imports — acceptable since it's a non-breaking refactor. If the engineer wants minimum churn, option (b) is fine; document the choice. Either way the behavior must match `get_admin_groups` exactly (superadmin sees all chats; per-chat admin sees only chats where they're in `admins`).
- **"Текст последнего сообщения" column:** export.py does not currently track last message text per user. Engineer must derive it during aggregation: track, per user_id in a chat, the message with the max `timestamp` and its `text_in_msg or text or "[Медиа/Без текста]"`. Keep this consistent with export.py's text fallback.
- **No real API calls in tests.** Patch `modules.gsheets._get_client` (or the gspread module) with MagicMock. Provide a fake `gc` whose `create` returns a fake spreadsheet exposing `.id`, `.add_worksheet`, `.get_worksheet`, `.del_worksheet`, `.worksheets()`, `.share`, etc. Feed a small synthetic `db` mirroring the real schema (see `tests/test_export.py` for the shape). Assert call args and that written rows include the header and expected data.
- **Logging:** use `logging` (already configured in main.py). Log per-admin: `logging.info(f"Sheets sync: admin={admin_id} ok")` / `logging.error(f"Sheets sync failed for {admin_id}: {e}", exc_info=True)`.
- **Do not commit the service account JSON.** It lives in `~/Загрузки/`, outside the worktree; leave it there. Do not copy it into the repo. Do not print its private_key contents anywhere.
- **Backward compat:** keep `process_export` / `build_global_export_csv_bytes` working unchanged. If factoring shared aggregation into a helper, re-run `tests/test_export.py` to confirm identical CSV output.