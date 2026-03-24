"""
nifty_option_chain_app.py
-------------------------
Streamlit app — NIFTY option chain with 3 expiry tabs.
Run:  streamlit run dhan_websockets/nifty_option_chain_app.py
"""

import os
import time
import pandas as pd
import streamlit as st
from datetime import datetime, date
from dotenv import load_dotenv
from dhanhq import dhanhq

# ================= ENV =================
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)

CLIENT_ID    = os.getenv("DHAN_CLIENT_CODE")
ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID")
dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# ================= CONFIG =================
NIFTY_SCRIP   = 13
NIFTY_SEGMENT = "IDX_I"
STRIKE_RANGE  = 500
REFRESH_SECONDS = 30


# ================= DATA FUNCTIONS =================

def get_expiries(count=3):
    r = dhan.expiry_list(NIFTY_SCRIP, NIFTY_SEGMENT)
    if r.get("status") != "success":
        raise RuntimeError(f"expiry_list failed: {r}")

    data = r["data"]
    if isinstance(data, dict):
        data = data.get("data", data)
    if isinstance(data, dict):
        data = next(iter(data.values()))

    today = date.today()
    expiries = sorted(
        d for d in data
        if isinstance(d, str) and datetime.strptime(d, "%Y-%m-%d").date() > today
    )
    if not expiries:
        raise RuntimeError("No future expiries found.")
    return expiries[:count]


def fetch_option_chain(expiry):
    r = dhan.option_chain(NIFTY_SCRIP, NIFTY_SEGMENT, expiry)
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
                "LTP":     float(info.get("last_price", 0)),
                "OI":      int(info.get("oi", 0)),
                "IV (%)":  round(float(info.get("implied_volatility", 0)), 2),
                "Volume":  int(info.get("volume", 0)),
                "Delta":   round(float(greeks.get("delta", 0)), 4),
                "Gamma":   round(float(greeks.get("gamma", 0)), 6),
                "Theta":   round(float(greeks.get("theta", 0)), 4),
                "Vega":    round(float(greeks.get("vega", 0)), 4),
            })
    return spot, pd.DataFrame(rows)


def build_name_column(df, expiry):
    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
    exp_tag = exp_date.strftime("%d%b").upper()
    df.insert(0, "Name", df.apply(
        lambda r: f"NIFTY {exp_tag} {int(r['Strike'])} {r['Type']}", axis=1
    ))
    return df


def filter_and_split(df, atm):
    lower = atm - STRIKE_RANGE
    upper = atm + STRIKE_RANGE
    df = df[(df["Strike"] >= lower) & (df["Strike"] <= upper)].copy()
    df = df.sort_values("Strike").reset_index(drop=True)

    ce = df[df["Type"] == "CE"].drop(columns=["Type"]).reset_index(drop=True)
    pe = df[df["Type"] == "PE"].drop(columns=["Type"]).reset_index(drop=True)
    return ce, pe


def highlight_atm(row, atm):
    if row["Strike"] == atm:
        return ["background-color: #ffffb3"] * len(row)
    return [""] * len(row)


# ================= TREND LOGIC (SMA) =================
SMA_PERIOD = 5  # number of refreshes for the moving average

def add_trend(df, expiry, opt_type):
    """Use SMA to determine trend. LTP > SMA = Uptrend, LTP < SMA = Downtrend."""
    history_key = f"history_{expiry}_{opt_type}"

    # history is a dict: strike -> list of recent LTPs
    if history_key not in st.session_state:
        st.session_state[history_key] = {}
    history = st.session_state[history_key]

    trends = []
    sma_values = []
    for _, row in df.iterrows():
        strike = row["Strike"]
        ltp = row["LTP"]

        # Append current LTP to history, keep last SMA_PERIOD values
        if strike not in history:
            history[strike] = []
        history[strike].append(ltp)
        history[strike] = history[strike][-SMA_PERIOD:]

        prices = history[strike]
        if len(prices) < SMA_PERIOD:
            trends.append("—")
            sma_values.append("")
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


# ================= STREAMLIT APP =================

st.set_page_config(page_title="NIFTY Option Chain", layout="wide")
st.title("NIFTY Option Chain")

# Fetch expiries
try:
    expiries = get_expiries(3)
except Exception as e:
    st.error(f"Could not fetch expiries: {e}")
    st.stop()

# Create tabs
tabs = st.tabs([f"Expiry: {exp}" for exp in expiries])

# Fetch all data upfront with delay between calls to avoid rate limit
chain_data = {}
for expiry in expiries:
    try:
        spot, df = fetch_option_chain(expiry)
        chain_data[expiry] = (spot, df)
    except Exception as e:
        chain_data[expiry] = e
    time.sleep(2)  # avoid Dhan rate limit

for tab, expiry in zip(tabs, expiries):
    with tab:
        try:
            result = chain_data[expiry]
            if isinstance(result, Exception):
                raise result
            spot, df = result
            atm = round(spot / 50) * 50
            df = build_name_column(df, expiry)

            st.markdown(f"**Spot:** {spot}  |  **ATM:** {atm}  |  **Expiry:** {expiry}  |  **Refreshed:** {datetime.now().strftime('%H:%M:%S')}")

            ce, pe = filter_and_split(df, atm)

            # Add trend column
            ce = add_trend(ce, expiry, "CE")
            pe = add_trend(pe, expiry, "PE")

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

# Auto-refresh
st.markdown(f"_Auto-refreshes every {REFRESH_SECONDS}s_")
time.sleep(REFRESH_SECONDS)
st.rerun()
