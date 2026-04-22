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

load_dotenv()

_CLIENT_ID = os.getenv("DHAN_CLIENT_CODE", "")
_ACCESS_TOKEN = os.getenv("DHAN_TOKEN_ID", "")

# ── Equity Full-packet quote store (used by live algo tab) ───────────────────
# Fully independent from the index feed below — separate thread, separate loop,
# separate credentials read directly from env.
# {str(security_id): {ltp, bid, ask, bid_qty, ask_qty, oi, volume}}
_quote_store: dict = {}
_quote_tick_time: dict = {}   # str(security_id) → datetime of last tick
_eq_subscribed: frozenset = frozenset()
_eq_consuming = threading.Event()


def get_quote(security_id) -> dict:
    """Return latest Full-packet data for an equity security, or {} if not received yet."""
    return dict(_quote_store.get(str(security_id), {}))


def get_last_tick_time(security_id) -> datetime | None:
    """Return the datetime of the last received tick for an equity, or None."""
    return _quote_tick_time.get(str(security_id))


def subscribe(securities: list) -> None:
    """
    Start (or restart) the equity Full-packet feed in a background daemon thread.

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

    _eq_client_id    = os.getenv("DHAN_CLIENT_CODE", "")
    _eq_access_token = os.getenv("DHAN_TOKEN_ID", "")

    def _run():
        # Isolated event loop — never touches NiceGUI's asyncio loop.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            instruments = [(seg, str(sid), marketfeed.Full) for seg, sid in securities]
            feed = marketfeed.DhanFeed(_eq_client_id, _eq_access_token, instruments, version="v2")
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
                _quote_tick_time[sec_id] = datetime.now()
        except Exception as e:
            print(f"  [ws_feed equity] feed error: {e}")
            _eq_consuming.clear()
        finally:
            loop.close()

    threading.Thread(target=_run, daemon=True, name="ws-feed-equity").start()

# ─────────────────────────────────────────────────────────────────────────────

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


def _run_index_feed() -> None:
    """
    Blocking index feed loop — runs in a daemon thread with its own isolated
    event loop so it never conflicts with NiceGUI's running asyncio loop.
    Reconnects automatically with exponential backoff on failure.
    """
    backoff = 2
    while True:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            feed = DhanFeed(_CLIENT_ID, _ACCESS_TOKEN, _INSTRUMENTS, version="v2")
            loop.run_until_complete(feed.connect())
            state.set_ws_connected(True)
            print("  [ws_feed] connected, streaming ticks...")
            backoff = 2  # reset on successful connect
            while True:
                tick = loop.run_until_complete(feed.get_instrument_data())
                _process_tick(tick)
        except Exception as exc:
            state.set_ws_connected(False)
            print(f"  [ws_feed] disconnected ({exc}), retrying in {backoff}s...")
            import time as _time
            _time.sleep(backoff)
            backoff = min(backoff * 2, 60)
        finally:
            loop.close()


async def start_ws_feed() -> None:
    """
    Spawn the index feed in a background daemon thread and return immediately.
    The thread handles its own reconnect loop — no asyncio involvement needed.
    """
    threading.Thread(target=_run_index_feed, daemon=True, name="ws-feed-index").start()
