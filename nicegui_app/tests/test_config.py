"""Tests for config.py: holiday detection and trading day logic."""

import pytest
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")


def _date(year, month, day):
    return IST.localize(datetime(year, month, day, 10, 0))


# ── is_nse_holiday ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("year,month,day", [
    (2026, 1, 26),   # Republic Day
    (2026, 4, 3),    # Good Friday
    (2026, 4, 14),   # Ambedkar Jayanti
    (2026, 5, 1),    # Maharashtra Day
    (2025, 8, 15),   # Independence Day
])
def test_is_nse_holiday_true(year, month, day):
    from config import is_nse_holiday
    assert is_nse_holiday(_date(year, month, day)) is True


@pytest.mark.parametrize("year,month,day", [
    (2026, 3, 10),   # Normal Tuesday
    (2026, 3, 11),   # Normal Wednesday
    (2026, 3, 12),   # Normal Thursday
])
def test_is_nse_holiday_false(year, month, day):
    from config import is_nse_holiday
    assert is_nse_holiday(_date(year, month, day)) is False


# ── _is_trading_day ─────────────────────────────────────────────────────────

def test_is_trading_day_false_saturday():
    from config import _is_trading_day
    # 2026-03-07 is a Saturday
    assert _is_trading_day(_date(2026, 3, 7)) is False


def test_is_trading_day_false_sunday():
    from config import _is_trading_day
    # 2026-03-08 is a Sunday
    assert _is_trading_day(_date(2026, 3, 8)) is False


def test_is_trading_day_false_nse_holiday():
    from config import _is_trading_day
    # 2026-01-26 Republic Day — weekday but holiday
    assert _is_trading_day(_date(2026, 1, 26)) is False


def test_is_trading_day_true_weekday():
    from config import _is_trading_day
    # 2026-03-10 is a normal Tuesday
    assert _is_trading_day(_date(2026, 3, 10)) is True
