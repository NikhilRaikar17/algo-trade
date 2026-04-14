"""
Shared pytest fixtures for the algotrading test suite.

Requires dev dependencies: uv sync --group dev
"""

import time
from datetime import datetime
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytz
import pytest

IST = pytz.timezone("Asia/Kolkata")


def _ist(year, month, day, hour=10, minute=0):
    """Helper: create an IST-aware datetime."""
    return IST.localize(datetime(year, month, day, hour, minute))


@pytest.fixture
def sample_ohlcv_df():
    """
    Synthetic 30-bar OHLCV DataFrame with IST timestamps.

    Bars 0-29, spaced 15 minutes apart starting at 09:15 on 2026-03-10
    (a normal trading weekday, not a holiday).

    Bars 3, 7, 12, 18 are crafted to form a Bullish ABCD swing sequence:
      A (low)  at bar 3,  price 100
      B (high) at bar 7,  price 120  → AB = 20
      C (low)  at bar 12, price 106  → BC = 14, BC/AB = 0.70 (in [0.618-0.15, 0.786+0.15])
      D (high) at bar 18, price 126  → CD = 20, CD/AB = 1.0  (in [1.0-0.15, 1.618+0.15])

    All other bars are neutral (open=close=110, high=112, low=108) except
    the swing bars which have exaggerated highs/lows to be detected by
    find_swing_points with order=3.
    """
    base = _ist(2026, 3, 10, 9, 15)
    from datetime import timedelta
    times = [base + timedelta(minutes=15 * i) for i in range(30)]

    opens  = [110.0] * 30
    closes = [110.0] * 30
    highs  = [112.0] * 30
    lows   = [108.0] * 30

    # Bar 3: swing LOW (A) — price dips to 100
    lows[3] = 100.0; highs[3] = 101.0; opens[3] = 101.0; closes[3] = 100.5

    # Bar 7: swing HIGH (B) — price peaks at 120
    highs[7] = 120.0; lows[7] = 119.0; opens[7] = 119.5; closes[7] = 119.8

    # Bar 12: swing LOW (C) — price dips to 106  (BC/AB = 14/20 = 0.70)
    lows[12] = 106.0; highs[12] = 107.0; opens[12] = 107.0; closes[12] = 106.5

    # Bar 18: swing HIGH (D) — price peaks at 126  (CD/AB = 20/20 = 1.0)
    highs[18] = 126.0; lows[18] = 125.0; opens[18] = 125.0; closes[18] = 125.5

    df = pd.DataFrame({
        "timestamp": times,
        "open":  opens,
        "high":  highs,
        "low":   lows,
        "close": closes,
        "volume": [1000] * 30,
    })
    return df


@pytest.fixture
def mock_dhan():
    """
    MagicMock replacing the dhanhq Dhan client.

    Pre-configured canned returns:
      .expiry_list() → success response with two expiry dates
      .intraday_minute_data() → success response with empty data list
    """
    m = MagicMock()
    m.expiry_list.return_value = {
        "status": "success",
        "data": ["2026-03-27", "2026-04-03"],
    }
    m.intraday_minute_data.return_value = {
        "status": "success",
        "data": {
            "open": [], "high": [], "low": [], "close": [],
            "volume": [], "timestamp": [],
        },
    }
    return m


@pytest.fixture
def freeze_ist(mocker):
    """
    Factory fixture. Call freeze_ist(module_name, year, month, day, hour, minute)
    to patch now_ist() in a given module namespace.

    Usage:
        def test_something(freeze_ist):
            freeze_ist("state", 2026, 3, 10, 10, 0)  # weekday, 10:00 IST
    """
    def _freeze(module_name, year, month, day, hour=10, minute=0):
        fixed = _ist(year, month, day, hour, minute)
        mocker.patch(f"{module_name}.now_ist", return_value=fixed)
        return fixed
    return _freeze
