"""
Configuration, constants, environment, and timezone utilities.
"""

import os
import sys
import threading
import pytz
from datetime import datetime, timedelta
from dotenv import load_dotenv
from dhanhq import dhanhq

# ================= PATH SETUP =================
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dhan_services.telegram import send_alert_to_all

# ================= TIMEZONE =================
IST = pytz.timezone("Asia/Kolkata")
CEST = pytz.timezone("Europe/Berlin")


def now_ist():
    return datetime.now(IST)


def now_cest():
    return datetime.now(CEST)


# ================= LIVE STRATEGIES =================
# Initial live on/off defaults, applied once when a strategy row is first created in
# algo.db. After that, toggle strategies from the Strategies page (strategy_registry.py).
LIVE_STRATEGY_ENABLED = {
    "abcd":  True,
    "dtc":   False,  # Double Top Customized
    "dts":   False,  # Double Top Standard
    "db":    False,  # Double Bottom
    "ema10": False,
    "sma50": True,
}

# ================= TRADE DESK RISK LIMITS =================
# Used by trade_desk.py to size each live signal and PASS/BLOCK it. Nothing places orders:
# daily limits assume every PASSED signal is taken, in signal-time order.
# Strategy Analysis verdicts: a strategy is "Not good" when more than max_loss_rate % of its trades
# lose money after charges — in the backtest and in live trading (each with at least min_trades trades).
STRATEGY_REVIEW = {
    "max_loss_rate": 50,          # % of trades with a net loss
    "min_trades": 10,             # fewer trades than this is too few to judge
}

RISK_LIMITS = {
    "funds": 100_000,             # ₹ cash for open positions at any moment; every day starts with it all
                                  # free (no compounding, no intraday leverage)
    "max_loss_per_trade": 1000,   # ₹ lost if the stop fills at the stop price; sets the quantity
    "max_trades_per_day": 3,      # passed signals per day
    "max_daily_loss": 3000,       # ₹, sum of the max losses of the day's passed signals
    "min_reward_risk": 1.0,       # (target − entry) / (entry − stop), absolute
    "no_entries_before": "09:20",
    "no_entries_after": "15:00",  # matches algo_strategies._NO_NEW_TRADE_AFTER
}

# Trade-store prefix / dropdown key → trade["strategy"] name used in P&L
STRATEGY_NAMES = {
    "abcd":  "ABCD",
    "dtc":   "Double Top Customized",
    "dts":   "Double Top Standard",
    "db":    "Double Bottom",
    "ema10": "EMA10",
    "sma50": "SMA50",
}


# ================= NSE HOLIDAYS (2025-2026) =================
# Source 2025: NSE Circular CMTR65587
# Source 2026: NSE Circular CMTR71775
NSE_HOLIDAYS = {
    # --- 2025 ---
    "2025-02-26",  # Maha Shivratri
    "2025-03-14",  # Holi
    "2025-03-31",  # Id-Ul-Fitr (Ramadan)
    "2025-04-10",  # Shri Mahavir Jayanti
    "2025-04-14",  # Dr. Baba Saheb Ambedkar Jayanti
    "2025-04-18",  # Good Friday
    "2025-05-01",  # Maharashtra Day
    "2025-08-15",  # Independence Day
    "2025-08-27",  # Ganesh Chaturthi
    "2025-10-02",  # Mahatma Gandhi Jayanti
    "2025-10-21",  # Diwali Laxmi Pujan (Muhurat Trading)
    "2025-10-22",  # Diwali Balipratipada
    "2025-11-05",  # Prakash Gurpurab Sri Guru Nanak Dev
    "2025-12-25",  # Christmas
    # --- 2026 --- Source: NSE Circular CMTR71775
    "2026-01-26",  # Republic Day
    "2026-03-03",  # Maha Shivratri
    "2026-03-26",  # Holi
    "2026-03-31",  # Shri Ram Navami
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Baba Saheb Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-05-27",  # Bakri Id (Id-ul-Adha)
    "2026-06-17",  # Muharram
    "2026-08-17",  # Independence Day (observed)
    "2026-09-02",  # Ganesh Chaturthi
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-10-21",  # Dussehra (Vijaya Dashami)
    "2026-11-10",  # Diwali Laxmi Pujan (Muhurat Trading)
    "2026-11-11",  # Diwali Balipratipada
    "2026-11-14",  # Gurunanak Jayanti
    "2026-12-25",  # Christmas
}


def is_nse_holiday(dt=None):
    if dt is None:
        dt = now_ist()
    return dt.strftime("%Y-%m-%d") in NSE_HOLIDAYS


def get_next_holiday():
    """Return (date_str, date_obj, days_left) for the next upcoming NSE holiday."""
    today = now_ist().date()
    future = sorted(
        d for d in NSE_HOLIDAYS if datetime.strptime(d, "%Y-%m-%d").date() >= today
    )
    if not future:
        return None
    next_str = future[0]
    next_date = datetime.strptime(next_str, "%Y-%m-%d").date()
    days_left = (next_date - today).days
    return next_str, next_date, days_left


def _is_trading_day(dt=None):
    if dt is None:
        dt = now_ist()
    return dt.weekday() <= 4 and not is_nse_holiday(dt)


# ================= ENV =================
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)

import dhan_auth

_last_token_alert = 0.0


def _token_alert(error):
    """Telegram the token failure, at most once an hour."""
    global _last_token_alert
    import time

    if time.time() - _last_token_alert < 3600 or not TELEGRAM_ENABLED:
        return
    _last_token_alert = time.time()
    send_alert_to_all(f"⚠️ Dhan token refresh failed: {error}", RECEIVER_CHAT_IDS, BOT_TOKEN)


if os.getenv("DHAN_TOTP_SECRET"):
    dhan_auth.ensure_fresh_token(ENV_FILE)
    dhan_auth.start_refresher(ENV_FILE, on_error=_token_alert)

CLIENT_ID = os.getenv("DHAN_CLIENT_CODE")
ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID")
dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

BOT_TOKEN = os.getenv("DHAN_BOT_TOKEN")
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "True").strip().lower() not in (
    "false",
    "0",
    "no",
)
MAIL_ENABLED = os.getenv("MAIL_ENABLED", "True").strip().lower() not in (
    "false",
    "0",
    "no",
)


def reinit_dhan():
    """Re-read .env and reinitialise the dhan client. Called by the file-watcher or UI button."""
    global dhan, CLIENT_ID, ACCESS_TOKEN, BOT_TOKEN, TELEGRAM_ENABLED, MAIL_ENABLED
    load_dotenv(dotenv_path=ENV_FILE, override=True)
    CLIENT_ID = os.getenv("DHAN_CLIENT_CODE")
    ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID")
    BOT_TOKEN = os.getenv("DHAN_BOT_TOKEN")
    TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "True").strip().lower() not in (
        "false",
        "0",
        "no",
    )
    MAIL_ENABLED = os.getenv("MAIL_ENABLED", "True").strip().lower() not in (
        "false",
        "0",
        "no",
    )
    dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)


def _watch_env_file():
    """Background thread: reinit dhan whenever .env is modified."""
    import time

    last_mtime = os.path.getmtime(ENV_FILE) if os.path.exists(ENV_FILE) else 0
    while True:
        time.sleep(5)
        try:
            mtime = os.path.getmtime(ENV_FILE)
            if mtime != last_mtime:
                last_mtime = mtime
                reinit_dhan()
        except OSError:
            pass


_env_watcher = threading.Thread(target=_watch_env_file, daemon=True)
_env_watcher.start()
# RECEIVER_CHAT_IDS = ["8272803637", "1623717769", "1354941649"]
RECEIVER_CHAT_IDS = ["8272803637"]

# ================= CONFIG =================
REFRESH_SECONDS = 120
SMA_PERIOD = 5
EXPIRY_ROLLOVER_HOUR = 15
MARKET_OPEN_HOUR, MARKET_OPEN_MIN = 9, 15
MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN = 15, 30

RSI_PERIOD = 14
SMA_FAST = 9
SMA_SLOW = 21
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# Swing trade momentum thresholds (SMA crossover + RSI filter)
SWING_RSI_BULL = 55  # RSI must be above this for a bullish swing candidate
SWING_RSI_BEAR = 45  # RSI must be below this for a bearish swing candidate

INDICES = {
    "NIFTY": {
        "scrip": 13,
        "segment": "IDX_I",
        "strike_step": 50,
        "strike_range": 500,
        "name_prefix": "NIFTY",
    },
    "BANKNIFTY": {
        "scrip": 25,
        "segment": "IDX_I",
        "strike_step": 100,
        "strike_range": 1000,
        "name_prefix": "BANKNIFTY",
    },
}
