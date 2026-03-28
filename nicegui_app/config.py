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
    # --- 2026 ---
    "2026-01-26",  # Republic Day
    "2026-03-03",  # Holi
    "2026-03-26",  # Shri Ram Navami
    "2026-03-31",  # Shri Mahavir Jayanti
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Baba Saheb Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-05-28",  # Bakri Id
    "2026-06-26",  # Muharram
    "2026-09-14",  # Ganesh Chaturthi
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-10-20",  # Dussehra
    "2026-11-10",  # Diwali Balipratipada
    "2026-11-24",  # Prakash Gurpurab Sri Guru Nanak Dev
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
