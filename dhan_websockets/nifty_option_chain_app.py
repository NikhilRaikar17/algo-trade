"""
nifty_option_chain_app.py
-------------------------
Streamlit app — NIFTY & BANKNIFTY option chain with 3 expiry tabs each.
Run:  streamlit run dhan_websockets/nifty_option_chain_app.py
"""

import os
import time
import pandas as pd
import streamlit as st
from datetime import datetime, date
from dotenv import load_dotenv
from dhanhq import dhanhq
import plotly.graph_objects as go
import pytz

IST = pytz.timezone("Asia/Kolkata")


def now_ist():
    """Current time in IST."""
    return datetime.now(IST)
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dhan_services.telegram import send_alert_to_all

# ================= ENV =================
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)

CLIENT_ID    = os.getenv("DHAN_CLIENT_CODE")
ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID")
dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# ================= TELEGRAM CONFIG =================
BOT_TOKEN = os.getenv("DHAN_BOT_TOKEN")
RECEIVER_CHAT_IDS = ["8272803637", "1623717769"]

# ================= CONFIG =================
REFRESH_SECONDS = 120
SMA_PERIOD = 5
EXPIRY_ROLLOVER_HOUR = 15  # on expiry day, switch to next expiry after this hour (IST)

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


# ================= API HELPER =================

def api_call(fn, *args, retries=3, delay=3, **kwargs):
    """Call a Dhan API function with retry on rate limit / failure."""
    for attempt in range(retries):
        r = fn(*args, **kwargs)
        if isinstance(r, dict):
            # Check for rate limit (HTTP 429 or 805 error)
            err_data = r.get("data", {})
            if isinstance(err_data, dict):
                inner = err_data.get("data", {})
                if isinstance(inner, dict) and any("Too many" in str(v) for v in inner.values()):
                    print(f"  [rate limit] attempt {attempt+1}/{retries}, waiting {delay}s...")
                    time.sleep(delay)
                    delay *= 2
                    continue
            if r.get("status") == "failure" and attempt < retries - 1:
                print(f"  [api retry] attempt {attempt+1}/{retries}, waiting {delay}s...")
                time.sleep(delay)
                delay *= 2
                continue
        return r
    return r  # return last response even if failed


# ================= DATA FUNCTIONS =================

def get_expiries(scrip, segment, count=3, for_algo=False):
    """Return nearest future expiry dates.

    If for_algo=True, on expiry day after EXPIRY_ROLLOVER_HOUR IST,
    skip today's expiry and roll to the next one.
    """
    r = api_call(dhan.expiry_list, scrip, segment)
    if r.get("status") != "success":
        raise RuntimeError(f"expiry_list failed: {r}")

    data = r["data"]
    if isinstance(data, dict):
        data = data.get("data", data)
    if isinstance(data, dict):
        data = next(iter(data.values()))

    ist_now = now_ist()
    today = ist_now.date()

    all_future = sorted(
        d for d in data
        if isinstance(d, str) and datetime.strptime(d, "%Y-%m-%d").date() >= today
    )

    if for_algo:
        # On expiry day after rollover hour, skip today's expiry
        filtered = []
        for d in all_future:
            exp_date = datetime.strptime(d, "%Y-%m-%d").date()
            if exp_date == today and ist_now.hour >= EXPIRY_ROLLOVER_HOUR:
                continue  # skip — too close to expiry
            if exp_date < today:
                continue
            filtered.append(d)
        expiries = filtered
    else:
        # For option chain tabs, only strictly future
        expiries = [d for d in all_future if datetime.strptime(d, "%Y-%m-%d").date() > today]

    if not expiries:
        raise RuntimeError("No future expiries found.")
    return expiries[:count]


def fetch_option_chain(scrip, segment, expiry):
    r = api_call(dhan.option_chain, scrip, segment, expiry)
    if r.get("status") != "success":
        raise RuntimeError(f"option_chain failed: {r}")

    inner = r["data"]["data"]
    spot = float(inner["last_price"])
    oc = inner["oc"]

    rows = []
    for strike_str, sides in oc.items():
        strike = float(strike_str)
        for opt_type, key in [("CE", "ce"), ("PE", "pe")]:
            info = sides.get(key, {})
            if not info:
                continue
            greeks = info.get("greeks", {})
            rows.append({
                "Strike":  strike,
                "Type":    opt_type,
                "LTP":     round(float(info.get("last_price", 0)), 2),
                "IV (%)":  round(float(info.get("implied_volatility", 0)), 2),
                "Delta":   round(float(greeks.get("delta", 0)), 4),
                "Gamma":   round(float(greeks.get("gamma", 0)), 6),
                "Theta":   round(float(greeks.get("theta", 0)), 4),
                "Vega":    round(float(greeks.get("vega", 0)), 4),
            })
    return spot, pd.DataFrame(rows)


def build_name_column(df, expiry, prefix):
    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
    exp_tag = exp_date.strftime("%d%b").upper()
    df.insert(0, "Name", df.apply(
        lambda r: f"{prefix} {exp_tag} {int(r['Strike'])} {r['Type']}", axis=1
    ))
    return df


def filter_and_split(df, atm, strike_range):
    lower = atm - strike_range
    upper = atm + strike_range
    df = df[(df["Strike"] >= lower) & (df["Strike"] <= upper)].copy()
    df = df.sort_values("Strike").reset_index(drop=True)

    ce = df[df["Type"] == "CE"].drop(columns=["Type"]).reset_index(drop=True)
    pe = df[df["Type"] == "PE"].drop(columns=["Type"]).reset_index(drop=True)
    return ce, pe


# ================= TREND LOGIC (SMA) =================

def add_trend(df, index_name, expiry, opt_type):
    history_key = f"history_{index_name}_{expiry}_{opt_type}"

    if history_key not in st.session_state:
        st.session_state[history_key] = {}
    history = st.session_state[history_key]

    trends = []
    sma_values = []
    for _, row in df.iterrows():
        strike = row["Strike"]
        ltp = row["LTP"]

        if strike not in history:
            history[strike] = []
        history[strike].append(ltp)
        history[strike] = history[strike][-SMA_PERIOD:]

        prices = history[strike]
        if len(prices) < SMA_PERIOD:
            trends.append("—")
            sma_values.append(None)
        else:
            sma = sum(prices) / SMA_PERIOD
            sma_values.append(round(sma, 2))
            if ltp > sma:
                trends.append("UP")
            elif ltp < sma:
                trends.append("DOWN")
            else:
                trends.append("FLAT")

    df = df.copy()
    df["SMA"] = sma_values
    df["Trend"] = trends
    return df


def highlight_row(row, atm):
    styles = []
    is_atm = row["Strike"] == atm
    trend = row.get("Trend", "")
    for col in row.index:
        s = ""
        if is_atm:
            s = "background-color: #ffffb3; "
        if col == "Trend":
            if trend == "UP":
                s += "color: green; font-weight: bold"
            elif trend == "DOWN":
                s += "color: red; font-weight: bold"
        styles.append(s)
    return styles


# ================= RENDER ONE INDEX =================

def render_index(index_name, cfg):
    scrip = cfg["scrip"]
    segment = cfg["segment"]
    strike_step = cfg["strike_step"]
    strike_range = cfg["strike_range"]
    prefix = cfg["name_prefix"]

    # Fetch expiries
    try:
        expiries = get_expiries(scrip, segment, 3)
    except Exception as e:
        st.error(f"Could not fetch {index_name} expiries: {e}")
        return

    # Fetch all chains with rate-limit delay
    chain_data = {}
    for expiry in expiries:
        try:
            spot, df = fetch_option_chain(scrip, segment, expiry)
            chain_data[expiry] = (spot, df)
        except Exception as e:
            chain_data[expiry] = e
        time.sleep(3)

    # Spot price box
    spot_val = None
    for result in chain_data.values():
        if not isinstance(result, Exception):
            spot_val = result[0]
            break

    prev_key = f"prev_spot_{index_name}"
    prev_spot = st.session_state.get(prev_key)
    spot_delta = round(spot_val - prev_spot, 2) if (spot_val and prev_spot) else None
    if spot_val:
        st.session_state[prev_key] = spot_val

    col_price, col_atm, col_time, _ = st.columns([1, 1, 1, 3])
    with col_price:
        st.metric(index_name, f"{spot_val:,.2f}" if spot_val else "N/A",
                  delta=f"{spot_delta:+.2f}" if spot_delta else None)
    with col_atm:
        atm_display = round(spot_val / strike_step) * strike_step if spot_val else "N/A"
        st.metric("ATM Strike", f"{atm_display:,}" if spot_val else "N/A")
    with col_time:
        st.metric("Last Updated", now_ist().strftime("%H:%M:%S"))

    st.divider()

    # Expiry tabs
    expiry_tabs = st.tabs([f"Expiry: {exp}" for exp in expiries])

    for tab, expiry in zip(expiry_tabs, expiries):
        with tab:
            try:
                result = chain_data[expiry]
                if isinstance(result, Exception):
                    raise result
                spot, df = result
                atm = round(spot / strike_step) * strike_step
                df = build_name_column(df, expiry, prefix)

                ce, pe = filter_and_split(df, atm, strike_range)
                ce = add_trend(ce, index_name, expiry, "CE")
                pe = add_trend(pe, index_name, expiry, "PE")

                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("CALL (CE)")
                    st.dataframe(
                        ce.style.apply(highlight_row, atm=atm, axis=1),
                        use_container_width=True,
                        hide_index=True,
                    )
                with col2:
                    st.subheader("PUT (PE)")
                    st.dataframe(
                        pe.style.apply(highlight_row, atm=atm, axis=1),
                        use_container_width=True,
                        hide_index=True,
                    )

            except Exception as e:
                st.error(f"Error loading {expiry}: {e}")


# ================= ABCD PATTERN DETECTION =================

def get_atm_security_ids(scrip, segment, expiry, spot):
    """Get security IDs for ATM CE and PE from option chain."""
    r = api_call(dhan.option_chain, scrip, segment, expiry)
    if r.get("status") != "success":
        return None, None, None

    inner = r["data"]["data"]
    oc = inner["oc"]
    atm = round(spot / 50) * 50

    # Find closest strike to ATM
    strikes = sorted(oc.keys(), key=lambda s: abs(float(s) - atm))
    if not strikes:
        return None, None, atm

    best = strikes[0]
    sides = oc[best]
    ce_id = sides.get("ce", {}).get("security_id")
    pe_id = sides.get("pe", {}).get("security_id")
    return ce_id, pe_id, atm


def fetch_5min_candles(security_id):
    """Fetch 5-min intraday candles for a security (last 5 days)."""
    today = now_ist().strftime("%Y-%m-%d")
    from_date = (pd.Timestamp(now_ist().date()) - pd.Timedelta(days=5)).strftime("%Y-%m-%d")

    r = api_call(
        dhan.intraday_minute_data,
        str(security_id), "NSE_FNO", "OPTIDX", from_date, today, interval=5,
    )
    if r.get("status") != "success":
        return pd.DataFrame()

    d = r["data"]
    df = pd.DataFrame({
        "timestamp": d.get("timestamp", []),
        "open":      d.get("open", []),
        "high":      d.get("high", []),
        "low":       d.get("low", []),
        "close":     d.get("close", []),
        "volume":    d.get("volume", []),
    })
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    return df


def find_swing_points(df, order=3):
    """Find swing highs and lows using a rolling window comparison."""
    swings = []
    highs = df["high"].values
    lows = df["low"].values

    for i in range(order, len(df) - order):
        # Swing high: high[i] is highest in window
        if all(highs[i] >= highs[i - j] for j in range(1, order + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, order + 1)):
            swings.append({"index": i, "type": "high", "price": highs[i],
                           "time": df["timestamp"].iloc[i]})

        # Swing low: low[i] is lowest in window
        if all(lows[i] <= lows[i - j] for j in range(1, order + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, order + 1)):
            swings.append({"index": i, "type": "low", "price": lows[i],
                           "time": df["timestamp"].iloc[i]})

    return sorted(swings, key=lambda s: s["index"])


def detect_abcd_patterns(swings, tolerance=0.15):
    """
    Detect ABCD patterns from swing points.
    Bullish ABCD: A(low) -> B(high) -> C(low) -> D(high) — sell at D
    Bearish ABCD: A(high) -> B(low) -> C(high) -> D(low) — buy at D

    BC should retrace 61.8%-78.6% of AB (with tolerance).
    CD should be ~equal to AB in length (with tolerance).
    """
    patterns = []

    for i in range(len(swings) - 3):
        a, b, c, d = swings[i], swings[i+1], swings[i+2], swings[i+3]

        # Bullish: low -> high -> low -> high
        if a["type"] == "low" and b["type"] == "high" and \
           c["type"] == "low" and d["type"] == "high":
            ab = b["price"] - a["price"]
            bc = b["price"] - c["price"]
            cd = d["price"] - c["price"]

            if ab <= 0:
                continue

            bc_ratio = bc / ab  # should be 0.618–0.786
            cd_ab_ratio = cd / ab  # should be ~1.0

            if (0.618 - tolerance) <= bc_ratio <= (0.786 + tolerance) and \
               (1.0 - tolerance) <= cd_ab_ratio <= (1.618 + tolerance):
                patterns.append({
                    "type": "Bullish",
                    "A": a, "B": b, "C": c, "D": d,
                    "BC_retrace": round(bc_ratio, 3),
                    "CD_AB_ratio": round(cd_ab_ratio, 3),
                    "entry": d["price"],
                    "target": d["price"] + ab,  # project AB from D
                    "stop_loss": c["price"],
                    "signal": "SELL CE / BUY PE at D",
                })

        # Bearish: high -> low -> high -> low
        if a["type"] == "high" and b["type"] == "low" and \
           c["type"] == "high" and d["type"] == "low":
            ab = a["price"] - b["price"]
            bc = c["price"] - b["price"]
            cd = c["price"] - d["price"]

            if ab <= 0:
                continue

            bc_ratio = bc / ab
            cd_ab_ratio = cd / ab

            if (0.618 - tolerance) <= bc_ratio <= (0.786 + tolerance) and \
               (1.0 - tolerance) <= cd_ab_ratio <= (1.618 + tolerance):
                patterns.append({
                    "type": "Bearish",
                    "A": a, "B": b, "C": c, "D": d,
                    "BC_retrace": round(bc_ratio, 3),
                    "CD_AB_ratio": round(cd_ab_ratio, 3),
                    "entry": d["price"],
                    "target": d["price"] - ab,
                    "stop_loss": c["price"],
                    "signal": "BUY CE / SELL PE at D",
                })

    return patterns


def _pattern_key(p):
    """Unique key for a pattern based on A and D timestamps."""
    return f"{p['A']['time']}_{p['D']['time']}_{p['type']}"


def _send_telegram(message):
    """Send a Telegram alert, silently ignore failures."""
    try:
        if BOT_TOKEN and RECEIVER_CHAT_IDS:
            send_alert_to_all(message, RECEIVER_CHAT_IDS, BOT_TOKEN)
    except Exception as e:
        print(f"  [telegram] failed: {e}")


def classify_trades(patterns, current_price, contract_name=""):
    """Split patterns into active and completed trades, send Telegram alerts for new events."""
    active = []
    completed = []

    # Track which patterns we've already alerted on
    if "alerted_active" not in st.session_state:
        st.session_state["alerted_active"] = set()
    if "alerted_completed" not in st.session_state:
        st.session_state["alerted_completed"] = set()

    for p in patterns:
        entry = p["entry"]
        target = p["target"]
        sl = p["stop_loss"]
        key = _pattern_key(p)

        if p["type"] == "Bullish":
            pnl = entry - current_price
            if current_price <= target or current_price >= sl:
                p["exit_price"] = current_price
                p["pnl"] = round(pnl, 2)
                p["status"] = "Target Hit" if current_price <= target else "SL Hit"
                completed.append(p)

                # Alert on trade completion
                if key not in st.session_state["alerted_completed"]:
                    st.session_state["alerted_completed"].add(key)
                    emoji = "+" if p["pnl"] > 0 else ""
                    _send_telegram(
                        f"TRADE CLOSED | {contract_name}\n"
                        f"Pattern: {p['type']} ABCD\n"
                        f"Signal: {p['signal']}\n"
                        f"Entry: {entry:.2f} | Exit: {current_price:.2f}\n"
                        f"PnL: {emoji}{p['pnl']:.2f}\n"
                        f"Status: {p['status']}"
                    )
            else:
                p["unrealized_pnl"] = round(pnl, 2)
                active.append(p)

                # Alert on new active trade
                if key not in st.session_state["alerted_active"]:
                    st.session_state["alerted_active"].add(key)
                    _send_telegram(
                        f"NEW TRADE | {contract_name}\n"
                        f"Pattern: {p['type']} ABCD\n"
                        f"Signal: {p['signal']}\n"
                        f"Entry (D): {entry:.2f}\n"
                        f"Target: {target:.2f} | SL: {sl:.2f}\n"
                        f"BC Retrace: {p['BC_retrace']} | CD/AB: {p['CD_AB_ratio']}"
                    )
        else:
            pnl = current_price - entry
            if current_price >= target or current_price <= sl:
                p["exit_price"] = current_price
                p["pnl"] = round(pnl, 2)
                p["status"] = "Target Hit" if current_price >= target else "SL Hit"
                completed.append(p)

                if key not in st.session_state["alerted_completed"]:
                    st.session_state["alerted_completed"].add(key)
                    emoji = "+" if p["pnl"] > 0 else ""
                    _send_telegram(
                        f"TRADE CLOSED | {contract_name}\n"
                        f"Pattern: {p['type']} ABCD\n"
                        f"Signal: {p['signal']}\n"
                        f"Entry: {entry:.2f} | Exit: {current_price:.2f}\n"
                        f"PnL: {emoji}{p['pnl']:.2f}\n"
                        f"Status: {p['status']}"
                    )
            else:
                p["unrealized_pnl"] = round(pnl, 2)
                active.append(p)

                if key not in st.session_state["alerted_active"]:
                    st.session_state["alerted_active"].add(key)
                    _send_telegram(
                        f"NEW TRADE | {contract_name}\n"
                        f"Pattern: {p['type']} ABCD\n"
                        f"Signal: {p['signal']}\n"
                        f"Entry (D): {entry:.2f}\n"
                        f"Target: {target:.2f} | SL: {sl:.2f}\n"
                        f"BC Retrace: {p['BC_retrace']} | CD/AB: {p['CD_AB_ratio']}"
                    )

    return active, completed


# ================= RSI + SMA CROSSOVER DETECTION =================

RSI_PERIOD = 14
SMA_FAST = 9
SMA_SLOW = 21
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70


def compute_rsi(series, period=RSI_PERIOD):
    """Compute RSI from a price series."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_sma(series, period):
    return series.rolling(window=period, min_periods=period).mean()


def detect_rsi_sma_signals(candles):
    """
    Detect RSI + SMA crossover signals on 5-min candles.

    Buy signal:  SMA fast crosses above SMA slow AND RSI crosses above oversold (30)
    Sell signal: SMA fast crosses below SMA slow AND RSI crosses below overbought (70)

    Returns list of signal dicts.
    """
    df = candles.copy()
    df["rsi"] = compute_rsi(df["close"])
    df["sma_fast"] = compute_sma(df["close"], SMA_FAST)
    df["sma_slow"] = compute_sma(df["close"], SMA_SLOW)
    df = df.dropna().reset_index(drop=True)

    if len(df) < 2:
        return [], df

    signals = []
    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        curr = df.iloc[i]

        # Bullish: SMA fast crosses above slow + RSI was below 30 and now above
        if prev["sma_fast"] <= prev["sma_slow"] and curr["sma_fast"] > curr["sma_slow"] \
                and curr["rsi"] > RSI_OVERSOLD:
            target = curr["close"] * 1.02  # 2% target
            sl = curr["close"] * 0.98      # 2% stop loss
            signals.append({
                "type": "Bullish",
                "signal": "BUY CE — SMA crossover + RSI recovery",
                "entry": round(curr["close"], 2),
                "target": round(target, 2),
                "stop_loss": round(sl, 2),
                "time": curr["timestamp"],
                "rsi": round(curr["rsi"], 2),
                "sma_fast": round(curr["sma_fast"], 2),
                "sma_slow": round(curr["sma_slow"], 2),
            })

        # Bearish: SMA fast crosses below slow + RSI was above 70 and now below
        if prev["sma_fast"] >= prev["sma_slow"] and curr["sma_fast"] < curr["sma_slow"] \
                and curr["rsi"] < RSI_OVERBOUGHT:
            target = curr["close"] * 0.98
            sl = curr["close"] * 1.02
            signals.append({
                "type": "Bearish",
                "signal": "BUY PE — SMA crossover + RSI overbought",
                "entry": round(curr["close"], 2),
                "target": round(target, 2),
                "stop_loss": round(sl, 2),
                "time": curr["timestamp"],
                "rsi": round(curr["rsi"], 2),
                "sma_fast": round(curr["sma_fast"], 2),
                "sma_slow": round(curr["sma_slow"], 2),
            })

    return signals, df


def _rsi_signal_key(s):
    return f"rsi_{s['time']}_{s['type']}"


def classify_rsi_trades(signals, current_price, contract_name=""):
    """Classify RSI+SMA signals into active/completed, send Telegram alerts."""
    active = []
    completed = []

    if "alerted_rsi_active" not in st.session_state:
        st.session_state["alerted_rsi_active"] = set()
    if "alerted_rsi_completed" not in st.session_state:
        st.session_state["alerted_rsi_completed"] = set()

    for s in signals:
        entry = s["entry"]
        target = s["target"]
        sl = s["stop_loss"]
        key = _rsi_signal_key(s)

        if s["type"] == "Bullish":
            pnl = current_price - entry
            hit_target = current_price >= target
            hit_sl = current_price <= sl
        else:
            pnl = entry - current_price
            hit_target = current_price <= target
            hit_sl = current_price >= sl

        pnl = round(pnl, 2)

        if hit_target or hit_sl:
            s["exit_price"] = current_price
            s["pnl"] = pnl
            s["status"] = "Target Hit" if hit_target else "SL Hit"
            completed.append(s)

            if key not in st.session_state["alerted_rsi_completed"]:
                st.session_state["alerted_rsi_completed"].add(key)
                emoji = "+" if pnl > 0 else ""
                _send_telegram(
                    f"TRADE CLOSED [RSI+SMA] | {contract_name}\n"
                    f"Signal: {s['signal']}\n"
                    f"Entry: {entry:.2f} | Exit: {current_price:.2f}\n"
                    f"PnL: {emoji}{pnl:.2f}\n"
                    f"Status: {s['status']}"
                )
        else:
            s["unrealized_pnl"] = pnl
            active.append(s)

            if key not in st.session_state["alerted_rsi_active"]:
                st.session_state["alerted_rsi_active"].add(key)
                _send_telegram(
                    f"NEW TRADE [RSI+SMA] | {contract_name}\n"
                    f"Signal: {s['signal']}\n"
                    f"Entry: {entry:.2f}\n"
                    f"Target: {target:.2f} | SL: {sl:.2f}\n"
                    f"RSI: {s['rsi']} | SMA {SMA_FAST}/{SMA_SLOW}: {s['sma_fast']}/{s['sma_slow']}"
                )

    return active, completed


def render_rsi_expiry(cfg, expiry, raw):
    """Render RSI+SMA scanner for a single expiry."""
    spot = float(raw["last_price"])
    oc = raw["oc"]
    atm = round(spot / cfg["strike_step"]) * cfg["strike_step"]

    strikes = sorted(oc.keys(), key=lambda s: abs(float(s) - atm))
    if not strikes:
        st.error("No strikes found")
        return

    best_strike = strikes[0]
    sides = oc[best_strike]
    ce_id = sides.get("ce", {}).get("security_id")
    pe_id = sides.get("pe", {}).get("security_id")

    if not ce_id or not pe_id:
        st.error(f"No security IDs for ATM strike {best_strike}")
        return

    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
    exp_tag = exp_date.strftime("%d%b").upper()

    col_price, col_atm, col_exp = st.columns(3)
    with col_price:
        st.metric("NIFTY Spot", f"{spot:,.2f}")
    with col_atm:
        st.metric("ATM Strike", f"{atm:,}")
    with col_exp:
        st.metric("Expiry", expiry)

    st.divider()

    ce_tab, pe_tab = st.tabs([
        f"ATM CE — NIFTY {exp_tag} {int(atm)} CE",
        f"ATM PE — NIFTY {exp_tag} {int(atm)} PE",
    ])

    for opt_tab, sec_id, opt_type in [(ce_tab, ce_id, "CE"), (pe_tab, pe_id, "PE")]:
        with opt_tab:
            time.sleep(1)
            candles = fetch_5min_candles(sec_id)

            if candles.empty:
                st.warning(f"No candle data for ATM {opt_type} (ID: {sec_id})")
                continue

            contract_name = f"NIFTY {exp_tag} {int(atm)} {opt_type}"
            current_price = candles["close"].iloc[-1]

            # Detect RSI+SMA signals
            signals, df_ind = detect_rsi_sma_signals(candles)

            # Filter to today only
            today_date = pd.Timestamp(now_ist().date())
            signals = [s for s in signals
                       if pd.Timestamp(s["time"]).normalize() == today_date]

            # Chart: candlestick + SMA lines + RSI signals
            st.markdown(f"**{contract_name}** — Last: **{current_price}** | Candles: **{len(candles)}**")

            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=candles["timestamp"], open=candles["open"],
                high=candles["high"], low=candles["low"], close=candles["close"],
                name="Price", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
            ))

            if not df_ind.empty:
                fig.add_trace(go.Scatter(
                    x=df_ind["timestamp"], y=df_ind["sma_fast"],
                    mode="lines", line=dict(color="#2196f3", width=1.5),
                    name=f"SMA {SMA_FAST}",
                ))
                fig.add_trace(go.Scatter(
                    x=df_ind["timestamp"], y=df_ind["sma_slow"],
                    mode="lines", line=dict(color="#ff9800", width=1.5),
                    name=f"SMA {SMA_SLOW}",
                ))

            # Mark buy/sell signals
            buy_sigs = [s for s in signals if s["type"] == "Bullish"]
            sell_sigs = [s for s in signals if s["type"] == "Bearish"]
            if buy_sigs:
                fig.add_trace(go.Scatter(
                    x=[s["time"] for s in buy_sigs],
                    y=[s["entry"] for s in buy_sigs],
                    mode="markers", marker=dict(symbol="triangle-up", size=14, color="#26a69a"),
                    name="Buy Signal",
                ))
            if sell_sigs:
                fig.add_trace(go.Scatter(
                    x=[s["time"] for s in sell_sigs],
                    y=[s["entry"] for s in sell_sigs],
                    mode="markers", marker=dict(symbol="triangle-down", size=14, color="#ef5350"),
                    name="Sell Signal",
                ))

            fig.update_layout(
                height=500, xaxis_rangeslider_visible=False,
                xaxis_title="Time", yaxis_title="Price",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=0, r=0, t=30, b=0),
            )
            st.plotly_chart(fig, use_container_width=True)

            # RSI subplot
            if not df_ind.empty:
                fig_rsi = go.Figure()
                fig_rsi.add_trace(go.Scatter(
                    x=df_ind["timestamp"], y=df_ind["rsi"],
                    mode="lines", line=dict(color="#9c27b0", width=1.5), name="RSI",
                ))
                fig_rsi.add_hline(y=RSI_OVERBOUGHT, line_dash="dash", line_color="red",
                                  annotation_text="Overbought (70)")
                fig_rsi.add_hline(y=RSI_OVERSOLD, line_dash="dash", line_color="green",
                                  annotation_text="Oversold (30)")
                fig_rsi.update_layout(
                    height=200, yaxis_title="RSI", xaxis_title="Time",
                    margin=dict(l=0, r=0, t=10, b=0),
                )
                st.plotly_chart(fig_rsi, use_container_width=True)

            if not signals:
                st.info("No RSI+SMA signals detected today.")

            active, completed = classify_rsi_trades(signals, current_price, contract_name)

            # Store trades in session state for P&L tab
            rsi_key = f"rsi_trades_{contract_name}"
            st.session_state[rsi_key] = {"active": active, "completed": completed}

            active_tab, completed_tab = st.tabs(["Active Trades", "Completed Trades"])

            with active_tab:
                if not active:
                    st.info("No active trades")
                else:
                    rows = [{
                        "Signal":     t["signal"],
                        "Entry":      t["entry"],
                        "Target":     t["target"],
                        "Stop Loss":  t["stop_loss"],
                        "Current":    current_price,
                        "Unreal. PnL": t["unrealized_pnl"],
                        "RSI":        t["rsi"],
                        "Time":       t["time"].strftime("%d %b %H:%M") if hasattr(t["time"], "strftime") else str(t["time"]),
                    } for t in active]
                    adf = pd.DataFrame(rows)

                    def hl_pnl_a(row):
                        styles = [""] * len(row)
                        idx = row.index.get_loc("Unreal. PnL")
                        if row["Unreal. PnL"] > 0:
                            styles[idx] = "background-color: #c6efce; color: #006100; font-weight: bold"
                        elif row["Unreal. PnL"] < 0:
                            styles[idx] = "background-color: #ffc7ce; color: #9c0006; font-weight: bold"
                        return styles

                    st.dataframe(adf.style.apply(hl_pnl_a, axis=1),
                                 use_container_width=True, hide_index=True)

            with completed_tab:
                if not completed:
                    st.info("No completed trades")
                else:
                    rows = [{
                        "Signal":    t["signal"],
                        "Entry":     t["entry"],
                        "Target":    t["target"],
                        "Stop Loss": t["stop_loss"],
                        "Exit":      round(t["exit_price"], 2),
                        "PnL":       t["pnl"],
                        "Status":    t["status"],
                        "Time":      t["time"].strftime("%d %b %H:%M") if hasattr(t["time"], "strftime") else str(t["time"]),
                    } for t in completed]
                    cdf = pd.DataFrame(rows)

                    def hl_pnl_c(row):
                        styles = [""] * len(row)
                        pi = row.index.get_loc("PnL")
                        si = row.index.get_loc("Status")
                        if row["PnL"] > 0:
                            styles[pi] = "background-color: #c6efce; color: #006100; font-weight: bold"
                            styles[si] = "background-color: #c6efce; color: #006100"
                        elif row["PnL"] < 0:
                            styles[pi] = "background-color: #ffc7ce; color: #9c0006; font-weight: bold"
                            styles[si] = "background-color: #ffc7ce; color: #9c0006"
                        return styles

                    st.dataframe(cdf.style.apply(hl_pnl_c, axis=1),
                                 use_container_width=True, hide_index=True)


def render_rsi_sma_trade():
    """Render the RSI+SMA Crossover tab with rolling expiry tabs."""
    st.subheader("RSI + SMA Crossover Scanner — NIFTY ATM (5-min candles)")

    cfg = INDICES["NIFTY"]

    try:
        expiries = get_expiries(cfg["scrip"], cfg["segment"], 2, for_algo=True)
    except Exception as e:
        st.error(f"Could not fetch expiries: {e}")
        return

    expiry_data = {}
    for exp in expiries:
        try:
            raw = fetch_option_chain_raw(cfg["scrip"], cfg["segment"], exp)
            expiry_data[exp] = raw
        except Exception as e:
            expiry_data[exp] = e
        time.sleep(3)

    expiry_tabs = st.tabs([f"Expiry: {exp}" for exp in expiries])

    for tab, exp in zip(expiry_tabs, expiries):
        with tab:
            result = expiry_data[exp]
            if isinstance(result, Exception):
                st.error(f"Error loading {exp}: {result}")
            else:
                render_rsi_expiry(cfg, exp, result)


# ================= P&L SUMMARY =================

def collect_all_trades():
    """Collect all trades from ABCD and RSI strategies stored in session state."""
    all_active = []
    all_completed = []

    for key, val in st.session_state.items():
        if isinstance(val, dict) and "active" in val and "completed" in val:
            strategy = "ABCD" if key.startswith("abcd_") else "RSI+SMA" if key.startswith("rsi_") else "Unknown"
            for t in val["active"]:
                t["strategy"] = strategy
                all_active.append(t)
            for t in val["completed"]:
                t["strategy"] = strategy
                all_completed.append(t)

    return all_active, all_completed


def render_pnl_summary():
    """Render the P&L summary tab."""
    st.subheader("Profit / Loss Summary — All Strategies")

    all_active, all_completed = collect_all_trades()

    # --- Completed trades summary ---
    st.markdown("### Completed Trades")
    if not all_completed:
        st.info("No completed trades today")
    else:
        rows = [{
            "Strategy":  t.get("strategy", ""),
            "Signal":    t.get("signal", ""),
            "Entry":     t.get("entry", 0),
            "Exit":      round(t.get("exit_price", 0), 2),
            "PnL":       t.get("pnl", 0),
            "Status":    t.get("status", ""),
        } for t in all_completed]
        cdf = pd.DataFrame(rows)

        total_pnl = cdf["PnL"].sum()
        winners = len(cdf[cdf["PnL"] > 0])
        losers = len(cdf[cdf["PnL"] < 0])

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Total P&L", f"{total_pnl:+.2f}",
                      delta_color="normal" if total_pnl >= 0 else "inverse")
        with c2:
            st.metric("Total Trades", len(cdf))
        with c3:
            st.metric("Winners", winners)
        with c4:
            st.metric("Losers", losers)

        st.divider()

        # Per-strategy breakdown
        for strat in cdf["Strategy"].unique():
            sdf = cdf[cdf["Strategy"] == strat]
            spnl = sdf["PnL"].sum()
            st.markdown(f"**{strat}**: {len(sdf)} trades | PnL: **{spnl:+.2f}**")

        st.divider()

        def hl_pnl(row):
            styles = [""] * len(row)
            pi = row.index.get_loc("PnL")
            si = row.index.get_loc("Status")
            if row["PnL"] > 0:
                styles[pi] = "background-color: #c6efce; color: #006100; font-weight: bold"
                styles[si] = "background-color: #c6efce; color: #006100"
            elif row["PnL"] < 0:
                styles[pi] = "background-color: #ffc7ce; color: #9c0006; font-weight: bold"
                styles[si] = "background-color: #ffc7ce; color: #9c0006"
            return styles

        st.dataframe(cdf.style.apply(hl_pnl, axis=1),
                     use_container_width=True, hide_index=True)

    # --- Active trades ---
    st.markdown("### Active Trades")
    if not all_active:
        st.info("No active trades")
    else:
        rows = [{
            "Strategy":    t.get("strategy", ""),
            "Signal":      t.get("signal", ""),
            "Entry":       t.get("entry", 0),
            "Target":      t.get("target", 0),
            "Stop Loss":   t.get("stop_loss", 0),
            "Unreal. PnL": t.get("unrealized_pnl", 0),
        } for t in all_active]
        adf = pd.DataFrame(rows)

        total_unreal = adf["Unreal. PnL"].sum()
        st.metric("Unrealized P&L", f"{total_unreal:+.2f}")

        def hl_upnl(row):
            styles = [""] * len(row)
            idx = row.index.get_loc("Unreal. PnL")
            if row["Unreal. PnL"] > 0:
                styles[idx] = "background-color: #c6efce; color: #006100; font-weight: bold"
            elif row["Unreal. PnL"] < 0:
                styles[idx] = "background-color: #ffc7ce; color: #9c0006; font-weight: bold"
            return styles

        st.dataframe(adf.style.apply(hl_upnl, axis=1),
                     use_container_width=True, hide_index=True)


def send_daily_pnl_summary():
    """Send daily P&L summary via Telegram at 3:30 PM IST (once per day)."""
    now = now_ist()
    today_str = now.strftime("%Y-%m-%d")
    summary_key = f"daily_pnl_sent_{today_str}"

    # Only send once per day, after 3:30 PM
    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
        return
    if st.session_state.get(summary_key):
        return

    all_active, all_completed = collect_all_trades()

    total_realized = sum(t.get("pnl", 0) for t in all_completed)
    total_unrealized = sum(t.get("unrealized_pnl", 0) for t in all_active)
    total_trades = len(all_completed)
    winners = sum(1 for t in all_completed if t.get("pnl", 0) > 0)
    losers = sum(1 for t in all_completed if t.get("pnl", 0) < 0)

    # Per-strategy breakdown
    strat_lines = []
    strategies = set(t.get("strategy", "Unknown") for t in all_completed)
    for strat in sorted(strategies):
        strat_trades = [t for t in all_completed if t.get("strategy") == strat]
        spnl = sum(t.get("pnl", 0) for t in strat_trades)
        sw = sum(1 for t in strat_trades if t.get("pnl", 0) > 0)
        sl = sum(1 for t in strat_trades if t.get("pnl", 0) < 0)
        emoji = "+" if spnl > 0 else ""
        strat_lines.append(f"  {strat}: {len(strat_trades)} trades | {sw}W/{sl}L | PnL: {emoji}{spnl:.2f}")

    emoji_total = "+" if total_realized > 0 else ""
    breakdown = "\n".join(strat_lines) if strat_lines else "  No trades today"
    msg = (
        f"DAILY P&L SUMMARY | {today_str}\n"
        f"{'=' * 30}\n"
        f"Realized P&L: {emoji_total}{total_realized:.2f}\n"
        f"Unrealized P&L: {total_unrealized:+.2f}\n"
        f"Total Trades: {total_trades} ({winners}W / {losers}L)\n"
        f"\nStrategy Breakdown:\n{breakdown}"
    )

    _send_telegram(msg)
    st.session_state[summary_key] = True
    print(f"  [telegram] Daily P&L summary sent for {today_str}")


def fetch_option_chain_raw(scrip, segment, expiry):
    """Fetch raw option chain response (includes security_id per strike)."""
    r = api_call(dhan.option_chain, scrip, segment, expiry)
    if r.get("status") != "success":
        raise RuntimeError(f"option_chain failed: {r}")
    return r["data"]["data"]


def render_algo_expiry(cfg, expiry, raw):
    """Render ABCD scanner for a single expiry."""
    spot = float(raw["last_price"])
    oc = raw["oc"]
    atm = round(spot / cfg["strike_step"]) * cfg["strike_step"]

    # Find closest strike and get CE/PE security IDs
    strikes = sorted(oc.keys(), key=lambda s: abs(float(s) - atm))
    if not strikes:
        st.error("No strikes found in option chain")
        return

    best_strike = strikes[0]
    sides = oc[best_strike]
    ce_id = sides.get("ce", {}).get("security_id")
    pe_id = sides.get("pe", {}).get("security_id")

    if not ce_id or not pe_id:
        st.error(f"No security IDs for ATM strike {best_strike}. CE: {ce_id}, PE: {pe_id}")
        return

    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
    exp_tag = exp_date.strftime("%d%b").upper()

    col_price, col_atm, col_exp = st.columns(3)
    with col_price:
        st.metric("NIFTY Spot", f"{spot:,.2f}")
    with col_atm:
        st.metric("ATM Strike", f"{atm:,}")
    with col_exp:
        st.metric("Expiry", expiry)

    st.divider()

    # Fetch 5-min candles for CE and PE
    ce_tab, pe_tab = st.tabs([
        f"ATM CE — NIFTY {exp_tag} {int(atm)} CE",
        f"ATM PE — NIFTY {exp_tag} {int(atm)} PE",
    ])

    for opt_tab, sec_id, opt_type in [(ce_tab, ce_id, "CE"), (pe_tab, pe_id, "PE")]:
        with opt_tab:
            time.sleep(1)  # rate limit
            candles = fetch_5min_candles(sec_id)

            if candles.empty:
                st.warning(f"No candle data for ATM {opt_type} (ID: {sec_id})")
                continue

            contract_name = f"NIFTY {exp_tag} {int(atm)} {opt_type}"
            current_price = candles["close"].iloc[-1]

            # Detect ABCD patterns (before chart so we can overlay)
            swings = find_swing_points(candles, order=2)
            patterns = detect_abcd_patterns(swings)

            # Candlestick chart with ABCD overlay
            st.markdown(f"**{contract_name}** — Last: **{current_price}** | Candles: **{len(candles)}**")

            fig = go.Figure()

            # Candlestick
            fig.add_trace(go.Candlestick(
                x=candles["timestamp"],
                open=candles["open"],
                high=candles["high"],
                low=candles["low"],
                close=candles["close"],
                name="Price",
                increasing_line_color="#26a69a",
                decreasing_line_color="#ef5350",
            ))

            # Overlay swing points
            if swings:
                swing_highs = [s for s in swings if s["type"] == "high"]
                swing_lows = [s for s in swings if s["type"] == "low"]

                if swing_highs:
                    fig.add_trace(go.Scatter(
                        x=[s["time"] for s in swing_highs],
                        y=[s["price"] for s in swing_highs],
                        mode="markers",
                        marker=dict(symbol="triangle-down", size=10, color="#ef5350"),
                        name="Swing High",
                    ))
                if swing_lows:
                    fig.add_trace(go.Scatter(
                        x=[s["time"] for s in swing_lows],
                        y=[s["price"] for s in swing_lows],
                        mode="markers",
                        marker=dict(symbol="triangle-up", size=10, color="#26a69a"),
                        name="Swing Low",
                    ))

            # Overlay ABCD patterns as connected lines
            colors = ["#ff9800", "#2196f3", "#9c27b0", "#00bcd4", "#e91e63"]
            for idx, p in enumerate(patterns):
                color = colors[idx % len(colors)]
                pts = [p["A"], p["B"], p["C"], p["D"]]
                fig.add_trace(go.Scatter(
                    x=[pt["time"] for pt in pts],
                    y=[pt["price"] for pt in pts],
                    mode="lines+markers+text",
                    line=dict(color=color, width=2, dash="dot"),
                    marker=dict(size=12, color=color),
                    text=["A", "B", "C", "D"],
                    textposition="top center",
                    textfont=dict(size=14, color=color),
                    name=f"ABCD {idx+1} ({p['type']})",
                ))

                # Target and stop loss horizontal lines
                fig.add_hline(
                    y=p["target"], line_dash="dash", line_color="green",
                    annotation_text=f"Target {p['target']:.2f}",
                    annotation_position="bottom right",
                )
                fig.add_hline(
                    y=p["stop_loss"], line_dash="dash", line_color="red",
                    annotation_text=f"SL {p['stop_loss']:.2f}",
                    annotation_position="bottom right",
                )

            fig.update_layout(
                height=500,
                xaxis_rangeslider_visible=False,
                xaxis_title="Time",
                yaxis_title="Price",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=0, r=0, t=30, b=0),
            )

            st.plotly_chart(fig, use_container_width=True)

            # Only keep patterns where D (entry point) is from today
            today_date = pd.Timestamp(now_ist().date())
            patterns = [
                p for p in patterns
                if pd.Timestamp(p["D"]["time"]).normalize() == today_date
            ]

            if not patterns:
                st.info("No ABCD patterns detected today. Patterns will appear as price action develops.")

            active, completed = classify_trades(patterns, current_price, contract_name)

            # Store trades in session state for P&L tab
            abcd_key = f"abcd_trades_{contract_name}"
            st.session_state[abcd_key] = {"active": active, "completed": completed}

            # Nested tabs: Active / Completed
            active_tab, completed_tab = st.tabs(["Active Trades", "Completed Trades"])

            with active_tab:
                if not active:
                    st.info("No active trades")
                else:
                    rows = []
                    for t in active:
                        rows.append({
                            "Pattern":    t["type"],
                            "Signal":     t["signal"],
                            "Entry (D)":  round(t["entry"], 2),
                            "Target":     round(t["target"], 2),
                            "Stop Loss":  round(t["stop_loss"], 2),
                            "Current":    current_price,
                            "Unreal. PnL": t["unrealized_pnl"],
                            "A Time":     t["A"]["time"].strftime("%d %b %H:%M") if hasattr(t["A"]["time"], "strftime") else str(t["A"]["time"]),
                            "D Time":     t["D"]["time"].strftime("%d %b %H:%M") if hasattr(t["D"]["time"], "strftime") else str(t["D"]["time"]),
                            "BC Retrace":  t["BC_retrace"],
                            "CD/AB":       t["CD_AB_ratio"],
                        })
                    adf = pd.DataFrame(rows)

                    def highlight_pnl_active(row):
                        pnl = row["Unreal. PnL"]
                        styles = [""] * len(row)
                        pnl_idx = row.index.get_loc("Unreal. PnL")
                        if pnl > 0:
                            styles[pnl_idx] = "background-color: #c6efce; color: #006100; font-weight: bold"
                        elif pnl < 0:
                            styles[pnl_idx] = "background-color: #ffc7ce; color: #9c0006; font-weight: bold"
                        return styles

                    st.dataframe(
                        adf.style.apply(highlight_pnl_active, axis=1),
                        use_container_width=True, hide_index=True,
                    )

            with completed_tab:
                if not completed:
                    st.info("No completed trades")
                else:
                    rows = []
                    for t in completed:
                        rows.append({
                            "Pattern":   t["type"],
                            "Signal":    t["signal"],
                            "Entry (D)": round(t["entry"], 2),
                            "Target":    round(t["target"], 2),
                            "Stop Loss": round(t["stop_loss"], 2),
                            "Exit":      round(t["exit_price"], 2),
                            "PnL":       t["pnl"],
                            "Status":    t["status"],
                            "A Time":    t["A"]["time"].strftime("%d %b %H:%M") if hasattr(t["A"]["time"], "strftime") else str(t["A"]["time"]),
                            "D Time":    t["D"]["time"].strftime("%d %b %H:%M") if hasattr(t["D"]["time"], "strftime") else str(t["D"]["time"]),
                        })
                    cdf = pd.DataFrame(rows)

                    def highlight_pnl_completed(row):
                        pnl = row["PnL"]
                        status = row["Status"]
                        styles = [""] * len(row)
                        pnl_idx = row.index.get_loc("PnL")
                        status_idx = row.index.get_loc("Status")
                        if pnl > 0:
                            styles[pnl_idx] = "background-color: #c6efce; color: #006100; font-weight: bold"
                            styles[status_idx] = "background-color: #c6efce; color: #006100"
                        elif pnl < 0:
                            styles[pnl_idx] = "background-color: #ffc7ce; color: #9c0006; font-weight: bold"
                            styles[status_idx] = "background-color: #ffc7ce; color: #9c0006"
                        return styles

                    st.dataframe(
                        cdf.style.apply(highlight_pnl_completed, axis=1),
                        use_container_width=True, hide_index=True,
                    )

            # Show detected swing points
            with st.expander("Swing Points & Pattern Details"):
                if swings:
                    swing_df = pd.DataFrame(swings)
                    swing_df["time"] = swing_df["time"].dt.strftime("%d %b %H:%M")
                    swing_df["price"] = swing_df["price"].round(2)
                    st.dataframe(swing_df[["time", "type", "price"]], hide_index=True)
                else:
                    st.write("No swing points detected")

                if patterns:
                    for i, p in enumerate(patterns):
                        st.markdown(
                            f"**Pattern {i+1} ({p['type']})**: "
                            f"A={p['A']['price']:.2f} → B={p['B']['price']:.2f} → "
                            f"C={p['C']['price']:.2f} → D={p['D']['price']:.2f} | "
                            f"BC retrace: {p['BC_retrace']} | CD/AB: {p['CD_AB_ratio']}"
                        )


def render_algo_trade():
    """Render the Algo Trade tab with rolling expiry tabs."""
    st.subheader("ABCD Pattern Scanner — NIFTY ATM (5-min candles)")

    cfg = INDICES["NIFTY"]

    # Get 2 nearest expiries (rolling window — auto-skips expired after 3 PM)
    try:
        expiries = get_expiries(cfg["scrip"], cfg["segment"], 2, for_algo=True)
    except Exception as e:
        st.error(f"Could not fetch expiries: {e}")
        return

    # Fetch raw option chain for each expiry
    expiry_data = {}
    for exp in expiries:
        try:
            raw = fetch_option_chain_raw(cfg["scrip"], cfg["segment"], exp)
            expiry_data[exp] = raw
        except Exception as e:
            expiry_data[exp] = e
        time.sleep(3)

    # Create one tab per expiry
    expiry_tabs = st.tabs([f"Expiry: {exp}" for exp in expiries])

    for tab, exp in zip(expiry_tabs, expiries):
        with tab:
            result = expiry_data[exp]
            if isinstance(result, Exception):
                st.error(f"Error loading {exp}: {result}")
            else:
                render_algo_expiry(cfg, exp, result)


# ================= MARKET HOURS =================

MARKET_OPEN_HOUR, MARKET_OPEN_MIN = 9, 15
MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN = 15, 30


def is_market_open():
    """Check if current time (IST) is within market hours (9:15 AM - 3:30 PM IST, weekdays)."""
    now = now_ist()
    if now.weekday() > 4:
        return False
    market_open = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0, microsecond=0)
    market_close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MIN, second=0, microsecond=0)
    return market_open <= now <= market_close


def get_next_market_open():
    """Get the next market open datetime in IST."""
    now = now_ist()
    target = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0, microsecond=0)

    # If today is a weekday and market hasn't opened yet
    if now.weekday() <= 4 and now < target:
        return target

    # Otherwise, find next weekday
    days_ahead = 1
    while True:
        next_day = now + pd.Timedelta(days=days_ahead)
        if next_day.weekday() <= 4:
            return next_day.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0, microsecond=0)
        days_ahead += 1


# ================= STREAMLIT APP =================

st.set_page_config(page_title="Option Chain", layout="wide")
st.title("Option Chain")

# Make tabs bigger
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] button {
        font-size: 1.2rem;
        padding: 12px 24px;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
</style>
""", unsafe_allow_html=True)

if is_market_open():
    # Top-level tabs
    nifty_tab, banknifty_tab, algo_tab, rsi_tab, pnl_tab = st.tabs([
        "NIFTY", "BANKNIFTY", "ALGO TRADE (ABCD)", "ALGO TRADE (RSI+SMA)", "P&L SUMMARY"
    ])

    with nifty_tab:
        render_index("NIFTY", INDICES["NIFTY"])

    with banknifty_tab:
        render_index("BANKNIFTY", INDICES["BANKNIFTY"])

    with algo_tab:
        render_algo_trade()

    with rsi_tab:
        render_rsi_sma_trade()

    with pnl_tab:
        render_pnl_summary()

    # Morning market open message (once per day)
    today_str = now_ist().strftime("%Y-%m-%d")
    open_msg_key = f"market_open_sent_{today_str}"
    if not st.session_state.get(open_msg_key):
        st.session_state[open_msg_key] = True
        _send_telegram(
            f"MARKET OPEN | {today_str}\n"
            f"{'=' * 30}\n"
            f"Paper trading started for {now_ist().strftime('%A, %d %b %Y')}\n"
            f"Strategies active: ABCD, RSI+SMA\n"
            f"Monitoring: NIFTY ATM options\n"
            f"Refresh interval: {REFRESH_SECONDS}s\n"
            f"Good luck today!"
        )

    # Daily P&L Telegram at 3:30 PM IST
    send_daily_pnl_summary()

    # Auto-refresh
    st.markdown(f"_Auto-refreshes every {REFRESH_SECONDS}s_")
    time.sleep(REFRESH_SECONDS)
    st.rerun()

else:
    # Market is closed — show countdown
    next_open = get_next_market_open()
    remaining = next_open - now_ist()

    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    st.markdown("---")
    st.markdown(
        f"<div style='text-align:center; padding: 60px 0;'>"
        f"<h2>Market is Closed</h2>"
        f"<p style='font-size:1.2rem; color: #888;'>Next market open: <b>{next_open.strftime('%A, %d %b %Y at %I:%M %p')}</b></p>"
        f"<h1 style='font-size:4rem; color: #2196f3;'>{hours:02d}h {minutes:02d}m {seconds:02d}s</h1>"
        f"<p style='color: #888;'>Market hours: 9:15 AM — 3:30 PM IST (Mon–Fri)</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Still show P&L summary from today even after market close
    st.markdown("---")
    render_pnl_summary()

    # Refresh every 30s to update the countdown
    time.sleep(30)
    st.rerun()
