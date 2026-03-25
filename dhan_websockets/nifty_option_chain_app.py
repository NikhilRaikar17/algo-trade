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

    today = date.today()
    now_ist = datetime.now()  # system clock assumed IST

    all_future = sorted(
        d for d in data
        if isinstance(d, str) and datetime.strptime(d, "%Y-%m-%d").date() >= today
    )

    if for_algo:
        # On expiry day after rollover hour, skip today's expiry
        filtered = []
        for d in all_future:
            exp_date = datetime.strptime(d, "%Y-%m-%d").date()
            if exp_date == today and now_ist.hour >= EXPIRY_ROLLOVER_HOUR:
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
    today = date.today().strftime("%Y-%m-%d")
    from_date = (pd.Timestamp.today() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")

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
            today_date = pd.Timestamp.today().normalize()
            patterns = [
                p for p in patterns
                if pd.Timestamp(p["D"]["time"]).normalize() == today_date
            ]

            if not patterns:
                st.info("No ABCD patterns detected today. Patterns will appear as price action develops.")

            active, completed = classify_trades(patterns, current_price, contract_name)

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

# Top-level tabs: NIFTY, BANKNIFTY, Algo Trade
nifty_tab, banknifty_tab, algo_tab = st.tabs(["NIFTY", "BANKNIFTY", "ALGO TRADE"])

with nifty_tab:
    render_index("NIFTY", INDICES["NIFTY"])

with banknifty_tab:
    render_index("BANKNIFTY", INDICES["BANKNIFTY"])

with algo_tab:
    render_algo_trade()

# Auto-refresh
st.markdown(f"_Auto-refreshes every {REFRESH_SECONDS}s_")
time.sleep(REFRESH_SECONDS)
st.rerun()
