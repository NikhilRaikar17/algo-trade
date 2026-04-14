"""Tests for state.py: cache, dedup, and market hours."""

import json
import time
from datetime import datetime
from unittest.mock import mock_open, patch

import pytest
import pytz

IST = pytz.timezone("Asia/Kolkata")


def _ist(year, month, day, hour=10, minute=0):
    return IST.localize(datetime(year, month, day, hour, minute))


# ── Cache ────────────────────────────────────────────────────────────────────

def test_cache_miss_returns_none():
    from state import _cache_get, _data_cache
    _data_cache.clear()
    assert _cache_get("nonexistent_key_xyz") is None


def test_cache_hit_returns_value():
    from state import _cache_get, _cache_set, _data_cache
    _data_cache.clear()
    _cache_set("mykey", {"foo": 42})
    assert _cache_get("mykey") == {"foo": 42}


def test_cache_expires_after_ttl(mocker):
    from state import _cache_get, _cache_set, _data_cache, CACHE_TTL
    _data_cache.clear()
    # Set entry with a timestamp far in the past
    _data_cache["oldkey"] = {"data": "stale", "time": time.time() - CACHE_TTL - 1}
    assert _cache_get("oldkey") is None


# ── Dedup ────────────────────────────────────────────────────────────────────

def test_dedup_false_before_mark(mocker):
    from state import _is_already_sent
    mocker.patch("state._load_dedup", return_value={})
    assert _is_already_sent("some_key") is False


def test_dedup_true_after_mark(mocker):
    from state import _is_already_sent, _mark_sent
    store = {}

    def fake_load():
        return dict(store)

    def fake_save(data):
        store.clear()
        store.update(data)

    mocker.patch("state._load_dedup", side_effect=fake_load)
    mocker.patch("state._save_dedup", side_effect=fake_save)
    mocker.patch("state.now_ist", return_value=_ist(2026, 3, 10, 10, 0))

    _mark_sent("trade_key_abc")
    assert _is_already_sent("trade_key_abc") is True


# ── Market Hours ─────────────────────────────────────────────────────────────

def test_is_market_open_during_hours(mocker):
    from state import is_market_open
    mocker.patch("state.now_ist", return_value=_ist(2026, 3, 10, 10, 0))
    assert is_market_open() is True


def test_is_market_open_before_open(mocker):
    from state import is_market_open
    mocker.patch("state.now_ist", return_value=_ist(2026, 3, 10, 9, 0))
    assert is_market_open() is False


def test_is_market_open_after_close(mocker):
    from state import is_market_open
    mocker.patch("state.now_ist", return_value=_ist(2026, 3, 10, 15, 31))
    assert is_market_open() is False


def test_is_market_open_on_weekend(mocker):
    from state import is_market_open
    # 2026-03-07 is a Saturday
    mocker.patch("state.now_ist", return_value=_ist(2026, 3, 7, 10, 0))
    assert is_market_open() is False


def test_is_market_open_on_nse_holiday(mocker):
    from state import is_market_open
    # 2026-04-14 is Ambedkar Jayanti (NSE holiday)
    mocker.patch("state.now_ist", return_value=_ist(2026, 4, 14, 10, 0))
    assert is_market_open() is False
