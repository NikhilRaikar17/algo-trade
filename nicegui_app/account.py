"""
The live paper account: starting funds (config.RISK_LIMITS["funds"]) from a fixed start moment,
compounded with every closed trade's net P&L, i.e. after brokerage, STT, exchange, GST, SEBI and
stamp charges.

Its book (.live_book.json) holds one decision per live signal, made once, the first time the engine
sees the signal (open_signal): trade_desk.check() sizes it to risk the max loss at the stop and takes
or skips it against the account at that moment. A taken trade holds its capital until it hits its
target or stop (close_signal) or is squared off at RISK_LIMITS["square_off"] (square_off). Decisions
are never worked out again, so nothing changes after the fact. Only taken trades are alerted on
Telegram and count in the balance. Nothing here places an order.

The start moment and starting funds live in .live_account.json (created on first use, "now"), so the
balance survives restarts; reset_account() starts a fresh account (the book's older entries are kept
but no longer counted).
"""

import json
import os
import threading
from datetime import datetime

import pandas as pd

from backtest_metrics import _CHARGE_KEYS, inr, rupees_text
from brokerage import calculate_brokerage
from config import IST, RISK_LIMITS, now_ist
from trade_desk import SKIPPED, TAKEN, Book, _hhmm, check, signal_key, to_row

_FILE = os.path.join(os.path.dirname(__file__), ".live_account.json")
_BOOK_FILE = os.path.join(os.path.dirname(__file__), ".live_book.json")
_lock = threading.RLock()  # the engine thread and the Live Algos page both write the book


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
    """Signals that closed after the account started (normalized trades: exit_time is a Timestamp).
    For judging strategies on every signal; the account's own trades come from account_state()."""
    start = start_time()
    return [t for t in trades if t["exit_time"] >= start]


# ── the book ──────────────────────────────────────────────────────────────────

def _load_book() -> dict:
    try:
        with open(_BOOK_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_book(book: dict) -> None:
    tmp = _BOOK_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(book, f)
    os.replace(tmp, _BOOK_FILE)


def _ts(s):
    return pd.Timestamp(s).tz_convert(IST) if s else None


def _counted(book: dict) -> list[dict]:
    """Book entries made since the account started, oldest first."""
    start = start_time()
    recs = [r for r in book.values() if _ts(r["decided_at"]) >= start]
    return sorted(recs, key=lambda r: r["decided_at"])


def _pnl(r: dict, exit_price: float) -> dict:
    b = calculate_brokerage(r["entry"], exit_price, lot_size=1, quantity=r["qty"],
                            segment="equity_intraday", short=r["side"] == "SELL")
    return {"gross": b["gross_pnl"], "charges": b["total_charges"], "net": b["net_pnl"],
            "charge_parts": {k: b[k] for k in _CHARGE_KEYS}}


def _is_open(r: dict) -> bool:
    return r["verdict"] == TAKEN and r["status"] == "Open"


def _holdings(recs: list[dict], today: str) -> Book:
    initial = float(get_settings()["initial"])
    open_ = [r for r in recs if _is_open(r)]
    taken_today = [r for r in recs if r["verdict"] == TAKEN and r["trade_date"] == today]
    return Book(
        balance=initial + sum(r["net"] for r in recs if r["verdict"] == TAKEN and r["status"] != "Open"),
        open_capital=sum(r["capital"] for r in open_),
        open_symbols={r["symbol"] for r in open_},
        taken_today=len(taken_today),
        risk_today=sum(r["max_loss"] for r in taken_today),
    )


def _plan(trade: dict) -> dict:
    """The signal without the engine's running price fields."""
    return {k: v for k, v in trade.items() if k not in ("unrealized_pnl", "exit_price")}


def _record(row, trade: dict, now: datetime, status: str | None) -> dict:
    return {
        "key": row.key, "strategy": row.strategy, "symbol": row.symbol, "signal": str(trade.get("signal", "")),
        "side": row.side, "time": pd.Timestamp(row.signal_time).isoformat(),
        "decided_at": now.isoformat(timespec="seconds"), "trade_date": now.strftime("%Y-%m-%d"),
        "entry": row.entry, "stop_loss": row.stop, "target": row.target,
        "verdict": row.verdict, "reasons": row.reasons, "warnings": row.warnings,
        "qty": row.qty, "capital": row.capital, "max_loss": row.max_loss,
        "risk_per_share": row.risk_per_share, "reward_risk": row.reward_risk,
        "status": status, "last_price": row.current_price,
        "exit_price": None, "exit_time": None, "gross": 0.0, "charges": 0.0, "net": 0.0,
    }


def open_signal(trade: dict, strategy: str, symbol: str, price: float,
                now: datetime | None = None) -> tuple[dict | None, bool]:
    """Take or skip a signal the engine sees open at `price`. → (book entry, decided just now).
    The decision is made once; later calls only return it."""
    now = now or now_ist()
    key = signal_key(trade, strategy, symbol)
    if key is None:
        return None, False
    with _lock:
        book = _load_book()
        if key in book:
            return book[key], False
        row = to_row(_plan(trade), strategy, symbol)
        if row is None:
            return None, False
        row.current_price = price
        check(row, _holdings(_counted(book), now.strftime("%Y-%m-%d")), RISK_LIMITS, now)
        book[key] = rec = _record(row, trade, now, "Open" if row.verdict == TAKEN else None)
        _save_book(book)
    return rec, True


def mark_price(trade: dict, strategy: str, symbol: str, price: float) -> None:
    """Latest price of an open taken trade, for unrealised P&L and the square-off."""
    key = signal_key(trade, strategy, symbol)
    with _lock:
        book = _load_book()
        r = book.get(key)
        if r and _is_open(r) and r["last_price"] != price:
            r["last_price"] = price
            _save_book(book)


def _close(r: dict, exit_price: float, status: str, now: datetime) -> None:
    r.update(status=status, exit_price=float(exit_price), last_price=float(exit_price),
             exit_time=now.isoformat(timespec="seconds"), **_pnl(r, float(exit_price)))


def close_signal(trade: dict, strategy: str, symbol: str, exit_price: float, status: str,
                 now: datetime | None = None) -> dict | None:
    """The signal hit its target or stop. → its book entry if this closed a taken trade, else None.
    A signal never seen open (already past its target or stop at first sight) is booked as skipped."""
    now = now or now_ist()
    key = signal_key(trade, strategy, symbol)
    if key is None:
        return None
    with _lock:
        book = _load_book()
        r = book.get(key)
        if r is None:
            row = to_row(_plan(trade), strategy, symbol)
            if row is None:
                return None
            row.verdict, row.reasons = SKIPPED, ["hit its target or stop before the engine saw it open"]
            book[key] = _record(row, trade, now, None)
            _save_book(book)
            return None
        if not _is_open(r):
            return None
        _close(r, exit_price, status, now)
        _save_book(book)
    return r


def square_off(now: datetime | None = None) -> list[dict]:
    """Close every open taken trade at its last price once it is RISK_LIMITS["square_off"], or if it was
    left open on an earlier day (the app was down), and Telegram each one. → the trades closed."""
    from state import _send_telegram  # noqa: PLC0415 — state pulls in the Dhan client; keep imports light

    now = now or now_ist()
    today, late = now.strftime("%Y-%m-%d"), now.time() >= _hhmm(RISK_LIMITS["square_off"])
    closed = []
    with _lock:
        book = _load_book()
        for r in book.values():
            if _is_open(r) and (late or r["trade_date"] < today):
                _close(r, r["last_price"] or r["entry"], "Day Close", now)
                closed.append(r)
        if closed:
            _save_book(book)
    for r in closed:
        _send_telegram(f"SQUARED OFF [{r['strategy']}] | {r['symbol']}\n{r['side']} {r['qty']:,} @ {r['entry']:,.2f} "
                       f"→ {r['exit_price']:,.2f} at {RISK_LIMITS['square_off']}\nPnL: {pnl_text(r)}")
    return closed


def size_text(r: dict) -> str:
    """'BUY 10 × ₹2,303.70 = ₹23,037 · risks ₹230 at the stop' for alerts."""
    return (f"{r['side']} {r['qty']:,} × ₹{r['entry']:,.2f} = ₹{inr(r['capital'])} · "
            f"risks ₹{inr(r['max_loss'])} at the stop")


def pnl_text(r: dict) -> str:
    return f"{rupees_text(r['net'])} net on {r['qty']:,} shares (after ₹{inr(r['charges'])} charges)"


def decisions(day: str | None = None) -> dict:
    """{signal key: book entry} decided on `day` (default today)."""
    day = day or now_ist().strftime("%Y-%m-%d")
    with _lock:
        return {k: r for k, r in _load_book().items() if r["trade_date"] == day}


# ── account state ─────────────────────────────────────────────────────────────

def _as_trade(r: dict) -> dict:
    """A closed taken trade in the shape size_trades() gives the P&L widgets."""
    entry, exit_px = float(r["entry"]), float(r["exit_price"])
    return {
        **r, "stock": r["symbol"], "time": _ts(r["time"]), "exit_time": _ts(r["exit_time"]),
        "pnl": (exit_px - entry) if r["side"] == "BUY" else (entry - exit_px),
        "funds_cut": any("size cut" in w for w in r["warnings"]),
        "ret_pct": r["net"] / r["capital"] * 100 if r["capital"] else 0.0,
    }


def account_state(now: datetime | None = None) -> dict:
    """Balance, funds and trades from the book.

    Returns initial, start, balance (initial + realized net), realized (net), gross, charges, trades,
    wins, losses, return_pct, in_positions (capital of open trades), free, unrealized (before charges),
    open, sized (closed taken trades, P&L-widget shape), positions (open taken book entries, with
    "unrealized"), skipped_today (today's skipped book entries)."""
    from backtest_metrics import summarize  # noqa: PLC0415

    now = now or now_ist()
    square_off(now)
    with _lock:
        recs = _counted(_load_book())
    settings = get_settings()
    initial = float(settings["initial"])
    sized = [_as_trade(r) for r in recs if r["verdict"] == TAKEN and r["status"] != "Open"]
    s = summarize(sized)
    positions = []
    for r in recs:
        if _is_open(r):
            price = float(r["last_price"] or r["entry"])
            move = (price - r["entry"]) if r["side"] == "BUY" else (r["entry"] - price)
            positions.append({**r, "stock": r["symbol"], "time": _ts(r["time"]), "unrealized": move * r["qty"]})
    balance = initial + s["net"]
    in_positions = sum(p["capital"] for p in positions)
    today = now.strftime("%Y-%m-%d")
    return {
        "initial": initial, "start": start_time(), "balance": balance,
        "realized": s["net"], "gross": s["gross"], "charges": s["charges"],
        "trades": s["trades"], "wins": s["wins"], "losses": s["losses"],
        "return_pct": (balance - initial) / initial * 100,
        "in_positions": in_positions, "free": max(balance - in_positions, 0.0),
        "unrealized": sum(p["unrealized"] for p in positions), "open": len(positions),
        "sized": sized, "positions": positions,
        "skipped_today": [{**r, "stock": r["symbol"]} for r in recs
                          if r["verdict"] == SKIPPED and r["trade_date"] == today],
    }


def current_state() -> dict:
    return account_state()
