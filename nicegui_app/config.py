"""
Configuration, constants, environment, and timezone utilities.
"""

import os
import sys
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


# ================= NSE HOLIDAYS (2025-2026) =================
NSE_HOLIDAYS = {
    "2025-02-26",
    "2025-03-14",
    "2025-03-31",
    "2025-04-10",
    "2025-04-14",
    "2025-04-18",
    "2025-05-01",
    "2025-06-07",
    "2025-08-15",
    "2025-08-16",
    "2025-08-27",
    "2025-10-02",
    "2025-10-21",
    "2025-10-22",
    "2025-11-05",
    "2025-12-25",
    "2026-01-26",
    "2026-02-17",
    "2026-03-03",
    "2026-03-20",
    "2026-03-30",
    "2026-04-03",
    "2026-04-14",
    "2026-05-01",
    "2026-05-28",
    "2026-08-15",
    "2026-08-18",
    "2026-10-02",
    "2026-10-10",
    "2026-10-29",
    "2026-11-25",
    "2026-12-25",
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

CLIENT_ID = os.getenv("DHAN_CLIENT_CODE")
ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID")
dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

BOT_TOKEN = os.getenv("DHAN_BOT_TOKEN")
RECEIVER_CHAT_IDS = ["8272803637", "1623717769"]

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
