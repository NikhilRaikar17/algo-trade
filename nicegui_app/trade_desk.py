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


@dataclass
class Book:
    """What the account holds when a signal is checked."""
    balance: float                 # starting funds + net P&L of every closed trade
    open_capital: float = 0.0      # capital of taken trades still open
    open_symbols: set = field(default_factory=set)
    taken_today: int = 0
    risk_today: float = 0.0        # sum of the max losses of today's taken trades


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
    want = math.floor(max_loss / r.risk_per_share)
    free = max(book.balance - book.open_capital, 0.0)
    cap = book.balance * float(limits.get("max_capital_pct") or 100) / 100
    r.qty = min(want, math.floor(min(free, cap) / r.entry))

    if want < 1:
        r.reasons.append(f"one share risks ₹{r.risk_per_share:,.2f}, over your ₹{max_loss:,.0f} max loss per trade")
    elif free < r.entry:
        r.reasons.append(f"no free funds: ₹{book.open_capital:,.0f} of your ₹{book.balance:,.0f} is in open positions")
    elif r.qty < 1:
        r.reasons.append(f"one share costs more than the ₹{cap:,.0f} per-trade cap")
    elif r.qty < want:
        why = "free funds" if free < cap else f"₹{cap:,.0f} per-trade cap"
        cut_risk = r.qty * r.risk_per_share
        if cut_risk < max_loss * float(limits.get("min_risk_pct") or 0) / 100:
            r.reasons.append(f"the {why} only buys {r.qty} shares, risking ₹{cut_risk:,.0f}: "
                             f"under {limits['min_risk_pct']}% of your ₹{max_loss:,.0f}")
        else:
            r.warnings.append(f"size cut from {want} to {r.qty} shares by the {why} "
                              f"(risks ₹{cut_risk:,.0f}, not ₹{max_loss:,.0f})")
    r.qty = max(r.qty, 0)
    r.capital = round(r.qty * r.entry, 2)
    r.max_loss = round(r.qty * r.risk_per_share, 2)

    if r.reward_risk < limits["min_reward_risk"]:
        r.reasons.append(f"reward:risk {r.reward_risk:.2f} is under your minimum {limits['min_reward_risk']:.2f}")
    t = now.time()
    if t < _hhmm(limits["no_entries_before"]) or t > _hhmm(limits["no_entries_after"]):
        r.reasons.append(f"{t:%H:%M} is outside your entry window "
                         f"{limits['no_entries_before']}–{limits['no_entries_after']}")
    if r.symbol in book.open_symbols:
        r.reasons.append(f"already holding {r.symbol}")
    if book.taken_today >= limits["max_trades_per_day"]:
        r.reasons.append(f"daily limit reached: {book.taken_today} of {limits['max_trades_per_day']} trades taken")
    elif book.risk_today + r.max_loss > limits["max_daily_loss"]:
        r.reasons.append(f"daily loss limit: ₹{book.risk_today:,.0f} already at risk + ₹{r.max_loss:,.0f} "
                         f"is over ₹{limits['max_daily_loss']:,.0f}")

    if r.current_price is not None:
        moved = (r.current_price - r.entry) if r.side == "BUY" else (r.entry - r.current_price)
        if reward > 0 and moved / reward >= 0.5:
            r.warnings.append(f"price already covered {moved / reward * 100:.0f}% of the way to the target")

    r.verdict = SKIPPED if r.reasons else TAKEN
    return r


def day_summary(rows: list[DeskRow], limits: dict) -> dict:
    taken = [r for r in rows if r.verdict == TAKEN]
    return {
        "signals": len(rows),
        "passed": len(taken),
        "blocked": sum(1 for r in rows if r.verdict == SKIPPED),
        "pending": sum(1 for r in rows if not r.verdict),
        "trades_used": len(taken),
        "trades_limit": limits["max_trades_per_day"],
        "loss_used": round(sum(r.max_loss for r in taken), 2),
        "loss_limit": limits["max_daily_loss"],
        "capital_passed": round(sum(r.capital for r in taken), 2),
    }
