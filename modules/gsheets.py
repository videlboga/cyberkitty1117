"""Google Sheets integration for admin dashboards.

gspread is imported lazily inside `_get_client()` so that importing this
module never fails — even when gspread / google-auth are not installed or the
service-account JSON is missing. Bot startup must succeed regardless of the
Sheets environment.

The public spreadsheet functions (create_admin_spreadsheet,
update_admin_spreadsheet, get_or_create_admin_spreadsheet) are added in
subsequent tasks; this file currently provides only the lazy client factory.
"""

import os
import logging
import asyncio

from modules.roles import get_admin_groups
from modules.db import save_database


# Module-level cache for the gspread client. Populated on first successful
# `_get_client()` call; reset to None only on import-time so tests can patch it.
_gc = None


def _get_client():
    """Lazily build and cache a gspread.service_account client.

    Returns the cached gspread client on success, or None if gspread is not
    importable, the credentials file is missing, or auth fails. Never raises
    on the expected failure paths — logs a warning and returns None so callers
    can skip the Sheets sync gracefully.
    """
    global _gc
    if _gc is not None:
        return _gc

    try:
        import gspread
    except Exception as e:  # ImportError, ModuleNotFoundError, etc.
        logging.warning(
            "modules.gsheets: gspread not available, Sheets sync disabled: %s", e
        )
        return None

    creds_path = os.environ.get(
        'GOOGLE_APPLICATION_CREDENTIALS',
        '/home/cyberkitty/Загрузки/overproject-455420-a75ed4f4592e.json',
    )

    if not creds_path or not os.path.exists(creds_path):
        logging.warning(
            "modules.gsheets: credentials file not found at %s, "
            "Sheets sync disabled",
            creds_path,
        )
        return None

    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ]

    try:
        _gc = gspread.service_account(filename=creds_path, scopes=scopes)
    except Exception as e:
        logging.warning(
            "modules.gsheets: failed to init gspread client from %s: %s",
            creds_path, e, exc_info=True,
        )
        _gc = None
        return None

    logging.info("modules.gsheets: gspread client initialized from %s", creds_path)
    return _gc