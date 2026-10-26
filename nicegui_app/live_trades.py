"""
The live engine's trades, cleaned up for P&L: used by the Live P&L page and the 3:30 PM Telegram summary.

Completed trades come from .trade_history.json (state.save_completed_trade) plus any of today's that
are still only in the engine's memory; open positions come from the engine. backtest_metrics then
keeps one position per stock and strategy, exactly as Backtest P&L does.
"""

import pandas as pd

from backtest_metrics import finalize_trades
from config import IST, now_ist
from pnl import collect_all_trades
from state import load_trade_history
from strategy_registry import get_live_strategy_names


def _to_ts(v):
    if v is None or v == "":
        return None
    try:
        ts = pd.Timestamp(v)
    except (TypeError, ValueError):
        return None
    return ts.tz_localize(IST) if ts.tzinfo is None else ts


def normalize(t: dict) -> dict:
    """Copy of a live trade with stock / time / exit_time / trade_date filled in. Records saved before
    times were stored get the session open/close and approx_time=True (no overlap check, no clock time)."""
    r = dict(t)
    r["stock"] = r.get("symbol") or r.get("stock") or ""
    entry_t = _to_ts(r.get("time") or (r.get("D") or {}).get("time"))
    exit_t = _to_ts(r.get("exit_time"))
    if entry_t is None or exit_t is None:
        day = pd.Timestamp(r.get("trade_date") or now_ist().strftime("%Y-%m-%d")).tz_localize(IST)
        entry_t = entry_t or day + pd.Timedelta(hours=9, minutes=15)
        exit_t = exit_t or day + pd.Timedelta(hours=15, minutes=30)
        r["approx_time"] = True
    r["time"], r["exit_time"] = entry_t, exit_t
    r["trade_date"] = r.get("trade_date") or entry_t.strftime("%Y-%m-%d")
    return r


def merge_completed(mem_completed, hist_completed):
    """History is the record; add today's in-memory trades that aren't saved yet (whole trade kept)."""
    result = list(hist_completed)
    today = now_ist().strftime("%Y-%m-%d")
    for t in mem_completed:
        saved = any(
            r.get("strategy") == t.get("strategy") and r.get("symbol") == t.get("symbol")
            and str(r.get("signal")) == str(t.get("signal"))
            and abs(float(r.get("entry", 0)) - float(t.get("entry", 0))) < 0.01
            for r in hist_completed
        )
        if not saved:
            result.append({**t, "trade_date": t.get("trade_date") or today})
    return result


def open_positions(active: list[dict], completed: list[dict]) -> tuple[list[dict], int]:
    """Active signals an account would actually hold: the first per stock and strategy, and only if
    no counted trade on that stock/strategy was still open at that moment. → (kept, overlapping)."""
    busy: dict[tuple, list] = {}
    for t in completed:
        if not t.get("approx_time"):
            busy.setdefault((t["stock"], t["strategy"]), []).append((t["time"], t["exit_time"]))
    kept, overlap, holding = [], 0, set()
    for t in sorted(active, key=lambda t: t["time"]):
        lane = (t["stock"], t["strategy"])
        if lane in holding or any(s <= t["time"] < e for s, e in busy.get(lane, [])):
            overlap += 1
            continue
        holding.add(lane)
        kept.append(t)
    return kept, overlap


def load_live_trades() -> tuple[list[dict], list[dict], dict]:
    """(completed, open positions, notes) for the strategies switched on for Live.
    notes: overlap (signals not counted), broken (records without prices), approx (no saved times)."""
    live_names = get_live_strategy_names()
    all_active, mem_completed = collect_all_trades()
    hist = [t for t in load_trade_history() if t.get("strategy") in live_names]
    merged = [normalize(t) for t in merge_completed(mem_completed, hist)]
    usable = [t for t in merged if float(t.get("entry") or 0) > 0 and float(t.get("exit_price") or 0) > 0]
    completed, ex = finalize_trades(usable, now_ist())
    active = [normalize(t) for t in all_active if t.get("strategy") in live_names and float(t.get("entry") or 0) > 0]
    positions, open_overlap = open_positions(active, completed)
    return completed, positions, {
        "overlap": ex["overlap"] + open_overlap,
        "broken": len(merged) - len(usable),
        "approx": sum(1 for t in completed if t.get("approx_time")),
    }
