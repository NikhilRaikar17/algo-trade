"""
Shared mutable state: cache, dedup, telegram, market hours, API helper.
"""

import os
import json
import time
import threading
from datetime import timedelta

from config import (
    now_ist,
    _is_trading_day,
    is_nse_holiday,
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MIN,
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MIN,
    BOT_TOKEN,
    TELEGRAM_ENABLED,
    RECEIVER_CHAT_IDS,
    send_alert_to_all,
)

# ================= FILE-BASED DEDUP =================
_DEDUP_FILE = os.path.join(os.path.dirname(__file__), ".telegram_sent.json")


def _load_dedup():
    try:
        with open(_DEDUP_FILE, "r") as f:
            data = json.load(f)
        cutoff = (now_ist() - timedelta(days=3)).strftime("%Y-%m-%d")
        return {k: v for k, v in data.items() if k >= cutoff}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_dedup(data):
    with open(_DEDUP_FILE, "w") as f:
        json.dump(data, f)


def _is_already_sent(key):
    return key in _load_dedup()


def _mark_sent(key):
    data = _load_dedup()
    data[key] = now_ist().strftime("%Y-%m-%d %H:%M:%S")
    _save_dedup(data)


# ================= IN-MEMORY TRADE STORE =================
_trade_store = {}  # key -> {"active": [...], "completed": [...]}
_ltp_history = {}  # history for SMA trend


# ================= TRADE HISTORY (PERSISTENT) =================
_TRADE_HISTORY_FILE = os.path.join(os.path.dirname(__file__), ".trade_history.json")


def load_trade_history():
    """Load all persisted completed trades from disk."""
    try:
        with open(_TRADE_HISTORY_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_completed_trade(key, trade):
    """Persist a completed trade keyed by dedup key. Deduplicates and trims to 90 days."""
    try:
        history = load_trade_history()
        if any(r.get("key") == key for r in history):
            return
        record = {
            "key": key,
            "trade_date": trade.get("trade_date", now_ist().strftime("%Y-%m-%d")),
            "strategy": str(trade.get("strategy", "Unknown")),
            "signal": str(trade.get("signal", "")),
            "entry": float(trade.get("entry", 0)),
            "exit_price": float(trade.get("exit_price", 0)),
            "pnl": float(trade.get("pnl", 0)),
            "status": str(trade.get("status", "")),
        }
        history.append(record)
        cutoff = (now_ist() - timedelta(days=90)).strftime("%Y-%m-%d")
        history = [r for r in history if r.get("trade_date", "") >= cutoff]
        with open(_TRADE_HISTORY_FILE, "w") as f:
            json.dump(history, f)
    except Exception as e:
        print(f"  [trade_history] save failed: {e}")


# ================= TELEGRAM =================


def _send_telegram(message):
    if not TELEGRAM_ENABLED:
        print(f"  [telegram] disabled — skipping: {message[:80]}")
        return
    try:
        if BOT_TOKEN and RECEIVER_CHAT_IDS:
            send_alert_to_all(message, RECEIVER_CHAT_IDS, BOT_TOKEN)
    except Exception as e:
        print(f"  [telegram] failed: {e}")


# ================= MARKET HOURS =================


def is_market_open():
    now = now_ist()
    if not _is_trading_day(now):
        return False
    market_open = now.replace(
        hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0, microsecond=0
    )
    market_close = now.replace(
        hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MIN, second=0, microsecond=0
    )
    return market_open <= now <= market_close


def get_next_market_open():
    now = now_ist()
    target = now.replace(
        hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0, microsecond=0
    )
    if _is_trading_day(now) and now < target:
        return target
    days_ahead = 1
    while days_ahead < 30:
        next_day = now + timedelta(days=days_ahead)
        if _is_trading_day(next_day):
            return next_day.replace(
                hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0, microsecond=0
            )
        days_ahead += 1
    return (now + timedelta(days=1)).replace(
        hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0, microsecond=0
    )


# ================= API HELPER =================


_NO_RETRY_PHRASES = (
    "no data", "data not available", "invalid", "not found",
    "outside market hours", "no record",
)


def api_call(fn, *args, retries=3, delay=3, **kwargs):
    for attempt in range(retries):
        r = fn(*args, **kwargs)
        if isinstance(r, dict):
            err_data = r.get("data", {})
            if isinstance(err_data, dict):
                inner = err_data.get("data", {})
                if isinstance(inner, dict) and any(
                    "Too many" in str(v) for v in inner.values()
                ):
                    print(
                        f"  [rate limit] attempt {attempt+1}/{retries}, waiting {delay}s..."
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue
            if r.get("status") == "failure" and attempt < retries - 1:
                # Don't retry permanent "no data" errors — only transient ones
                remarks = str(r.get("remarks", "")).lower()
                err_msg = str(err_data).lower()
                if any(p in remarks or p in err_msg for p in _NO_RETRY_PHRASES):
                    return r
                # retries=1 means no retry loop — skip silently
                if retries == 1:
                    return r
                print(
                    f"  [api retry] attempt {attempt+1}/{retries}, waiting {delay}s..."
                )
                time.sleep(delay)
                delay *= 2
                continue
        return r
    return r


# ================= GLOBAL DATA CACHE =================
_data_cache = {}  # key -> {"data": ..., "time": float}
_cache_lock = threading.Lock()
CACHE_TTL = 90  # seconds before cache is considered stale

# Per-key fetch locks: prevents concurrent threads from making duplicate API calls
# for the same key. Second caller waits for the first to finish, then hits cache.
_fetch_locks: dict[str, threading.Lock] = {}
_fetch_locks_lock = threading.Lock()


def _get_fetch_lock(key: str) -> threading.Lock:
    with _fetch_locks_lock:
        if key not in _fetch_locks:
            _fetch_locks[key] = threading.Lock()
        return _fetch_locks[key]


def _cache_get(key):
    with _cache_lock:
        entry = _data_cache.get(key)
        if entry and (time.time() - entry["time"]) < CACHE_TTL:
            return entry["data"]
    return None


def _cache_set(key, data):
    with _cache_lock:
        _data_cache[key] = {"data": data, "time": time.time()}


def _cache_get_stable(key):
    """Return cached data regardless of TTL — for data that should not change within a trading day."""
    with _cache_lock:
        entry = _data_cache.get(key)
        if entry:
            return entry["data"]
    return None
