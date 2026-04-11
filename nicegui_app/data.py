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
    INDICES,
)
from state import api_call, _cache_get, _cache_set, _ltp_history, _get_fetch_lock


def check_dhan_api():
    """Quick health check — fetch NIFTY expiry list and return status dict."""
    import time as _time
    t0 = _time.time()
    try:
        r = dhan.expiry_list("13", "IDX_I")
        latency_ms = int((_time.time() - t0) * 1000)
        if isinstance(r, dict) and r.get("status") == "success":
            return {"ok": True,  "latency_ms": latency_ms, "error": None}
        msg = str(r.get("remarks", r)) if isinstance(r, dict) else str(r)
        return {"ok": False, "latency_ms": latency_ms, "error": msg[:80]}
    except Exception as e:
        latency_ms = int((_time.time() - t0) * 1000)
        return {"ok": False, "latency_ms": latency_ms, "error": str(e)[:80]}


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


def fetch_option_chain_raw(scrip, segment, expiry):
    cache_key = f"oc_raw:{scrip}:{segment}:{expiry}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Serialize concurrent callers for the same key — second caller waits,
    # then returns from cache instead of making a duplicate API call.
    with _get_fetch_lock(cache_key):
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        r = api_call(dhan.option_chain, scrip, segment, expiry)
        if r.get("status") != "success":
            raise RuntimeError(f"option_chain failed: {r}")
        result = r["data"]["data"]
        _cache_set(cache_key, result)
        return result


def fetch_option_chain(scrip, segment, expiry):
    cache_key = f"oc:{scrip}:{segment}:{expiry}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Delegate to fetch_option_chain_raw so both share a single API call + cache entry
    inner = fetch_option_chain_raw(scrip, segment, expiry)
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


INDEX_SECURITY_IDS = {
    "NIFTY":     "13",
    "BANKNIFTY": "25",
}

# All tracked indices grouped by category for the Markets page
# security_id values sourced from Dhan instrument master (IDX_I segment)
MARKET_WATCH_GROUPS = [
    {
        "group": "Broad Market",
        "indices": [
            {"name": "NIFTY 50",       "security_id": "13"},
            {"name": "NIFTY NEXT 50",  "security_id": "38"},
            {"name": "NIFTY 100",      "security_id": "17"},
            {"name": "NIFTY 200",      "security_id": "18"},
            {"name": "NIFTY 500",      "security_id": "19"},
            {"name": "NIFTY MIDCAP 100","security_id": "37"},
            {"name": "NIFTY MIDCAP 50","security_id": "20"},
            {"name": "NIFTY SMLCAP 100","security_id": "5"},
            {"name": "INDIA VIX",      "security_id": "21"},
        ],
    },
    {
        "group": "Banks & Financials",
        "indices": [
            {"name": "BANK NIFTY",     "security_id": "25"},
            {"name": "FINNIFTY",       "security_id": "27"},
            {"name": "NIFTY PSU BANK", "security_id": "33"},
            {"name": "NIFTY PVT BANK", "security_id": "15"},
        ],
    },
    {
        "group": "Sectors",
        "indices": [
            {"name": "NIFTY IT",       "security_id": "29"},
            {"name": "NIFTY PHARMA",   "security_id": "32"},
            {"name": "NIFTY AUTO",     "security_id": "14"},
            {"name": "NIFTY FMCG",     "security_id": "28"},
            {"name": "NIFTY METAL",    "security_id": "31"},
            {"name": "NIFTY REALTY",   "security_id": "34"},
            {"name": "NIFTY ENERGY",   "security_id": "42"},
            {"name": "NIFTY INFRA",    "security_id": "43"},
            {"name": "NIFTY MEDIA",    "security_id": "30"},
        ],
    },
]


def _candles_to_daily_change(df):
    """Extract today's stats vs previous close from a 15-min candle DataFrame."""
    if df.empty:
        return None
    dates = sorted(df["timestamp"].dt.date.unique())
    if len(dates) < 2:
        return None
    today_df = df[df["timestamp"].dt.date == dates[-1]]
    prev_df  = df[df["timestamp"].dt.date == dates[-2]]
    prev_close = float(prev_df["close"].iloc[-1])
    current    = float(today_df["close"].iloc[-1]) if not today_df.empty else prev_close
    high       = float(today_df["high"].max())     if not today_df.empty else prev_close
    low        = float(today_df["low"].min())       if not today_df.empty else prev_close
    open_      = float(today_df["open"].iloc[0])   if not today_df.empty else prev_close
    change     = current - prev_close
    return {
        "current":    round(current, 2),
        "prev_close": round(prev_close, 2),
        "open":       round(open_, 2),
        "high":       round(high, 2),
        "low":        round(low, 2),
        "change":     round(change, 2),
        "change_pct": round((change / prev_close) * 100, 2),
        "is_green":   change >= 0,
    }


STOCK_WATCH_GROUPS = [
    {
        "group": "Large Cap",
        "stocks": [
            {"name": "RELIANCE",    "security_id": "2885"},
            {"name": "TCS",         "security_id": "11536"},
            {"name": "HDFCBANK",    "security_id": "1330"},
            {"name": "INFY",        "security_id": "1594"},
            {"name": "ICICIBANK",   "security_id": "4963"},
            {"name": "HINDUNILVR",  "security_id": "1394"},
            {"name": "ITC",         "security_id": "1660"},
            {"name": "SBIN",        "security_id": "3045"},
            {"name": "BHARTIARTL",  "security_id": "317"},
            {"name": "KOTAKBANK",   "security_id": "1922"},
            {"name": "LT",          "security_id": "11483"},
            {"name": "AXISBANK",    "security_id": "5900"},
            {"name": "WIPRO",       "security_id": "3787"},
            {"name": "HCLTECH",     "security_id": "7229"},
            {"name": "ASIANPAINT",  "security_id": "236"},
            {"name": "MARUTI",      "security_id": "10999"},
            {"name": "BAJFINANCE",  "security_id": "16675"},
            {"name": "TITAN",       "security_id": "3506"},
            {"name": "SUNPHARMA",   "security_id": "3351"},
            {"name": "ULTRACEMCO",  "security_id": "11532"},
        ],
    },
    {
        "group": "Mid Cap",
        "stocks": [
            {"name": "PIIND",       "security_id": "2412"},
            {"name": "MPHASIS",     "security_id": "4397"},
            {"name": "PERSISTENT",  "security_id": "2452"},
            {"name": "COFORGE",     "security_id": "10096"},
            {"name": "LTIM",        "security_id": "17818"},
            {"name": "TATACOMM",    "security_id": "14109"},
            {"name": "ADANIPORTS",  "security_id": "15083"},
            {"name": "GRASIM",      "security_id": "1232"},
            {"name": "HINDALCO",    "security_id": "1375"},
            {"name": "JSWSTEEL",    "security_id": "11723"},
        ],
    },
    {
        "group": "Banks",
        "stocks": [
            {"name": "INDUSINDBK",  "security_id": "5258"},
            {"name": "FEDERALBNK",  "security_id": "1023"},
            {"name": "BANDHANBNK",  "security_id": "1510"},
            {"name": "IDFCFIRSTB",  "security_id": "11809"},
            {"name": "PNB",         "security_id": "2730"},
            {"name": "BANKBARODA",  "security_id": "1152"},
            {"name": "CANBK",       "security_id": "10794"},
            {"name": "AUBANK",      "security_id": "3660"},
        ],
    },
]


def _fetch_any_stock_candles(security_id: str, interval: int = 15) -> pd.DataFrame:
    """Fetch candles for any NSE equity (stock) by security_id."""
    today     = now_ist().strftime("%Y-%m-%d")
    from_date = (pd.Timestamp(now_ist().date()) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    cache_key = f"eq_candles_{security_id}:{interval}:{from_date}:{today}"
    cached    = _cache_get(cache_key)
    if cached is not None:
        return cached
    r = api_call(
        dhan.intraday_minute_data,
        security_id, "NSE_EQ", "EQUITY",
        from_date, today, interval=interval,
        retries=1,
    )
    if r.get("status") != "success":
        return pd.DataFrame()
    d  = r["data"]
    df = pd.DataFrame({
        "timestamp": d.get("timestamp", []),
        "open":      d.get("open", []),
        "high":      d.get("high", []),
        "low":       d.get("low", []),
        "close":     d.get("close", []),
    })
    if not df.empty:
        df["timestamp"] = pd.to_datetime(
            df["timestamp"], unit="s", utc=True
        ).dt.tz_convert("Asia/Kolkata")
    _cache_set(cache_key, df)
    return df


def _fetch_any_index_candles(security_id: str, interval: int = 15) -> pd.DataFrame:
    """Fetch candles for any NSE index by security_id."""
    today     = now_ist().strftime("%Y-%m-%d")
    from_date = (pd.Timestamp(now_ist().date()) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    cache_key = f"idx_candles_{security_id}:{interval}:{from_date}:{today}"
    cached    = _cache_get(cache_key)
    if cached is not None:
        return cached
    r = api_call(
        dhan.intraday_minute_data,
        security_id, "IDX_I", "INDEX",
        from_date, today, interval=interval,
        retries=1,  # no retry — bulk best-effort call
    )
    if r.get("status") != "success":
        return pd.DataFrame()
    d  = r["data"]
    df = pd.DataFrame({
        "timestamp": d.get("timestamp", []),
        "open":      d.get("open", []),
        "high":      d.get("high", []),
        "low":       d.get("low", []),
        "close":     d.get("close", []),
    })
    if not df.empty:
        df["timestamp"] = pd.to_datetime(
            df["timestamp"], unit="s", utc=True
        ).dt.tz_convert("Asia/Kolkata")
    _cache_set(cache_key, df)
    return df


def fetch_daily_candles_for_index(security_id: str, days: int = 365) -> pd.DataFrame:
    """Fetch daily OHLC candles for an NSE index by security_id."""
    today     = now_ist().strftime("%Y-%m-%d")
    from_date = (pd.Timestamp(now_ist().date()) - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    cache_key = f"daily_candles_{security_id}:{from_date}:{today}"
    cached    = _cache_get(cache_key)
    if cached is not None:
        return cached
    r = api_call(
        dhan.historical_daily_data,
        security_id, "IDX_I", "INDEX",
        from_date, today,
        retries=1,
    )
    if r.get("status") != "success":
        return pd.DataFrame()
    d  = r["data"]
    df = pd.DataFrame({
        "timestamp": d.get("timestamp", []),
        "open":      d.get("open", []),
        "high":      d.get("high", []),
        "low":       d.get("low", []),
        "close":     d.get("close", []),
    })
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    _cache_set(cache_key, df)
    return df


def fetch_market_overview():
    """Return grouped index data for the Markets page."""
    cache_key = f"market_overview:{now_ist().strftime('%Y-%m-%d %H')}"
    cached    = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Reuse already-cached NIFTY / BANKNIFTY candles where possible
    _known = {
        "13": lambda: fetch_index_15min_candles("NIFTY"),
        "25": lambda: fetch_index_15min_candles("BANKNIFTY"),
    }

    result = []
    for group in MARKET_WATCH_GROUPS:
        entries = []
        for idx in group["indices"]:
            sid  = idx["security_id"]
            data = None
            try:
                df   = _known[sid]() if sid in _known else _fetch_any_index_candles(sid)
                data = _candles_to_daily_change(df)
            except Exception as e:
                print(f"  [market_overview] {idx['name']} error: {e}")
            entries.append({"name": idx["name"], "security_id": sid, "data": data})
        result.append({"group": group["group"], "indices": entries})

    _cache_set(cache_key, result)
    return result


def fetch_index_15min_candles(index_name="NIFTY"):
    """Fetch 15-min OHLCV candles for NIFTY or BANKNIFTY index (last 5 trading days)."""
    sec_id = INDEX_SECURITY_IDS.get(index_name, "13")
    today = now_ist().strftime("%Y-%m-%d")
    from_date = (pd.Timestamp(now_ist().date()) - pd.Timedelta(days=7)).strftime(
        "%Y-%m-%d"
    )
    cache_key = f"{index_name}_15min:{from_date}:{today}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    r = api_call(
        dhan.intraday_minute_data,
        sec_id,
        "IDX_I",
        "INDEX",
        from_date,
        today,
        interval=15,
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
    _cache_set(cache_key, df)
    return df


def fetch_atm_option_15min_candles(index_name: str, expiry_idx: int, opt_type: str) -> tuple[str, pd.DataFrame]:
    """Fetch 15-min candles for the ATM CE or PE of NIFTY/BANKNIFTY at a given expiry index.

    Args:
        index_name: "NIFTY" or "BANKNIFTY"
        expiry_idx: 0 = current/nearest expiry, 1 = next, 2 = next+1
        opt_type: "CE" or "PE"

    Returns:
        (contract_label, candles_df)  — label e.g. "NIFTY 03APR 23000 CE"
    """
    cfg = INDICES[index_name]
    scrip = cfg["scrip"]
    segment = cfg["segment"]

    # Fetch enough expiries (expiry_idx + 1)
    expiries = get_expiries(scrip, segment, count=expiry_idx + 1)
    expiry = expiries[expiry_idx]

    raw = fetch_option_chain_raw(scrip, segment, expiry)
    spot = round(float(raw["last_price"]), 2)
    atm = round(spot / cfg["strike_step"]) * cfg["strike_step"]

    strikes = sorted(raw["oc"].keys(), key=lambda s: abs(float(s) - atm))
    if not strikes:
        raise RuntimeError(f"No strikes found in option chain for {index_name} {expiry}")

    sides = raw["oc"][strikes[0]]
    key = opt_type.lower()
    sec_id = sides.get(key, {}).get("security_id")
    if not sec_id:
        raise RuntimeError(f"No security_id for {index_name} {expiry} ATM {opt_type}")

    exp_date = pd.Timestamp(expiry)
    exp_tag = exp_date.strftime("%d%b").upper()
    ltp = round(float(sides.get(opt_type.lower(), {}).get("last_price", 0)), 2)
    ltp_str = f" @ {ltp:.2f}" if ltp else ""
    contract_label = f"{index_name} {exp_tag} {int(atm)} {opt_type}{ltp_str}"

    today = now_ist().strftime("%Y-%m-%d")
    from_date = (pd.Timestamp(now_ist().date()) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    cache_key = f"opt_15min:{sec_id}:{from_date}:{today}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return contract_label, cached

    r = api_call(
        dhan.intraday_minute_data,
        str(sec_id),
        "NSE_FNO",
        "OPTIDX",
        from_date,
        today,
        interval=15,
        retries=1,
    )
    if r.get("status") != "success":
        return contract_label, pd.DataFrame()

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
        df["timestamp"] = pd.to_datetime(
            df["timestamp"], unit="s", utc=True
        ).dt.tz_convert("Asia/Kolkata")
    _cache_set(cache_key, df)
    return contract_label, df


def resolve_option_label(index_name: str, expiry_idx: int, opt_type: str) -> str:
    """Resolve the real contract label (e.g. 'NIFTY 07APR 22350 CE') without fetching candles."""
    cfg = INDICES[index_name]
    scrip = cfg["scrip"]
    segment = cfg["segment"]
    expiries = get_expiries(scrip, segment, count=expiry_idx + 1)
    expiry = expiries[expiry_idx]
    raw = fetch_option_chain_raw(scrip, segment, expiry)
    spot = round(float(raw["last_price"]), 2)
    atm = round(spot / cfg["strike_step"]) * cfg["strike_step"]
    exp_tag = pd.Timestamp(expiry).strftime("%d%b").upper()
    return f"{index_name} {exp_tag} {int(atm)} {opt_type}"


def fetch_5min_candles(security_id, interval=5):
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
        interval=interval,
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
