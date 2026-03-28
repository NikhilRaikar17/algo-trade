"""
P&L collection, daily summary, and market open messages.
"""

from config import now_ist, _is_trading_day, REFRESH_SECONDS
from state import _trade_store, _is_already_sent, _mark_sent, _send_telegram


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
