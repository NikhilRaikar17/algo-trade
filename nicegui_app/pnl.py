"""
P&L collection, daily summary, and scheduled Telegram messages.
"""

from config import now_ist, _is_trading_day, is_nse_holiday, REFRESH_SECONDS
from state import _trade_store, _is_already_sent, _mark_sent, _send_telegram


def collect_all_trades():
    all_active = []
    all_completed = []
    for key, val in _trade_store.items():
        if isinstance(val, dict) and "active" in val and "completed" in val:
            strategy = (
                "ABCD"
                if key.startswith("abcd_")
                else "RSI"
                if key.startswith("rsionly_")
                else "RSI+SMA"
                if key.startswith("rsi_")
                else "Unknown"
            )
            for t in val["active"]:
                t["strategy"] = strategy
                all_active.append(t)
            for t in val["completed"]:
                t["strategy"] = strategy
                all_completed.append(t)
    return all_active, all_completed


def send_morning_message():
    """Send at 9:00 AM every day — trading day or not."""
    now = now_ist()
    today_str = now.strftime("%Y-%m-%d")
    morning_key = f"morning_msg_{today_str}"

    if not (
        (now.hour == 9 and 15 <= now.minute <= 25) or   # real trigger
        (now.hour == 21 and 0 <= now.minute <= 10)        # TEST only — remove when done
    ):
        return
    if _is_already_sent(morning_key):
        return
    _mark_sent(morning_key)

    day_name = now.strftime("%A, %d %b %Y")

    if now.weekday() > 4:
        _send_telegram(
            f"Good morning! | {day_name}\n{'=' * 30}\n"
            f"It's the weekend — no trading today.\n"
            f"Relax, recharge, and enjoy your {now.strftime('%A')}!"
        )
    elif is_nse_holiday(now):
        _send_telegram(
            f"Good morning! | {day_name}\n{'=' * 30}\n"
            f"NSE is closed today (holiday).\n"
            f"Take a break and enjoy the day off!"
        )
    else:
        _send_telegram(
            f"ALGO TRADING STARTING | {day_name}\n{'=' * 30}\n"
            f"Strategies: ABCD Harmonic + RSI+SMA Crossover + RSI Only\n"
            f"Monitoring: NIFTY ATM options (5-min candles)\n"
            f"Refresh interval: {REFRESH_SECONDS}s\n"
            f"Market opens at 9:15 AM IST. Let's go!"
        )
    print(f"  [telegram] Morning message sent for {today_str}")


def send_daily_pnl_summary():
    """Send P&L summary + closing message at 3:30 PM on trading days."""
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

    day_name = now.strftime("%A, %d %b %Y")
    result_emoji = "📈" if total_realized >= 0 else "📉"

    msg = (
        f"MARKET CLOSED — DAILY SUMMARY {result_emoji}\n"
        f"{day_name}\n{'=' * 30}\n\n"
        f"Realized P&L: {emoji_total}{total_realized:.2f}\n"
        f"Unrealized P&L: {total_unrealized:+.2f}\n"
        f"Total Trades: {total_trades} ({winners}W / {losers}L)\n"
        f"\nStrategy Breakdown:\n{breakdown}\n\n"
        f"{'=' * 30}\n"
        f"Trading session complete. See you tomorrow!"
    )
    _send_telegram(msg)
    _mark_sent(summary_key)
    print(f"  [telegram] Daily P&L summary sent for {today_str}")
