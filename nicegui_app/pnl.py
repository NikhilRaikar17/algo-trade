"""
P&L collection, daily summary, and scheduled Telegram messages.
"""

import ssl
import urllib.request
import xml.etree.ElementTree as ET

from config import now_ist, _is_trading_day, is_nse_holiday, STRATEGY_NAMES
from state import _trade_store, _is_already_sent, _mark_sent, _send_telegram
from strategy_registry import get_live_strategy_names


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


_STORE_STRATEGY_MAP = [(f"{k}_", name) for k, name in STRATEGY_NAMES.items()]


def _strategy_from_key(key):
    for prefix, name in _STORE_STRATEGY_MAP:
        if key.startswith(prefix):
            return name
    return "Unknown"


def _symbol_from_key(key):
    """Extract stock name from trade store key, e.g. 'abcd_trades_RELIANCE' → 'RELIANCE'."""
    marker = "_trades_"
    idx = key.find(marker)
    if idx != -1:
        return key[idx + len(marker):]
    return ""


def collect_all_trades():
    all_active = []
    all_completed = []
    live_names = get_live_strategy_names()
    for key, val in _trade_store.items():
        if isinstance(val, dict) and "active" in val and "completed" in val:
            strategy = _strategy_from_key(key)
            if strategy not in live_names:
                continue
            symbol = _symbol_from_key(key)
            for t in val["active"]:
                t["strategy"] = strategy
                if not t.get("symbol"):
                    t["symbol"] = symbol
                all_active.append(t)
            for t in val["completed"]:
                t["strategy"] = strategy
                if not t.get("symbol"):
                    t["symbol"] = symbol
                all_completed.append(t)
    return all_active, all_completed


_DAY_QUOTES = [
    "Discipline is choosing what you want most over what you want now.",
    "Small steps every day add up to big results.",
    "Your best trade today may be the one you don't take.",
    "Calm minds make clear decisions.",
    "Progress, not perfection.",
    "Protect your capital first; profits follow patience.",
    "Every day is a fresh chart. Read it with an open mind.",
    "Consistency beats intensity.",
    "Stick to the plan. The plan is there for the days you doubt it.",
    "A good loss taken quickly is better than a bad hope held long.",
    "Focus on the process, and let the results take care of themselves.",
    "Gratitude turns what we have into enough.",
    "Be patient with the market and kind to yourself.",
    "Strength grows in the moments you think you can't go on but keep going anyway.",
    "Today is a good day to do your best work.",
]

_SHIVA_BLESSINGS = [
    "Om Namah Shivaya 🙏\nMay Lord Shiva keep your mind steady and your choices wise today.",
    "Har Har Mahadev 🔱\nMay Mahadev remove every obstacle from your path today.",
    "Om Tryambakam Yajamahe Sugandhim Pushtivardhanam 🙏\nMay Lord Shiva bless you with health, courage and peace.",
    "Om Namah Shivaya 🕉️\nMay Bholenath fill your day with calm, clarity and strength.",
    "Jai Bhole Nath 🔱\nMay the blessings of Lord Shiva guide every step you take today.",
    "Om Namah Shivaya 🙏\nMay Neelkanth give you the strength to stay calm through every storm.",
    "Har Har Mahadev 🕉️\nMay Shiva's grace bring patience to your mind and success to your work.",
    "Om Shambhave Namah 🙏\nMay Lord Shiva bless your home with happiness and your day with good fortune.",
    "Jai Shiv Shankar 🔱\nMay Mahadev keep fear away and fill you with quiet confidence.",
    "Om Namah Shivaya 🕉️\nMay the light of Lord Shiva shine on you and everyone you love.",
    "Har Har Mahadev 🙏\nMay Lord Shiva grant you wisdom to act and the peace to let go.",
]


def send_morning_blessing():
    """Send at 8:55 AM IST every day: a positive quote for the day and Lord Shiva's blessing,
    just before the 9:00 pre-market alert. Both rotate day by day."""
    now = now_ist()
    today_str = now.strftime("%Y-%m-%d")
    key = f"morning_blessing_{today_str}"

    if not (now.hour == 8 and 55 <= now.minute <= 59):
        return
    if _is_already_sent(key):
        return

    day = now.toordinal()
    _send_telegram(
        f"🌅 Good morning! | {now.strftime('%A, %d %b %Y')}\n{'=' * 30}\n"
        f"✨ Thought for the day:\n\"{_DAY_QUOTES[day % len(_DAY_QUOTES)]}\"\n\n"
        f"{_SHIVA_BLESSINGS[day % len(_SHIVA_BLESSINGS)]}"
    )
    _mark_sent(key)
    print(f"  [telegram] Morning blessing sent for {today_str}")


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
    live_names = " | ".join(get_live_strategy_names()) or "none enabled"
    _send_telegram(
        f"ALGO TRADING STARTING | {day_name}\n{'=' * 30}\n"
        f"Strategies: {live_names}\n"
        f"Monitoring: Top Stocks on the live feed\n"
        f"Stocks ({len(stocks)}): {stock_names}\n"
        f"Signals: at every 5-min bar close · exits: on live ticks\n"
        f"Market opens at 9:15 AM IST. Let's go!"
    )
    _mark_sent(morning_key)
    print(f"  [telegram] Morning message sent for {today_str}")


def _account_summary(acct, now, title: str, what: str) -> str:
    """The 3:30 PM message for one paper account (account.EQUITY or account.OPTIONS)."""
    from backtest_metrics import inr, rupees_text, sizing_label, summarize
    from brokerage import is_short

    today_str = now.strftime("%Y-%m-%d")
    state = acct.account_state(now)
    _, stopped = acct.day_status(now)
    today = [t for t in state["sized"] if t["trade_date"] == today_str]
    day = summarize(today)
    total_realized = day["net"]

    strat_lines = []
    for strat in sorted({t["strategy"] for t in today}):
        g = summarize([t for t in today if t["strategy"] == strat])
        strat_lines.append(
            f"  {strat}: {g['trades']}T | {g['wins']}W/{g['losses']}L | WR:{g['win_rate']:.0f}% | {rupees_text(g['net'])}"
        )

    # Individual trade log (max 10 trades to keep message size reasonable)
    trade_log_lines = []
    for t in sorted(today, key=lambda t: t["exit_time"])[-10:]:
        status_icon = "✅" if t.get("status") == "Target Hit" else ("❌" if t.get("status") == "SL Hit" else "🔔")
        side = "SELL" if is_short(t) else "BUY"
        trade_log_lines.append(
            f"  {status_icon} {t.get('stock', '?')} {side} | {t.get('strategy', '?')} | {rupees_text(t['net'])}"
        )

    breakdown = "\n".join(strat_lines) if strat_lines else "  No trades today"
    trade_log = "\n".join(trade_log_lines) if trade_log_lines else "  No completed trades"
    result_emoji = "📈" if total_realized >= 0 else "📉"

    return (
        f"{title} {result_emoji}\n"
        f"{now.strftime('%A, %d %b %Y')}\n{'=' * 30}\n\n"
        f"Realized P&L:   {rupees_text(total_realized)} (after ₹{inr(day['charges'])} charges)\n"
        f"Unrealized P&L: {rupees_text(state['unrealized'])} ({state['open']} open)\n"
        f"Account:        ₹{inr(state['balance'])} ({state['return_pct']:+.2f}% since "
        f"{state['start']:%d %b}, started ₹{inr(state['initial'])})\n"
        f"Free funds:     ₹{inr(state['free'])}\n"
        f"Sizing:         {sizing_label(funds=None)}, compounding\n"
        f"Total Trades:   {day['trades']} | Win Rate: {day['win_rate']:.0f}%\n"
        f"Skipped:        {len(state['skipped_today'])} signals not taken (limits / funds)\n"
        + (f"Day stopped:    {stopped}\n" if stopped else "") +
        f"Winners/Losers: {day['wins']}W / {day['losses']}L\n"
        f"\n{what}\n"
        f"\nStrategy Breakdown:\n{breakdown}\n\n"
        f"Trade Log (last {min(10, len(today))}):\n{trade_log}\n\n"
        f"{'=' * 30}\n"
        f"Trading session complete. See you tomorrow!"
    )


def send_daily_pnl_summary():
    """Send intraday live-trading P&L summaries at 3:30 PM on trading days, in rupees: one for the
    stock account, one for the options account. Trades come from each paper account's book
    (account.py): only the signals it took, at the size it took them, compounding, net of brokerage
    and taxes — the same trades and maths as the Live P&L pages.
    """
    now = now_ist()
    today_str = now.strftime("%Y-%m-%d")

    if not _is_trading_day(now):
        return
    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
        return

    from account import EQUITY, OPTIONS

    summary_key = f"daily_pnl_{today_str}"
    if not _is_already_sent(summary_key):
        from db import get_active_top_stocks
        stocks = get_active_top_stocks()
        stock_names = ", ".join(s["name"] for s in stocks) if stocks else "—"
        _send_telegram(_account_summary(EQUITY, now, "MARKET CLOSED — DAILY SUMMARY",
                                        f"Stocks Monitored: {stock_names}"))
        _mark_sent(summary_key)
        print(f"  [telegram] Daily P&L summary sent for {today_str}")

    options_key = f"daily_pnl_options_{today_str}"
    if not _is_already_sent(options_key):
        from options_engine import snapshot
        contracts = ", ".join(c["symbol"] for c in snapshot()["contracts"]) or "—"
        _send_telegram(_account_summary(OPTIONS, now, "OPTIONS — DAILY SUMMARY", f"Contracts traded: {contracts}"))
        _mark_sent(options_key)
        print(f"  [telegram] Options P&L summary sent for {today_str}")
