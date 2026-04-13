"""
P&L collection, daily summary, and scheduled Telegram messages.
"""

import ssl
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


_RSS_FEEDS = [
    "https://www.livemint.com/rss/markets",
    "https://feeds.feedburner.com/ndtvprofit-latest",
]
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def _fetch_market_news(max_items=4):
    """Fetch top headlines from market RSS feeds, trying each in order."""
    for url in _RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            headlines = []
            for item in root.findall(".//item")[:max_items]:
                title = item.findtext("title", "").strip()
                if title:
                    headlines.append(title)
            if headlines:
                return headlines
        except Exception as e:
            print(f"  [news] {url} failed: {e}")
    return []


_STORE_STRATEGY_MAP = [
    ("abcd_",  "ABCD"),
    ("dt_",    "Double Top"),
    ("db_",    "Double Bottom"),
    ("ema10_", "EMA10"),
    ("sma50_", "SMA50"),
]


def _strategy_from_key(key):
    for prefix, name in _STORE_STRATEGY_MAP:
        if key.startswith(prefix):
            return name
    return "Unknown"


def collect_all_trades():
    all_active = []
    all_completed = []
    for key, val in _trade_store.items():
        if isinstance(val, dict) and "active" in val and "completed" in val:
            strategy = _strategy_from_key(key)
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

    if not (now.hour == 9 and 0 <= now.minute <= 10):
        return
    if _is_already_sent(premarket_key):
        return

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
    _mark_sent(premarket_key)
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

    from db import get_active_top_stocks
    stocks = get_active_top_stocks()
    stock_names = ", ".join(s["name"] for s in stocks) if stocks else "No stocks loaded yet"

    day_name = now.strftime("%A, %d %b %Y")
    _send_telegram(
        f"ALGO TRADING STARTING | {day_name}\n{'=' * 30}\n"
        f"Strategies: ABCD Harmonic | Double Top | Double Bottom | EMA10 | SMA50\n"
        f"Monitoring: Top Stocks (5-min equity candles)\n"
        f"Stocks ({len(stocks)}): {stock_names}\n"
        f"Refresh interval: {REFRESH_SECONDS}s\n"
        f"Market opens at 9:15 AM IST. Let's go!"
    )
    _mark_sent(morning_key)
    print(f"  [telegram] Morning message sent for {today_str}")


def send_daily_pnl_summary():
    """Send intraday live-trading P&L summary at 3:30 PM on trading days.
    Reads from _trade_store (populated by trading_engine) plus today's
    persisted records from .trade_history.json so no trade is missed.
    """
    from state import load_trade_history
    now = now_ist()
    today_str = now.strftime("%Y-%m-%d")
    summary_key = f"daily_pnl_{today_str}"

    if not _is_trading_day(now):
        return
    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
        return
    if _is_already_sent(summary_key):
        return

    # Merge in-memory trades with today's persisted trades (dedup by entry price + strategy + signal)
    all_active, mem_completed = collect_all_trades()
    hist_today = [t for t in load_trade_history() if t.get("trade_date") == today_str]
    seen = set()
    all_completed = list(hist_today)
    for t in hist_today:
        seen.add((t.get("strategy"), t.get("signal"), round(float(t.get("entry", 0)), 1)))
    for t in mem_completed:
        key = (t.get("strategy"), t.get("signal"), round(float(t.get("entry", 0)), 1))
        if key not in seen:
            all_completed.append(t)
            seen.add(key)

    total_realized = sum(t.get("pnl", 0) for t in all_completed)
    total_unrealized = sum(t.get("unrealized_pnl", 0) for t in all_active)
    total_trades = len(all_completed)
    winners = sum(1 for t in all_completed if t.get("pnl", 0) > 0)
    losers = sum(1 for t in all_completed if t.get("pnl", 0) < 0)
    win_rate = (winners / total_trades * 100) if total_trades else 0

    # Per-strategy breakdown with win rate
    strat_lines = []
    strategies = sorted(set(t.get("strategy", "Unknown") for t in all_completed))
    for strat in strategies:
        strat_trades = [t for t in all_completed if t.get("strategy") == strat]
        spnl = sum(t.get("pnl", 0) for t in strat_trades)
        sw = sum(1 for t in strat_trades if t.get("pnl", 0) > 0)
        sl_count = sum(1 for t in strat_trades if t.get("pnl", 0) < 0)
        swr = int(sw / len(strat_trades) * 100) if strat_trades else 0
        emoji = "+" if spnl > 0 else ""
        strat_lines.append(
            f"  {strat}: {len(strat_trades)}T | {sw}W/{sl_count}L | WR:{swr}% | PnL:{emoji}{spnl:.2f}"
        )

    # Individual trade log (max 10 trades to keep message size reasonable)
    trade_log_lines = []
    for t in all_completed[-10:]:
        pnl = t.get("pnl", 0)
        sign = "+" if pnl > 0 else ""
        status_icon = "✅" if t.get("status") == "Target Hit" else ("❌" if t.get("status") == "SL Hit" else "🔔")
        trade_log_lines.append(
            f"  {status_icon} {t.get('strategy','?')} | {t.get('signal','')[:25]} | {sign}{pnl:.2f}"
        )

    emoji_total = "+" if total_realized > 0 else ""
    breakdown = "\n".join(strat_lines) if strat_lines else "  No trades today"
    trade_log = "\n".join(trade_log_lines) if trade_log_lines else "  No completed trades"

    day_name = now.strftime("%A, %d %b %Y")
    result_emoji = "📈" if total_realized >= 0 else "📉"

    from db import get_active_top_stocks
    stocks = get_active_top_stocks()
    stock_names = ", ".join(s["name"] for s in stocks) if stocks else "—"

    msg = (
        f"MARKET CLOSED — DAILY SUMMARY {result_emoji}\n"
        f"{day_name}\n{'=' * 30}\n\n"
        f"Realized P&L:   {emoji_total}{total_realized:.2f}\n"
        f"Unrealized P&L: {total_unrealized:+.2f}\n"
        f"Total Trades:   {total_trades} | Win Rate: {win_rate:.0f}%\n"
        f"Winners/Losers: {winners}W / {losers}L\n"
        f"\nStocks Monitored: {stock_names}\n"
        f"\nStrategy Breakdown:\n{breakdown}\n\n"
        f"Trade Log (last {min(10, len(all_completed))}):\n{trade_log}\n\n"
        f"{'=' * 30}\n"
        f"Trading session complete. See you tomorrow!"
    )
    _send_telegram(msg)
    _mark_sent(summary_key)
    print(f"  [telegram] Daily P&L summary sent for {today_str}")
