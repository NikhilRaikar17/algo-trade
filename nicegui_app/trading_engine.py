"""
Background trading engine — runs all strategies on ATM CE/PE 5-min candles
every 120 seconds during market hours, independent of any browser connection.

Populates _trade_store and persists completed trades to .trade_history.json
exactly as the live algo tab does, but driven by the server-side scheduler.
"""

import asyncio
import traceback
from datetime import datetime

from config import now_ist, INDICES, REFRESH_SECONDS
from state import _trade_store, is_market_open
from data import get_expiries, fetch_option_chain_raw, fetch_5min_candles
from algo_strategies import (
    find_swing_points,
    detect_abcd_patterns,
    classify_trades,
    detect_double_top_signals,
    classify_double_top_trades,
    detect_double_bottom_signals,
    classify_double_bottom_trades,
    detect_ema10_signals,
    classify_ema10_trades,
    detect_sma50_signals,
    classify_sma50_trades,
)


def _run_strategies_for_contract(candles, current_price, contract_name):
    """Run all 7 strategies for a single ATM option contract. Updates _trade_store."""

    # ABCD
    try:
        swings = find_swing_points(candles, order=2)
        patterns = detect_abcd_patterns(swings)
        active, completed = classify_trades(patterns, current_price, contract_name)
        _trade_store[f"abcd_trades_{contract_name}"] = {"active": active, "completed": completed}
    except Exception:
        print(f"  [engine:abcd:{contract_name}] {traceback.format_exc()}")

    # Double Top
    try:
        signals = detect_double_top_signals(candles)
        active, completed = classify_double_top_trades(signals, current_price, contract_name)
        _trade_store[f"dt_trades_{contract_name}"] = {"active": active, "completed": completed}
    except Exception:
        print(f"  [engine:dt:{contract_name}] {traceback.format_exc()}")

    # Double Bottom
    try:
        signals = detect_double_bottom_signals(candles)
        active, completed = classify_double_bottom_trades(signals, current_price, contract_name)
        _trade_store[f"db_trades_{contract_name}"] = {"active": active, "completed": completed}
    except Exception:
        print(f"  [engine:db:{contract_name}] {traceback.format_exc()}")

    # EMA10
    try:
        signals, _ = detect_ema10_signals(candles)
        active, completed = classify_ema10_trades(signals, current_price, contract_name)
        _trade_store[f"ema10_trades_{contract_name}"] = {"active": active, "completed": completed}
    except Exception:
        print(f"  [engine:ema10:{contract_name}] {traceback.format_exc()}")

    # SMA50
    try:
        signals, _ = detect_sma50_signals(candles)
        active, completed = classify_sma50_trades(signals, current_price, contract_name)
        _trade_store[f"sma50_trades_{contract_name}"] = {"active": active, "completed": completed}
    except Exception:
        print(f"  [engine:sma50:{contract_name}] {traceback.format_exc()}")


def _run_engine_tick():
    """One full scan: fetch data for NIFTY + BANKNIFTY and run all strategies."""
    today_date = now_ist().date()

    for idx_key, cfg in INDICES.items():
        try:
            expiries = get_expiries(cfg["scrip"], cfg["segment"], 2, for_algo=True)
        except Exception as e:
            print(f"  [engine:{idx_key}] expiries failed: {e}")
            continue

        for expiry in expiries:
            try:
                raw = fetch_option_chain_raw(cfg["scrip"], cfg["segment"], expiry)
            except Exception as e:
                print(f"  [engine:{idx_key}:{expiry}] option chain failed: {e}")
                continue

            spot = round(float(raw["last_price"]), 2)
            atm = round(spot / cfg["strike_step"]) * cfg["strike_step"]
            exp_tag = datetime.strptime(expiry, "%Y-%m-%d").strftime("%d%b").upper()

            strikes = sorted(raw["oc"].keys(), key=lambda s: abs(float(s) - atm))
            if not strikes:
                continue
            sides = raw["oc"][strikes[0]]

            for opt_type in ["CE", "PE"]:
                sec_id = sides.get(opt_type.lower(), {}).get("security_id")
                if not sec_id:
                    continue
                try:
                    candles = fetch_5min_candles(sec_id)
                    if candles is None or candles.empty:
                        continue
                    # Filter to today's candles only (same as algo.py)
                    candles = candles[candles["timestamp"].dt.date == today_date].reset_index(drop=True)
                    if candles.empty:
                        continue
                    current_price = round(float(candles["close"].iloc[-1]), 2)
                    contract_name = f"{cfg['name_prefix']} {exp_tag} {int(atm)} {opt_type}"
                    _run_strategies_for_contract(candles, current_price, contract_name)
                    print(f"  [engine] {contract_name} @ {current_price:.2f} — strategies updated")
                except Exception as e:
                    print(f"  [engine:{idx_key}:{expiry}:{opt_type}] candles/classify failed: {e}")


async def run_trading_engine():
    """
    Async loop that drives the engine every REFRESH_SECONDS during market hours.
    Call once from _start_scheduler in main.py.
    """
    print("  [engine] Trading engine started.")
    loop = asyncio.get_event_loop()

    while True:
        await asyncio.sleep(REFRESH_SECONDS)
        if not is_market_open():
            continue
        try:
            # Run synchronous blocking work in a thread so the event loop stays free
            await loop.run_in_executor(None, _run_engine_tick)
        except Exception as e:
            print(f"  [engine] tick error: {e}\n{traceback.format_exc()}")
