"""
Option Chain NiceGUI App
------------------------
NIFTY & BANKNIFTY option chain with ABCD and RSI+SMA algo trading.
Run:  cd nicegui_app && uv run python main.py
"""

import os
import sys
import json
import time
import asyncio
import threading
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from dhanhq import dhanhq
import plotly.graph_objects as go
import pytz
from nicegui import ui, app, context

# ================= PATH SETUP =================
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dhan_services.telegram import send_alert_to_all

# ================= TIMEZONE =================
IST = pytz.timezone("Asia/Kolkata")


def now_ist():
    return datetime.now(IST)


# ================= NSE HOLIDAYS (2025-2026) =================
NSE_HOLIDAYS = {
    "2025-02-26",
    "2025-03-14",
    "2025-03-31",
    "2025-04-10",
    "2025-04-14",
    "2025-04-18",
    "2025-05-01",
    "2025-06-07",
    "2025-08-15",
    "2025-08-16",
    "2025-08-27",
    "2025-10-02",
    "2025-10-21",
    "2025-10-22",
    "2025-11-05",
    "2025-12-25",
    "2026-01-26",
    "2026-02-17",
    "2026-03-03",
    "2026-03-20",
    "2026-03-30",
    "2026-04-03",
    "2026-04-14",
    "2026-05-01",
    "2026-05-28",
    "2026-08-15",
    "2026-08-18",
    "2026-10-02",
    "2026-10-10",
    "2026-10-29",
    "2026-11-25",
    "2026-12-25",
}


def is_nse_holiday(dt=None):
    if dt is None:
        dt = now_ist()
    return dt.strftime("%Y-%m-%d") in NSE_HOLIDAYS


def _is_trading_day(dt=None):
    if dt is None:
        dt = now_ist()
    return dt.weekday() <= 4 and not is_nse_holiday(dt)


# ================= ENV =================
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)

CLIENT_ID = os.getenv("DHAN_CLIENT_CODE")
ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID")
dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

BOT_TOKEN = os.getenv("DHAN_BOT_TOKEN")
RECEIVER_CHAT_IDS = ["8272803637", "1623717769"]

# ================= CONFIG =================
REFRESH_SECONDS = 120
SMA_PERIOD = 5
EXPIRY_ROLLOVER_HOUR = 15
MARKET_OPEN_HOUR, MARKET_OPEN_MIN = 9, 15
MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN = 15, 30

RSI_PERIOD = 14
SMA_FAST = 9
SMA_SLOW = 21
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

INDICES = {
    "NIFTY": {
        "scrip": 13,
        "segment": "IDX_I",
        "strike_step": 50,
        "strike_range": 500,
        "name_prefix": "NIFTY",
    },
    "BANKNIFTY": {
        "scrip": 25,
        "segment": "IDX_I",
        "strike_step": 100,
        "strike_range": 1000,
        "name_prefix": "BANKNIFTY",
    },
}

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
# NiceGUI runs as a persistent server, so we use module-level dicts instead of session_state
_trade_store = {}  # key -> {"active": [...], "completed": [...]}
_ltp_history = {}  # history for SMA trend


# ================= TELEGRAM =================


def _send_telegram(message):
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
                print(
                    f"  [api retry] attempt {attempt+1}/{retries}, waiting {delay}s..."
                )
                time.sleep(delay)
                delay *= 2
                continue
        return r
    return r


# ================= GLOBAL DATA CACHE =================
# Fetched once, shared across all browser clients
_data_cache = {}  # key -> {"data": ..., "time": float}
_cache_lock = threading.Lock()
CACHE_TTL = 90  # seconds before cache is considered stale


def _cache_get(key):
    with _cache_lock:
        entry = _data_cache.get(key)
        if entry and (time.time() - entry["time"]) < CACHE_TTL:
            return entry["data"]
    return None


def _cache_set(key, data):
    with _cache_lock:
        _data_cache[key] = {"data": data, "time": time.time()}


# ================= DATA FUNCTIONS =================


def get_expiries(scrip, segment, count=3, for_algo=False):
    cache_key = f"expiries:{scrip}:{segment}:{for_algo}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached[:count]

    r = api_call(dhan.expiry_list, scrip, segment)
    if r.get("status") != "success":
        raise RuntimeError(f"expiry_list failed: {r}")
    data = r["data"]
    if isinstance(data, dict):
        data = data.get("data", data)
    if isinstance(data, dict):
        data = next(iter(data.values()))

    ist_now = now_ist()
    today = ist_now.date()
    all_future = sorted(
        d
        for d in data
        if isinstance(d, str) and datetime.strptime(d, "%Y-%m-%d").date() >= today
    )

    if for_algo:
        filtered = []
        for d in all_future:
            exp_date = datetime.strptime(d, "%Y-%m-%d").date()
            if exp_date == today and ist_now.hour >= EXPIRY_ROLLOVER_HOUR:
                continue
            if exp_date < today:
                continue
            filtered.append(d)
        expiries = filtered
    else:
        expiries = [
            d for d in all_future if datetime.strptime(d, "%Y-%m-%d").date() > today
        ]

    if not expiries:
        raise RuntimeError("No future expiries found.")
    _cache_set(cache_key, expiries)
    return expiries[:count]


def fetch_option_chain(scrip, segment, expiry):
    cache_key = f"oc:{scrip}:{segment}:{expiry}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    r = api_call(dhan.option_chain, scrip, segment, expiry)
    if r.get("status") != "success":
        raise RuntimeError(f"option_chain failed: {r}")
    inner = r["data"]["data"]
    spot = round(float(inner["last_price"]), 2)
    oc = inner["oc"]

    rows = []
    for strike_str, sides in oc.items():
        strike = float(strike_str)
        for opt_type, key in [("CE", "ce"), ("PE", "pe")]:
            info = sides.get(key, {})
            if not info:
                continue
            greeks = info.get("greeks", {})
            rows.append(
                {
                    "Strike": strike,
                    "Type": opt_type,
                    "LTP": round(float(info.get("last_price", 0)), 2),
                    "IV (%)": round(float(info.get("implied_volatility", 0)), 2),
                    "Delta": round(float(greeks.get("delta", 0)), 4),
                    "Gamma": round(float(greeks.get("gamma", 0)), 6),
                    "Theta": round(float(greeks.get("theta", 0)), 4),
                    "Vega": round(float(greeks.get("vega", 0)), 4),
                }
            )
    result = (spot, pd.DataFrame(rows))
    _cache_set(cache_key, result)
    return result


def fetch_option_chain_raw(scrip, segment, expiry):
    cache_key = f"oc_raw:{scrip}:{segment}:{expiry}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    r = api_call(dhan.option_chain, scrip, segment, expiry)
    if r.get("status") != "success":
        raise RuntimeError(f"option_chain failed: {r}")
    result = r["data"]["data"]
    _cache_set(cache_key, result)
    return result


def build_name_column(df, expiry, prefix):
    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
    exp_tag = exp_date.strftime("%d%b").upper()
    df = df.copy()
    df.insert(
        0,
        "Name",
        df.apply(
            lambda r: f"{prefix} {exp_tag} {int(r['Strike'])} {r['Type']}", axis=1
        ),
    )
    return df


def filter_and_split(df, atm, strike_range):
    lower = atm - strike_range
    upper = atm + strike_range
    df = df[(df["Strike"] >= lower) & (df["Strike"] <= upper)].copy()
    df = df.sort_values("Strike").reset_index(drop=True)
    ce = df[df["Type"] == "CE"].drop(columns=["Type"]).reset_index(drop=True)
    pe = df[df["Type"] == "PE"].drop(columns=["Type"]).reset_index(drop=True)
    return ce, pe


def add_trend(df, index_name, expiry, opt_type):
    history_key = f"history_{index_name}_{expiry}_{opt_type}"
    if history_key not in _ltp_history:
        _ltp_history[history_key] = {}
    history = _ltp_history[history_key]

    trends = []
    sma_values = []
    for _, row in df.iterrows():
        strike = row["Strike"]
        ltp = row["LTP"]
        if strike not in history:
            history[strike] = []
        history[strike].append(ltp)
        history[strike] = history[strike][-SMA_PERIOD:]

        prices = history[strike]
        if len(prices) < SMA_PERIOD:
            trends.append("—")
            sma_values.append(None)
        else:
            sma = sum(prices) / SMA_PERIOD
            sma_values.append(round(sma, 2))
            if ltp > sma:
                trends.append("UP")
            elif ltp < sma:
                trends.append("DOWN")
            else:
                trends.append("FLAT")
    df = df.copy()
    df["SMA"] = sma_values
    df["Trend"] = trends
    return df


def fetch_5min_candles(security_id):
    today = now_ist().strftime("%Y-%m-%d")
    from_date = (pd.Timestamp(now_ist().date()) - pd.Timedelta(days=5)).strftime(
        "%Y-%m-%d"
    )
    r = api_call(
        dhan.intraday_minute_data,
        str(security_id),
        "NSE_FNO",
        "OPTIDX",
        from_date,
        today,
        interval=5,
    )
    if r.get("status") != "success":
        return pd.DataFrame()
    d = r["data"]
    df = pd.DataFrame(
        {
            "timestamp": d.get("timestamp", []),
            "open": d.get("open", []),
            "high": d.get("high", []),
            "low": d.get("low", []),
            "close": d.get("close", []),
            "volume": d.get("volume", []),
        }
    )
    if not df.empty:
        df["timestamp"] = pd.to_datetime(
            df["timestamp"], unit="s", utc=True
        ).dt.tz_convert("Asia/Kolkata")
    return df


# ================= PATTERN DETECTION =================


def find_swing_points(df, order=3):
    swings = []
    highs = df["high"].values
    lows = df["low"].values
    for i in range(order, len(df) - order):
        if all(highs[i] >= highs[i - j] for j in range(1, order + 1)) and all(
            highs[i] >= highs[i + j] for j in range(1, order + 1)
        ):
            swings.append(
                {
                    "index": i,
                    "type": "high",
                    "price": highs[i],
                    "time": df["timestamp"].iloc[i],
                }
            )
        if all(lows[i] <= lows[i - j] for j in range(1, order + 1)) and all(
            lows[i] <= lows[i + j] for j in range(1, order + 1)
        ):
            swings.append(
                {
                    "index": i,
                    "type": "low",
                    "price": lows[i],
                    "time": df["timestamp"].iloc[i],
                }
            )
    return sorted(swings, key=lambda s: s["index"])


def detect_abcd_patterns(swings, tolerance=0.15):
    patterns = []
    for i in range(len(swings) - 3):
        a, b, c, d = swings[i], swings[i + 1], swings[i + 2], swings[i + 3]
        if (
            a["type"] == "low"
            and b["type"] == "high"
            and c["type"] == "low"
            and d["type"] == "high"
        ):
            ab = b["price"] - a["price"]
            bc = b["price"] - c["price"]
            cd = d["price"] - c["price"]
            if ab <= 0:
                continue
            bc_ratio = bc / ab
            cd_ab_ratio = cd / ab
            if (0.618 - tolerance) <= bc_ratio <= (0.786 + tolerance) and (
                1.0 - tolerance
            ) <= cd_ab_ratio <= (1.618 + tolerance):
                patterns.append(
                    {
                        "type": "Bullish",
                        "A": a,
                        "B": b,
                        "C": c,
                        "D": d,
                        "BC_retrace": round(bc_ratio, 3),
                        "CD_AB_ratio": round(cd_ab_ratio, 3),
                        "entry": d["price"],
                        "target": d["price"] + ab,
                        "stop_loss": c["price"],
                        "signal": "SELL CE / BUY PE at D",
                    }
                )
        if (
            a["type"] == "high"
            and b["type"] == "low"
            and c["type"] == "high"
            and d["type"] == "low"
        ):
            ab = a["price"] - b["price"]
            bc = c["price"] - b["price"]
            cd = c["price"] - d["price"]
            if ab <= 0:
                continue
            bc_ratio = bc / ab
            cd_ab_ratio = cd / ab
            if (0.618 - tolerance) <= bc_ratio <= (0.786 + tolerance) and (
                1.0 - tolerance
            ) <= cd_ab_ratio <= (1.618 + tolerance):
                patterns.append(
                    {
                        "type": "Bearish",
                        "A": a,
                        "B": b,
                        "C": c,
                        "D": d,
                        "BC_retrace": round(bc_ratio, 3),
                        "CD_AB_ratio": round(cd_ab_ratio, 3),
                        "entry": d["price"],
                        "target": d["price"] - ab,
                        "stop_loss": c["price"],
                        "signal": "BUY CE / SELL PE at D",
                    }
                )
    return patterns


def _pattern_key(p):
    return f"{p['A']['time']}_{p['D']['time']}_{p['type']}"


def classify_trades(patterns, current_price, contract_name=""):
    active = []
    completed = []
    for p in patterns:
        entry = p["entry"]
        target = p["target"]
        sl = p["stop_loss"]
        key = _pattern_key(p)
        active_key = f"abcd_active_{key}"
        completed_key = f"abcd_closed_{key}"

        if p["type"] == "Bullish":
            pnl = entry - current_price
            if current_price <= target or current_price >= sl:
                p["exit_price"] = current_price
                p["pnl"] = round(pnl, 2)
                p["status"] = "Target Hit" if current_price <= target else "SL Hit"
                completed.append(p)
                if not _is_already_sent(completed_key):
                    _mark_sent(completed_key)
                    emoji = "+" if p["pnl"] > 0 else ""
                    _send_telegram(
                        f"TRADE CLOSED | {contract_name}\nPattern: {p['type']} ABCD\nSignal: {p['signal']}\nEntry: {entry:.2f} | Exit: {current_price:.2f}\nPnL: {emoji}{p['pnl']:.2f}\nStatus: {p['status']}"
                    )
            else:
                p["unrealized_pnl"] = round(pnl, 2)
                active.append(p)
                if not _is_already_sent(active_key):
                    _mark_sent(active_key)
                    _send_telegram(
                        f"NEW TRADE | {contract_name}\nPattern: {p['type']} ABCD\nSignal: {p['signal']}\nEntry (D): {entry:.2f}\nTarget: {target:.2f} | SL: {sl:.2f}\nBC Retrace: {p['BC_retrace']} | CD/AB: {p['CD_AB_ratio']}"
                    )
        else:
            pnl = current_price - entry
            if current_price >= target or current_price <= sl:
                p["exit_price"] = current_price
                p["pnl"] = round(pnl, 2)
                p["status"] = "Target Hit" if current_price >= target else "SL Hit"
                completed.append(p)
                if not _is_already_sent(completed_key):
                    _mark_sent(completed_key)
                    emoji = "+" if p["pnl"] > 0 else ""
                    _send_telegram(
                        f"TRADE CLOSED | {contract_name}\nPattern: {p['type']} ABCD\nSignal: {p['signal']}\nEntry: {entry:.2f} | Exit: {current_price:.2f}\nPnL: {emoji}{p['pnl']:.2f}\nStatus: {p['status']}"
                    )
            else:
                p["unrealized_pnl"] = round(pnl, 2)
                active.append(p)
                if not _is_already_sent(active_key):
                    _mark_sent(active_key)
                    _send_telegram(
                        f"NEW TRADE | {contract_name}\nPattern: {p['type']} ABCD\nSignal: {p['signal']}\nEntry (D): {entry:.2f}\nTarget: {target:.2f} | SL: {sl:.2f}\nBC Retrace: {p['BC_retrace']} | CD/AB: {p['CD_AB_ratio']}"
                    )
    return active, completed


# ================= RSI + SMA =================


def compute_rsi(series, period=RSI_PERIOD):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_sma(series, period):
    return series.rolling(window=period, min_periods=period).mean()


def detect_rsi_sma_signals(candles):
    df = candles.copy()
    df["rsi"] = compute_rsi(df["close"])
    df["sma_fast"] = compute_sma(df["close"], SMA_FAST)
    df["sma_slow"] = compute_sma(df["close"], SMA_SLOW)
    df = df.dropna().reset_index(drop=True)
    if len(df) < 2:
        return [], df
    signals = []
    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        curr = df.iloc[i]
        if (
            prev["sma_fast"] <= prev["sma_slow"]
            and curr["sma_fast"] > curr["sma_slow"]
            and curr["rsi"] > RSI_OVERSOLD
        ):
            target = curr["close"] * 1.02
            sl = curr["close"] * 0.98
            signals.append(
                {
                    "type": "Bullish",
                    "signal": "BUY CE — SMA crossover + RSI recovery",
                    "entry": round(curr["close"], 2),
                    "target": round(target, 2),
                    "stop_loss": round(sl, 2),
                    "time": curr["timestamp"],
                    "rsi": round(curr["rsi"], 2),
                    "sma_fast": round(curr["sma_fast"], 2),
                    "sma_slow": round(curr["sma_slow"], 2),
                }
            )
        if (
            prev["sma_fast"] >= prev["sma_slow"]
            and curr["sma_fast"] < curr["sma_slow"]
            and curr["rsi"] < RSI_OVERBOUGHT
        ):
            target = curr["close"] * 0.98
            sl = curr["close"] * 1.02
            signals.append(
                {
                    "type": "Bearish",
                    "signal": "BUY PE — SMA crossover + RSI overbought",
                    "entry": round(curr["close"], 2),
                    "target": round(target, 2),
                    "stop_loss": round(sl, 2),
                    "time": curr["timestamp"],
                    "rsi": round(curr["rsi"], 2),
                    "sma_fast": round(curr["sma_fast"], 2),
                    "sma_slow": round(curr["sma_slow"], 2),
                }
            )
    return signals, df


def _rsi_signal_key(s):
    return f"rsi_{s['time']}_{s['type']}"


def classify_rsi_trades(signals, current_price, contract_name=""):
    active = []
    completed = []
    for s in signals:
        entry = s["entry"]
        target = s["target"]
        sl = s["stop_loss"]
        key = _rsi_signal_key(s)
        active_key = f"rsi_active_{key}"
        completed_key = f"rsi_closed_{key}"
        if s["type"] == "Bullish":
            pnl = current_price - entry
            hit_target = current_price >= target
            hit_sl = current_price <= sl
        else:
            pnl = entry - current_price
            hit_target = current_price <= target
            hit_sl = current_price >= sl
        pnl = round(pnl, 2)
        if hit_target or hit_sl:
            s["exit_price"] = current_price
            s["pnl"] = pnl
            s["status"] = "Target Hit" if hit_target else "SL Hit"
            completed.append(s)
            if not _is_already_sent(completed_key):
                _mark_sent(completed_key)
                emoji = "+" if pnl > 0 else ""
                _send_telegram(
                    f"TRADE CLOSED [RSI+SMA] | {contract_name}\nSignal: {s['signal']}\nEntry: {entry:.2f} | Exit: {current_price:.2f}\nPnL: {emoji}{pnl:.2f}\nStatus: {s['status']}"
                )
        else:
            s["unrealized_pnl"] = pnl
            active.append(s)
            if not _is_already_sent(active_key):
                _mark_sent(active_key)
                _send_telegram(
                    f"NEW TRADE [RSI+SMA] | {contract_name}\nSignal: {s['signal']}\nEntry: {entry:.2f}\nTarget: {target:.2f} | SL: {sl:.2f}\nRSI: {s['rsi']} | SMA {SMA_FAST}/{SMA_SLOW}: {s['sma_fast']}/{s['sma_slow']}"
                )
    return active, completed


# ================= P&L COLLECTION =================


def collect_all_trades():
    all_active = []
    all_completed = []
    for key, val in _trade_store.items():
        if isinstance(val, dict) and "active" in val and "completed" in val:
            strategy = (
                "ABCD"
                if key.startswith("abcd_")
                else "RSI+SMA" if key.startswith("rsi_") else "Unknown"
            )
            for t in val["active"]:
                t["strategy"] = strategy
                all_active.append(t)
            for t in val["completed"]:
                t["strategy"] = strategy
                all_completed.append(t)
    return all_active, all_completed


def send_daily_pnl_summary():
    now = now_ist()
    today_str = now.strftime("%Y-%m-%d")
    summary_key = f"daily_pnl_{today_str}"
    if not _is_trading_day(now):
        return
    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
        return
    if _is_already_sent(summary_key):
        return

    all_active, all_completed = collect_all_trades()
    total_realized = sum(t.get("pnl", 0) for t in all_completed)
    total_unrealized = sum(t.get("unrealized_pnl", 0) for t in all_active)
    total_trades = len(all_completed)
    winners = sum(1 for t in all_completed if t.get("pnl", 0) > 0)
    losers = sum(1 for t in all_completed if t.get("pnl", 0) < 0)

    strat_lines = []
    strategies = set(t.get("strategy", "Unknown") for t in all_completed)
    for strat in sorted(strategies):
        strat_trades = [t for t in all_completed if t.get("strategy") == strat]
        spnl = sum(t.get("pnl", 0) for t in strat_trades)
        sw = sum(1 for t in strat_trades if t.get("pnl", 0) > 0)
        sl_count = sum(1 for t in strat_trades if t.get("pnl", 0) < 0)
        emoji = "+" if spnl > 0 else ""
        strat_lines.append(
            f"  {strat}: {len(strat_trades)} trades | {sw}W/{sl_count}L | PnL: {emoji}{spnl:.2f}"
        )

    emoji_total = "+" if total_realized > 0 else ""
    breakdown = "\n".join(strat_lines) if strat_lines else "  No trades today"
    msg = (
        f"DAILY P&L SUMMARY | {today_str}\n{'=' * 30}\n"
        f"Realized P&L: {emoji_total}{total_realized:.2f}\n"
        f"Unrealized P&L: {total_unrealized:+.2f}\n"
        f"Total Trades: {total_trades} ({winners}W / {losers}L)\n"
        f"\nStrategy Breakdown:\n{breakdown}"
    )
    _send_telegram(msg)
    _mark_sent(summary_key)
    print(f"  [telegram] Daily P&L summary sent for {today_str}")


def send_market_open_msg():
    now = now_ist()
    today_str = now.strftime("%Y-%m-%d")
    open_msg_key = f"market_open_{today_str}"
    if not (now.hour == 9 and 15 <= now.minute <= 20):
        return
    if _is_already_sent(open_msg_key):
        return
    _mark_sent(open_msg_key)
    _send_telegram(
        f"MARKET OPEN | {today_str}\n{'=' * 30}\n"
        f"Paper trading started for {now.strftime('%A, %d %b %Y')}\n"
        f"Strategies active: ABCD, RSI+SMA\nMonitoring: NIFTY ATM options\n"
        f"Refresh interval: {REFRESH_SECONDS}s\nGood luck today!"
    )


# ================= HELPER: format float for tables =================
def _f2(v):
    """Format a value to 2 decimal places if numeric."""
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


# ================= UI BUILDERS =================


def _build_option_chain_table(container, df, atm):
    """Build a NiceGUI table for option chain data inside a container."""
    container.clear()
    with container:
        if df.empty:
            ui.label("No data available").classes("text-grey")
            return

        # Round numeric columns — keep 6 decimals for Gamma
        num_cols = list(df.select_dtypes("number").columns)
        display_df = df.copy()
        for c in num_cols:
            if c == "Gamma":
                display_df[c] = display_df[c].apply(
                    lambda x: round(x, 6) if pd.notna(x) else x
                )
            else:
                display_df[c] = display_df[c].apply(
                    lambda x: round(x, 4) if pd.notna(x) else x
                )

        columns = [
            {"name": col, "label": col, "field": col, "sortable": True, "align": "left"}
            for col in display_df.columns
        ]
        rows = display_df.to_dict("records")

        table = ui.table(columns=columns, rows=rows, row_key="Strike").classes("w-full")
        table.props("dense flat bordered")

        # Highlight ATM row in yellow
        table.add_slot(
            "body-cell",
            """
            <q-td :props="props"
                   :style="props.row.Strike == """
            + str(atm)
            + """ ? 'background: #ffffb3; font-weight: bold' : ''">
                {{ props.value }}
            </q-td>
        """,
        )


def _build_trade_table(container, rows, pnl_col="PnL"):
    """Build a trade table with PnL highlighting."""
    container.clear()
    with container:
        if not rows:
            ui.label("No trades").classes("text-grey italic")
            return

        columns = list(rows[0].keys())
        with ui.element("div").classes("w-full overflow-x-auto"):
            with ui.element("table").classes("w-full border-collapse text-sm"):
                # Header
                with ui.element("thead"):
                    with ui.element("tr").classes("bg-gray-100"):
                        for col in columns:
                            ui.element("th").classes(
                                "px-3 py-2 text-left font-semibold border-b"
                            ).text(col)
                # Body
                with ui.element("tbody"):
                    for row in rows:
                        pnl_val = row.get(pnl_col, 0)
                        with ui.element("tr").classes("border-b hover:bg-gray-50"):
                            for col in columns:
                                val = row[col]
                                cell = ui.element("td").classes("px-3 py-2")
                                if col == pnl_col:
                                    if isinstance(pnl_val, (int, float)):
                                        if pnl_val > 0:
                                            cell.classes(
                                                "text-green-700 font-bold bg-green-50"
                                            )
                                        elif pnl_val < 0:
                                            cell.classes(
                                                "text-red-700 font-bold bg-red-50"
                                            )
                                if col == "Status" and isinstance(
                                    pnl_val, (int, float)
                                ):
                                    if pnl_val > 0:
                                        cell.classes("text-green-700 bg-green-50")
                                    elif pnl_val < 0:
                                        cell.classes("text-red-700 bg-red-50")
                                cell.text(
                                    _f2(val) if isinstance(val, float) else str(val)
                                )


# ================= OPTION CHAIN TAB =================


def render_index_tab(container, index_name, cfg):
    """Build the NIFTY or BANKNIFTY option chain tab content inside container."""
    scrip = cfg["scrip"]
    segment = cfg["segment"]
    strike_step = cfg["strike_step"]
    strike_range = cfg["strike_range"]
    prefix = cfg["name_prefix"]

    with container:
        with ui.row().classes("w-full items-center gap-4 mb-2"):
            spot_label = ui.label("Loading...").classes("text-2xl font-bold")
            atm_label = ui.label("").classes("text-lg text-gray-500")
            time_label = ui.label("").classes("text-sm text-gray-400 ml-auto")

        expiry_tabs_container = ui.element("div").classes("w-full")

    async def refresh():
        try:
            expiries = get_expiries(scrip, segment, 3)
            print(f"  [{index_name}] got expiries: {expiries}")
        except Exception as e:
            print(f"  [{index_name}] expiry error: {e}")
            spot_label.text = f"Error: {e}"
            return

        chain_data = {}
        for expiry in expiries:
            try:
                spot, df = fetch_option_chain(scrip, segment, expiry)
                chain_data[expiry] = (spot, df)
                print(f"  [{index_name}] {expiry}: spot={spot}, rows={len(df)}")
            except Exception as e:
                print(f"  [{index_name}] {expiry} error: {e}")
                chain_data[expiry] = e
            await asyncio.sleep(1)

        spot_val = None
        for result in chain_data.values():
            if not isinstance(result, Exception):
                spot_val = result[0]
                break

        spot_label.text = (
            f"{index_name}: {spot_val:,.2f}" if spot_val else f"{index_name}: N/A"
        )
        atm_val = round(spot_val / strike_step) * strike_step if spot_val else "N/A"
        atm_label.text = f"ATM: {atm_val:,}" if spot_val else "ATM: N/A"
        time_label.text = f"Updated: {now_ist().strftime('%H:%M:%S')}"

        expiry_tabs_container.clear()
        with expiry_tabs_container:
            if not expiries:
                ui.label("No expiries found").classes("text-grey")
            else:
                with ui.tabs().classes("w-full") as tabs:
                    tab_items = []
                    for exp in expiries:
                        tab_items.append(ui.tab(f"Expiry: {exp}"))

                with ui.tab_panels(tabs, value=tab_items[0]).classes("w-full"):
                    for tab_item, exp in zip(tab_items, expiries):
                        with ui.tab_panel(tab_item):
                            result = chain_data.get(exp)
                            if isinstance(result, Exception):
                                ui.label(f"Error: {result}").classes("text-red-500")
                                continue
                            if result is None:
                                ui.label("No data").classes("text-grey")
                                continue

                            spot, df = result
                            atm = round(spot / strike_step) * strike_step
                            df = build_name_column(df, exp, prefix)
                            ce, pe = filter_and_split(df, atm, strike_range)
                            ce = add_trend(ce, index_name, exp, "CE")
                            pe = add_trend(pe, index_name, exp, "PE")

                            print(
                                f"  [{index_name}] {exp}: CE rows={len(ce)}, PE rows={len(pe)}, ATM={atm}"
                            )

                            with ui.row().classes(
                                "w-full gap-4 flex-nowrap items-start"
                            ):
                                with ui.column().classes("flex-1 min-w-0"):
                                    ui.label("CALL (CE)").classes(
                                        "text-lg font-bold text-green-600"
                                    )
                                    ce_container = ui.element("div").classes("w-full")
                                    _build_option_chain_table(ce_container, ce, atm)

                                with ui.column().classes("flex-1 min-w-0"):
                                    ui.label("PUT (PE)").classes(
                                        "text-lg font-bold text-red-600"
                                    )
                                    pe_container = ui.element("div").classes("w-full")
                                    _build_option_chain_table(pe_container, pe, atm)

    return refresh


# ================= ABCD ALGO TAB =================


def _build_candlestick_with_abcd(
    candles, swings, patterns, contract_name, current_price
):
    """Build a Plotly candlestick chart with ABCD pattern overlay."""
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=candles["timestamp"],
            open=candles["open"],
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            name="Price",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        )
    )

    if swings:
        swing_highs = [s for s in swings if s["type"] == "high"]
        swing_lows = [s for s in swings if s["type"] == "low"]
        if swing_highs:
            fig.add_trace(
                go.Scatter(
                    x=[s["time"] for s in swing_highs],
                    y=[s["price"] for s in swing_highs],
                    mode="markers",
                    marker=dict(symbol="triangle-down", size=10, color="#ef5350"),
                    name="Swing High",
                )
            )
        if swing_lows:
            fig.add_trace(
                go.Scatter(
                    x=[s["time"] for s in swing_lows],
                    y=[s["price"] for s in swing_lows],
                    mode="markers",
                    marker=dict(symbol="triangle-up", size=10, color="#26a69a"),
                    name="Swing Low",
                )
            )

    colors = ["#ff9800", "#2196f3", "#9c27b0", "#00bcd4", "#e91e63"]
    for idx, p in enumerate(patterns):
        color = colors[idx % len(colors)]
        pts = [p["A"], p["B"], p["C"], p["D"]]
        fig.add_trace(
            go.Scatter(
                x=[pt["time"] for pt in pts],
                y=[pt["price"] for pt in pts],
                mode="lines+markers+text",
                line=dict(color=color, width=2, dash="dot"),
                marker=dict(size=12, color=color),
                text=["A", "B", "C", "D"],
                textposition="top center",
                textfont=dict(size=14, color=color),
                name=f"ABCD {idx+1} ({p['type']})",
            )
        )
        fig.add_hline(
            y=p["target"],
            line_dash="dash",
            line_color="green",
            annotation_text=f"Target {p['target']:.2f}",
            annotation_position="bottom right",
        )
        fig.add_hline(
            y=p["stop_loss"],
            line_dash="dash",
            line_color="red",
            annotation_text=f"SL {p['stop_loss']:.2f}",
            annotation_position="bottom right",
        )

    fig.update_layout(
        height=500,
        xaxis_rangeslider_visible=False,
        xaxis_title="Time",
        yaxis_title="Price",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=30, b=0),
    )
    return fig


def _build_candlestick_with_rsi_sma(candles, df_ind, signals):
    """Build Plotly candlestick + SMA + RSI charts for RSI+SMA strategy."""
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=candles["timestamp"],
            open=candles["open"],
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            name="Price",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        )
    )
    if not df_ind.empty:
        fig.add_trace(
            go.Scatter(
                x=df_ind["timestamp"],
                y=df_ind["sma_fast"],
                mode="lines",
                line=dict(color="#2196f3", width=1.5),
                name=f"SMA {SMA_FAST}",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df_ind["timestamp"],
                y=df_ind["sma_slow"],
                mode="lines",
                line=dict(color="#ff9800", width=1.5),
                name=f"SMA {SMA_SLOW}",
            )
        )

    buy_sigs = [s for s in signals if s["type"] == "Bullish"]
    sell_sigs = [s for s in signals if s["type"] == "Bearish"]
    if buy_sigs:
        fig.add_trace(
            go.Scatter(
                x=[s["time"] for s in buy_sigs],
                y=[s["entry"] for s in buy_sigs],
                mode="markers",
                marker=dict(symbol="triangle-up", size=14, color="#26a69a"),
                name="Buy Signal",
            )
        )
    if sell_sigs:
        fig.add_trace(
            go.Scatter(
                x=[s["time"] for s in sell_sigs],
                y=[s["entry"] for s in sell_sigs],
                mode="markers",
                marker=dict(symbol="triangle-down", size=14, color="#ef5350"),
                name="Sell Signal",
            )
        )
    fig.update_layout(
        height=500,
        xaxis_rangeslider_visible=False,
        xaxis_title="Time",
        yaxis_title="Price",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=30, b=0),
    )

    fig_rsi = go.Figure()
    if not df_ind.empty:
        fig_rsi.add_trace(
            go.Scatter(
                x=df_ind["timestamp"],
                y=df_ind["rsi"],
                mode="lines",
                line=dict(color="#9c27b0", width=1.5),
                name="RSI",
            )
        )
        fig_rsi.add_hline(
            y=RSI_OVERBOUGHT,
            line_dash="dash",
            line_color="red",
            annotation_text="Overbought (70)",
        )
        fig_rsi.add_hline(
            y=RSI_OVERSOLD,
            line_dash="dash",
            line_color="green",
            annotation_text="Oversold (30)",
        )
        fig_rsi.update_layout(
            height=200,
            yaxis_title="RSI",
            xaxis_title="Time",
            margin=dict(l=0, r=0, t=10, b=0),
        )

    return fig, fig_rsi


def _render_algo_option(container, cfg, expiry, raw, algo_type="abcd"):
    """Render one CE/PE option's algo analysis inside a container."""
    spot = round(float(raw["last_price"]), 2)
    oc = raw["oc"]
    atm = round(spot / cfg["strike_step"]) * cfg["strike_step"]

    strikes = sorted(oc.keys(), key=lambda s: abs(float(s) - atm))
    if not strikes:
        with container:
            ui.label("No strikes found").classes("text-red-500")
        return

    best_strike = strikes[0]
    sides = oc[best_strike]
    ce_id = sides.get("ce", {}).get("security_id")
    pe_id = sides.get("pe", {}).get("security_id")

    if not ce_id or not pe_id:
        with container:
            ui.label(f"No security IDs for ATM strike {best_strike}").classes(
                "text-red-500"
            )
        return

    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
    exp_tag = exp_date.strftime("%d%b").upper()

    container.clear()
    with container:
        with ui.row().classes("gap-8"):
            ui.label(f"Spot: {spot:,.2f}").classes("text-lg font-bold")
            ui.label(f"ATM: {atm:,}").classes("text-lg")
            ui.label(f"Expiry: {expiry}").classes("text-lg text-gray-600")

        ui.separator()

        with ui.tabs().classes("w-full") as opt_tabs:
            ce_tab_item = ui.tab(f"ATM CE — NIFTY {exp_tag} {int(atm)} CE")
            pe_tab_item = ui.tab(f"ATM PE — NIFTY {exp_tag} {int(atm)} PE")

        with ui.tab_panels(opt_tabs).classes("w-full"):
            for tab_item, sec_id, opt_type in [
                (ce_tab_item, ce_id, "CE"),
                (pe_tab_item, pe_id, "PE"),
            ]:
                with ui.tab_panel(tab_item):
                    time.sleep(1)
                    candles = fetch_5min_candles(sec_id)

                    if candles.empty:
                        ui.label(
                            f"No candle data for ATM {opt_type} (ID: {sec_id})"
                        ).classes("text-orange-500")
                        continue

                    contract_name = f"NIFTY {exp_tag} {int(atm)} {opt_type}"
                    current_price = round(candles["close"].iloc[-1], 2)

                    if algo_type == "abcd":
                        swings = find_swing_points(candles, order=2)
                        patterns = detect_abcd_patterns(swings)

                        ui.label(
                            f"{contract_name} — Last: {current_price:.2f} | Candles: {len(candles)}"
                        ).classes("text-md font-semibold")

                        fig = _build_candlestick_with_abcd(
                            candles, swings, patterns, contract_name, current_price
                        )
                        ui.plotly(fig).classes("w-full")

                        today_date = pd.Timestamp(now_ist().date())
                        patterns = [
                            p
                            for p in patterns
                            if pd.Timestamp(p["D"]["time"]).normalize() == today_date
                        ]

                        if not patterns:
                            ui.label("No ABCD patterns detected today.").classes(
                                "text-gray-500 italic"
                            )

                        active, completed = classify_trades(
                            patterns, current_price, contract_name
                        )
                        _trade_store[f"abcd_trades_{contract_name}"] = {
                            "active": active,
                            "completed": completed,
                        }

                        with ui.tabs().classes("w-full") as trade_tabs:
                            active_tab_item = ui.tab("Active Trades")
                            completed_tab_item = ui.tab("Completed Trades")

                        with ui.tab_panels(trade_tabs).classes("w-full"):
                            with ui.tab_panel(active_tab_item):
                                if not active:
                                    ui.label("No active trades").classes(
                                        "text-gray-500 italic"
                                    )
                                else:
                                    rows = [
                                        {
                                            "Pattern": t["type"],
                                            "Signal": t["signal"],
                                            "Entry (D)": round(t["entry"], 2),
                                            "Target": round(t["target"], 2),
                                            "Stop Loss": round(t["stop_loss"], 2),
                                            "Current": round(current_price, 2),
                                            "Unreal. PnL": t["unrealized_pnl"],
                                            "A Time": (
                                                t["A"]["time"].strftime("%d %b %H:%M")
                                                if hasattr(t["A"]["time"], "strftime")
                                                else str(t["A"]["time"])
                                            ),
                                            "D Time": (
                                                t["D"]["time"].strftime("%d %b %H:%M")
                                                if hasattr(t["D"]["time"], "strftime")
                                                else str(t["D"]["time"])
                                            ),
                                            "BC Retrace": t["BC_retrace"],
                                            "CD/AB": t["CD_AB_ratio"],
                                        }
                                        for t in active
                                    ]
                                    trade_container = ui.element("div").classes(
                                        "w-full"
                                    )
                                    _build_trade_table(
                                        trade_container, rows, "Unreal. PnL"
                                    )

                            with ui.tab_panel(completed_tab_item):
                                if not completed:
                                    ui.label("No completed trades").classes(
                                        "text-gray-500 italic"
                                    )
                                else:
                                    rows = [
                                        {
                                            "Pattern": t["type"],
                                            "Signal": t["signal"],
                                            "Entry (D)": round(t["entry"], 2),
                                            "Target": round(t["target"], 2),
                                            "Stop Loss": round(t["stop_loss"], 2),
                                            "Exit": round(t["exit_price"], 2),
                                            "PnL": t["pnl"],
                                            "Status": t["status"],
                                            "A Time": (
                                                t["A"]["time"].strftime("%d %b %H:%M")
                                                if hasattr(t["A"]["time"], "strftime")
                                                else str(t["A"]["time"])
                                            ),
                                            "D Time": (
                                                t["D"]["time"].strftime("%d %b %H:%M")
                                                if hasattr(t["D"]["time"], "strftime")
                                                else str(t["D"]["time"])
                                            ),
                                        }
                                        for t in completed
                                    ]
                                    trade_container = ui.element("div").classes(
                                        "w-full"
                                    )
                                    _build_trade_table(trade_container, rows, "PnL")

                        # Swing points expander
                        with ui.expansion("Swing Points & Pattern Details").classes(
                            "w-full"
                        ):
                            if swings:
                                swing_rows = [
                                    {
                                        "Time": (
                                            s["time"].strftime("%d %b %H:%M")
                                            if hasattr(s["time"], "strftime")
                                            else str(s["time"])
                                        ),
                                        "Type": s["type"],
                                        "Price": round(s["price"], 2),
                                    }
                                    for s in swings
                                ]
                                for sr in swing_rows:
                                    ui.label(
                                        f"{sr['Time']} | {sr['Type']} | {sr['Price']:.2f}"
                                    ).classes("text-sm")
                            if patterns:
                                for i, p in enumerate(patterns):
                                    ui.label(
                                        f"Pattern {i+1} ({p['type']}): A={p['A']['price']:.2f} → B={p['B']['price']:.2f} → "
                                        f"C={p['C']['price']:.2f} → D={p['D']['price']:.2f} | "
                                        f"BC: {p['BC_retrace']} | CD/AB: {p['CD_AB_ratio']}"
                                    ).classes("text-sm")

                    else:  # RSI+SMA
                        signals, df_ind = detect_rsi_sma_signals(candles)
                        today_date = pd.Timestamp(now_ist().date())
                        signals = [
                            s
                            for s in signals
                            if pd.Timestamp(s["time"]).normalize() == today_date
                        ]

                        ui.label(
                            f"{contract_name} — Last: {current_price:.2f} | Candles: {len(candles)}"
                        ).classes("text-md font-semibold")

                        fig, fig_rsi = _build_candlestick_with_rsi_sma(
                            candles, df_ind, signals
                        )
                        ui.plotly(fig).classes("w-full")
                        if not df_ind.empty:
                            ui.plotly(fig_rsi).classes("w-full")

                        if not signals:
                            ui.label("No RSI+SMA signals detected today.").classes(
                                "text-gray-500 italic"
                            )

                        active, completed = classify_rsi_trades(
                            signals, current_price, contract_name
                        )
                        _trade_store[f"rsi_trades_{contract_name}"] = {
                            "active": active,
                            "completed": completed,
                        }

                        with ui.tabs().classes("w-full") as trade_tabs:
                            active_tab_item = ui.tab("Active Trades")
                            completed_tab_item = ui.tab("Completed Trades")

                        with ui.tab_panels(trade_tabs).classes("w-full"):
                            with ui.tab_panel(active_tab_item):
                                if not active:
                                    ui.label("No active trades").classes(
                                        "text-gray-500 italic"
                                    )
                                else:
                                    rows = [
                                        {
                                            "Signal": t["signal"],
                                            "Entry": t["entry"],
                                            "Target": t["target"],
                                            "Stop Loss": t["stop_loss"],
                                            "Current": round(current_price, 2),
                                            "Unreal. PnL": t["unrealized_pnl"],
                                            "RSI": t["rsi"],
                                            "Time": (
                                                t["time"].strftime("%d %b %H:%M")
                                                if hasattr(t["time"], "strftime")
                                                else str(t["time"])
                                            ),
                                        }
                                        for t in active
                                    ]
                                    trade_container = ui.element("div").classes(
                                        "w-full"
                                    )
                                    _build_trade_table(
                                        trade_container, rows, "Unreal. PnL"
                                    )

                            with ui.tab_panel(completed_tab_item):
                                if not completed:
                                    ui.label("No completed trades").classes(
                                        "text-gray-500 italic"
                                    )
                                else:
                                    rows = [
                                        {
                                            "Signal": t["signal"],
                                            "Entry": t["entry"],
                                            "Target": t["target"],
                                            "Stop Loss": t["stop_loss"],
                                            "Exit": round(t["exit_price"], 2),
                                            "PnL": t["pnl"],
                                            "Status": t["status"],
                                            "Time": (
                                                t["time"].strftime("%d %b %H:%M")
                                                if hasattr(t["time"], "strftime")
                                                else str(t["time"])
                                            ),
                                        }
                                        for t in completed
                                    ]
                                    trade_container = ui.element("div").classes(
                                        "w-full"
                                    )
                                    _build_trade_table(trade_container, rows, "PnL")


def render_algo_tab(container, algo_type="abcd"):
    """Build the ABCD or RSI+SMA algo trading tab content inside container."""
    title = (
        "ABCD Harmonic Scanner"
        if algo_type == "abcd"
        else "RSI + SMA Crossover Scanner"
    )

    with container:
        ui.label(f"{title} — NIFTY ATM (5-min candles)").classes(
            "text-xl font-bold mb-2"
        )
        content_container = ui.element("div").classes("w-full")

    async def refresh():
        cfg = INDICES["NIFTY"]
        try:
            expiries = get_expiries(cfg["scrip"], cfg["segment"], 2, for_algo=True)
        except Exception as e:
            content_container.clear()
            with content_container:
                ui.label(f"Could not fetch expiries: {e}").classes("text-red-500")
            return

        expiry_data = {}
        for exp in expiries:
            try:
                raw = fetch_option_chain_raw(cfg["scrip"], cfg["segment"], exp)
                expiry_data[exp] = raw
            except Exception as e:
                expiry_data[exp] = e
            await asyncio.sleep(3)

        content_container.clear()
        with content_container:
            with ui.tabs().classes("w-full") as tabs:
                tab_items = []
                for exp in expiries:
                    tab_items.append(ui.tab(f"Expiry: {exp}"))

            with ui.tab_panels(tabs).classes("w-full"):
                for tab_item, exp in zip(tab_items, expiries):
                    with ui.tab_panel(tab_item):
                        result = expiry_data.get(exp)
                        if isinstance(result, Exception):
                            ui.label(f"Error: {result}").classes("text-red-500")
                        elif result is None:
                            ui.label("No data").classes("text-grey")
                        else:
                            inner_container = ui.element("div").classes("w-full")
                            _render_algo_option(
                                inner_container, cfg, exp, result, algo_type
                            )

    return refresh


# ================= P&L SUMMARY TAB =================


def render_pnl_tab(container):
    """Build the P&L summary tab content inside container."""
    with container:
        ui.label("Profit / Loss Summary — All Strategies").classes(
            "text-xl font-bold mb-2"
        )
        summary_container = ui.element("div").classes("w-full")

    async def refresh():
        all_active, all_completed = collect_all_trades()

        summary_container.clear()
        with summary_container:
            # Completed trades
            ui.label("Completed Trades").classes("text-lg font-bold mt-4")
            if not all_completed:
                ui.label("No completed trades today").classes("text-gray-500 italic")
            else:
                total_pnl = sum(t.get("pnl", 0) for t in all_completed)
                winners = sum(1 for t in all_completed if t.get("pnl", 0) > 0)
                losers = sum(1 for t in all_completed if t.get("pnl", 0) < 0)

                with ui.row().classes("gap-8"):
                    with ui.card().classes("p-4"):
                        ui.label("Total P&L").classes("text-sm text-gray-500")
                        color = "text-green-600" if total_pnl >= 0 else "text-red-600"
                        ui.label(f"{total_pnl:+.2f}").classes(
                            f"text-2xl font-bold {color}"
                        )
                    with ui.card().classes("p-4"):
                        ui.label("Total Trades").classes("text-sm text-gray-500")
                        ui.label(str(len(all_completed))).classes("text-2xl font-bold")
                    with ui.card().classes("p-4"):
                        ui.label("Winners").classes("text-sm text-gray-500")
                        ui.label(str(winners)).classes(
                            "text-2xl font-bold text-green-600"
                        )
                    with ui.card().classes("p-4"):
                        ui.label("Losers").classes("text-sm text-gray-500")
                        ui.label(str(losers)).classes("text-2xl font-bold text-red-600")

                ui.separator()

                strategies = set(t.get("strategy", "Unknown") for t in all_completed)
                for strat in sorted(strategies):
                    strat_trades = [
                        t for t in all_completed if t.get("strategy") == strat
                    ]
                    spnl = sum(t.get("pnl", 0) for t in strat_trades)
                    ui.label(
                        f"{strat}: {len(strat_trades)} trades | PnL: {spnl:+.2f}"
                    ).classes("text-md font-semibold")

                ui.separator()

                rows = [
                    {
                        "Strategy": t.get("strategy", ""),
                        "Signal": t.get("signal", ""),
                        "Entry": t.get("entry", 0),
                        "Exit": round(t.get("exit_price", 0), 2),
                        "PnL": t.get("pnl", 0),
                        "Status": t.get("status", ""),
                    }
                    for t in all_completed
                ]
                trade_container = ui.element("div").classes("w-full")
                _build_trade_table(trade_container, rows, "PnL")

            # Active trades
            ui.label("Active Trades").classes("text-lg font-bold mt-6")
            if not all_active:
                ui.label("No active trades").classes("text-gray-500 italic")
            else:
                total_unreal = sum(t.get("unrealized_pnl", 0) for t in all_active)
                color = "text-green-600" if total_unreal >= 0 else "text-red-600"
                ui.label(f"Unrealized P&L: {total_unreal:+.2f}").classes(
                    f"text-lg font-bold {color}"
                )

                rows = [
                    {
                        "Strategy": t.get("strategy", ""),
                        "Signal": t.get("signal", ""),
                        "Entry": t.get("entry", 0),
                        "Target": t.get("target", 0),
                        "Stop Loss": t.get("stop_loss", 0),
                        "Unreal. PnL": t.get("unrealized_pnl", 0),
                    }
                    for t in all_active
                ]
                trade_container = ui.element("div").classes("w-full")
                _build_trade_table(trade_container, rows, "Unreal. PnL")

    return refresh


# ================= COUNTDOWN DISPLAY =================


def render_market_closed(container):
    """Build the market-closed countdown view inside container."""
    ist_now = now_ist()
    if is_nse_holiday(ist_now):
        close_reason = "NSE Holiday"
    elif ist_now.weekday() > 4:
        close_reason = "Weekend"
    else:
        close_reason = "After Hours"

    next_open = get_next_market_open()
    remaining = next_open - now_ist()
    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    with container:
        with ui.element("div").classes(
            "w-full flex flex-col items-center justify-center py-20"
        ):
            ui.icon("schedule", size="64px").classes("text-blue-300 mb-4")
            ui.label(f"Market is Closed — {close_reason}").classes(
                "text-3xl font-bold text-gray-700"
            )
            ui.label(
                f"Next market open: {next_open.strftime('%A, %d %b %Y at %I:%M %p')}"
            ).classes("text-lg text-gray-500 mt-2")
            countdown_label = ui.label(
                f"{hours:02d}h {minutes:02d}m {seconds:02d}s"
            ).classes("text-6xl font-bold text-blue-500 mt-6")
            ui.label(
                "Market hours: 9:15 AM — 3:30 PM IST (Mon-Fri, excl. NSE holidays)"
            ).classes("text-sm text-gray-400 mt-4")

    return countdown_label


# ================= SIDEBAR NAV ITEMS =================

NAV_ITEMS = [
    {"id": "nifty", "label": "NIFTY", "icon": "show_chart"},
    {"id": "banknifty", "label": "BANKNIFTY", "icon": "candlestick_chart"},
    {"id": "abcd", "label": "ABCD Algo", "icon": "insights"},
    {"id": "rsi", "label": "RSI + SMA", "icon": "analytics"},
    {"id": "pnl", "label": "P&L Summary", "icon": "account_balance_wallet"},
]


# ================= MAIN PAGE =================


@ui.page("/")
async def index():
    ui.page_title("Algo Trading")

    # ---- Custom CSS ----
    ui.add_head_html(
        """
    <style>
        .q-tab { font-size: 1.1rem !important; padding: 12px 20px !important; }
        .nav-btn { width: 100%; justify-content: flex-start !important; text-transform: none !important; }
        .nav-btn .q-btn__content { justify-content: flex-start !important; gap: 12px; }
        .nav-btn-active { background: rgba(59, 130, 246, 0.12) !important; color: #3b82f6 !important; font-weight: 600 !important; }
        .header-bar { backdrop-filter: blur(8px); }
    </style>
    """
    )

    # ---- State ----
    active_page = {"value": "nifty"}
    refresh_fns = []
    _prev_market_open = [None]
    nav_btn_refs = {}
    page_client = context.client  # capture client ref for timer callbacks

    # ---- Header ----
    with (
        ui.header()
        .classes("header-bar bg-white shadow-sm border-b items-center px-6 py-0")
        .style("height: 56px")
    ):
        with ui.row().classes("items-center gap-3 w-full"):
            # Hamburger menu for mobile / toggle drawer
            menu_btn = (
                ui.button(icon="menu", on_click=lambda: drawer.toggle())
                .props("flat dense round")
                .classes("text-gray-600")
            )

            ui.icon("trending_up", size="28px").classes("text-blue-600")
            ui.label("Algo Trade").classes(
                "text-xl font-bold text-gray-800 tracking-tight"
            )

            ui.space()

            # Market status badge
            market_open = is_market_open()
            if market_open:
                with ui.element("div").classes(
                    "flex items-center gap-2 bg-green-50 border border-green-200 rounded-full px-3 py-1"
                ):
                    ui.element("div").classes("w-2 h-2 rounded-full bg-green-500")
                    market_badge_label = ui.label("Market Open").classes(
                        "text-sm font-semibold text-green-700"
                    )
            else:
                with ui.element("div").classes(
                    "flex items-center gap-2 bg-red-50 border border-red-200 rounded-full px-3 py-1"
                ):
                    ui.element("div").classes("w-2 h-2 rounded-full bg-red-500")
                    market_badge_label = ui.label("Market Closed").classes(
                        "text-sm font-semibold text-red-700"
                    )

            # Refresh status
            status_label = ui.label("").classes("text-xs text-gray-400 hidden sm:block")

    # ---- Sidebar ----
    with (
        ui.left_drawer(value=True, bordered=True)
        .classes("bg-gray-50 border-r")
        .style("width: 220px; padding-top: 8px") as drawer
    ):
        # Sidebar header
        with ui.element("div").classes("px-4 py-3 mb-2"):
            ui.label("Navigation").classes(
                "text-xs font-bold text-gray-400 uppercase tracking-wider"
            )

        # Nav buttons
        def set_active_page(page_id):
            active_page["value"] = page_id
            # Update button styles
            for nid, btn in nav_btn_refs.items():
                if nid == page_id:
                    btn.classes(add="nav-btn-active")
                else:
                    btn.classes(remove="nav-btn-active")
            # Switch visible page
            for nid, cont in page_containers.items():
                cont.set_visibility(nid == page_id)

        for item in NAV_ITEMS:
            btn = (
                ui.button(
                    item["label"],
                    icon=item["icon"],
                    on_click=lambda e, pid=item["id"]: set_active_page(pid),
                )
                .props("flat no-caps align=left")
                .classes("nav-btn rounded-lg mx-2 mb-1 text-gray-600")
            )
            if item["id"] == active_page["value"]:
                btn.classes(add="nav-btn-active")
            nav_btn_refs[item["id"]] = btn

        ui.separator().classes("my-3 mx-4")

        # Market info in sidebar
        with ui.element("div").classes("px-4"):
            ui.label("Market Hours").classes(
                "text-xs font-bold text-gray-400 uppercase tracking-wider mb-1"
            )
            ui.label("9:15 AM — 3:30 PM IST").classes("text-sm text-gray-600")
            ui.label("Mon — Fri (excl. holidays)").classes("text-xs text-gray-400")
            current_time_label = ui.label(
                f"Current Time: {now_ist().strftime('%H:%M:%S')} IST"
            ).classes("text-sm text-gray-600 mt-2")
            ui.timer(
                1,
                lambda: current_time_label.set_text(
                    f"Current Time: {now_ist().strftime('%H:%M:%S')} IST"
                ),
            )

        ui.space()

        # Refresh interval info
        with ui.element("div").classes("px-4 pb-4"):
            ui.label(f"Auto-refresh: {REFRESH_SECONDS}s").classes(
                "text-xs text-gray-400"
            )

    # ---- Main Content Area ----
    with ui.element("div").classes("w-full p-6"):
        # Create page containers (all pages live here, visibility toggled)
        page_containers = {}

        for item in NAV_ITEMS:
            cont = ui.element("div").classes("w-full")
            cont.set_visibility(item["id"] == active_page["value"])
            page_containers[item["id"]] = cont

        # Also a market-closed overlay container
        closed_container = ui.element("div").classes("w-full")
        closed_container.set_visibility(False)

    # ---- Build Page Content ----
    async def build_ui():
        nonlocal refresh_fns
        refresh_fns = []

        market_open = is_market_open()

        for item in NAV_ITEMS:
            page_containers[item["id"]].clear()

        # Option chains + P&L always render (REST API works anytime)
        refresh_fns.append(
            render_index_tab(page_containers["nifty"], "NIFTY", INDICES["NIFTY"])
        )
        refresh_fns.append(
            render_index_tab(
                page_containers["banknifty"], "BANKNIFTY", INDICES["BANKNIFTY"]
            )
        )
        refresh_fns.append(render_pnl_tab(page_containers["pnl"]))

        # Algo tabs need live candle data — show countdown when market is closed
        if market_open:
            refresh_fns.append(render_algo_tab(page_containers["abcd"], "abcd"))
            refresh_fns.append(render_algo_tab(page_containers["rsi"], "rsi"))
        else:
            render_market_closed(page_containers["abcd"])
            render_market_closed(page_containers["rsi"])

    async def full_refresh():
        """Rebuild UI if market state changed, then refresh data."""
        if page_client._deleted:
            return

        current_open = is_market_open()

        if current_open != _prev_market_open[0]:
            _prev_market_open[0] = current_open
            await build_ui()

        status_label.text = f"Refreshing... {now_ist().strftime('%H:%M:%S')}"
        try:
            for fn in refresh_fns:
                if page_client._deleted:
                    return
                try:
                    await fn()
                except Exception as fn_err:
                    print(f"  [refresh fn error] {fn_err}")
                await asyncio.sleep(1)  # stagger between refresh functions
            if not page_client._deleted:
                status_label.text = f"Last refresh: {now_ist().strftime('%H:%M:%S')} | Next in {REFRESH_SECONDS}s"
        except Exception as e:
            if not page_client._deleted:
                status_label.text = f"Refresh error: {e}"
            print(f"  [refresh error] {e}")

        if is_market_open():
            send_market_open_msg()
        send_daily_pnl_summary()

    # Initial build and refresh
    await build_ui()
    _prev_market_open[0] = is_market_open()
    ui.timer(2, lambda: asyncio.ensure_future(full_refresh()), once=True)

    # Periodic data refresh
    ui.timer(REFRESH_SECONDS, lambda: asyncio.ensure_future(full_refresh()))

    # Live countdown updater (every 1s)
    def update_countdown():
        if page_client._deleted:
            return
        if not is_market_open():
            next_open = get_next_market_open()
            remaining = next_open - now_ist()
            total_sec = max(0, int(remaining.total_seconds()))
            h, rem = divmod(total_sec, 3600)
            m, s = divmod(rem, 60)
            status_label.text = f"Next open: {h:02d}h {m:02d}m {s:02d}s"

    ui.timer(1, update_countdown)


# ================= RUN =================

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="AlgTrd", host="0.0.0.0", port=8501, reload=False)
