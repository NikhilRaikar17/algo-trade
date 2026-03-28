"""
Data fetching: expiries, option chains, candles, trend analysis.
"""

import pandas as pd
from datetime import datetime

from config import (
    dhan,
    now_ist,
    EXPIRY_ROLLOVER_HOUR,
    SMA_PERIOD,
)
from state import api_call, _cache_get, _cache_set, _ltp_history


def get_expiries(scrip, segment, count=3, for_algo=False):
    cache_key = f"expiries:{scrip}:{segment}:{for_algo}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached[:count]

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
        d
        for d in data
        if isinstance(d, str) and datetime.strptime(d, "%Y-%m-%d").date() >= today
    )

    if for_algo:
        filtered = []
        for d in all_future:
            exp_date = datetime.strptime(d, "%Y-%m-%d").date()
            if exp_date == today and ist_now.hour >= EXPIRY_ROLLOVER_HOUR:
                continue
            if exp_date < today:
                continue
            filtered.append(d)
        expiries = filtered
    else:
        expiries = [
            d for d in all_future if datetime.strptime(d, "%Y-%m-%d").date() > today
        ]

    if not expiries:
        raise RuntimeError("No future expiries found.")
    _cache_set(cache_key, expiries)
    return expiries[:count]


def fetch_option_chain(scrip, segment, expiry):
    cache_key = f"oc:{scrip}:{segment}:{expiry}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    r = api_call(dhan.option_chain, scrip, segment, expiry)
    if r.get("status") != "success":
        raise RuntimeError(f"option_chain failed: {r}")
    inner = r["data"]["data"]
    spot = round(float(inner["last_price"]), 2)
    oc = inner["oc"]

    rows = []
    for strike_str, sides in oc.items():
        strike = float(strike_str)
        for opt_type, key in [("CE", "ce"), ("PE", "pe")]:
            info = sides.get(key, {})
            if not info:
                continue
            greeks = info.get("greeks", {})
            rows.append(
                {
                    "Strike": strike,
                    "Type": opt_type,
                    "LTP": round(float(info.get("last_price", 0)), 2),
                    "IV (%)": round(float(info.get("implied_volatility", 0)), 2),
                    "Delta": round(float(greeks.get("delta", 0)), 4),
                    "Gamma": round(float(greeks.get("gamma", 0)), 6),
                    "Theta": round(float(greeks.get("theta", 0)), 4),
                    "Vega": round(float(greeks.get("vega", 0)), 4),
                }
            )
    result = (spot, pd.DataFrame(rows))
    _cache_set(cache_key, result)
    return result


def fetch_option_chain_raw(scrip, segment, expiry):
    cache_key = f"oc_raw:{scrip}:{segment}:{expiry}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    r = api_call(dhan.option_chain, scrip, segment, expiry)
    if r.get("status") != "success":
        raise RuntimeError(f"option_chain failed: {r}")
    result = r["data"]["data"]
    _cache_set(cache_key, result)
    return result


def build_name_column(df, expiry, prefix):
    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
    exp_tag = exp_date.strftime("%d%b").upper()
    df = df.copy()
    df.insert(
        0,
        "Name",
        df.apply(
            lambda r: f"{prefix} {exp_tag} {int(r['Strike'])} {r['Type']}", axis=1
        ),
    )
    return df


def filter_and_split(df, atm, strike_range):
    lower = atm - strike_range
    upper = atm + strike_range
    df = df[(df["Strike"] >= lower) & (df["Strike"] <= upper)].copy()
    df = df.sort_values("Strike").reset_index(drop=True)
    ce = df[df["Type"] == "CE"].drop(columns=["Type"]).reset_index(drop=True)
    pe = df[df["Type"] == "PE"].drop(columns=["Type"]).reset_index(drop=True)
    return ce, pe


def add_trend(df, index_name, expiry, opt_type):
    history_key = f"history_{index_name}_{expiry}_{opt_type}"
    if history_key not in _ltp_history:
        _ltp_history[history_key] = {}
    history = _ltp_history[history_key]

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


def fetch_5min_candles(security_id):
    today = now_ist().strftime("%Y-%m-%d")
    from_date = (pd.Timestamp(now_ist().date()) - pd.Timedelta(days=5)).strftime(
        "%Y-%m-%d"
    )
    r = api_call(
        dhan.intraday_minute_data,
        str(security_id),
        "NSE_FNO",
        "OPTIDX",
        from_date,
        today,
        interval=5,
    )
    if r.get("status") != "success":
        return pd.DataFrame()
    d = r["data"]
    df = pd.DataFrame(
        {
            "timestamp": d.get("timestamp", []),
            "open": d.get("open", []),
            "high": d.get("high", []),
            "low": d.get("low", []),
            "close": d.get("close", []),
            "volume": d.get("volume", []),
        }
    )
    if not df.empty:
        df["timestamp"] = pd.to_datetime(
            df["timestamp"], unit="s", utc=True
        ).dt.tz_convert("Asia/Kolkata")
    return df
