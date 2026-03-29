"""
P&L collection, daily summary, and scheduled Telegram messages.
"""

import urllib.request
import xml.etree.ElementTree as ET

from config import now_ist, _is_trading_day, is_nse_holiday, REFRESH_SECONDS
from state import _trade_store, _is_already_sent, _mark_sent, _send_telegram


def _fetch_index_summary():
    """Return formatted prev-close lines for NIFTY and BANKNIFTY."""
    from data import fetch_index_15min_candles
    lines = []
    for name in ["NIFTY", "BANKNIFTY"]:
        try:
            df = fetch_index_15min_candles(name)
            if df.empty:
                lines.append(f"  {name}: N/A")
                continue
            last_close = float(df["close"].iloc[-1])
            prev_day_df = df[df["timestamp"].dt.date < df["timestamp"].dt.date.iloc[-1]]
            if prev_day_df.empty:
                lines.append(f"  {name}: {last_close:,.2f}")
                continue
            prev_close = float(prev_day_df["close"].iloc[-1])
            change = last_close - prev_close
            sign = "+" if change >= 0 else ""
            arrow = "▲" if change >= 0 else "▼"
            lines.append(
                f"  {name}: {last_close:,.2f}  {arrow} {sign}{change:,.2f} ({sign}{change / prev_close * 100:.2f}%)"
            )
        except Exception:
            lines.append(f"  {name}: N/A")
    return lines


def _fetch_market_news(max_items=4):
    """Fetch top headlines from Economic Times Markets RSS."""
    url = "https://economictimes.indiatimes.com/markets/rss.cms"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        headlines = []
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title", "").strip()
            if title:
                headlines.append(title)
        return headlines
    except Exception as e:
        print(f"  [news] fetch failed: {e}")
        return []


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


def send_premarket_alert():
    """Send at 9:00 AM IST every day — prep alert on trading days, rest/holiday message otherwise."""
    now = now_ist()
    today_str = now.strftime("%Y-%m-%d")
    premarket_key = f"premarket_alert_{today_str}"

    if not (
        (now.hour == 9 and 0 <= now.minute <= 10) or
        (now.hour == 21 and 15 <= now.minute <= 25)   # TEST only — remove when done
    ):
        return
    if _is_already_sent(premarket_key):
        return
    _mark_sent(premarket_key)

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
        index_lines = _fetch_index_summary()
        news_items = _fetch_market_news()

        index_section = "\n".join(index_lines) if index_lines else "  Data unavailable"

        if news_items:
            news_section = "\n".join(f"  {i+1}. {h}" for i, h in enumerate(news_items))
            caution = (
                "\n⚠️ CAUTION: Review headlines before trading — "
                "news events can trigger sharp/unexpected moves."
            )
        else:
            news_section = "  Could not fetch news headlines."
            caution = ""

        _send_telegram(
            f"PRE-MARKET ALERT | {day_name}\n{'=' * 30}\n"
            f"Market opens in 15 minutes (9:15 AM IST).\n\n"
            f"Prev Close:\n{index_section}\n\n"
            f"Market News:\n{news_section}"
            f"{caution}"
        )
    print(f"  [telegram] Pre-market alert sent for {today_str}")


def send_morning_message():
    """Send algo start message at 9:15 AM IST on trading days only."""
    now = now_ist()
    today_str = now.strftime("%Y-%m-%d")
    morning_key = f"morning_msg_{today_str}"

    if not (now.hour == 9 and 15 <= now.minute <= 25):
        return
    if not _is_trading_day(now):
        return
    if _is_already_sent(morning_key):
        return
    _mark_sent(morning_key)

    day_name = now.strftime("%A, %d %b %Y")
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
