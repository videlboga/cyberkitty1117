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