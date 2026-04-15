"""
WebSocket feed for live NIFTY, BANKNIFTY, and India VIX prices.

Connects to Dhan's marketfeed WebSocket and writes ticks to state._live_prices.
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


def _on_tick(tick: dict) -> None:
    """Process a single tick from the WebSocket and write to state."""
    sec_id = str(tick.get("security_id", ""))
    name = _SECURITY_MAP.get(sec_id)
    if name is None:
        return

    ltp = tick.get("LTP")
    if ltp is None:
        return

    prev_close = tick.get("prev_close") or ltp
    change = round(float(ltp) - float(prev_close), 2)
    change_pct = round((change / float(prev_close)) * 100, 2) if prev_close else 0.0

    state.set_live_price(name, {
        "ltp": float(ltp),
        "prev_close": float(prev_close),
        "change": change,
        "change_pct": change_pct,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    })
    state._ws_connected = True


async def start_ws_feed() -> None:
    """
    Connect to Dhan WebSocket and stream ticks into state._live_prices.
    Reconnects with exponential backoff (2 → 4 → 8 → … → 60 s) on failure.
    """
    backoff = 2
    while True:
        try:
            feed = DhanFeed(_CLIENT_ID, _ACCESS_TOKEN, _INSTRUMENTS, version="v2",
                            on_message=_on_tick)
            print("  [ws_feed] connecting to Dhan WebSocket...")
            await asyncio.get_event_loop().run_in_executor(None, feed.run_forever)
        except Exception as exc:
            state._ws_connected = False
            print(f"  [ws_feed] disconnected ({exc}), retrying in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
        else:
            # run_forever returned cleanly -- reconnect after a short delay
            state._ws_connected = False
            await asyncio.sleep(2)
            backoff = 2
