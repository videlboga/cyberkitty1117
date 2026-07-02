"""Pytest configuration for the project root.

`test_chat.py` at the repo root is a manual debug script (not a unit test): it
imports `aiogram`, which is not installed in the lightweight test environment.
Without this ignore, a bare `pytest` run from the root aborts collection with
ModuleNotFoundError and masks the real test suite under `tests/`.
"""
collect_ignore = ["test_chat.py"]