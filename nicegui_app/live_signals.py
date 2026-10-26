"""
live_signals.py — today's live signals for the Trade Desk and Trade Replay pages.

Source of truth is the trading engine's in-memory _trade_store (pnl.collect_all_trades).
When the engine has nothing (app restarted, or after the close — it only scans in market
hours) today's signals are rebuilt from today's 5-minute candles with the engine's own
detectors. The rebuild is read-only: no Telegram alerts, nothing written to trade history.

Blocking (Dhan calls): call get_today_signals() from a worker thread, not the UI loop.
"""

import threading
import time as _time

from config import STRATEGY_NAMES, now_ist
from data import _fetch_any_stock_candles
from db import get_active_top_stocks
from pnl import collect_all_trades
from strategy_registry import get_live_strategy_keys
from trade_desk import signal_bar_time

SOURCE_ENGINE = "live engine"
SOURCE_REBUILT = "rebuilt from today's candles (engine not scanning: restarted or market closed)"

_CACHE_SECONDS = 60
_cache = {"at": 0.0, "value": None}
_lock = threading.Lock()


def _scan_today():
    """Rebuild today's live signals from today's 5-minute candles.
    Status comes from walking the bars after each signal bar: stop checked before target."""
    from trading_engine import _STRATEGY_RUNNERS  # the engine's own detectors

    today = now_ist().date()
    live_keys = get_live_strategy_keys()
    active, completed = [], []
    for stock in get_active_top_stocks():
        candles = _fetch_any_stock_candles(stock["security_id"], interval=5)
        _time.sleep(0.35)  # Dhan rate limit
        if candles is None or candles.empty:
            continue
        candles = candles[candles["timestamp"].dt.date == today].reset_index(drop=True)
        if candles.empty:
            continue
        for key in live_keys:
            detect, _ = _STRATEGY_RUNNERS[key]
            try:
                signals = detect(candles)
            except Exception:
                continue
            for sig in signals:
                t = dict(sig, strategy=STRATEGY_NAMES.get(key, key), symbol=stock["name"])
                ts = signal_bar_time(t)
                if ts is None:
                    continue
                buy = t["target"] > t["entry"]
                after = candles[candles["timestamp"] > ts]
                outcome = None
                for hi, lo in zip(after["high"], after["low"]):
                    if (lo <= t["stop_loss"]) if buy else (hi >= t["stop_loss"]):
                        outcome = ("SL Hit", t["stop_loss"])
                        break
                    if (hi >= t["target"]) if buy else (lo <= t["target"]):
                        outcome = ("Target Hit", t["target"])
                        break
                if outcome:
                    t["status"], t["exit_price"] = outcome
                    completed.append(t)
                else:
                    last = float(candles["close"].iloc[-1])
                    t["unrealized_pnl"] = (last - t["entry"]) if buy else (t["entry"] - last)
                    active.append(t)
    return active, completed


def get_today_signals() -> tuple[list[dict], list[dict], str]:
    """(active, completed, source). Engine memory first; otherwise a rebuild cached for a minute
    so the Trade Desk and Trade Replay pages don't each re-scan every stock."""
    active, completed = collect_all_trades()
    if active or completed:
        return active, completed, SOURCE_ENGINE
    with _lock:
        if _cache["value"] is None or _time.time() - _cache["at"] > _CACHE_SECONDS:
            _cache["value"] = _scan_today()
            _cache["at"] = _time.time()
        active, completed = _cache["value"]
    return active, completed, SOURCE_REBUILT
