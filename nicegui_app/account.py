"""
The live paper account: starting funds (config.RISK_LIMITS["funds"]) from a fixed start moment,
compounded with every closed live trade's net P&L, i.e. after brokerage, STT, exchange, GST,
SEBI and stamp charges.

Each trading day opens with the balance so far; trades are sized to risk the max loss at the stop
and cut to the free balance (backtest_metrics.size_trades). Positions still open hold their capital,
so free = balance − capital in open positions. Nothing here places an order.

The start moment and starting funds live in .live_account.json (created on first use, "now"), so the
balance survives restarts; reset_account() starts a fresh account.
"""

import json
import os
from datetime import datetime

import pandas as pd

from backtest_metrics import DEFAULT_MODE, DEFAULT_SIZING, size_open_positions, size_trades, summarize
from config import IST, RISK_LIMITS, now_ist

_FILE = os.path.join(os.path.dirname(__file__), ".live_account.json")


def get_settings() -> dict:
    """{"start": ISO datetime, "initial": ₹}. Creates the account (starting now) on first use."""
    try:
        with open(_FILE, "r") as f:
            s = json.load(f)
        if s.get("start") and s.get("initial"):
            return s
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return reset_account()


def reset_account(initial: float | None = None) -> dict:
    """Start a fresh account now with `initial` ₹ (default RISK_LIMITS["funds"])."""
    s = {"start": now_ist().isoformat(timespec="seconds"), "initial": float(initial or RISK_LIMITS["funds"])}
    with open(_FILE, "w") as f:
        json.dump(s, f)
    return s


def start_time() -> datetime:
    ts = pd.Timestamp(get_settings()["start"])
    return ts.tz_localize(IST) if ts.tzinfo is None else ts


def in_account(trades: list[dict]) -> list[dict]:
    """Trades that closed after the account started (normalized trades: exit_time is a Timestamp)."""
    start = start_time()
    return [t for t in trades if t["exit_time"] >= start]


def account_state(completed: list[dict], positions: list[dict]) -> dict:
    """Balance and funds for normalized live trades (live_trades.load_live_trades()).

    Returns initial, start, balance (initial + realized net), realized (net), gross, charges, trades,
    wins, losses, return_pct, in_positions (capital of open positions), free, unrealized, open, unfunded,
    sized (the account's closed trades, sized and compounded), report (size_trades' funds report),
    before_start (closed trades from before the account started, not counted)."""
    settings = get_settings()
    initial = float(settings["initial"])
    mode, amount = DEFAULT_MODE, DEFAULT_SIZING[DEFAULT_MODE]
    report: dict = {}
    sized = size_trades(in_account(completed), mode, amount, initial, report, compound=True)
    s = summarize(sized)
    balance = initial + s["net"]
    start = start_time()
    held = [(t, q) for t, q in size_open_positions([p for p in positions if p["time"] >= start],
                                                    mode, amount, balance)]
    in_positions = sum(float(t["entry"]) * q for t, q in held)
    unrealized = sum(float(t.get("unrealized_pnl", 0) or 0) * q for t, q in held)
    return {
        "initial": initial, "start": start, "balance": balance,
        "realized": s["net"], "gross": s["gross"], "charges": s["charges"],
        "trades": s["trades"], "wins": s["wins"], "losses": s["losses"],
        "return_pct": (balance - initial) / initial * 100,
        "in_positions": in_positions, "free": max(balance - in_positions, 0.0),
        "unrealized": unrealized, "open": sum(1 for _, q in held if q > 0),
        "unfunded": sum(1 for _, q in held if q < 1),
        "sized": sized, "report": report,
        "before_start": len(completed) - len(in_account(completed)),
    }


def current_state() -> dict:
    """account_state() for the engine's trades right now."""
    from live_trades import load_live_trades   # noqa: PLC0415 — live_trades imports pnl, which imports us lazily
    completed, positions, _ = load_live_trades()
    return account_state(completed, positions)
