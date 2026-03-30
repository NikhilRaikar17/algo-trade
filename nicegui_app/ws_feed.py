"""
Live WebSocket market feed manager (Dhan Full packet, type 21).
Runs DhanFeed in a single daemon thread — connect + consume in sequence.
NiceGUI reads _quote_store via ui.timer (no asyncio involved here).

Full packet fields used:
  LTP, OI, volume  —  from the top-level dict
  depth[0].bid_price / ask_price / bid_quantity / ask_quantity  — best bid/ask
"""
import threading
from dhanhq import marketfeed
from config import CLIENT_ID, ACCESS_TOKEN

# {str(security_id): {ltp, bid, ask, bid_qty, ask_qty, oi, volume}}
_quote_store: dict = {}

# Track what's currently subscribed so we don't restart unnecessarily
_subscribed: frozenset = frozenset()
_consuming = threading.Event()  # set while the consume loop is running


def get_quote(security_id) -> dict:
    """Return latest Full-packet data for a security, or {} if not yet received."""
    return dict(_quote_store.get(str(security_id), {}))


def subscribe(securities: list):
    """
    Start (or restart) the Full market data feed.

    securities: list of (segment_int, security_id_str)
      e.g. [(marketfeed.NSE_FNO, "123456"), (marketfeed.NSE_FNO, "654321")]

    Non-blocking — returns immediately; WebSocket connects in the background.
    If the same set is already active, this is a no-op.
    """
    global _subscribed

    new_set = frozenset((int(seg), str(sid)) for seg, sid in securities)
    if new_set == _subscribed and _consuming.is_set():
        return  # already live, nothing to do

    _subscribed = new_set
    _consuming.clear()

    def _run():
        try:
            instruments = [(seg, str(sid), marketfeed.Full) for seg, sid in securities]
            feed = marketfeed.DhanFeed(CLIENT_ID, ACCESS_TOKEN, instruments, version="v2")

            # run_forever() = loop.run_until_complete(connect())
            # Blocks until the WebSocket handshake is complete, then returns.
            feed.run_forever()
            _consuming.set()
            ids = [str(s) for _, s in securities]
            print(f"  [ws_feed] connected — consuming {ids}")

            # Consume loop: each get_data() call receives one packet
            while True:
                data = feed.get_data()
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
            print(f"  [ws_feed] feed error: {e}")
            _consuming.clear()

    threading.Thread(target=_run, daemon=True, name="ws-feed").start()
