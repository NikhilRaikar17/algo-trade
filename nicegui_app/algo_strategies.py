"""
Trading strategies: ABCD harmonic patterns and RSI + SMA crossover.
"""

from datetime import time as _dtime

import numpy as np
import talib

from config import RSI_PERIOD, SMA_FAST, SMA_SLOW, RSI_OVERSOLD, RSI_OVERBOUGHT
from state import _is_already_sent, _mark_sent, _send_telegram

_MARKET_CLOSE = _dtime(15, 30)


def _same_day_candles(future, signal_time):
    """Return candles on the same date as signal_time, up to 3:30 PM only."""
    sig_date = signal_time.date()
    mask = (future["timestamp"].dt.date == sig_date) & (
        future["timestamp"].dt.time <= _MARKET_CLOSE
    )
    return future[mask]

RSI_ONLY_TARGET_PCT = 0.015  # 1.5% target
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
                    "index": i,
                    "type": "high",
                    "price": highs[i],
                    "time": df["timestamp"].iloc[i],
                }
            )
        if all(lows[i] <= lows[i - j] for j in range(1, order + 1)) and all(
            lows[i] <= lows[i + j] for j in range(1, order + 1)
        ):
            swings.append(
                {
                    "index": i,
                    "type": "low",
                    "price": lows[i],
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
                        "BC_retrace": round(bc_ratio, 3),
                        "CD_AB_ratio": round(cd_ab_ratio, 3),
                        "entry": d["price"],
                        "target": d["price"] + ab,
                        "stop_loss": c["price"],
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
                        "BC_retrace": round(bc_ratio, 3),
                        "CD_AB_ratio": round(cd_ab_ratio, 3),
                        "entry": d["price"],
                        "target": d["price"] - ab,
                        "stop_loss": c["price"],
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
            target = curr["close"] * 1.02
            sl = curr["close"] * 0.98
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
            target = curr["close"] * 0.98
            sl = curr["close"] * 1.02
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
                _mark_sent(completed_key)
                emoji = "+" if pnl > 0 else ""
                _send_telegram(
                    f"TRADE CLOSED [RSI+SMA] | {contract_name}\nSignal: {s['signal']}\nEntry: {entry:.2f} | Exit: {current_price:.2f}\nPnL: {emoji}{pnl:.2f}\nStatus: {s['status']}"
                )
        else:
            s["unrealized_pnl"] = pnl
            active.append(s)
            if not _is_already_sent(active_key):
                _mark_sent(active_key)
                _send_telegram(
                    f"NEW TRADE [RSI+SMA] | {contract_name}\nSignal: {s['signal']}\nEntry: {entry:.2f}\nTarget: {target:.2f} | SL: {sl:.2f}\nRSI: {s['rsi']} | SMA {SMA_FAST}/{SMA_SLOW}: {s['sma_fast']}/{s['sma_slow']}"
                )
    return active, completed


# ================= RSI-ONLY =================


def detect_rsi_only_signals(candles):
    """Generate trade signals based purely on RSI overbought/oversold crossings."""
    df = candles.copy()
    df["rsi"] = compute_rsi(df["close"])
    df = df.dropna().reset_index(drop=True)
    if len(df) < 2:
        return [], df
    signals = []
    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        curr = df.iloc[i]
        # Bullish: RSI crosses above oversold from below
        if prev["rsi"] <= RSI_OVERSOLD and curr["rsi"] > RSI_OVERSOLD:
            target = curr["close"] * (1 + RSI_ONLY_TARGET_PCT)
            sl = curr["close"] * (1 - RSI_ONLY_SL_PCT)
            signals.append(
                {
                    "type": "Bullish",
                    "signal": "BUY — RSI exits oversold",
                    "entry": round(float(curr["close"]), 2),
                    "target": round(float(target), 2),
                    "stop_loss": round(float(sl), 2),
                    "time": curr["timestamp"],
                    "rsi": round(float(curr["rsi"]), 2),
                    "prev_rsi": round(float(prev["rsi"]), 2),
                }
            )
        # Bearish: RSI crosses below overbought from above
        if prev["rsi"] >= RSI_OVERBOUGHT and curr["rsi"] < RSI_OVERBOUGHT:
            target = curr["close"] * (1 - RSI_ONLY_TARGET_PCT)
            sl = curr["close"] * (1 + RSI_ONLY_SL_PCT)
            signals.append(
                {
                    "type": "Bearish",
                    "signal": "SELL — RSI exits overbought",
                    "entry": round(float(curr["close"]), 2),
                    "target": round(float(target), 2),
                    "stop_loss": round(float(sl), 2),
                    "time": curr["timestamp"],
                    "rsi": round(float(curr["rsi"]), 2),
                    "prev_rsi": round(float(prev["rsi"]), 2),
                }
            )
    return signals, df


def backtest_rsi_only(signals, candles):
    """Walk through same-day candles after each signal. Force-close at 3:30 PM."""
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
        # Force-close any trade still open at end of day
        if result["status"] == "Open" and last_bar is not None:
            exit_px = round(float(last_bar["close"]), 2)
            if s["type"] == "Bullish":
                pnl = round(float(exit_px - entry), 2)
            else:
                pnl = round(float(entry - exit_px), 2)
            result = {
                "status": "Day Close",
                "exit_price": exit_px,
                "exit_time": last_bar["timestamp"],
                "pnl": pnl,
            }
        trades.append({**s, **result})
    return trades
