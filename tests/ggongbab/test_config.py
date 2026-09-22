# -*- coding: utf-8 -*-
"""Environment handling, in particular the Supabase key rename."""
from __future__ import annotations

import pytest

from ggongbab.config import SUPABASE_KEY_ENV, Settings

BOTH = ("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")


@pytest.fixture(autouse=True)
def clear_supabase_env(monkeypatch):
    for name in BOTH + ("SUPABASE_URL",):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")


def test_primary_key_env_order():
    assert SUPABASE_KEY_ENV == ("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")


def test_secret_key_is_preferred(monkeypatch):
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_new")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "legacy_jwt")
    s = Settings()
    assert s.supabase_secret_key == "sb_secret_new"
    assert s.supabase_key_env == "SUPABASE_SECRET_KEY"
    assert s.supabase_key_is_legacy is False
    assert s.has_supabase


def test_service_role_key_is_legacy_fallback(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "legacy_jwt")
    s = Settings()
    assert s.supabase_secret_key == "legacy_jwt"
    assert s.supabase_key_env == "SUPABASE_SERVICE_ROLE_KEY"
    assert s.supabase_key_is_legacy is True
    assert s.has_supabase


def test_empty_primary_falls_through(monkeypatch):
    # GitHub Actions passes an unset secret as an empty string, not as an absent variable.
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "legacy_jwt")
    s = Settings()
    assert s.supabase_secret_key == "legacy_jwt"
    assert s.supabase_key_is_legacy is True


def test_no_key_disables_supabase(monkeypatch):
    s = Settings()
    assert s.supabase_secret_key == ""
    assert s.supabase_key_env == ""
    assert s.has_supabase is False
