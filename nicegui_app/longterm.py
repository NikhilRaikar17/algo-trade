"""
Long term: one-week swing trades in the current NIFTY future, in their own paper account
(account.LONGTERM). Not intraday — a trade is held across days. The same loop as the other engines, on a
daily clock, independent of any browser connection:

- Contract: the current-month NIFTY future from Dhan's NSE_FNO instrument list (read once a day) —
  the next month's once the current one expires within max_hold_days trading days, so a trade never
  outlives its contract.
- Candles: the NIFTY index's daily bars (Dhan historical, fetched once a day; the future's own history
  has gaps at each roll) plus today's bar from one bulk quote call that also prices the future.
- Signals: the moving-average strategies enabled for Backtest on the Strategies page (strategy_keys),
  run on the daily bars — BUY on a cross up, SELL (short the future) on a cross down — with daily
  levels: stop 1.5 × ATR(14), target 3 × ATR(14). Scanned once a day at LONGTERM_LIMITS["scan_at"], a few
  minutes before the close; the stop and target are carried over to the future as the same distances
  from its price. The account takes or skips each signal (trade_desk.check(): whole lots, margin), one
  position at a time.
- Exits: run_longterm_monitor() closes an open trade at its target or stop on the first tick of the
  future there (market hours, any day it is held); LONGTERM.square_off() closes the rest after
  max_hold_days trading days at their last price ("Time Exit").

Telegram: the same NEW TRADE / SKIPPED / TRADE CLOSED alerts as the other accounts, tagged LONGTERM,
and a daily summary at 3:30 PM (pnl.send_daily_pnl_summary).
"""

import asyncio
import csv
import io
import json
import math
import os
import threading
import traceback
import urllib.request

import numpy as np
import pandas as pd
import talib
from dhanhq import marketfeed

import live_candles
import ws_feed
from account import LONGTERM, trading_days_held
from algo_strategies import (
    MA_STRATEGIES, _classify_generic, detect_ema10_signals, detect_ma_signals, detect_sma50_signals, ma_lines,
)
from backtest_metrics import _CHARGE_KEYS
from brokerage import LOT_SIZES, calculate_brokerage
from config import (
    INDICES, IST, LONGTERM_ATR, LONGTERM_HISTORY_DAYS, LONGTERM_LIMITS, LONGTERM_UNDERLYING, STRATEGY_NAMES,
    _is_trading_day, dhan, now_ist,
)
from state import _send_telegram, api_call, is_market_open
from strategy_registry import get_strategy_rows
from trade_desk import _hhmm
from trading_engine import _TICK_MAX_AGE, MONITOR_SECONDS

_INSTRUMENTS_URL = "https://api.dhan.co/v2/instrument/NSE_FNO"  # ~15 MB CSV
_FUTURES_FILE = os.path.join(os.path.dirname(__file__), ".nifty_futures.json")
GROUP = f"{LONGTERM_UNDERLYING} futures"  # one position at a time, whichever month

_lock = threading.Lock()
_futures: dict = {"day": None, "list": []}
_history: dict[str, tuple[str, pd.DataFrame]] = {}  # security id → (day fetched, daily bars before today)
_last_scan: dict = {}                               # what the page shows: when, what fired, errors

# The moving-average strategies, the only ones that work on daily bars (the patterns look within a day)
_DETECT = {
    "ema10": lambda df: detect_ema10_signals(df)[0],
    "sma50": lambda df: detect_sma50_signals(df)[0],
    **{k: (lambda df, k=k: detect_ma_signals(df, k)[0]) for k in MA_STRATEGIES},
}
_SHOWN = {"ema10": [("ema10", "EMA10")], "sma50": [("sma50", "SMA50")], **{k: ma_lines(k) for k in MA_STRATEGIES}}


def strategy_keys() -> list[str]:
    """The moving-average strategies enabled for Backtest on the Strategies page."""
    return [r["key"] for r in get_strategy_rows() if r["backtest_enabled"] and r["key"] in _DETECT]


def strategy_names() -> list[str]:
    return [STRATEGY_NAMES[k] for k in strategy_keys()]


# ── the contract ──────────────────────────────────────────────────────────────

def _download_futures() -> list[dict]:
    with urllib.request.urlopen(_INSTRUMENTS_URL, timeout=60) as resp:
        text = io.TextIOWrapper(resp, encoding="utf-8", newline="")
        return [{"symbol": row["DISPLAY_NAME"], "security_id": row["SECURITY_ID"], "expiry": row["SM_EXPIRY_DATE"],
                 "lot_size": int(float(row["LOT_SIZE"]))}
                for row in csv.DictReader(text)
                if row.get("INSTRUMENT") == "FUTIDX" and row.get("UNDERLYING_SYMBOL") == LONGTERM_UNDERLYING]


def futures_list() -> list[dict]:
    """The underlying's futures from Dhan's instrument list, nearest expiry first (downloaded once a day,
    kept in .nifty_futures.json across restarts)."""
    today = now_ist().strftime("%Y-%m-%d")
    with _lock:
        if _futures["day"] == today:
            return _futures["list"]
    found = []
    try:
        with open(_FUTURES_FILE) as f:
            saved = json.load(f)
        if saved.get("day") == today:
            found = saved["list"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    if not found:
        found = sorted(_download_futures(), key=lambda c: c["expiry"])
        with open(_FUTURES_FILE, "w") as f:
            json.dump({"day": today, "list": found}, f)
    with _lock:
        _futures.update(day=today, list=found)
    return found


def pick_future(futures: list[dict], today: str, hold: int = LONGTERM_LIMITS["max_hold_days"]) -> dict:
    """The current-month future, or the next month's if the current one expires within `hold` trading days."""
    live = sorted((c for c in futures if c["expiry"] > today), key=lambda c: c["expiry"])
    if not live:
        raise RuntimeError(f"no {LONGTERM_UNDERLYING} future expiring after {today}")
    for c in live:
        if trading_days_held(today, c["expiry"]) > hold:
            return c
    return live[-1]


def current_future() -> dict:
    return pick_future(futures_list(), now_ist().strftime("%Y-%m-%d"))


def _meta(c: dict) -> dict:
    """What the book keeps with a trade in this contract (and the monitor needs to price it)."""
    return {"security_id": c["security_id"], "expiry": c["expiry"], "lot_size": c["lot_size"], "group": GROUP}


def _key(security_id: str) -> str:
    return ws_feed.feed_key(marketfeed.NSE_FNO, security_id)


# ── candles ───────────────────────────────────────────────────────────────────

def fetch_daily_history(security_id: str | None = None, segment: str = "IDX_I",
                        instrument: str = "INDEX") -> pd.DataFrame:
    """Daily bars for the last LONGTERM_HISTORY_DAYS, before today (default: the underlying index).
    Fetched once a day."""
    security_id = security_id or str(INDICES[LONGTERM_UNDERLYING]["scrip"])
    today = now_ist().strftime("%Y-%m-%d")
    with _lock:
        hit = _history.get(security_id)
    if hit and hit[0] == today:
        return hit[1]
    from_date = (pd.Timestamp(today) - pd.Timedelta(days=LONGTERM_HISTORY_DAYS)).strftime("%Y-%m-%d")
    r = api_call(dhan.historical_daily_data, security_id, segment, instrument, from_date, today, retries=2)
    d = r.get("data") if isinstance(r, dict) and r.get("status") == "success" else None
    if not d or not d.get("timestamp"):
        return pd.DataFrame()
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(d["timestamp"], unit="s", utc=True).tz_convert(IST).normalize(),
        "open": d["open"], "high": d["high"], "low": d["low"], "close": d["close"],
    })
    df = df[df["timestamp"].dt.strftime("%Y-%m-%d") < today].reset_index(drop=True)
    with _lock:
        _history[security_id] = (today, df)
    return df


def fetch_quotes(future_id: str) -> tuple[dict | None, float | None]:
    """(today's index bar so far {open, high, low, close} with the last price as the close, the future's
    last price) from one bulk quote call."""
    index_id = INDICES[LONGTERM_UNDERLYING]["scrip"]
    r = api_call(dhan.ohlc_data, securities={"IDX_I": [int(index_id)], "NSE_FNO": [int(future_id)]}, retries=2)
    data = r.get("data") if isinstance(r, dict) else None
    data = (data or {}).get("data", data) or {}  # dhanhq wraps the payload in "data" twice
    q = (data.get("IDX_I") or {}).get(str(index_id)) or {}
    ohlc, ltp = q.get("ohlc") or {}, q.get("last_price")
    bar = None
    if ltp and ohlc.get("open"):
        bar = {"open": float(ohlc["open"]), "high": max(float(ohlc["high"]), float(ltp)),
               "low": min(float(ohlc["low"]), float(ltp)), "close": float(ltp)}
    fut = ((data.get("NSE_FNO") or {}).get(str(future_id)) or {}).get("last_price")
    return bar, (float(fut) if fut else None)


def with_today(history: pd.DataFrame, bar: dict | None) -> pd.DataFrame:
    """The history with today's bar (if any) on the end."""
    if not bar or history.empty:
        return history
    today = pd.Timestamp(now_ist().date()).tz_localize(IST)
    return pd.concat([history, pd.DataFrame([{"timestamp": today, **bar}])], ignore_index=True)


# ── signals ───────────────────────────────────────────────────────────────────

def detect_daily_signals(df: pd.DataFrame, key: str) -> list[dict]:
    """Every signal of moving-average strategy `key` on daily bars `df`, with daily levels: stop
    LONGTERM_ATR["stop"] × ATR and target LONGTERM_ATR["target"] × ATR from the close (the strategy's
    own intraday 1-2 % levels are replaced). Each signal carries its bar index ("bar") and the ATR."""
    if df is None or len(df) < 3:
        return []
    d = df.reset_index(drop=True)
    atr = talib.ATR(d["high"].values.astype(np.float64), d["low"].values.astype(np.float64),
                    d["close"].values.astype(np.float64), timeperiod=LONGTERM_ATR["period"])
    bar_of = {ts: i for i, ts in enumerate(d["timestamp"])}
    out = []
    for s in _DETECT[key](d):
        i = bar_of.get(s["time"])
        if i is None or np.isnan(atr[i]):
            continue
        entry, a, sign = float(d["close"].iloc[i]), float(atr[i]), 1 if s["type"] == "Bullish" else -1
        out.append({**s, "entry": round(entry, 2), "bar": i, "atr": round(a, 2),
                    "target": round(entry + sign * LONGTERM_ATR["target"] * a, 2),
                    "stop_loss": round(entry - sign * LONGTERM_ATR["stop"] * a, 2)})
    return out


def on_future(s: dict, price: float) -> dict:
    """An index signal moved onto the future: entered at `price`, the stop and target the same distances
    away as on the index."""
    return {**s, "index_entry": s["entry"], "entry": round(price, 2),
            "target": round(price + (s["target"] - s["entry"]), 2),
            "stop_loss": round(price + (s["stop_loss"] - s["entry"]), 2)}


def _alert_extra(key):
    def extra(s: dict) -> str:
        avgs = " | ".join(f"{label}: {s.get(col, '-')}" for col, label in _SHOWN[key])
        return (f"\n{LONGTERM_UNDERLYING} index {s.get('index_entry', '-')} | {avgs} | ATR(14): {s.get('atr', '-')}"
                f"\nDaily chart · held up to {LONGTERM_LIMITS['max_hold_days']} trading days")
    return extra


# ── the daily scan ────────────────────────────────────────────────────────────

def scan(book: bool = False) -> dict:
    """Today's signals on the index's daily chart, traded in the current future. book=True (the engine,
    once a day): the account takes or skips each and Telegram says which. book=False: display only (the
    Long Term page) — on a day the market is shut, the last trading day's signals at index levels."""
    now = now_ist()
    today = now.strftime("%Y-%m-%d")
    trading = _is_trading_day(now)
    found, errors, contract, fut_price = [], [], None, None
    try:
        contract = current_future()
        bar, fut_price = fetch_quotes(contract["security_id"]) if trading else (None, None)
        df = with_today(fetch_daily_history(), bar)
        LONGTERM.meta[contract["symbol"]] = _meta(contract)
        if df.empty:
            errors.append("no daily candles for the index")
        elif (book or trading) and (df["timestamp"].iloc[-1].strftime("%Y-%m-%d") != today or fut_price is None):
            errors.append("no quote for today's bar or the future yet")
        else:
            for key in strategy_keys():
                todays = [s for s in detect_daily_signals(df, key) if s["bar"] == len(df) - 1]
                if not todays:
                    continue
                name = STRATEGY_NAMES[key]
                if fut_price is None:  # display only on a shut market: the index levels, nothing to trade
                    found += [{**s, "strategy": name, "verdict": None, "reasons": [], "qty": None} for s in todays]
                    continue
                active, _ = _classify_generic([on_future(s, fut_price) for s in todays], fut_price,
                                              contract["symbol"], name, key, _alert_extra(key),
                                              book=LONGTERM if book else False)
                found += [{**s, "strategy": name} for s in active]
    except Exception as e:
        errors.append(str(e))
        print(f"  [longterm] {traceback.format_exc()}")
    decided = LONGTERM.decisions(today)
    for f in found:
        if "verdict" in f:
            continue
        rec = next((r for r in decided.values() if r["symbol"] == contract["symbol"] and r["strategy"] == f["strategy"]),
                   None)
        f.update(verdict=rec["verdict"] if rec else None, reasons=rec["reasons"] if rec else [],
                 qty=rec["qty"] if rec else None)
    result = {"at": now, "booked": book, "trading_day": trading, "contract": contract, "future_price": fut_price,
              "strategies": strategy_names(), "signals": found, "errors": errors}
    with _lock:
        _last_scan.clear()
        _last_scan.update(result)
    print(f"  [longterm] {contract['symbol'] if contract else LONGTERM_UNDERLYING}: {len(found)} signals"
          + (", booked" if book else "") + (f", errors: {errors}" if errors else ""))
    return result


def last_scan() -> dict:
    with _lock:
        return dict(_last_scan)


async def run_longterm_engine():
    """Async loop: scan(book=True) once per trading day, at LONGTERM_LIMITS["scan_at"] (or later, until
    the close, if the app starts after it). Start once from main.py."""
    print(f"  [longterm] Long-term engine started ({LONGTERM_UNDERLYING} futures, daily scan at "
          f"{LONGTERM_LIMITS['scan_at']}).")
    loop = asyncio.get_event_loop()
    done = None
    while True:
        await asyncio.sleep(30)
        now = now_ist()
        today = now.strftime("%Y-%m-%d")
        if done == today or not is_market_open() or now.time() < _hhmm(LONGTERM_LIMITS["scan_at"]):
            continue
        done = today
        try:
            await loop.run_in_executor(None, scan, True)
        except Exception as e:
            print(f"  [longterm] scan error: {e}\n{traceback.format_exc()}")


# ── exits ─────────────────────────────────────────────────────────────────────

def _monitor_tick() -> None:
    """Live prices of the future for the open trade: close it at its target or stop on the first tick
    there, and close it once past its holding period."""
    trades = [r for r in LONGTERM.open_trades() if r.get("security_id")]
    ws_feed.watch("longterm_positions", [(marketfeed.NSE_FNO, r["security_id"]) for r in trades])
    for r in trades:
        ltp = live_candles.last_price(_key(r["security_id"]), max_age=_TICK_MAX_AGE)
        if ltp is None:
            continue
        rec = LONGTERM.on_tick(r["key"], ltp)
        if rec:
            print(f"  [longterm monitor] {rec['symbol']} {rec['status']} at {rec['exit_price']:.2f} (tick {ltp:.2f})")
            _send_telegram(LONGTERM.closed_text(rec))
    for r in LONGTERM.square_off():
        print(f"  [longterm] time exit {r['symbol']} ({r['strategy']}) at {r['exit_price']:.2f}")


async def run_longterm_monitor():
    """Async loop: _monitor_tick() every MONITOR_SECONDS in market hours. Start once from main.py."""
    loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(MONITOR_SECONDS)
        if not is_market_open():
            continue
        try:
            await loop.run_in_executor(None, _monitor_tick)
        except Exception as e:
            print(f"  [longterm monitor] error: {e}\n{traceback.format_exc()}")


# ── backtest ──────────────────────────────────────────────────────────────────

def backtest_signals(df: pd.DataFrame, signals: list[dict], hold: int | None = None) -> list[dict]:
    """Walk the next `hold` daily bars after each signal (entered at its close), long or short: the stop
    first if a bar spans both, then the target, else out at the close of the last bar ("Time Exit"). A gap
    past a level fills at the open. Signals without `hold` bars after them yet are left out (still running)."""
    hold = hold or LONGTERM_LIMITS["max_hold_days"]
    trades = []
    for s in signals:
        i, buy = s["bar"], s["target"] > s["entry"]
        if i + hold >= len(df):
            continue
        status = exit_price = exit_time = None
        for j in range(i + 1, i + hold + 1):
            bar = df.iloc[j]
            o, hi, lo = float(bar["open"]), float(bar["high"]), float(bar["low"])
            if (lo <= s["stop_loss"]) if buy else (hi >= s["stop_loss"]):
                status, exit_price = "SL Hit", min(s["stop_loss"], o) if buy else max(s["stop_loss"], o)
            elif (hi >= s["target"]) if buy else (lo <= s["target"]):
                status, exit_price = "Target Hit", max(s["target"], o) if buy else min(s["target"], o)
            if status:
                exit_time = bar["timestamp"]
                break
        if not status:
            bar = df.iloc[i + hold]
            status, exit_price, exit_time = "Time Exit", float(bar["close"]), bar["timestamp"]
        trades.append({**s, "status": status, "exit_price": round(float(exit_price), 2), "exit_time": exit_time})
    return trades


def simulate_account(trades: list[dict], limits: dict = LONGTERM_LIMITS,
                     lot: int = LOT_SIZES[LONGTERM_UNDERLYING]) -> tuple[list[dict], dict]:
    """Run backtest trades through a paper account as the live one would: in entry order, one position at
    a time, whole lots sized to risk max_loss_per_trade at the stop, cut to the margin the balance allows,
    compounding net of futures charges. → (sized trades, {"skipped": n, "cut": n})."""
    balance, holding, out = float(limits["funds"]), None, []
    margin = float(limits.get("margin_pct") or 100) / 100
    report = {"skipped": 0, "cut": 0}
    for t in sorted(trades, key=lambda t: (t["time"], t["strategy"])):
        if holding and holding["exit_time"] <= t["time"]:  # the open position closed by now: it pays out
            balance += holding["net"]
            holding = None
        if holding:
            report["skipped"] += 1
            continue
        entry, buy = float(t["entry"]), t["target"] > t["entry"]
        risk = abs(entry - float(t["stop_loss"])) * lot
        want = math.floor(float(limits["max_loss_per_trade"]) / risk) if risk > 0 else 0
        cap = balance * float(limits.get("max_capital_pct") or 100) / 100
        lots = min(want, math.floor(max(cap, 0) / (entry * lot * margin)))
        if lots < 1:
            report["skipped"] += 1
            continue
        report["cut"] += lots < want
        qty = lots * lot
        b = calculate_brokerage(entry, float(t["exit_price"]), lot_size=1, quantity=qty, segment=limits["segment"],
                                short=not buy)
        capital = entry * qty * margin
        holding = {**t, "qty": qty, "side": "BUY" if buy else "SELL", "lot_size": lot, "gross": b["gross_pnl"],
                   "charges": b["total_charges"], "net": b["net_pnl"], "capital": capital, "funds_cut": lots < want,
                   "ret_pct": b["net_pnl"] / capital * 100, "charge_parts": {k: b[k] for k in _CHARGE_KEYS},
                   "trade_date": t["time"].strftime("%Y-%m-%d")}
        out.append(holding)
    return out, report


def run_backtest(days: int = 365) -> dict:
    """Every enabled strategy on the index's daily chart over the last `days` calendar days, sized
    through simulate_account() as trades in the future (the index price stands in for the future's)."""
    since = pd.Timestamp(now_ist().date()).tz_localize(IST) - pd.Timedelta(days=days)
    df = fetch_daily_history()
    if df.empty:
        raise RuntimeError("no daily candles for the index")
    raw = []
    for key in strategy_keys():
        sigs = [s for s in detect_daily_signals(df, key) if s["time"] >= since]
        raw += [{**t, "stock": GROUP, "strategy": STRATEGY_NAMES[key]} for t in backtest_signals(df, sigs)]
    sized, report = simulate_account(raw)
    return {"trades": sized, "signals": len(raw), "report": report, "since": since,
            "strategies": strategy_names(), "end_balance": float(LONGTERM_LIMITS["funds"]) + sum(t["net"] for t in sized)}
