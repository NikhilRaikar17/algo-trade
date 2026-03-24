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

# ================= ENV =================
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)

CLIENT_ID    = os.getenv("DHAN_CLIENT_CODE")
ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID")
dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# ================= CONFIG =================
REFRESH_SECONDS = 30
SMA_PERIOD = 5

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


# ================= DATA FUNCTIONS =================

def get_expiries(scrip, segment, count=3):
    r = dhan.expiry_list(scrip, segment)
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


def fetch_option_chain(scrip, segment, expiry):
    r = dhan.option_chain(scrip, segment, expiry)
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
        time.sleep(2)

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
        st.metric("Last Updated", datetime.now().strftime("%H:%M:%S"))

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

# Top-level tabs: NIFTY and BANKNIFTY
nifty_tab, banknifty_tab = st.tabs(["NIFTY", "BANKNIFTY"])

with nifty_tab:
    render_index("NIFTY", INDICES["NIFTY"])

with banknifty_tab:
    render_index("BANKNIFTY", INDICES["BANKNIFTY"])

# Auto-refresh
st.markdown(f"_Auto-refreshes every {REFRESH_SECONDS}s_")
time.sleep(REFRESH_SECONDS)
st.rerun()
