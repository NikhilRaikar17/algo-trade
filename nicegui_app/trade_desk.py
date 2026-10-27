"""
trade_desk.py — size a live signal to the max loss per trade and check it against the risk limits
(config.RISK_LIMITS). Pure logic, no I/O.

account.open_signal() calls check() once, the first time the engine sees a signal, with the account
as it is at that moment; the verdict (TAKEN / SKIPPED) is saved and never worked out again.
pages/trade_desk.py shows those saved decisions next to today's signals.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

import pandas as pd

from brokerage import calculate_brokerage

TAKEN, SKIPPED = "TAKEN", "SKIPPED"


@dataclass
class DeskRow:
    key: str
    symbol: str
    strategy: str
    side: str                 # BUY / SELL
    signal_time: datetime     # close time of the signal bar (when the entry is valid)
    entry: float
    stop: float
    target: float
    status: str               # Active / Target Hit / SL Hit
    current_price: float | None = None
    risk_per_share: float = 0.0
    reward_risk: float = 0.0
    qty: int = 0
    capital: float = 0.0
    max_loss: float = 0.0
    verdict: str = ""         # TAKEN / SKIPPED; "" = the engine hasn't decided it
    reasons: list = field(default_factory=list)   # why it was skipped
    warnings: list = field(default_factory=list)  # shown, never skip
    decided_at: datetime | None = None
    lot_size: int = 1         # units per lot: qty is a whole number of lots (options), 1 for shares
    group: str = ""           # holding one position per group, e.g. "NIFTY options" ("" = per symbol)


@dataclass
class Book:
    """What the account holds when a signal is checked."""
    balance: float                 # starting funds + net P&L of every closed trade
    open_capital: float = 0.0      # capital of taken trades still open
    open_symbols: set = field(default_factory=set)   # symbols and groups of open trades
    taken_today: int = 0
    day_stopped: str = ""          # why trading is over for today ("" = still trading)


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def signal_bar_time(trade: dict):
    """Start time of the signal bar. Most strategies stamp it as "time"; ABCD on the D swing point."""
    ts = trade.get("time") or (trade.get("D") or {}).get("time")
    return pd.Timestamp(ts) if ts is not None else None


def signal_key(trade: dict, strategy: str, symbol: str) -> str | None:
    """One id per signal, shared by the account's book and the Trade Desk."""
    ts = signal_bar_time(trade)
    return f"{strategy}|{symbol}|{ts.isoformat()}" if ts is not None else None


def to_row(t: dict, strategy: str, symbol: str, status: str = "Active", bar_minutes: int = 5) -> DeskRow | None:
    ts = signal_bar_time(t)
    if ts is None or not all(t.get(k) is not None for k in ("entry", "stop_loss", "target")):
        return None
    entry, stop, target = float(t["entry"]), float(t["stop_loss"]), float(t["target"])
    side = "BUY" if target > entry else "SELL"
    price = None
    if "unrealized_pnl" in t:  # active trades carry P&L at the last price
        pnl = float(t["unrealized_pnl"])
        price = entry + pnl if side == "BUY" else entry - pnl
    elif t.get("exit_price") is not None:
        price = float(t["exit_price"])
    return DeskRow(
        key=signal_key(t, strategy, symbol), symbol=symbol, strategy=strategy, side=side,
        signal_time=(ts + timedelta(minutes=bar_minutes)).to_pydatetime(),
        entry=entry, stop=stop, target=target, status=status, current_price=price,
    )


def build_rows(active: list[dict], completed: list[dict], decisions: dict | None = None) -> list[DeskRow]:
    """Today's signals as desk rows, oldest first, each with the account's saved decision (if any)."""
    decisions = decisions or {}
    rows = []
    for status_default, trades in (("Active", active), (None, completed)):
        for t in trades:
            r = to_row(t, t.get("strategy", "?"), t.get("symbol", "?"), status_default or t.get("status", "Closed"))
            if r is None:
                continue
            d = decisions.get(r.key)
            if d:
                r.verdict, r.reasons, r.warnings = d["verdict"], list(d["reasons"]), list(d["warnings"])
                r.qty, r.capital, r.max_loss = d["qty"], d["capital"], d["max_loss"]
                r.risk_per_share, r.reward_risk = d["risk_per_share"], d["reward_risk"]
                r.decided_at = pd.Timestamp(d["decided_at"]).to_pydatetime()
                if d["verdict"] == TAKEN and d["status"] == "Day Close":
                    r.status = "Squared off"
            rows.append(r)
    rows.sort(key=lambda r: (r.signal_time, r.symbol, r.strategy))
    return rows


def check(r: DeskRow, book: Book, limits: dict, now: datetime) -> DeskRow:
    """Size `r` and take or skip it against `limits`, given what the account holds at `now`."""
    r.reasons, r.warnings = [], []
    max_loss = float(limits["max_loss_per_trade"])
    r.risk_per_share = round(abs(r.entry - r.stop), 2)
    reward = abs(r.target - r.entry)

    stop_ok = (r.stop < r.entry) if r.side == "BUY" else (r.stop > r.entry)
    if r.risk_per_share <= 0 or not stop_ok:
        r.reasons.append("stop is missing or on the wrong side of the entry")
        r.verdict = SKIPPED
        return r

    r.reward_risk = round(reward / r.risk_per_share, 2)
    # sized in whole lots: a lot is one share for stocks, lot_size units for options
    lot = max(int(r.lot_size or 1), 1)
    unit = "share" if lot == 1 else "lot"
    lot_risk, lot_cost = r.risk_per_share * lot, r.entry * lot
    want = math.floor(max_loss / lot_risk)
    free = max(book.balance - book.open_capital, 0.0)
    cap = book.balance * float(limits.get("max_capital_pct") or 100) / 100
    lots = min(want, math.floor(min(free, cap) / lot_cost))

    if want < 1:
        r.reasons.append(f"one {unit} risks ₹{lot_risk:,.2f}, over your ₹{max_loss:,.0f} max loss per trade")
    elif free < lot_cost:
        r.reasons.append(f"no free funds: ₹{book.open_capital:,.0f} of your ₹{book.balance:,.0f} is in open positions")
    elif lots < 1:
        r.reasons.append(f"one {unit} costs more than the ₹{cap:,.0f} per-trade cap")
    elif lots < want:
        why = "free funds" if free < cap else f"₹{cap:,.0f} per-trade cap"
        cut_risk = lots * lot_risk
        if cut_risk < max_loss * float(limits.get("min_risk_pct") or 0) / 100:
            r.reasons.append(f"the {why} only buys {lots} {unit}{'s' if lots != 1 else ''}, risking ₹{cut_risk:,.0f}: "
                             f"under {limits['min_risk_pct']}% of your ₹{max_loss:,.0f}")
        else:
            r.warnings.append(f"size cut from {want} to {lots} {unit}{'s' if lots != 1 else ''} by the {why} "
                              f"(risks ₹{cut_risk:,.0f}, not ₹{max_loss:,.0f})")
    r.qty = max(lots, 0) * lot
    r.capital = round(r.qty * r.entry, 2)
    r.max_loss = round(r.qty * r.risk_per_share, 2)

    if limits.get("reward_risk_after_charges") and r.qty:
        # options: ~₹90 of charges a round trip is a big slice of a small move, so judge R:R net of them
        seg, short = limits.get("segment", "equity_intraday"), r.side == "SELL"
        won = calculate_brokerage(r.entry, r.target, 1, r.qty, seg, short=short)
        lost = calculate_brokerage(r.entry, r.stop, 1, r.qty, seg, short=short)
        net_rr = won["net_pnl"] / -lost["net_pnl"] if lost["net_pnl"] < 0 else 0.0
        if net_rr < limits["min_reward_risk"]:
            r.reasons.append(f"reward:risk after charges is {net_rr:.2f} (₹{won['net_pnl']:,.0f} at the target, "
                             f"₹{lost['net_pnl']:,.0f} at the stop), under your minimum "
                             f"{limits['min_reward_risk']:.2f}")
    elif r.reward_risk < limits["min_reward_risk"]:
        r.reasons.append(f"reward:risk {r.reward_risk:.2f} is under your minimum {limits['min_reward_risk']:.2f}")
    t = now.time()
    if t < _hhmm(limits["no_entries_before"]) or t > _hhmm(limits["no_entries_after"]):
        r.reasons.append(f"{t:%H:%M} is outside your entry window "
                         f"{limits['no_entries_before']}–{limits['no_entries_after']}")
    if r.symbol in book.open_symbols:
        r.reasons.append(f"already holding {r.symbol}")
    elif r.group and r.group in book.open_symbols:
        r.reasons.append(f"already holding {r.group}")
    if book.day_stopped:
        r.reasons.append(f"trading stopped for today: {book.day_stopped}")
    max_trades = limits.get("max_trades_per_day")
    if max_trades and book.taken_today >= max_trades:
        r.reasons.append(f"daily limit reached: {book.taken_today} of {max_trades} trades taken")

    if r.current_price is not None:
        moved = (r.current_price - r.entry) if r.side == "BUY" else (r.entry - r.current_price)
        if reward > 0 and moved / reward >= 0.5:
            r.warnings.append(f"price already covered {moved / reward * 100:.0f}% of the way to the target")

    r.verdict = SKIPPED if r.reasons else TAKEN
    return r


def day_stop(closed: list[dict], limits: dict) -> str:
    """Why trading is over for the day, from the day's closed trades ({"net", "exit_time"}), or "".
    Once a limit is hit the day stays stopped, whatever the trades still open do afterwards."""
    streak, total = 0, 0.0
    max_streak, max_loss = limits.get("max_losing_streak"), limits.get("max_daily_loss")
    for t in sorted(closed, key=lambda t: t["exit_time"]):
        total += t["net"]
        streak = streak + 1 if t["net"] < 0 else 0
        if max_streak and streak >= max_streak:
            return f"{streak} losing trades in a row"
        if max_loss and total <= -max_loss:
            return f"down ₹{-total:,.0f} today, the daily loss limit is ₹{max_loss:,.0f}"
    return ""


def day_summary(rows: list[DeskRow], limits: dict) -> dict:
    taken = [r for r in rows if r.verdict == TAKEN]
    return {
        "signals": len(rows),
        "passed": len(taken),
        "blocked": sum(1 for r in rows if r.verdict == SKIPPED),
        "pending": sum(1 for r in rows if not r.verdict),
        "trades_used": len(taken),
        "loss_used": round(sum(r.max_loss for r in taken), 2),
        "capital_passed": round(sum(r.capital for r in taken), 2),
    }
