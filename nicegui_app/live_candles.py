"""
live_candles.py — today's 5-minute candles for each stock, built from the websocket feed.

ws_feed calls on_tick() for every equity tick; each tick folds into the bar of its 5-minute slot
(09:15, 09:20, …), and a bar is complete once its slot has ended. Bars from before a stock was first
fed (app start, or a stock added mid-day) are seeded from Dhan's REST candles (seed()). That, and a
re-seed when a stock's ticks stop (needs_seed()), is the only REST use in the live path.
"""

import threading
from datetime import datetime, time, timedelta

import pandas as pd

from config import IST, now_ist

BAR_MINUTES = 5
STALE_SECONDS = 90           # no tick for this long: the feed is not covering the stock
_RESEED_SECONDS = 240        # a stale stock is re-seeded from REST at most this often
_OPEN, _CLOSE = time(9, 15), time(15, 30)

_lock = threading.Lock()
_bars: dict[str, dict[pd.Timestamp, dict]] = {}   # security id → {slot start → {open, high, low, close}}
_seeded: dict[str, datetime] = {}                  # security id → last REST seed
_last: dict[str, tuple[float, datetime]] = {}      # security id → (last traded price, when)


def slot(ts: datetime) -> pd.Timestamp:
    """Start of the 5-minute bar `ts` falls in."""
    ts = pd.Timestamp(ts)
    ts = ts.tz_localize(IST) if ts.tzinfo is None else ts.tz_convert(IST)
    return ts.floor(f"{BAR_MINUTES}min")


def on_tick(security_id: str, ltp: float, ts: datetime | None = None) -> None:
    """Fold one traded price into its bar (ticks outside 09:15–15:30 only update the last price)."""
    if not ltp:
        return
    ts = ts or now_ist()
    sid, s = str(security_id), slot(ts)
    with _lock:
        _last[sid] = (float(ltp), ts)
        if not (_OPEN <= s.time() < _CLOSE):
            return
        bars = _bars.setdefault(sid, {})
        b = bars.get(s)
        if b is None:
            bars[s] = {"open": ltp, "high": ltp, "low": ltp, "close": ltp}
        else:
            b["high"], b["low"], b["close"] = max(b["high"], ltp), min(b["low"], ltp), ltp


def seed(security_id: str, rest: pd.DataFrame, now: datetime | None = None) -> None:
    """Merge Dhan REST 5-minute candles (timestamp = bar start) for today. Finished bars take the REST
    values; the bar still forming keeps the feed's high/low/close, widened by REST's."""
    now = now or now_ist()
    sid, current = str(security_id), slot(now)
    with _lock:
        bars = {s: b for s, b in _bars.get(sid, {}).items() if s.date() == current.date()}
        if rest is not None and not rest.empty:
            for row in rest.itertuples(index=False):
                s = slot(row.timestamp)
                if s.date() != current.date():
                    continue
                r = {"open": float(row.open), "high": float(row.high), "low": float(row.low), "close": float(row.close)}
                if s < current or s not in bars:
                    bars[s] = r
                else:
                    b = bars[s]
                    b.update(open=r["open"], high=max(b["high"], r["high"]), low=min(b["low"], r["low"]))
        _bars[sid] = bars
        _seeded[sid] = now


def needs_seed(security_id: str, now: datetime | None = None) -> bool:
    """Not seeded today, or the feed has gone quiet for this stock (and it wasn't re-seeded lately)."""
    now = now or now_ist()
    sid = str(security_id)
    with _lock:
        seeded, last = _seeded.get(sid), _last.get(sid)
    if seeded is None or seeded.date() != now.date():
        return True
    quiet = last is None or (now - last[1]).total_seconds() > STALE_SECONDS
    return quiet and (now - seeded).total_seconds() > _RESEED_SECONDS


def candles(security_id: str, now: datetime | None = None, forming: bool = False) -> pd.DataFrame:
    """Today's bars, oldest first (timestamp = bar start, IST). Only finished bars unless `forming`."""
    now = now or now_ist()
    current = slot(now)
    with _lock:
        items = sorted((s, dict(b)) for s, b in _bars.get(str(security_id), {}).items()
                       if s.date() == current.date() and (forming or s < current))
    return pd.DataFrame([{"timestamp": s, **b} for s, b in items],
                        columns=["timestamp", "open", "high", "low", "close"])


def last_price(security_id: str, max_age: float = STALE_SECONDS, now: datetime | None = None) -> float | None:
    """Latest traded price from the feed, or None if there is no tick this recent."""
    now = now or now_ist()
    with _lock:
        last = _last.get(str(security_id))
    if last is None or (now - last[1]) > timedelta(seconds=max_age):
        return None
    return last[0]
