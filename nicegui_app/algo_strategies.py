"""
Trading strategies: ABCD harmonic patterns and RSI + SMA crossover.
"""

from datetime import time as _dtime

import numpy as np
import talib

from config import RSI_PERIOD, SMA_FAST, SMA_SLOW, RSI_OVERSOLD, RSI_OVERBOUGHT, now_ist
from state import _is_already_sent, _mark_sent, _send_telegram, save_completed_trade

_MARKET_CLOSE = _dtime(15, 30)


def _same_day_candles(future, signal_time):
    """Return candles on the same date as signal_time, up to 3:30 PM only."""
    sig_date = signal_time.date()
    mask = (future["timestamp"].dt.date == sig_date) & (
        future["timestamp"].dt.time <= _MARKET_CLOSE
    )
    return future[mask]

RSI_ONLY_TARGET_PCT = 0.02  # 2% target (1:2 R:R with 1% SL)
RSI_ONLY_SL_PCT = 0.01      # 1% stop loss


# ================= ABCD PATTERN DETECTION =================


def find_swing_points(df, order=3):
    swings = []
    highs = df["high"].values
    lows = df["low"].values
    for i in range(order, len(df) - order):
        if all(highs[i] >= highs[i - j] for j in range(1, order + 1)) and all(
            highs[i] >= highs[i + j] for j in range(1, order + 1)
        ):
            swings.append(
                {
                    "index": int(i),
                    "type": "high",
                    "price": float(highs[i]),
                    "time": df["timestamp"].iloc[i],
                }
            )
        if all(lows[i] <= lows[i - j] for j in range(1, order + 1)) and all(
            lows[i] <= lows[i + j] for j in range(1, order + 1)
        ):
            swings.append(
                {
                    "index": int(i),
                    "type": "low",
                    "price": float(lows[i]),
                    "time": df["timestamp"].iloc[i],
                }
            )
    return sorted(swings, key=lambda s: s["index"])


def detect_abcd_patterns(swings, tolerance=0.15):
    patterns = []
    for i in range(len(swings) - 3):
        a, b, c, d = swings[i], swings[i + 1], swings[i + 2], swings[i + 3]
        if (
            a["type"] == "low"
            and b["type"] == "high"
            and c["type"] == "low"
            and d["type"] == "high"
        ):
            ab = b["price"] - a["price"]
            bc = b["price"] - c["price"]
            cd = d["price"] - c["price"]
            if ab <= 0:
                continue
            bc_ratio = bc / ab
            cd_ab_ratio = cd / ab
            if (0.618 - tolerance) <= bc_ratio <= (0.786 + tolerance) and (
                1.0 - tolerance
            ) <= cd_ab_ratio <= (1.618 + tolerance):
                patterns.append(
                    {
                        "type": "Bullish",
                        "A": a,
                        "B": b,
                        "C": c,
                        "D": d,
                        "BC_retrace": round(float(bc_ratio), 3),
                        "CD_AB_ratio": round(float(cd_ab_ratio), 3),
                        "entry": float(d["price"]),
                        "stop_loss": float(c["price"]),
                        "target": float(d["price"] - 2 * (d["price"] - c["price"])),  # price falls from D; target below D
                        "signal": "SELL CE / BUY PE at D",
                    }
                )
        if (
            a["type"] == "high"
            and b["type"] == "low"
            and c["type"] == "high"
            and d["type"] == "low"
        ):
            ab = a["price"] - b["price"]
            bc = c["price"] - b["price"]
            cd = c["price"] - d["price"]
            if ab <= 0:
                continue
            bc_ratio = bc / ab
            cd_ab_ratio = cd / ab
            if (0.618 - tolerance) <= bc_ratio <= (0.786 + tolerance) and (
                1.0 - tolerance
            ) <= cd_ab_ratio <= (1.618 + tolerance):
                patterns.append(
                    {
                        "type": "Bearish",
                        "A": a,
                        "B": b,
                        "C": c,
                        "D": d,
                        "BC_retrace": round(float(bc_ratio), 3),
                        "CD_AB_ratio": round(float(cd_ab_ratio), 3),
                        "entry": float(d["price"]),
                        "stop_loss": float(c["price"]),
                        "target": float(d["price"] + 2 * (c["price"] - d["price"])),  # price rises from D; target above D
                        "signal": "BUY CE / SELL PE at D",
                    }
                )
    return patterns


def _pattern_key(p):
    return f"{p['A']['time']}_{p['D']['time']}_{p['type']}"


def classify_trades(patterns, current_price, contract_name=""):
    active = []
    completed = []
    for p in patterns:
        entry = p["entry"]
        target = p["target"]
        sl = p["stop_loss"]
        key = _pattern_key(p)
        active_key = f"abcd_active_{key}"
        completed_key = f"abcd_closed_{key}"

        if p["type"] == "Bullish":
            pnl = entry - current_price
            if current_price <= target or current_price >= sl:
                p["exit_price"] = current_price
                p["pnl"] = round(pnl, 2)
                p["status"] = "Target Hit" if current_price <= target else "SL Hit"
                completed.append(p)
                if not _is_already_sent(completed_key):
                    p["trade_date"] = now_ist().strftime("%Y-%m-%d")
                    p["strategy"] = "ABCD"
                    p["symbol"] = contract_name
                    save_completed_trade(completed_key, p)
                    _mark_sent(completed_key)
                    emoji = "+" if p["pnl"] > 0 else ""
                    _send_telegram(
                        f"TRADE CLOSED | {contract_name}\nPattern: {p['type']} ABCD\nSignal: {p['signal']}\nEntry: {entry:.2f} | Exit: {current_price:.2f}\nPnL: {emoji}{p['pnl']:.2f}\nStatus: {p['status']}"
                    )
            else:
                p["unrealized_pnl"] = round(pnl, 2)
                active.append(p)
                if not _is_already_sent(active_key):
                    _mark_sent(active_key)
                    _send_telegram(
                        f"NEW TRADE | {contract_name}\nPattern: {p['type']} ABCD\nSignal: {p['signal']}\nEntry (D): {entry:.2f}\nTarget: {target:.2f} | SL: {sl:.2f}\nBC Retrace: {p['BC_retrace']} | CD/AB: {p['CD_AB_ratio']}"
                    )
        else:
            pnl = current_price - entry
            if current_price >= target or current_price <= sl:
                p["exit_price"] = current_price
                p["pnl"] = round(pnl, 2)
                p["status"] = "Target Hit" if current_price >= target else "SL Hit"
                completed.append(p)
                if not _is_already_sent(completed_key):
                    p["trade_date"] = now_ist().strftime("%Y-%m-%d")
                    p["strategy"] = "ABCD"
                    p["symbol"] = contract_name
                    save_completed_trade(completed_key, p)
                    _mark_sent(completed_key)
                    emoji = "+" if p["pnl"] > 0 else ""
                    _send_telegram(
                        f"TRADE CLOSED | {contract_name}\nPattern: {p['type']} ABCD\nSignal: {p['signal']}\nEntry: {entry:.2f} | Exit: {current_price:.2f}\nPnL: {emoji}{p['pnl']:.2f}\nStatus: {p['status']}"
                    )
            else:
                p["unrealized_pnl"] = round(pnl, 2)
                p["symbol"] = contract_name
                active.append(p)
                if not _is_already_sent(active_key):
                    _mark_sent(active_key)
                    _send_telegram(
                        f"NEW TRADE | {contract_name}\nPattern: {p['type']} ABCD\nSignal: {p['signal']}\nEntry (D): {entry:.2f}\nTarget: {target:.2f} | SL: {sl:.2f}\nBC Retrace: {p['BC_retrace']} | CD/AB: {p['CD_AB_ratio']}"
                    )
    return active, completed


def backtest_abcd(patterns, candles):
    """Walk through same-day candles after each ABCD pattern. Force-close at 3:30 PM."""
    trades = []
    for p in patterns:
        entry = float(p["entry"])
        target = float(p["target"])
        sl = float(p["stop_loss"])
        signal_time = p["D"]["time"]
        future = _same_day_candles(candles[candles["timestamp"] > signal_time], signal_time)
        result = {"status": "Open", "exit_price": None, "exit_time": None, "pnl": 0.0}
        last_bar = None
        for _, bar in future.iterrows():
            last_bar = bar
            if p["type"] == "Bullish":
                # Bullish ABCD: price expected to drop from D → sell CE / buy PE
                if float(bar["low"]) <= target:
                    result = {
                        "status": "Target Hit",
                        "exit_price": round(float(target), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(entry - target), 2),
                    }
                    break
                if float(bar["high"]) >= sl:
                    result = {
                        "status": "SL Hit",
                        "exit_price": round(float(sl), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(entry - sl), 2),
                    }
                    break
            else:
                # Bearish ABCD: price expected to rise from D → buy CE / sell PE
                if float(bar["high"]) >= target:
                    result = {
                        "status": "Target Hit",
                        "exit_price": round(float(target), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(target - entry), 2),
                    }
                    break
                if float(bar["low"]) <= sl:
                    result = {
                        "status": "SL Hit",
                        "exit_price": round(float(sl), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(sl - entry), 2),
                    }
                    break
        # Force-close any trade still open at end of day
        if result["status"] == "Open" and last_bar is not None:
            exit_px = round(float(last_bar["close"]), 2)
            if p["type"] == "Bullish":
                pnl = round(float(entry - exit_px), 2)
            else:
                pnl = round(float(exit_px - entry), 2)
            result = {
                "status": "Day Close",
                "exit_price": exit_px,
                "exit_time": last_bar["timestamp"],
                "pnl": pnl,
            }
        trades.append({
            "type": p["type"],
            "signal": p["signal"],
            "entry": round(float(entry), 2),
            "target": round(float(target), 2),
            "stop_loss": round(float(sl), 2),
            "time": signal_time,
            "BC_retrace": p["BC_retrace"],
            "CD_AB_ratio": p["CD_AB_ratio"],
            **result,
        })
    return trades


# ================= RSI + SMA =================


def compute_rsi(series, period=RSI_PERIOD):
    import pandas as pd
    return pd.Series(
        talib.RSI(series.values.astype(np.float64), timeperiod=period),
        index=series.index,
    )


def compute_sma(series, period):
    import pandas as pd
    return pd.Series(
        talib.SMA(series.values.astype(np.float64), timeperiod=period),
        index=series.index,
    )


def detect_rsi_sma_signals(candles):
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
        if (
            prev["sma_fast"] <= prev["sma_slow"]
            and curr["sma_fast"] > curr["sma_slow"]
            and curr["rsi"] > RSI_OVERSOLD
        ):
            sl = curr["close"] * 0.98
            target = curr["close"] * 1.04  # 4% target = 2× the 2% SL (1:2 R:R)
            signals.append(
                {
                    "type": "Bullish",
                    "signal": "BUY CE — SMA crossover + RSI recovery",
                    "entry": round(curr["close"], 2),
                    "target": round(target, 2),
                    "stop_loss": round(sl, 2),
                    "time": curr["timestamp"],
                    "rsi": round(curr["rsi"], 2),
                    "sma_fast": round(curr["sma_fast"], 2),
                    "sma_slow": round(curr["sma_slow"], 2),
                }
            )
        if (
            prev["sma_fast"] >= prev["sma_slow"]
            and curr["sma_fast"] < curr["sma_slow"]
            and curr["rsi"] < RSI_OVERBOUGHT
        ):
            sl = curr["close"] * 1.02
            target = curr["close"] * 0.96  # 4% target = 2× the 2% SL (1:2 R:R)
            signals.append(
                {
                    "type": "Bearish",
                    "signal": "BUY PE — SMA crossover + RSI overbought",
                    "entry": round(curr["close"], 2),
                    "target": round(target, 2),
                    "stop_loss": round(sl, 2),
                    "time": curr["timestamp"],
                    "rsi": round(curr["rsi"], 2),
                    "sma_fast": round(curr["sma_fast"], 2),
                    "sma_slow": round(curr["sma_slow"], 2),
                }
            )
    return signals, df


def _rsi_signal_key(s):
    return f"rsi_{s['time']}_{s['type']}"


def classify_rsi_trades(signals, current_price, contract_name=""):
    active = []
    completed = []
    for s in signals:
        entry = s["entry"]
        target = s["target"]
        sl = s["stop_loss"]
        key = _rsi_signal_key(s)
        active_key = f"rsi_active_{key}"
        completed_key = f"rsi_closed_{key}"
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
            if not _is_already_sent(completed_key):
                s["trade_date"] = now_ist().strftime("%Y-%m-%d")
                s["strategy"] = "RSI+SMA"
                s["symbol"] = contract_name
                save_completed_trade(completed_key, s)
                _mark_sent(completed_key)
                emoji = "+" if pnl > 0 else ""
                _send_telegram(
                    f"TRADE CLOSED [RSI+SMA] | {contract_name}\nSignal: {s['signal']}\nEntry: {entry:.2f} | Exit: {current_price:.2f}\nPnL: {emoji}{pnl:.2f}\nStatus: {s['status']}"
                )
        else:
            s["unrealized_pnl"] = pnl
            s["symbol"] = contract_name
            active.append(s)
            if not _is_already_sent(active_key):
                _mark_sent(active_key)
                _send_telegram(
                    f"NEW TRADE [RSI+SMA] | {contract_name}\nSignal: {s['signal']}\nEntry: {entry:.2f}\nTarget: {target:.2f} | SL: {sl:.2f}\nRSI: {s['rsi']} | SMA {SMA_FAST}/{SMA_SLOW}: {s['sma_fast']}/{s['sma_slow']}"
                )
    return active, completed


# ================= RSI-ONLY =================


# ================= DOUBLE TOP =================


def detect_double_top_signals(candles, max_peak_diff_pts=5, min_bars_between=5):
    """
    Detect double top bearish reversal patterns in OHLC candle data.

    Two swing highs at ~same price level, with a trough (neckline) between them.
    Entry confirmed when price closes below the neckline after the second peak.
    Signal: SELL | Target: neckline − height | SL: above second peak

    Strictly intraday: P1 and P2 must be on the same calendar date.
    max_peak_diff_pts: maximum absolute point difference between P1 and P2 (default 5 pts).
    """
    all_signals = []

    # Group candles by trading date and process each day independently
    candles = candles.copy()
    candles["_date"] = candles["timestamp"].dt.date
    for date, day_candles in candles.groupby("_date"):
        day_candles = day_candles.reset_index(drop=True)
        swings = find_swing_points(day_candles, order=3)
        swing_highs = [s for s in swings if s["type"] == "high"]

        for i in range(len(swing_highs) - 1):
            for j in range(i + 1, len(swing_highs)):
                p1 = swing_highs[i]
                p2 = swing_highs[j]

                if p2["index"] - p1["index"] < min_bars_between:
                    continue

                if abs(p1["price"] - p2["price"]) > max_peak_diff_pts:
                    continue

                # Neckline = lowest low between the two peaks
                between = day_candles.iloc[p1["index"]: p2["index"] + 1]
                neckline = float(between["low"].min())

                # Signal confirmed on first close below neckline after peak2
                # Any candle exceeding the resistance level (max of P1/P2) before
                # the neckline break voids the pattern entirely.
                resistance = float(max(p1["price"], p2["price"]))
                after_p2 = day_candles.iloc[p2["index"] + 1:]
                pattern_valid = True
                for _, bar in after_p2.iterrows():
                    if float(bar["high"]) > resistance:
                        pattern_valid = False
                        break
                    if float(bar["close"]) < neckline:
                        entry = neckline  # limit entry at neckline, not the breakdown candle close
                        sl = resistance
                        height = sl - neckline
                        target = float(neckline - 2 * height)  # target = 2× SL distance
                        all_signals.append({
                            "time": bar["timestamp"],
                            "signal": "SELL — Double Top neckline break",
                            "entry": round(entry, 2),
                            "target": round(target, 2),
                            "stop_loss": round(sl, 2),
                            "peak1": round(float(p1["price"]), 2),
                            "peak1_time": p1["time"],
                            "peak2": round(float(p2["price"]), 2),
                            "peak2_time": p2["time"],
                            "neckline": round(neckline, 2),
                        })
                        break

    # De-duplicate by entry bar time — keep first occurrence per timestamp
    seen = set()
    unique = []
    for s in all_signals:
        key = str(s["time"])
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


def backtest_double_top(signals, candles):
    """Walk through same-day candles after each double top signal. Force-close at 3:30 PM."""
    trades = []
    for s in signals:
        entry = s["entry"]
        target = s["target"]
        sl = s["stop_loss"]
        signal_time = s["time"]
        future = _same_day_candles(candles[candles["timestamp"] > signal_time], signal_time)
        result = {"status": "Open", "exit_price": None, "exit_time": None, "pnl": 0.0}
        last_bar = None
        for _, bar in future.iterrows():
            last_bar = bar
            # SELL trade: target is below entry, SL is above entry
            if float(bar["low"]) <= target:
                result = {
                    "status": "Target Hit",
                    "exit_price": round(float(target), 2),
                    "exit_time": bar["timestamp"],
                    "pnl": round(float(entry - target), 2),
                }
                break
            if float(bar["high"]) >= sl:
                result = {
                    "status": "SL Hit",
                    "exit_price": round(float(sl), 2),
                    "exit_time": bar["timestamp"],
                    "pnl": round(float(entry - sl), 2),
                }
                break
        if result["status"] == "Open" and last_bar is not None:
            exit_px = round(float(last_bar["close"]), 2)
            result = {
                "status": "Day Close",
                "exit_price": exit_px,
                "exit_time": last_bar["timestamp"],
                "pnl": round(float(entry - exit_px), 2),
            }
        trades.append({**s, **result})
    return trades


def detect_double_bottom_signals(candles, max_trough_diff_pts=5, min_bars_between=5):
    """
    Detect double bottom bullish reversal patterns in OHLC candle data.

    Two swing lows at ~same price level, with a peak (neckline) between them.
    Entry confirmed when price closes above the neckline after the second trough.
    Signal: BUY | Target: neckline + height | SL: below second trough

    Strictly intraday: T1 and T2 must be on the same calendar date.
    max_trough_diff_pts: maximum absolute point difference between T1 and T2 (default 5 pts).
    """
    all_signals = []

    # Group candles by trading date and process each day independently
    candles = candles.copy()
    candles["_date"] = candles["timestamp"].dt.date
    for date, day_candles in candles.groupby("_date"):
        day_candles = day_candles.reset_index(drop=True)
        swings = find_swing_points(day_candles, order=3)
        swing_lows = [s for s in swings if s["type"] == "low"]

        for i in range(len(swing_lows) - 1):
            for j in range(i + 1, len(swing_lows)):
                t1 = swing_lows[i]
                t2 = swing_lows[j]

                if t2["index"] - t1["index"] < min_bars_between:
                    continue

                if abs(t1["price"] - t2["price"]) > max_trough_diff_pts:
                    continue

                # Neckline = highest high between the two troughs
                between = day_candles.iloc[t1["index"]: t2["index"] + 1]
                neckline = float(between["high"].max())

                # Signal confirmed on first close above neckline after trough2
                # Any candle breaching the support level (min of T1/T2) before
                # the neckline break voids the pattern entirely.
                support = float(min(t1["price"], t2["price"]))
                after_t2 = day_candles.iloc[t2["index"] + 1:]
                for _, bar in after_t2.iterrows():
                    if float(bar["low"]) < support:
                        break  # pattern voided
                    if float(bar["close"]) > neckline:
                        entry = neckline  # limit entry at neckline, not the breakout candle close
                        sl = support
                        height = neckline - sl
                        target = float(neckline + 2 * height)  # target = 2× SL distance
                        all_signals.append({
                            "time": bar["timestamp"],
                            "signal": "BUY — Double Bottom neckline break",
                            "entry": round(entry, 2),
                            "target": round(target, 2),
                            "stop_loss": round(sl, 2),
                            "trough1": round(float(t1["price"]), 2),
                            "trough1_time": t1["time"],
                            "trough2": round(float(t2["price"]), 2),
                            "trough2_time": t2["time"],
                            "neckline": round(neckline, 2),
                        })
                        break

    # De-duplicate by entry bar time — keep first occurrence per timestamp
    seen = set()
    unique = []
    for s in all_signals:
        key = str(s["time"])
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


def backtest_double_bottom(signals, candles):
    """Walk through same-day candles after each double bottom signal. Force-close at 3:30 PM."""
    trades = []
    for s in signals:
        entry = s["entry"]
        target = s["target"]
        sl = s["stop_loss"]
        signal_time = s["time"]
        future = _same_day_candles(candles[candles["timestamp"] > signal_time], signal_time)
        result = {"status": "Open", "exit_price": None, "exit_time": None, "pnl": 0.0}
        last_bar = None
        for _, bar in future.iterrows():
            last_bar = bar
            # BUY trade: target is above entry, SL is below entry
            if float(bar["high"]) >= target:
                result = {
                    "status": "Target Hit",
                    "exit_price": round(float(target), 2),
                    "exit_time": bar["timestamp"],
                    "pnl": round(float(target - entry), 2),
                }
                break
            if float(bar["low"]) <= sl:
                result = {
                    "status": "SL Hit",
                    "exit_price": round(float(sl), 2),
                    "exit_time": bar["timestamp"],
                    "pnl": round(float(sl - entry), 2),
                }
                break
        if result["status"] == "Open" and last_bar is not None:
            exit_px = round(float(last_bar["close"]), 2)
            result = {
                "status": "Day Close",
                "exit_price": exit_px,
                "exit_time": last_bar["timestamp"],
                "pnl": round(float(exit_px - entry), 2),
            }
        trades.append({**s, **result})
    return trades


# ================= RSI ONLY =================


# ================= EMA 10 CROSSOVER =================

EMA10_PERIOD = 10
EMA10_TARGET_PCT = 0.02  # 2% target (1:2 R:R with 1% SL)
EMA10_SL_PCT = 0.01      # 1.0% stop loss


def compute_ema(series, period):
    import pandas as pd
    return pd.Series(
        talib.EMA(series.values.astype(np.float64), timeperiod=period),
        index=series.index,
    )


def detect_ema10_signals(candles):
    """Generate signals when price crosses above/below EMA(10)."""
    df = candles.copy()
    df["ema10"] = compute_ema(df["close"], EMA10_PERIOD)
    df_ind = df.reset_index(drop=True)           # full df with indicator (NaNs kept for chart line)
    df_clean = df.dropna().reset_index(drop=True)  # NaN-free df for signal detection
    if len(df_clean) < 2:
        return [], df_ind
    signals = []
    for i in range(1, len(df_clean)):
        prev = df_clean.iloc[i - 1]
        curr = df_clean.iloc[i]
        # Bullish: close crosses above EMA 10
        if prev["close"] <= prev["ema10"] and curr["close"] > curr["ema10"]:
            target = curr["close"] * (1 + EMA10_TARGET_PCT)
            sl = curr["close"] * (1 - EMA10_SL_PCT)
            signals.append({
                "type": "Bullish",
                "signal": "BUY — Price crosses above EMA 10",
                "entry": round(float(curr["close"]), 2),
                "target": round(float(target), 2),
                "stop_loss": round(float(sl), 2),
                "time": curr["timestamp"],
                "ema10": round(float(curr["ema10"]), 2),
            })
        # Bearish: close crosses below EMA 10
        elif prev["close"] >= prev["ema10"] and curr["close"] < curr["ema10"]:
            target = curr["close"] * (1 - EMA10_TARGET_PCT)
            sl = curr["close"] * (1 + EMA10_SL_PCT)
            signals.append({
                "type": "Bearish",
                "signal": "SELL — Price crosses below EMA 10",
                "entry": round(float(curr["close"]), 2),
                "target": round(float(target), 2),
                "stop_loss": round(float(sl), 2),
                "time": curr["timestamp"],
                "ema10": round(float(curr["ema10"]), 2),
            })
    return signals, df_ind


def backtest_ema10(signals, candles):
    """Walk through same-day candles after each EMA10 signal. Force-close at 3:30 PM."""
    trades = []
    for s in signals:
        entry = s["entry"]
        target = s["target"]
        sl = s["stop_loss"]
        signal_time = s["time"]
        future = _same_day_candles(candles[candles["timestamp"] > signal_time], signal_time)
        result = {"status": "Open", "exit_price": None, "exit_time": None, "pnl": 0.0}
        last_bar = None
        for _, bar in future.iterrows():
            last_bar = bar
            if s["type"] == "Bullish":
                if float(bar["high"]) >= target:
                    result = {
                        "status": "Target Hit",
                        "exit_price": round(float(target), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(target - entry), 2),
                    }
                    break
                if float(bar["low"]) <= sl:
                    result = {
                        "status": "SL Hit",
                        "exit_price": round(float(sl), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(sl - entry), 2),
                    }
                    break
            else:
                if float(bar["low"]) <= target:
                    result = {
                        "status": "Target Hit",
                        "exit_price": round(float(target), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(entry - target), 2),
                    }
                    break
                if float(bar["high"]) >= sl:
                    result = {
                        "status": "SL Hit",
                        "exit_price": round(float(sl), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(entry - sl), 2),
                    }
                    break
        if result["status"] == "Open" and last_bar is not None:
            exit_px = round(float(last_bar["close"]), 2)
            pnl = round(float(exit_px - entry), 2) if s["type"] == "Bullish" else round(float(entry - exit_px), 2)
            result = {
                "status": "Day Close",
                "exit_price": exit_px,
                "exit_time": last_bar["timestamp"],
                "pnl": pnl,
            }
        trades.append({**s, **result})
    return trades


# ================= SMA 50 CROSSOVER =================

SMA50_PERIOD = 50
SMA50_TARGET_PCT = 0.02  # 2% target (1:2 R:R with 1% SL)
SMA50_SL_PCT = 0.01      # 1.0% stop loss


def detect_sma50_signals(candles):
    """Generate signals when price crosses above/below SMA(50)."""
    df = candles.copy()
    df["sma50"] = compute_sma(df["close"], SMA50_PERIOD)
    df_ind = df.reset_index(drop=True)           # full df with indicator (NaNs kept for chart line)
    df_clean = df.dropna().reset_index(drop=True)  # NaN-free df for signal detection
    if len(df_clean) < 2:
        return [], df_ind
    signals = []
    for i in range(1, len(df_clean)):
        prev = df_clean.iloc[i - 1]
        curr = df_clean.iloc[i]
        # Bullish: close crosses above SMA 50
        if prev["close"] <= prev["sma50"] and curr["close"] > curr["sma50"]:
            target = curr["close"] * (1 + SMA50_TARGET_PCT)
            sl = curr["close"] * (1 - SMA50_SL_PCT)
            signals.append({
                "type": "Bullish",
                "signal": "BUY — Price crosses above SMA 50",
                "entry": round(float(curr["close"]), 2),
                "target": round(float(target), 2),
                "stop_loss": round(float(sl), 2),
                "time": curr["timestamp"],
                "sma50": round(float(curr["sma50"]), 2),
            })
        # Bearish: close crosses below SMA 50
        elif prev["close"] >= prev["sma50"] and curr["close"] < curr["sma50"]:
            target = curr["close"] * (1 - SMA50_TARGET_PCT)
            sl = curr["close"] * (1 + SMA50_SL_PCT)
            signals.append({
                "type": "Bearish",
                "signal": "SELL — Price crosses below SMA 50",
                "entry": round(float(curr["close"]), 2),
                "target": round(float(target), 2),
                "stop_loss": round(float(sl), 2),
                "time": curr["timestamp"],
                "sma50": round(float(curr["sma50"]), 2),
            })
    return signals, df_ind


def backtest_sma50(signals, candles):
    """Walk through same-day candles after each SMA50 signal. Force-close at 3:30 PM."""
    trades = []
    for s in signals:
        entry = s["entry"]
        target = s["target"]
        sl = s["stop_loss"]
        signal_time = s["time"]
        future = _same_day_candles(candles[candles["timestamp"] > signal_time], signal_time)
        result = {"status": "Open", "exit_price": None, "exit_time": None, "pnl": 0.0}
        last_bar = None
        for _, bar in future.iterrows():
            last_bar = bar
            if s["type"] == "Bullish":
                if float(bar["high"]) >= target:
                    result = {
                        "status": "Target Hit",
                        "exit_price": round(float(target), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(target - entry), 2),
                    }
                    break
                if float(bar["low"]) <= sl:
                    result = {
                        "status": "SL Hit",
                        "exit_price": round(float(sl), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(sl - entry), 2),
                    }
                    break
            else:
                if float(bar["low"]) <= target:
                    result = {
                        "status": "Target Hit",
                        "exit_price": round(float(target), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(entry - target), 2),
                    }
                    break
                if float(bar["high"]) >= sl:
                    result = {
                        "status": "SL Hit",
                        "exit_price": round(float(sl), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(entry - sl), 2),
                    }
                    break
        if result["status"] == "Open" and last_bar is not None:
            exit_px = round(float(last_bar["close"]), 2)
            pnl = round(float(exit_px - entry), 2) if s["type"] == "Bullish" else round(float(entry - exit_px), 2)
            result = {
                "status": "Day Close",
                "exit_price": exit_px,
                "exit_time": last_bar["timestamp"],
                "pnl": pnl,
            }
        trades.append({**s, **result})
    return trades


# ================= LIVE CLASSIFY HELPERS =================

def _classify_generic(signals, current_price, contract_name, strategy_name, store_prefix, extra_alert_fn=None):
    active = []
    completed = []
    for s in signals:
        entry = s["entry"]
        target = s["target"]
        sl = s["stop_loss"]
        sig_key = "{}_{}".format(store_prefix, str(s["time"]))
        active_key = "live_active_" + sig_key
        completed_key = "live_closed_" + sig_key
        is_buy = target > entry
        if is_buy:
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
            if not _is_already_sent(completed_key):
                s["trade_date"] = now_ist().strftime("%Y-%m-%d")
                s["strategy"] = strategy_name
                s["symbol"] = contract_name
                save_completed_trade(completed_key, s)
                _mark_sent(completed_key)
                emoji = "+" if pnl > 0 else ""
                _send_telegram(
                    "TRADE CLOSED [{}] | {}\nSignal: {}\nEntry: {:.2f} | Exit: {:.2f}\nPnL: {}{:.2f}\nStatus: {}".format(
                        strategy_name, contract_name, s["signal"], entry, current_price, emoji, pnl, s["status"]
                    )
                )
        else:
            s["unrealized_pnl"] = pnl
            s["symbol"] = contract_name
            active.append(s)
            if not _is_already_sent(active_key):
                _mark_sent(active_key)
                alert = "NEW TRADE [{}] | {}\nSignal: {}\nEntry: {:.2f} | Target: {:.2f} | SL: {:.2f}".format(
                    strategy_name, contract_name, s["signal"], entry, target, sl
                )
                if extra_alert_fn:
                    alert += extra_alert_fn(s)
                _send_telegram(alert)
    return active, completed


def classify_double_top_trades(signals, current_price, contract_name=""):
    return _classify_generic(signals, current_price, contract_name, "Double Top", "dt",
        extra_alert_fn=lambda s: "\nNeckline: {} | Height: {}".format(s.get("neckline", "-"), s.get("height", "-")))


def classify_double_bottom_trades(signals, current_price, contract_name=""):
    return _classify_generic(signals, current_price, contract_name, "Double Bottom", "db",
        extra_alert_fn=lambda s: "\nNeckline: {} | Height: {}".format(s.get("neckline", "-"), s.get("height", "-")))


def classify_ema10_trades(signals, current_price, contract_name=""):
    return _classify_generic(signals, current_price, contract_name, "EMA10", "ema10",
        extra_alert_fn=lambda s: "\nEMA10: {}".format(s.get("ema10", "-")))


def classify_sma50_trades(signals, current_price, contract_name=""):
    return _classify_generic(signals, current_price, contract_name, "SMA50", "sma50",
        extra_alert_fn=lambda s: "\nSMA50: {}".format(s.get("sma50", "-")))
