"""
Backtest P&L maths — pure functions, no UI and no API calls.

finalize_trades() keeps only the trades an account could actually have taken; size_trades() turns
each trade's points into rupees for a sizing rule and nets off Dhan's intraday charges; summarize(),
group_by() and equity_curve() produce the page's numbers. All money is ₹, after charges unless
the key says gross.
"""

from collections import defaultdict
from datetime import datetime, time

from brokerage import calculate_brokerage, is_short

_CLOSE = time(15, 30)
_CHARGE_KEYS = ("brokerage", "stt", "exchange", "gst", "sebi", "stamp")

SIZING_MODES = {"capital": "₹ per trade", "shares": "Shares"}
DEFAULT_SIZING = {"capital": 100_000, "shares": 1}


def finalize_trades(trades: list[dict], now: datetime) -> tuple[list[dict], dict]:
    """(kept, excluded counts). Drops limit orders that never filled, trades still running today
    (their 'Day Close' is just the latest bar), and any signal that fires while the same strategy
    already holds the same stock — one position at a time, as a real account would."""
    excluded = {"no_fill": 0, "open": 0, "overlap": 0}
    finished = []
    for t in trades:
        status = t.get("status")
        if status == "No Fill" or t.get("exit_price") is None:
            excluded["no_fill" if status == "No Fill" else "open"] += 1
            continue
        exit_time = t.get("exit_time")
        if (status == "Day Close" and hasattr(exit_time, "date")
                and exit_time.date() == now.date() and now.time() < _CLOSE):
            excluded["open"] += 1
            continue
        finished.append(t)

    kept = []
    busy_until: dict[tuple, object] = {}
    for t in sorted(finished, key=lambda t: t["time"]):
        if t.get("approx_time"):  # old live records without real times: can't tell if they overlapped
            kept.append(t)
            continue
        lane = (t.get("stock", ""), t.get("strategy", ""))
        if lane in busy_until and t["time"] < busy_until[lane]:
            excluded["overlap"] += 1
            continue
        busy_until[lane] = t.get("exit_time") or t["time"]
        kept.append(t)
    return kept, excluded


def size_trades(trades: list[dict], mode: str, amount: float) -> list[dict]:
    """Add qty, side, gross, charges, net, capital and ret_pct to a copy of each trade.
    capital mode buys as many whole shares as `amount` rupees allows; trades priced above it are skipped."""
    out = []
    for t in trades:
        entry, exit_px = float(t["entry"]), float(t["exit_price"])
        qty = int(amount // entry) if mode == "capital" else int(amount)
        if qty < 1:
            continue
        short = is_short(t)
        b = calculate_brokerage(entry, exit_px, lot_size=1, quantity=qty, segment="equity_intraday", short=short)
        capital = entry * qty
        out.append({
            **t,
            "qty": qty,
            "side": "SELL" if short else "BUY",
            "gross": b["gross_pnl"],
            "charges": b["total_charges"],
            "net": b["net_pnl"],
            "capital": capital,
            "ret_pct": b["net_pnl"] / capital * 100,
            "charge_parts": {k: b[k] for k in _CHARGE_KEYS},
        })
    return out


def net_rupees(trade: dict, mode: str = "capital", amount: float | None = None) -> float | None:
    """Net ₹ for one finished trade at a sizing (default ₹1,00,000 per trade); None if it has no
    exit yet or one share costs more than the amount."""
    if not trade.get("entry") or not trade.get("exit_price"):
        return None
    sized = size_trades([trade], mode, amount if amount is not None else DEFAULT_SIZING[mode])
    return sized[0]["net"] if sized else None


def inr(v: float) -> str:
    """Whole rupees with Indian digit grouping, no sign: 1234567 → '12,34,567'."""
    digits = f"{abs(v):.0f}"
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head] + groups + [tail]) if head else ",".join(groups + [tail])


def rupees_text(v: float | None) -> str:
    """+₹1,234 / −₹1,00,560 for messages and labels ("—" when there is no value)."""
    if v is None:
        return "—"
    return f"{'+' if v > 0 else '−' if v < 0 else ''}₹{inr(v)}"


def _by_exit(trades):
    return sorted(trades, key=lambda t: (t.get("exit_time") or t["time"]))


def equity_curve(trades: list[dict]) -> list[tuple[dict, float]]:
    """[(trade, cumulative net after it)] in exit order."""
    total, curve = 0.0, []
    for t in _by_exit(trades):
        total += t["net"]
        curve.append((t, total))
    return curve


def max_drawdown(trades: list[dict]) -> float:
    """Largest fall in cumulative net P&L from a previous high (starting from 0), as a positive ₹."""
    peak = worst = 0.0
    for _, total in equity_curve(trades):
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return worst


def summarize(trades: list[dict]) -> dict:
    wins = [t["net"] for t in trades if t["net"] > 0]
    losses = [t["net"] for t in trades if t["net"] < 0]
    n = len(trades)
    win_sum, loss_sum = sum(wins), -sum(losses)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / n * 100 if n else 0.0,
        "gross": sum(t["gross"] for t in trades),
        "charges": sum(t["charges"] for t in trades),
        "net": sum(t["net"] for t in trades),
        "avg_win": win_sum / len(wins) if wins else 0.0,
        "avg_loss": -loss_sum / len(losses) if losses else 0.0,
        # None = no losing trades, so the ratio is undefined (shown as "—")
        "profit_factor": win_sum / loss_sum if loss_sum else None,
        "expectancy": sum(t["net"] for t in trades) / n if n else 0.0,
        "avg_ret_pct": sum(t["ret_pct"] for t in trades) / n if n else 0.0,
        "max_drawdown": max_drawdown(trades),
        "capital": sum(t["capital"] for t in trades) / n if n else 0.0,
        "charge_parts": {k: sum(t["charge_parts"][k] for t in trades) for k in _CHARGE_KEYS},
    }


def group_by(trades: list[dict], key: str) -> list[tuple[str, dict]]:
    """[(group value, summarize(group))], best net first."""
    groups = defaultdict(list)
    for t in trades:
        groups[t.get(key, "")].append(t)
    return sorted(((k, summarize(v)) for k, v in groups.items()), key=lambda kv: kv[1]["net"], reverse=True)
