"""
WebSocket feed for live NIFTY, BANKNIFTY, and India VIX prices.

Connects to Dhan's marketfeed WebSocket and polls ticks via get_data().
Writes ticks to state._live_prices.
Reconnects automatically with exponential backoff (2 → 4 → 8 → … → 60 s) on failure.

Usage (called once from main.py):
    asyncio.create_task(start_ws_feed())
"""
import asyncio
import os
from datetime import datetime

from dhanhq import marketfeed
from dotenv import load_dotenv

import state

load_dotenv()

_CLIENT_ID = os.getenv("DHAN_CLIENT_CODE", "")
_ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID", "")

# Dhan security IDs for index instruments
_SECURITY_MAP = {
    "13": "NIFTY",
    "25": "BANKNIFTY",
    "234613": "VIX",
}

# Instruments: (exchange_segment, security_id, subscription_type)
# marketfeed.IDX is the segment constant for NSE index instruments
_INSTRUMENTS = [
    (marketfeed.IDX, "13", marketfeed.Ticker),      # NIFTY
    (marketfeed.IDX, "25", marketfeed.Ticker),      # BANKNIFTY
    (marketfeed.IDX, "234613", marketfeed.Ticker),  # India VIX
]

# Re-export for test mocking
DhanFeed = marketfeed.DhanFeed

# Track last known prev_close per instrument (sent once by server as a separate packet)
_prev_close_cache: dict[str, float] = {}


def _process_tick(tick: dict) -> None:
    """Process a single tick from the WebSocket and write to state."""
    if tick is None:
        return

    tick_type = tick.get("type", "")

    # Cache prev_close packets — the server sends these separately from ticker ticks
    if tick_type == "Previous Close":
        sec_id = str(tick.get("security_id", ""))
        name = _SECURITY_MAP.get(sec_id)
        if name:
            try:
                _prev_close_cache[name] = float(tick.get("prev_close", 0))
            except (TypeError, ValueError):
                pass
        return

    # Only process Ticker (and Full) packets for LTP
    if tick_type not in ("Ticker Data", "Full Data"):
        return

    sec_id = str(tick.get("security_id", ""))
    name = _SECURITY_MAP.get(sec_id)
    if name is None:
        return

    ltp = tick.get("LTP")
    if ltp is None:
        return

    try:
        ltp = float(ltp)
    except (TypeError, ValueError):
        return

    prev_close = _prev_close_cache.get(name) or ltp
    change = round(ltp - prev_close, 2)
    change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0

    state.set_live_price(name, {
        "ltp": ltp,
        "prev_close": prev_close,
        "change": change,
        "change_pct": change_pct,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    })
    state.set_ws_connected(True)


def _run_feed_blocking(feed: "DhanFeed") -> None:
    """
    Blocking poll loop: connect then read ticks one by one via get_data().
    DhanFeed.run_forever() only calls connect() — it does not loop on recv().
    We must call connect() first, then poll get_data() in a tight loop.
    """
    import asyncio as _asyncio
    loop = feed.loop
    loop.run_until_complete(feed.connect())
    print("  [ws_feed] connected, streaming ticks...")
    while True:
        tick = loop.run_until_complete(feed.get_instrument_data())
        _process_tick(tick)


async def start_ws_feed() -> None:
    """
    Connect to Dhan WebSocket and stream ticks into state._live_prices.
    Reconnects with exponential backoff (2 → 4 → 8 → … → 60 s) on failure.
    """
    backoff = 2
    while True:
        feed = DhanFeed(_CLIENT_ID, _ACCESS_TOKEN, _INSTRUMENTS, version="v2")
        try:
            print("  [ws_feed] connecting to Dhan WebSocket...")
            await asyncio.get_running_loop().run_in_executor(None, _run_feed_blocking, feed)
        except Exception as exc:
            state.set_ws_connected(False)
            print(f"  [ws_feed] disconnected ({exc}), retrying in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
        else:
            state.set_ws_connected(False)
            await asyncio.sleep(2)
            backoff = 2
