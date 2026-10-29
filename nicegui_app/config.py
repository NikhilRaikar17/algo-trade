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
    "ema100": False,
    "sma100": False,
    "sma200": False,
    "ema50x100": False,  # EMA 50 crossing EMA 100
}

# ================= LIVE ACCOUNT RISK LIMITS =================
# trade_desk.check() sizes each live signal and the paper account (account.py) takes or skips it, once,
# when the engine first sees it. Only taken trades are alerted and counted. Nothing places orders.
# Strategy Analysis verdicts: a strategy is "Not good" when more than max_loss_rate % of its trades
# lose money after charges — in the backtest and in live trading (each with at least min_trades trades).
STRATEGY_REVIEW = {
    "max_loss_rate": 50,          # % of trades with a net loss
    "min_trades": 10,             # fewer trades than this is too few to judge
}

RISK_LIMITS = {
    "funds": 100_000,             # ₹ the paper account starts with; open positions hold their capital
                                  # until they close (no intraday leverage)
    "max_loss_per_trade": 1000,   # ₹ lost if the stop fills at the stop price; sets the quantity
    "deploy_pct": 70,             # % of the balance all open trades together may use; the rest stays idle
    "max_capital_pct": 30,        # % of the balance one trade may use, leaving room for other trades;
                                  # the quantity is cut to fit it, or to the free funds if less is left
    "min_risk_pct": 0,            # skip a trade cut by the funds below this % of max_loss_per_trade (0 = never)
    "max_trades_per_day": None,   # taken trades per day; None = no limit
    "max_daily_loss": 750,        # ₹ net loss (after charges) of the day's closed trades that ends the day
    "max_losing_streak": 3,       # losing trades in a row (net after charges) that end the day
    "min_reward_risk": 1.0,       # (target − entry) / (entry − stop), absolute
    "no_entries_before": "09:20",
    "no_entries_after": "15:00",  # matches algo_strategies._NO_NEW_TRADE_AFTER
    "square_off": "15:20",        # open trades are closed at the last price (intraday)
}

# ================= LIVE OPTIONS ACCOUNT =================
# A second paper account (account.OPTIONS) that buys NIFTY / BANKNIFTY options on signals from the
# options' own premium charts (options_engine.py). Same rules as the stock account, sized in whole lots.
OPTIONS_LIMITS = {
    **RISK_LIMITS,
    "funds": 200_000,             # ₹ of its own, separate from the stock account's
    "segment": "fno",            # brokerage and taxes as NSE options
    "reward_risk_after_charges": True,  # R:R counts the round trip's charges (~₹90 a lot): (reward − charges) / (risk + charges)
}

OPTIONS_UNDERLYINGS = ["NIFTY", "BANKNIFTY"]

# The opt_* templates switched on for Options P&L (Strategies page), paper-traded intraday in the options
# account on NIFTY and BANKNIFTY (options_templates.py), at the same expiry as the options engine
# (OPTIONS_SELECTION). Each is one position priced at its net premium, sized and checked like any option
# trade (OPTIONS_LIMITS). Legs: (CE/PE, strike steps from the ATM, +1 bought / −1 sold).
# Entry, at most once a day per template and index, on the index's 15-min bars (the 09:15 bar is the
# opening range), inside "window":
#   breakout  a finished bar closes above the opening range high (bullish)
#   squeeze   the opening range is at most max_range_pct of the index (a move is due, either way)
#   range     the day's range so far is at most max_range_pct and the index is inside the opening range
# Exit on the net premium: target_pct / stop_pct of the entry premium (a debit position's value up / down,
# a credit position's cost to close down / up), else the square-off.
OPTIONS_TEMPLATES = {
    "opt_long_call": {"legs": [("CE", 0, 1)], "entry": "breakout", "window": ("09:30", "14:00"),
                      "target_pct": 40, "stop_pct": 25},
    "opt_bull_call_spread": {"legs": [("CE", 0, 1), ("CE", 2, -1)], "entry": "breakout",
                             "window": ("09:30", "14:00"), "target_pct": 40, "stop_pct": 25},
    "opt_bull_put_spread": {"legs": [("PE", -1, -1), ("PE", -3, 1)], "entry": "breakout",
                            "window": ("09:30", "14:00"), "target_pct": 50, "stop_pct": 40},
    "opt_long_straddle": {"legs": [("CE", 0, 1), ("PE", 0, 1)], "entry": "squeeze", "window": ("09:30", "10:30"),
                          "max_range_pct": 0.35, "target_pct": 25, "stop_pct": 15},
    "opt_iron_condor": {"legs": [("PE", -4, 1), ("PE", -2, -1), ("CE", 2, -1), ("CE", 4, 1)], "entry": "range",
                        "window": ("10:15", "12:30"), "max_range_pct": 0.6, "target_pct": 40, "stop_pct": 30},
}
OPTIONS_TEMPLATE_MAX_SPREAD_PCT = 5.0  # each leg's bid-ask spread, % of its premium; wider → not entered

# ================= LONG TERM (SWING) ACCOUNT =================
# A third paper account (account.LONGTERM) for one-week swing trades in the current NIFTY future
# (longterm.py): signals from the NIFTY index's daily chart, scanned once a day near the close, long or
# short, sized in lots on margin, held until the target, the stop or max_hold_days trading days.
LONGTERM_LIMITS = {
    **RISK_LIMITS,
    "funds": 500_000,             # ₹ of its own, separate from the other two accounts
    "segment": "fno_futures",     # brokerage and taxes as index futures
    "margin_pct": 12.5,           # % of the contract value blocked as margin per lot (NIFTY SPAN + exposure, approx.)
    "max_loss_per_trade": 30_000, # ₹ lost at the stop: a 1.5 × ATR stop is ~400 points × 65 ≈ ₹26,000 a lot
    "max_capital_pct": 100,       # one position at a time (one future), so it may use the whole balance as margin
    "deploy_pct": 100,
    "max_daily_loss": None,       # trades close days apart: no intraday loss limit or losing streak
    "max_losing_streak": None,
    "min_reward_risk": 1.5,
    "no_entries_before": "09:20",
    "no_entries_after": "15:25",  # the scan runs at scan_at, a few minutes before the close
    "square_off": "15:20",        # a trade on its last day is closed at its last price from this time
    "max_hold_days": 5,           # trading days a trade may stay open: one week
    "scan_at": "15:15",           # when the day's (nearly finished) daily bar is scanned
}
LONGTERM_UNDERLYING = "NIFTY"     # the future traded; its index's daily chart gives the signals
# Strategies: the moving-average ones enabled for Backtest on the Strategies page (longterm.strategy_keys),
# with daily-chart levels: stop 1.5 × ATR(14), target 3 × ATR(14) of the index.
LONGTERM_ATR = {"period": 14, "stop": 1.5, "target": 3.0}
LONGTERM_HISTORY_DAYS = 700       # calendar days of daily bars fetched: SMA 200 warm-up (~290 days) + a year to backtest

# How option_contracts.select_contracts() picks the CE and PE to trade for each index
OPTIONS_SELECTION = {
    "expiry_skip": 1,             # expiries after today to pass over: 1 = next-to-next (today's expiry never counts)
    "max_days_to_expiry": 45,     # unless that is further out than this (monthly-only BANKNIFTY): then the next one
    "strikes_each_side": 4,       # strikes either side of the ATM to consider
    "min_delta": 0.35,            # |delta| range: near the money, so the premium follows the index
    "max_delta": 0.65,
    "min_oi": 50_000,             # open interest (units) — enough positions to get out
    "min_volume": 50_000,         # units traded today
    "max_spread_pct": 1.0,        # bid-ask spread, % of the premium
    "reselect_strikes": 3,        # pick again once the index has moved this many strikes from the chosen ATM
}

# Trade-store prefix / dropdown key → trade["strategy"] name used in P&L
STRATEGY_NAMES = {
    "abcd":  "ABCD",
    "dtc":   "Double Top Customized",
    "dts":   "Double Top Standard",
    "db":    "Double Bottom",
    "ema10": "EMA10",
    "sma50": "SMA50",
    "ema100": "EMA100",
    "sma100": "SMA100",
    "sma200": "SMA200",
    "ema50x100": "EMA50x100",
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


# A new token cancels the old one, so only one machine may refresh: the live server. Set
# DHAN_AUTO_REFRESH=false in a local .env and copy the server's token in instead.
AUTO_REFRESH_TOKEN = os.getenv("DHAN_AUTO_REFRESH", "true").strip().lower() not in ("false", "0", "no", "off")

if os.getenv("DHAN_TOTP_SECRET") and AUTO_REFRESH_TOKEN:
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
    # Update the existing client in place: data.py and pages use `from config import dhan`,
    # so a new object would leave them calling Dhan with the old token until a restart.
    dhan.client_id = str(CLIENT_ID)
    dhan.access_token = ACCESS_TOKEN
    dhan.header["access-token"] = ACCESS_TOKEN


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
