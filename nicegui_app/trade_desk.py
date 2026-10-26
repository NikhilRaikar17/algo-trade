"""
trade_desk.py — size every live signal to the max loss per trade and run it through the
risk limits (config.RISK_LIMITS). Pure logic, no I/O: pages/trade_desk.py feeds it the
engine's signals and shows the result.

Nothing here places an order. Daily limits assume every PASSED signal is taken, so signals
are checked in signal-time order and each PASS uses up a trade and its max loss.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

import pandas as pd


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
    verdict: str = ""         # PASS / BLOCK
    reasons: list = field(default_factory=list)   # why it was blocked
    warnings: list = field(default_factory=list)  # shown, never block


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def signal_bar_time(trade: dict):
    """Start time of the signal bar. Most strategies stamp it as "time"; ABCD on the D swing point."""
    ts = trade.get("time") or (trade.get("D") or {}).get("time")
    return pd.Timestamp(ts) if ts is not None else None


def build_rows(active: list[dict], completed: list[dict], bar_minutes: int = 5) -> list[DeskRow]:
    """Turn the engine's active/completed trades into desk rows, oldest signal first."""
    rows = []
    for status_default, trades in (("Active", active), (None, completed)):
        for t in trades:
            ts = signal_bar_time(t)
            if ts is None or not all(k in t for k in ("entry", "stop_loss", "target")):
                continue
            entry, stop, target = float(t["entry"]), float(t["stop_loss"]), float(t["target"])
            side = "BUY" if target > entry else "SELL"
            price = None
            if "unrealized_pnl" in t:  # active trades carry P&L at the last price
                pnl = float(t["unrealized_pnl"])
                price = entry + pnl if side == "BUY" else entry - pnl
            elif t.get("exit_price") is not None:
                price = float(t["exit_price"])
            rows.append(DeskRow(
                key=f"{t.get('strategy', '?')}|{t.get('symbol', '?')}|{ts.isoformat()}",
                symbol=t.get("symbol", "?"), strategy=t.get("strategy", "?"), side=side,
                signal_time=(ts + timedelta(minutes=bar_minutes)).to_pydatetime(),
                entry=entry, stop=stop, target=target,
                status=status_default or t.get("status", "Closed"), current_price=price,
            ))
    rows.sort(key=lambda r: (r.signal_time, r.symbol, r.strategy))
    return rows


def evaluate(rows: list[DeskRow], limits: dict) -> list[DeskRow]:
    """Size each row and PASS/BLOCK it against `limits`, in signal-time order."""
    before, after = _hhmm(limits["no_entries_before"]), _hhmm(limits["no_entries_after"])
    max_loss = float(limits["max_loss_per_trade"])
    passed_count, passed_loss = 0, 0.0
    open_passed = set()  # (symbol, side) already passed and not closed

    for r in rows:
        r.reasons, r.warnings = [], []
        r.risk_per_share = round(abs(r.entry - r.stop), 2)
        reward = abs(r.target - r.entry)

        stop_ok = (r.stop < r.entry) if r.side == "BUY" else (r.stop > r.entry)
        if r.risk_per_share <= 0 or not stop_ok:
            r.reasons.append("stop is missing or on the wrong side of the entry")
            r.verdict = "BLOCK"
            continue

        r.reward_risk = round(reward / r.risk_per_share, 2)
        r.qty = math.floor(max_loss / r.risk_per_share)
        r.capital = round(r.qty * r.entry, 2)
        r.max_loss = round(r.qty * r.risk_per_share, 2)

        if r.qty < 1:
            r.reasons.append(
                f"one share risks ₹{r.risk_per_share:,.2f}, over your ₹{max_loss:,.0f} max loss per trade"
            )
        if r.reward_risk < limits["min_reward_risk"]:
            r.reasons.append(f"reward:risk {r.reward_risk:.2f} is under your minimum {limits['min_reward_risk']:.2f}")
        t = r.signal_time.time()
        if t < before or t > after:
            r.reasons.append(
                f"signal at {t.strftime('%H:%M')} is outside your entry window "
                f"{limits['no_entries_before']}–{limits['no_entries_after']}"
            )
        if (r.symbol, r.side) in open_passed:
            r.reasons.append(f"a {r.side} on {r.symbol} already passed today and is still open")
        if passed_count >= limits["max_trades_per_day"]:
            r.reasons.append(f"daily limit reached: {passed_count} of {limits['max_trades_per_day']} trades already passed")
        elif passed_loss + r.max_loss > limits["max_daily_loss"]:
            r.reasons.append(
                f"daily loss limit: ₹{passed_loss:,.0f} already at risk + ₹{r.max_loss:,.0f} "
                f"is over ₹{limits['max_daily_loss']:,.0f}"
            )

        # Warnings: shown next to the verdict, never block
        if r.current_price is not None and r.status == "Active":
            moved = (r.current_price - r.entry) if r.side == "BUY" else (r.entry - r.current_price)
            if reward > 0 and moved / reward >= 0.5:
                r.warnings.append(f"price already covered {moved / reward * 100:.0f}% of the way to the target")

        r.verdict = "BLOCK" if r.reasons else "PASS"
        if r.verdict == "PASS":
            passed_count += 1
            passed_loss += r.max_loss
            if r.status == "Active":
                open_passed.add((r.symbol, r.side))
    return rows


def day_summary(rows: list[DeskRow], limits: dict) -> dict:
    passed = [r for r in rows if r.verdict == "PASS"]
    return {
        "signals": len(rows),
        "passed": len(passed),
        "blocked": len(rows) - len(passed),
        "trades_used": len(passed),
        "trades_limit": limits["max_trades_per_day"],
        "loss_used": round(sum(r.max_loss for r in passed), 2),
        "loss_limit": limits["max_daily_loss"],
        "capital_passed": round(sum(r.capital for r in passed), 2),
    }
