"""EMA 100 / SMA 100 / SMA 200 price crosses and the EMA 50/100 cross: signals, warm-up over earlier
days (live and backtest), and each strategy registered everywhere a strategy has to be."""

import numpy as np
import pandas as pd
import pytest

import live_candles as lc
from algo_strategies import MA_STRATEGIES, backtest_ma_window, detect_ma_signals, ma_lines, ma_warmup

IST = "Asia/Kolkata"


def _bars(closes, start="2026-10-20 09:15", freq="5min"):
    """Bars inside market hours only, so 72 five-minute bars a day."""
    ts, day = [], pd.Timestamp(start, tz=IST)
    while len(ts) < len(closes):
        if day.weekday() < 5:
            ts += list(pd.date_range(day.replace(hour=9, minute=15), day.replace(hour=14, minute=50), freq=freq))
        day += pd.Timedelta(days=1)
    ts = ts[:len(closes)]
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"timestamp": ts, "open": c, "high": c + 0.5, "low": c - 0.5, "close": c})


def test_price_cross_needs_the_full_period_then_signals_both_ways():
    closes = [100.0] * 220 + [104.0] * 5 + [96.0] * 5
    signals, df = detect_ma_signals(_bars(closes), "sma200")
    assert df["sma200"].isna().sum() == 199                      # nothing before 200 bars
    assert [s["type"] for s in signals] == ["Bullish", "Bearish"]
    buy = signals[0]
    assert buy["signal"] == "BUY — Price crosses above SMA 200"
    assert buy["entry"] == 104.0 and buy["target"] == pytest.approx(106.08) and buy["stop_loss"] == pytest.approx(102.96)
    assert "sma200" in buy


def test_ema_50_over_100_cross():
    closes = list(np.linspace(120, 100, 150)) + list(np.linspace(100, 130, 80))
    signals, _ = detect_ma_signals(_bars(closes), "ema50x100")
    assert signals and signals[0]["type"] == "Bullish"
    assert signals[0]["signal"] == "BUY — EMA 50 crosses above EMA 100"
    assert {"ema50", "ema100"} <= set(signals[0])
    assert ma_lines("ema50x100") == [("ema50", "EMA 50"), ("ema100", "EMA 100")] and ma_warmup("ema50x100") == 100


def test_live_bars_keep_earlier_days_for_warm_up(monkeypatch):
    monkeypatch.setattr(lc, "_bars", {})
    monkeypatch.setattr(lc, "_seeded", {})
    monkeypatch.setattr(lc, "_last", {})
    monkeypatch.setattr(lc, "_history", {})
    rest = _bars([100.0] * 300, start="2026-10-22 09:15")            # Thu, Fri, Mon … through Tue
    now = pd.Timestamp("2026-10-27 10:02", tz=IST).to_pydatetime()
    lc.seed("1", rest, now=now)
    today = lc.candles("1", now=now)
    full = lc.candles("1", now=now, history=True)
    assert len(today) and all(t.date() == now.date() for t in today["timestamp"])
    assert len(full) > len(today) and full["timestamp"].is_monotonic_increasing
    assert full.iloc[-len(today):]["timestamp"].tolist() == today["timestamp"].tolist()


def test_engine_keeps_only_todays_moving_average_signals():
    from trading_engine import detect_signals
    closes = [100.0] * 270 + [96.0] * 5 + [104.0] * 15         # 68 bars a day: down on day 4, up on day 5
    full = _bars(closes)
    day = full["timestamp"].iloc[-1].date()
    today = full[full["timestamp"].dt.date == day].reset_index(drop=True)
    every = detect_ma_signals(full, "sma200")[0]
    kept = detect_signals("sma200", today, full)
    assert len(every) > len(kept) >= 1 and all(s["time"].date() == day for s in kept)
    assert detect_signals("sma200", today) == detect_ma_signals(today, "sma200")[0] == []   # today alone is too short


def test_backtest_scores_only_the_window():
    closes = [100.0] * 270 + [96.0] * 5 + [104.0] * 15
    full = _bars(closes, freq="15min")
    since = full["timestamp"].iloc[272]                           # after the cross down at bar 270
    signals, _, trades = backtest_ma_window(full, "sma200", since)
    assert [s["type"] for s in signals] == ["Bullish"] and signals[0]["time"] >= since and len(trades) == 1


def test_every_strategy_is_registered_everywhere():
    from auth import _SEED_STRATEGIES
    from config import LIVE_STRATEGY_ENABLED, STRATEGY_NAMES
    from pages import BACKTEST_PAGES
    from pages.backtest_pnl_tab import _RUNNERS
    from pages.strategies import _STRATEGY_INFO
    from trading_engine import _STRATEGY_RUNNERS
    for key in MA_STRATEGIES:
        assert key in STRATEGY_NAMES and key in LIVE_STRATEGY_ENABLED and key in _STRATEGY_RUNNERS
        assert key in BACKTEST_PAGES and key in _STRATEGY_INFO and key in {k for k, _, _ in _RUNNERS}
        seed = {k: short for k, _, short, _ in _SEED_STRATEGIES}
        assert seed[key] == dict((k, n) for k, n, _ in _RUNNERS)[key]   # backtest trades carry the short name
