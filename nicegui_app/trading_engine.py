"""
Background trading engine — runs the enabled live strategies on top-stocks equity 5-min
candles every 120 seconds during market hours, independent of any browser
connection.

Populates _trade_store and persists completed trades to .trade_history.json
exactly as the live algo tab does, but driven by the server-side scheduler.
"""

import asyncio
import traceback

from config import now_ist, REFRESH_SECONDS, LIVE_STRATEGY_KEYS
from state import _trade_store, is_market_open
from data import _fetch_any_stock_candles
from algo_strategies import (
    find_swing_points,
    detect_abcd_patterns,
    classify_trades,
    detect_double_top_custom_signals,
    classify_double_top_custom_trades,
    detect_double_top_standard_signals,
    classify_double_top_standard_trades,
    detect_double_bottom_signals,
    classify_double_bottom_trades,
    detect_ema10_signals,
    classify_ema10_trades,
    detect_sma50_signals,
    classify_sma50_trades,
)


# key → (detect(candles) -> signals, classify(signals, current_price, name) -> (active, completed))
_STRATEGY_RUNNERS = {
    "abcd":  (lambda c: detect_abcd_patterns(find_swing_points(c, order=2)), classify_trades),
    "dtc":   (detect_double_top_custom_signals, classify_double_top_custom_trades),
    "dts":   (detect_double_top_standard_signals, classify_double_top_standard_trades),
    "db":    (detect_double_bottom_signals, classify_double_bottom_trades),
    "ema10": (lambda c: detect_ema10_signals(c)[0], classify_ema10_trades),
    "sma50": (lambda c: detect_sma50_signals(c)[0], classify_sma50_trades),
}


def _run_strategies_for_contract(candles, current_price, contract_name):
    """Run every enabled live strategy (config.LIVE_STRATEGY_ENABLED) for one stock. Updates _trade_store."""
    for key in LIVE_STRATEGY_KEYS:
        detect, classify = _STRATEGY_RUNNERS[key]
        try:
            signals = detect(candles)
            active, completed = classify(signals, current_price, contract_name)
            _trade_store[f"{key}_trades_{contract_name}"] = {"active": active, "completed": completed}
        except Exception:
            print(f"  [engine:{key}:{contract_name}] {traceback.format_exc()}")


def _run_engine_tick():
    """One full scan: fetch 5-min equity candles for all active top stocks and run the enabled live strategies."""
    from db import get_active_top_stocks

    today_date = now_ist().date()
    stocks = get_active_top_stocks()

    if not stocks:
        print("  [engine] No active top stocks in DB — skipping tick.")
        return

    for stock in stocks:
        name = stock["name"]
        security_id = stock["security_id"]
        try:
            candles = _fetch_any_stock_candles(security_id, interval=5)
            if candles is None or candles.empty:
                print(f"  [engine] {name}: no candles")
                continue
            candles = candles[candles["timestamp"].dt.date == today_date].reset_index(drop=True)
            if candles.empty:
                print(f"  [engine] {name}: no today candles")
                continue
            current_price = round(float(candles["close"].iloc[-1]), 2)
            _run_strategies_for_contract(candles, current_price, name)
            print(f"  [engine] {name} @ {current_price:.2f} — strategies updated")
        except Exception as e:
            print(f"  [engine:{name}] candles/classify failed: {e}")


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
            await loop.run_in_executor(None, _run_engine_tick)
        except Exception as e:
            print(f"  [engine] tick error: {e}\n{traceback.format_exc()}")
