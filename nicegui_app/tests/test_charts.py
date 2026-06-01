"""
Tests for charts.py: Plotly figure structure and float serialization safety.

Key constraint: NiceGUI uses orjson which rejects numpy.float64.
All float values in returned figures must be native Python float.
"""

import numpy as np
import pytest


def _all_floats_are_native(obj):
    """
    Recursively walk a dict/list/tuple structure.
    Returns True if every numeric float found is native Python float
    (not numpy.float64 or any other subclass).
    """
    if isinstance(obj, dict):
        return all(_all_floats_are_native(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return all(_all_floats_are_native(v) for v in obj)
    if type(obj) is float:          # exact type check — numpy.float64 fails here
        return True
    if isinstance(obj, float):      # catches numpy.float64 etc.
        return False                # numpy subclass — not native
    return True                     # int, str, None, bool — fine


# ── build_candlestick_with_abcd ──────────────────────────────────────────────

def test_candlestick_abcd_returns_plotly_structure(sample_ohlcv_df):
    from charts import build_candlestick_with_abcd
    from algo_strategies import find_swing_points, detect_abcd_patterns

    swings = find_swing_points(sample_ohlcv_df, order=3)
    patterns = detect_abcd_patterns(swings, tolerance=0.15)
    fig = build_candlestick_with_abcd(
        sample_ohlcv_df, swings, patterns,
        contract_name="NIFTY-TEST", current_price=110.0
    )
    d = fig.to_dict()
    assert "data" in d
    assert "layout" in d
    assert len(d["data"]) >= 1


def test_candlestick_abcd_no_numpy_floats(sample_ohlcv_df):
    from charts import build_candlestick_with_abcd
    from algo_strategies import find_swing_points, detect_abcd_patterns

    swings = find_swing_points(sample_ohlcv_df, order=3)
    patterns = detect_abcd_patterns(swings, tolerance=0.15)
    fig = build_candlestick_with_abcd(
        sample_ohlcv_df, swings, patterns,
        contract_name="NIFTY-TEST", current_price=110.0
    )
    d = fig.to_dict()
    assert _all_floats_are_native(d), (
        "Figure contains numpy.float64 values — orjson will reject them. "
        "Wrap with float() in charts.py."
    )


# ── build_candlestick_with_rsi_sma ───────────────────────────────────────────

def test_candlestick_rsi_sma_returns_plotly_structure(sample_ohlcv_df):
    from charts import build_candlestick_with_rsi_sma
    from algo_strategies import detect_rsi_sma_signals

    signals, enriched_df = detect_rsi_sma_signals(sample_ohlcv_df)
    fig, fig_rsi = build_candlestick_with_rsi_sma(sample_ohlcv_df, enriched_df, signals)
    d = fig.to_dict()
    d_rsi = fig_rsi.to_dict()
    assert "data" in d
    assert "layout" in d
    assert "data" in d_rsi
    assert "layout" in d_rsi


def test_candlestick_rsi_sma_no_numpy_floats(sample_ohlcv_df):
    from charts import build_candlestick_with_rsi_sma
    from algo_strategies import detect_rsi_sma_signals

    signals, enriched_df = detect_rsi_sma_signals(sample_ohlcv_df)
    fig, fig_rsi = build_candlestick_with_rsi_sma(sample_ohlcv_df, enriched_df, signals)
    d = fig.to_dict()
    d_rsi = fig_rsi.to_dict()
    assert _all_floats_are_native(d), (
        "Figure contains numpy.float64 values — orjson will reject them. "
        "Wrap with float() in charts.py."
    )
    assert _all_floats_are_native(d_rsi), (
        "RSI figure contains numpy.float64 values — orjson will reject them."
    )
