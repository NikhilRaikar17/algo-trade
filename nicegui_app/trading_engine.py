"""
Background live engine, driven by the websocket feed, independent of any browser connection.

- Candles: every top stock (plus any stock with an open trade) is subscribed on the equity feed and
  its ticks are built into 5-minute bars (live_candles). Bars from before the stock was subscribed
  are seeded once from Dhan's REST candles, and again only if its ticks stop.
- Signals: when each 5-minute bar closes, the enabled live strategies run on the finished bars at
  the live price. The paper account takes or skips new signals then (algo_strategies → account).
- Exits: run_position_monitor() reads the feed every few seconds and closes an open trade at its
  target or stop the moment a tick reaches it.

Populates _trade_store (the Live Algos page and Trade Desk read it) and persists closed signals to
.trade_history.json.
"""

import asyncio
import time
import traceback
from datetime import timedelta

from dhanhq import marketfeed

import live_candles
import ws_feed
from account import alert_day_stop, closed_text, on_tick, open_trades, square_off
from config import now_ist
from state import _send_telegram, _trade_store, is_market_open
from data import _fetch_any_stock_candles, NIFTY50_STOCKS, STOCK_WATCH_GROUPS
from strategy_registry import get_live_strategy_keys
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


def _run_strategies_for_contract(candles, current_price, contract_name, live_keys):
    """Run every enabled live strategy (Strategies page) for one stock. Updates _trade_store."""
    for key in live_keys:
        detect, classify = _STRATEGY_RUNNERS[key]
        try:
            signals = detect(candles)
            active, completed = classify(signals, current_price, contract_name)
            _trade_store[f"{key}_trades_{contract_name}"] = {"active": active, "completed": completed}
        except Exception:
            print(f"  [engine:{key}:{contract_name}] {traceback.format_exc()}")


MONITOR_SECONDS = 2
_TICK_MAX_AGE = 60  # seconds: an older quote is not used to close a trade
_sid_cache = {"at": 0.0, "map": {}}


def _security_ids() -> dict[str, str]:
    """Stock name → Dhan security id: the top stocks, then the NIFTY 50 and watch groups (cached a minute)."""
    from db import get_active_top_stocks

    if time.time() - _sid_cache["at"] > 60:
        sid_by_name = {s["name"]: str(s["security_id"]) for s in get_active_top_stocks()}
        for s in NIFTY50_STOCKS:
            sid_by_name.setdefault(s["name"], str(s["security_id"]))
        for grp in STOCK_WATCH_GROUPS:
            for s in grp["stocks"]:
                sid_by_name.setdefault(s["name"], str(s["security_id"]))
        _sid_cache.update(at=time.time(), map=sid_by_name)
    return _sid_cache["map"]


def _stocks_with_open_trades(known: set[str]) -> list[dict]:
    """Stocks that still have an open live trade but are no longer in the top-stocks list.
    They keep being scanned until the trade closes, so its exit is tracked and alerted."""
    sid_by_name = _security_ids()
    names = set()
    for key, val in list(_trade_store.items()):
        if "_trades_" in key and isinstance(val, dict) and val.get("active"):
            names.add(key.split("_trades_", 1)[1])
    return [{"name": n, "security_id": sid_by_name[n]} for n in sorted(names - known) if n in sid_by_name]


BAR_DELAY_SECONDS = 2  # run just after each 5-minute bar closes, once its last ticks are in


def feed_candles(security_id: str):
    """Today's finished 5-minute bars for a stock from the feed, seeding them from REST first if the
    feed hasn't covered the stock yet (or its ticks stopped)."""
    if live_candles.needs_seed(security_id):
        rest = _fetch_any_stock_candles(security_id, interval=5, retries=3)
        time.sleep(0.35)  # back-to-back REST calls get rate-limited
        live_candles.seed(security_id, rest)
    return live_candles.candles(security_id)


def _run_engine_tick():
    """At a bar close: subscribe every top stock (plus any stock with an open trade) on the feed and
    run the enabled live strategies on its finished bars at the live price."""
    from db import get_active_top_stocks

    stocks = get_active_top_stocks()
    stocks += _stocks_with_open_trades({s["name"] for s in stocks})
    live_keys = get_live_strategy_keys()
    ws_feed.watch("engine", [(marketfeed.NSE, str(s["security_id"])) for s in stocks])

    if not stocks:
        print("  [engine] No active top stocks in DB — skipping tick.")
        return

    for stock in stocks:
        name = stock["name"]
        security_id = str(stock["security_id"])
        try:
            candles = feed_candles(security_id)
            if candles.empty:
                print(f"  [engine] {name}: no candles yet today")
                continue
            live = live_candles.last_price(security_id)
            current_price = round(live if live is not None else float(candles["close"].iloc[-1]), 2)
            _run_strategies_for_contract(candles, current_price, name, live_keys)
            print(f"  [engine] {name} @ {current_price:.2f} ({'feed' if live is not None else 'last bar'}) "
                  f"— {len(candles)} bars, strategies updated")
        except Exception as e:
            print(f"  [engine:{name}] candles/classify failed: {e}")

    for r in square_off():
        print(f"  [engine] squared off {r['symbol']} ({r['strategy']}) at {r['exit_price']:.2f}")


def _monitor_tick():
    """Live prices for the account's open trades: subscribe them on the websocket, then record each
    fresh tick and close a trade at its target or stop as soon as the price reaches it."""
    trades = open_trades()
    ids = _security_ids() if trades else {}
    watched = {t["key"]: ids[t["symbol"]] for t in trades if t["symbol"] in ids}
    ws_feed.watch("positions", [(marketfeed.NSE, sid) for sid in set(watched.values())])
    for key, sid in watched.items():
        ltp = live_candles.last_price(sid, max_age=_TICK_MAX_AGE)
        if ltp is None:
            continue
        rec = on_tick(key, ltp)
        if rec:
            print(f"  [monitor] {rec['symbol']} {rec['status']} at {rec['exit_price']:.2f} (tick {ltp:.2f})")
            _send_telegram(closed_text(rec))
            alert_day_stop()


async def run_position_monitor():
    """Async loop: _monitor_tick() every MONITOR_SECONDS in market hours. Start once from main.py."""
    loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(MONITOR_SECONDS)
        if not is_market_open():
            continue
        try:
            await loop.run_in_executor(None, _monitor_tick)
        except Exception as e:
            print(f"  [monitor] error: {e}\n{traceback.format_exc()}")


def _seconds_to_next_bar(now) -> float:
    nxt = live_candles.slot(now) + timedelta(minutes=live_candles.BAR_MINUTES, seconds=BAR_DELAY_SECONDS)
    return max((nxt - now).total_seconds(), 1.0)


async def run_trading_engine():
    """Async loop: _run_engine_tick() once at start-up, then just after every 5-minute bar closes,
    in market hours. Call once from _start_scheduler in main.py."""
    print("  [engine] Trading engine started (feed-driven, every 5-minute bar).")
    loop = asyncio.get_event_loop()
    first = True
    while True:
        if not first:
            await asyncio.sleep(_seconds_to_next_bar(now_ist()))
        first = False
        if not is_market_open():
            continue
        try:
            await loop.run_in_executor(None, _run_engine_tick)
        except Exception as e:
            print(f"  [engine] tick error: {e}\n{traceback.format_exc()}")
