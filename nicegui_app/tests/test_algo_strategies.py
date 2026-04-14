"""Tests for algo_strategies.py: swing detection, ABCD patterns, RSI+SMA signals."""

import pytest
import pytz
import pandas as pd
from datetime import datetime, timedelta

IST = pytz.timezone("Asia/Kolkata")


# ── find_swing_points ────────────────────────────────────────────────────────

def test_find_swing_points_highs_and_lows(sample_ohlcv_df):
    from algo_strategies import find_swing_points
    swings = find_swing_points(sample_ohlcv_df, order=3)

    types = [s["type"] for s in swings]
    indices = [s["index"] for s in swings]

    # Bar 3 is a swing low (A), bar 7 a swing high (B),
    # bar 12 a swing low (C), bar 18 a swing high (D)
    assert 3 in indices
    assert 7 in indices
    assert 12 in indices
    assert 18 in indices

    swing_by_index = {s["index"]: s for s in swings}
    assert swing_by_index[3]["type"] == "low"
    assert swing_by_index[7]["type"] == "high"
    assert swing_by_index[12]["type"] == "low"
    assert swing_by_index[18]["type"] == "high"


# ── detect_abcd_patterns — Bullish ──────────────────────────────────────────

def test_detect_abcd_bullish_pattern(sample_ohlcv_df):
    from algo_strategies import find_swing_points, detect_abcd_patterns
    swings = find_swing_points(sample_ohlcv_df, order=3)
    patterns = detect_abcd_patterns(swings, tolerance=0.15)

    bullish = [p for p in patterns if p["type"] == "Bullish"]
    assert len(bullish) >= 1

    p = bullish[0]
    assert p["entry"] == pytest.approx(126.0, abs=1.0)
    assert 0.618 - 0.15 <= p["BC_retrace"] <= 0.786 + 0.15
    assert 1.0 - 0.15 <= p["CD_AB_ratio"] <= 1.618 + 0.15
    assert p["signal"] == "SELL CE / BUY PE at D"


def test_detect_abcd_bullish_entry_stop_loss_target(sample_ohlcv_df):
    from algo_strategies import find_swing_points, detect_abcd_patterns
    swings = find_swing_points(sample_ohlcv_df, order=3)
    patterns = detect_abcd_patterns(swings, tolerance=0.15)

    bullish = [p for p in patterns if p["type"] == "Bullish"][0]
    # For Bullish: entry=D, stop_loss=C, target=D - 2*(D-C)
    assert bullish["stop_loss"] == pytest.approx(bullish["C"]["price"], abs=0.01)
    expected_target = bullish["entry"] - 2 * (bullish["entry"] - bullish["C"]["price"])
    assert bullish["target"] == pytest.approx(expected_target, abs=0.01)


# ── detect_abcd_patterns — Bearish ──────────────────────────────────────────

def test_detect_abcd_bearish_pattern():
    """Bearish: high→low→high→low swing sequence."""
    from algo_strategies import detect_abcd_patterns

    base = IST.localize(datetime(2026, 3, 10, 9, 15))
    # A=high(120), B=low(100) → AB=20
    # C=high(114) → BC=14, BC/AB=0.70
    # D=low(94)   → CD=20, CD/AB=1.0
    swings = [
        {"index": 0, "type": "high", "price": 120.0, "time": base},
        {"index": 3, "type": "low",  "price": 100.0, "time": base + timedelta(minutes=45)},
        {"index": 6, "type": "high", "price": 114.0, "time": base + timedelta(minutes=90)},
        {"index": 9, "type": "low",  "price":  94.0, "time": base + timedelta(minutes=135)},
    ]
    patterns = detect_abcd_patterns(swings, tolerance=0.15)
    bearish = [p for p in patterns if p["type"] == "Bearish"]
    assert len(bearish) == 1
    assert bearish[0]["signal"] == "BUY CE / SELL PE at D"
    assert bearish[0]["entry"] == pytest.approx(94.0)


@pytest.mark.parametrize("bc_ratio,cd_ab_ratio", [
    (0.40, 1.0),    # BC/AB too low
    (0.95, 1.0),    # BC/AB too high
    (0.70, 0.70),   # CD/AB too low
    (0.70, 2.0),    # CD/AB too high
])
def test_detect_abcd_no_pattern_out_of_ratio(bc_ratio, cd_ab_ratio):
    from algo_strategies import detect_abcd_patterns
    base = IST.localize(datetime(2026, 3, 10, 9, 15))
    ab = 20.0
    bc = ab * bc_ratio
    cd = ab * cd_ab_ratio
    a_price = 100.0
    b_price = a_price + ab
    c_price = b_price - bc
    d_price = c_price + cd
    swings = [
        {"index": 0, "type": "low",  "price": a_price, "time": base},
        {"index": 3, "type": "high", "price": b_price, "time": base + timedelta(minutes=45)},
        {"index": 6, "type": "low",  "price": c_price, "time": base + timedelta(minutes=90)},
        {"index": 9, "type": "high", "price": d_price, "time": base + timedelta(minutes=135)},
    ]
    patterns = detect_abcd_patterns(swings, tolerance=0.15)
    assert patterns == []


# ── RSI+SMA helpers ──────────────────────────────────────────────────────────

def _make_crossover_df(cross_direction="up", n_bars=60):
    """
    Build a synthetic OHLCV DataFrame that produces a clean SMA(9)/SMA(21) crossover.

    cross_direction="up"  → fast SMA crosses above slow SMA at last bar (BUY signal)
    cross_direction="down" → fast SMA crosses below slow SMA at last bar (SELL signal)
    """
    base = IST.localize(datetime(2026, 3, 10, 9, 15))
    times = [base + timedelta(minutes=15 * i) for i in range(n_bars)]

    if cross_direction == "up":
        # Declining prices (fast SMA < slow SMA), then sharp rise at the end
        closes = [100.0 - i * 0.1 for i in range(n_bars - 5)]
        closes += [closes[-1] + i * 1.5 for i in range(1, 6)]
    else:
        # Rising prices (fast SMA > slow SMA), then sharp drop at the end
        closes = [100.0 + i * 0.1 for i in range(n_bars - 5)]
        closes += [closes[-1] - i * 1.5 for i in range(1, 6)]

    df = pd.DataFrame({
        "timestamp": times,
        "open":  closes,
        "high":  [c + 0.5 for c in closes],
        "low":   [c - 0.5 for c in closes],
        "close": closes,
        "volume": [1000] * n_bars,
    })
    return df


# ── detect_rsi_sma_signals ───────────────────────────────────────────────────

def test_detect_rsi_sma_buy_signal():
    from algo_strategies import detect_rsi_sma_signals
    df = _make_crossover_df(cross_direction="up")
    signals, _ = detect_rsi_sma_signals(df)
    buy_signals = [s for s in signals if s["type"] == "Bullish"]
    assert len(buy_signals) >= 1
    s = buy_signals[-1]
    assert s["signal"] == "BUY CE — SMA crossover + RSI recovery"
    assert s["entry"] > 0
    assert s["target"] > s["entry"]   # 4% above entry
    assert s["stop_loss"] < s["entry"]  # 2% below entry


def test_detect_rsi_sma_sell_signal():
    from algo_strategies import detect_rsi_sma_signals
    df = _make_crossover_df(cross_direction="down")
    signals, _ = detect_rsi_sma_signals(df)
    sell_signals = [s for s in signals if s["type"] == "Bearish"]
    assert len(sell_signals) >= 1
    s = sell_signals[-1]
    assert s["signal"] == "BUY PE — SMA crossover + RSI overbought"
    assert s["stop_loss"] > s["entry"]   # 2% above entry
    assert s["target"] < s["entry"]      # 4% below entry


def test_detect_rsi_sma_returns_dataframe_with_indicators():
    from algo_strategies import detect_rsi_sma_signals
    df = _make_crossover_df()
    _, enriched = detect_rsi_sma_signals(df)
    assert "rsi" in enriched.columns
    assert "sma_fast" in enriched.columns
    assert "sma_slow" in enriched.columns
    assert enriched["rsi"].notna().any()
