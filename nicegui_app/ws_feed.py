"""
WebSocket feed for live NIFTY, BANKNIFTY, and India VIX prices.

Connects to Dhan's marketfeed WebSocket and polls ticks via get_data().
Writes ticks to state._live_prices.
Reconnects automatically with exponential backoff (2 → 4 → 8 → … → 60 s) on failure.

Also provides get_quote() / subscribe() for per-equity Full-packet quotes
used by the live algo tab.

Usage (called once from main.py):
    asyncio.create_task(start_ws_feed())
"""
import asyncio
import os
import threading
from datetime import datetime

from dhanhq import marketfeed
from dotenv import load_dotenv

import state
from config import CLIENT_ID, ACCESS_TOKEN

load_dotenv()

# ── Equity Full-packet quote store ───────────────────────────────────────────
# {str(security_id): {ltp, bid, ask, bid_qty, ask_qty, oi, volume}}
_quote_store: dict = {}
_eq_subscribed: frozenset = frozenset()
_eq_consuming = threading.Event()


def get_quote(security_id) -> dict:
    """Return latest Full-packet data for an equity security, or {} if not received yet."""
    return dict(_quote_store.get(str(security_id), {}))


def subscribe(securities: list) -> None:
    """
    Start (or restart) the equity Full-packet feed in a background thread.

    securities: list of (segment_int, security_id_str)
      e.g. [(marketfeed.NSE, "2885")]

    Non-blocking — returns immediately. If the same set is already running, no-op.
    """
    global _eq_subscribed

    new_set = frozenset((int(seg), str(sid)) for seg, sid in securities)
    if new_set == _eq_subscribed and _eq_consuming.is_set():
        return

    _eq_subscribed = new_set
    _eq_consuming.clear()

    def _run():
        # Give the feed its own isolated event loop so it never conflicts
        # with NiceGUI's running asyncio loop on the main thread.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            instruments = [(seg, str(sid), marketfeed.Full) for seg, sid in securities]
            feed = marketfeed.DhanFeed(CLIENT_ID, ACCESS_TOKEN, instruments, version="v2")
            # feed.loop is now the new loop we just set
            loop.run_until_complete(feed.connect())
            _eq_consuming.set()
            ids = [str(s) for _, s in securities]
            print(f"  [ws_feed equity] connected — consuming {ids}")
            while True:
                data = loop.run_until_complete(feed.get_instrument_data())
                if not data or "security_id" not in data:
                    continue
                sec_id = str(data["security_id"])
                depth = data.get("depth") or []
                best = depth[0] if depth else {}
                _quote_store[sec_id] = {
                    "ltp":     float(data.get("LTP") or 0),
                    "bid":     float(best.get("bid_price") or 0),
                    "ask":     float(best.get("ask_price") or 0),
                    "bid_qty": int(best.get("bid_quantity") or 0),
                    "ask_qty": int(best.get("ask_quantity") or 0),
                    "oi":      int(data.get("OI") or 0),
                    "volume":  int(data.get("volume") or 0),
                }
        except Exception as e:
            print(f"  [ws_feed equity] feed error: {e}")
            _eq_consuming.clear()
        finally:
            loop.close()

    threading.Thread(target=_run, daemon=True, name="ws-feed-equity").start()

# ─────────────────────────────────────────────────────────────────────────────

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
