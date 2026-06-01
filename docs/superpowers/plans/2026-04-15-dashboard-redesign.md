# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Dhan WebSocket live prices, a global markets grid (yfinance), and four new widgets (sentiment gauge, VIX dial, top movers, economic calendar) to the NiceGUI dashboard page.

**Architecture:** A single `asyncio` background task (`ws_feed.py`) streams NIFTY/BANKNIFTY/VIX ticks from the Dhan WebSocket into `state._live_prices`. A second background task (`global_feed.py`) fetches 13 global symbols via `yfinance` every 60 s into `state._global_prices`. The dashboard UI reads both via fast `ui.timer` calls and updates labels in-place (no card rebuild per tick).

**Tech Stack:** NiceGUI, dhanhq (marketfeed WebSocket), yfinance, pytest, pytest-mock

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `nicegui_app/pyproject.toml` | Add `yfinance` dependency |
| Modify | `nicegui_app/state.py` | Add `_live_prices`, `_global_prices`, `_ws_connected` |
| **Create** | `nicegui_app/economic_calendar.py` | Hardcoded event dates + `get_upcoming_events(n)` |
| **Create** | `nicegui_app/ws_feed.py` | WebSocket lifecycle: connect, subscribe, reconnect, write state |
| **Create** | `nicegui_app/global_feed.py` | yfinance background loop, write state |
| Modify | `nicegui_app/main.py` | Wire `start_ws_feed()` and `start_global_feed()` into startup |
| Modify | `nicegui_app/pages/dashboard.py` | New layout: in-place price labels, global grid, 4 widgets |
| **Create** | `nicegui_app/tests/test_economic_calendar.py` | Tests for calendar logic |
| **Create** | `nicegui_app/tests/test_ws_feed.py` | Tests for WebSocket feed |
| **Create** | `nicegui_app/tests/test_global_feed.py` | Tests for global feed |
| **Create** | `nicegui_app/tests/test_dashboard_prices.py` | Tests for `_compute_synthetic_futures` |

---

## Task 1: Add yfinance dependency

**Files:**
- Modify: `nicegui_app/pyproject.toml`

- [ ] **Step 1: Add yfinance to dependencies**

Edit `nicegui_app/pyproject.toml`. In the `dependencies` list, add after `"ta-lib>=0.6.8",`:

```toml
    "yfinance>=0.2.54",
```

- [ ] **Step 2: Install the new dependency**

```bash
cd nicegui_app && uv sync
```

Expected: resolves and installs yfinance and its deps (multitasking, peewee, etc.) with no errors.

- [ ] **Step 3: Verify import works**

```bash
cd nicegui_app && uv run python -c "import yfinance; print(yfinance.__version__)"
```

Expected: prints a version string like `0.2.x`.

- [ ] **Step 4: Commit**

```bash
git add nicegui_app/pyproject.toml nicegui_app/uv.lock
git commit -m "chore: add yfinance dependency"
```

---

## Task 2: Add live-price state variables

**Files:**
- Modify: `nicegui_app/state.py`

- [ ] **Step 1: Add the three new state variables**

Open `nicegui_app/state.py`. After the line `_ltp_history = {}  # history for SMA trend` (around line 57), insert:

```python
# ================= LIVE PRICE STATE (WebSocket feed) =================
_live_prices: dict = {}
# Structure per key:
# {"NIFTY": {"ltp": 22450.5, "prev_close": 22300.0,
#             "change": 150.5, "change_pct": 0.67, "timestamp": "14:32:05"}}
# "VIX" key uses same structure; "ltp" holds the VIX value.

_global_prices: dict = {}
# Structure per key:
# {"^GSPC": {"name": "S&P 500", "price": 5200.1, "change_pct": 0.34,
#             "currency": "USD", "flag": "🇺🇸"}}

_ws_connected: bool = False
```

- [ ] **Step 2: Expose a thread-safe setter for live prices**

Still in `state.py`, add these two helpers at the bottom of the file (after `_cache_get_stable`):

```python
# ================= LIVE PRICE HELPERS =================
_live_lock = threading.Lock()
_global_lock = threading.Lock()


def set_live_price(key: str, data: dict) -> None:
    """Thread-safe write to _live_prices. Call from ws_feed background task."""
    global _live_prices
    with _live_lock:
        _live_prices[key] = data


def get_live_price(key: str) -> dict | None:
    """Thread-safe read from _live_prices."""
    with _live_lock:
        return _live_prices.get(key)


def set_global_price(key: str, data: dict) -> None:
    """Thread-safe write to _global_prices."""
    global _global_prices
    with _global_lock:
        _global_prices[key] = data


def get_all_global_prices() -> dict:
    """Thread-safe snapshot of _global_prices."""
    with _global_lock:
        return dict(_global_prices)
```

- [ ] **Step 3: Verify no import errors**

```bash
cd nicegui_app && uv run python -c "from state import set_live_price, get_live_price, set_global_price, get_all_global_prices; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add nicegui_app/state.py
git commit -m "feat: add live price state variables and thread-safe helpers"
```

---

## Task 3: Create economic_calendar.py (TDD)

**Files:**
- Create: `nicegui_app/economic_calendar.py`
- Create: `nicegui_app/tests/test_economic_calendar.py`

- [ ] **Step 1: Write the failing tests**

Create `nicegui_app/tests/test_economic_calendar.py`:

```python
"""Tests for economic_calendar.get_upcoming_events."""
from datetime import date
from unittest.mock import patch

import pytest


def test_returns_n_events():
    from economic_calendar import get_upcoming_events
    with patch("economic_calendar._today", return_value=date(2026, 1, 1)):
        events = get_upcoming_events(n=3)
    assert len(events) == 3


def test_events_are_in_future_only():
    from economic_calendar import get_upcoming_events
    today = date(2026, 6, 15)
    with patch("economic_calendar._today", return_value=today):
        events = get_upcoming_events(n=10)
    for ev in events:
        assert ev["date"] >= today, f"Past event returned: {ev}"


def test_events_sorted_ascending():
    from economic_calendar import get_upcoming_events
    with patch("economic_calendar._today", return_value=date(2026, 1, 1)):
        events = get_upcoming_events(n=10)
    dates = [ev["date"] for ev in events]
    assert dates == sorted(dates)


def test_event_has_required_keys():
    from economic_calendar import get_upcoming_events
    with patch("economic_calendar._today", return_value=date(2026, 1, 1)):
        events = get_upcoming_events(n=1)
    ev = events[0]
    assert "date" in ev
    assert "label" in ev
    assert "type" in ev
    assert ev["type"] in ("expiry", "rbi", "fed")


def test_returns_empty_if_no_future_events():
    from economic_calendar import get_upcoming_events
    # Far future date — no events defined beyond 2026
    with patch("economic_calendar._today", return_value=date(2030, 1, 1)):
        events = get_upcoming_events(n=5)
    assert events == []
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd nicegui_app && uv run pytest tests/test_economic_calendar.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'economic_calendar'`

- [ ] **Step 3: Implement economic_calendar.py**

Create `nicegui_app/economic_calendar.py`:

```python
"""
Economic calendar: NSE expiry dates, RBI MPC dates, US Fed FOMC dates for 2026.
"""
from datetime import date


def _today() -> date:
    """Returns today's date. Separated for easy mocking in tests."""
    return date.today()


# ── NSE Monthly expiry dates (last Thursday of each month, 2026) ──────────────
_NSE_MONTHLY_EXPIRIES = [
    date(2026, 1, 29),
    date(2026, 2, 26),
    date(2026, 3, 26),
    date(2026, 4, 30),
    date(2026, 5, 28),
    date(2026, 6, 25),
    date(2026, 7, 30),
    date(2026, 8, 27),
    date(2026, 9, 24),
    date(2026, 10, 29),
    date(2026, 11, 26),
    date(2026, 12, 31),
]

# ── RBI MPC decision dates 2026 ───────────────────────────────────────────────
_RBI_MPC_DATES = [
    date(2026, 2, 7),
    date(2026, 4, 9),
    date(2026, 6, 6),
    date(2026, 8, 7),
    date(2026, 10, 9),
    date(2026, 12, 4),
]

# ── US Fed FOMC decision dates 2026 ──────────────────────────────────────────
_FED_FOMC_DATES = [
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 5, 6),
    date(2026, 6, 10),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 9),
]


def _all_events() -> list[dict]:
    events = []
    for d in _NSE_MONTHLY_EXPIRIES:
        events.append({"date": d, "label": f"NSE Monthly Expiry", "type": "expiry"})
    for d in _RBI_MPC_DATES:
        events.append({"date": d, "label": "RBI MPC Decision", "type": "rbi"})
    for d in _FED_FOMC_DATES:
        events.append({"date": d, "label": "US Fed FOMC Decision", "type": "fed"})
    return sorted(events, key=lambda e: e["date"])


def get_upcoming_events(n: int = 5) -> list[dict]:
    """Return the next n events on or after today, sorted ascending by date."""
    today = _today()
    future = [e for e in _all_events() if e["date"] >= today]
    return future[:n]
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd nicegui_app && uv run pytest tests/test_economic_calendar.py -v
```

Expected output:
```
PASSED tests/test_economic_calendar.py::test_returns_n_events
PASSED tests/test_economic_calendar.py::test_events_are_in_future_only
PASSED tests/test_economic_calendar.py::test_events_sorted_ascending
PASSED tests/test_economic_calendar.py::test_event_has_required_keys
PASSED tests/test_economic_calendar.py::test_returns_empty_if_no_future_events
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add nicegui_app/economic_calendar.py nicegui_app/tests/test_economic_calendar.py
git commit -m "feat: add economic_calendar module with NSE/RBI/Fed events"
```

---

## Task 4: Create ws_feed.py (TDD)

**Files:**
- Create: `nicegui_app/ws_feed.py`
- Create: `nicegui_app/tests/test_ws_feed.py`

- [ ] **Step 1: Write the failing tests**

Create `nicegui_app/tests/test_ws_feed.py`:

```python
"""Tests for ws_feed: state writes on tick, reconnect logic, WS health flag."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import state


@pytest.fixture(autouse=True)
def reset_state():
    """Reset live price state before each test."""
    state._live_prices.clear()
    state._ws_connected = False
    yield
    state._live_prices.clear()
    state._ws_connected = False


def test_on_tick_writes_nifty_to_state():
    """A NIFTY tick should update state._live_prices["NIFTY"]."""
    from ws_feed import _on_tick
    tick = {
        "security_id": "13",
        "LTP": 22500.5,
        "prev_close": 22300.0,
    }
    _on_tick(tick)
    entry = state.get_live_price("NIFTY")
    assert entry is not None
    assert entry["ltp"] == 22500.5
    assert entry["change"] == pytest.approx(200.5, abs=0.1)
    assert entry["change_pct"] == pytest.approx(0.9, abs=0.1)


def test_on_tick_writes_banknifty_to_state():
    """A BANKNIFTY tick should update state._live_prices["BANKNIFTY"]."""
    from ws_feed import _on_tick
    tick = {
        "security_id": "25",
        "LTP": 48000.0,
        "prev_close": 47500.0,
    }
    _on_tick(tick)
    entry = state.get_live_price("BANKNIFTY")
    assert entry is not None
    assert entry["ltp"] == 48000.0


def test_on_tick_writes_vix_to_state():
    """A VIX tick should update state._live_prices["VIX"]."""
    from ws_feed import _on_tick
    tick = {
        "security_id": "234613",
        "LTP": 14.5,
        "prev_close": 14.0,
    }
    _on_tick(tick)
    entry = state.get_live_price("VIX")
    assert entry is not None
    assert entry["ltp"] == 14.5


def test_on_tick_sets_ws_connected_true():
    """Any valid tick should set _ws_connected = True."""
    from ws_feed import _on_tick
    tick = {"security_id": "13", "LTP": 22000.0, "prev_close": 21900.0}
    _on_tick(tick)
    assert state._ws_connected is True


def test_on_tick_unknown_security_ignored():
    """Ticks for unknown security IDs should not raise and not pollute state."""
    from ws_feed import _on_tick
    _on_tick({"security_id": "9999", "LTP": 100.0, "prev_close": 99.0})
    assert state._live_prices == {}


def test_on_tick_missing_ltp_ignored():
    """A tick missing 'LTP' key should not raise."""
    from ws_feed import _on_tick
    _on_tick({"security_id": "13"})  # no LTP
    assert state.get_live_price("NIFTY") is None


@pytest.mark.asyncio
async def test_start_ws_feed_sets_disconnected_on_exception(mocker):
    """When DhanFeed raises, _ws_connected should be set to False."""
    mock_feed_cls = mocker.patch("ws_feed.DhanFeed")
    mock_feed = MagicMock()
    mock_feed.run_forever.side_effect = Exception("connection refused")
    mock_feed_cls.return_value = mock_feed

    # Patch sleep so the reconnect loop exits quickly
    sleep_calls = []
    async def fake_sleep(n):
        sleep_calls.append(n)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError()
    mocker.patch("ws_feed.asyncio.sleep", side_effect=fake_sleep)

    from ws_feed import start_ws_feed
    with pytest.raises(asyncio.CancelledError):
        await start_ws_feed()

    assert state._ws_connected is False
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd nicegui_app && uv run pytest tests/test_ws_feed.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'ws_feed'`

- [ ] **Step 3: Implement ws_feed.py**

Create `nicegui_app/ws_feed.py`:

```python
"""
WebSocket feed for live NIFTY, BANKNIFTY, and India VIX prices.

Connects to Dhan's marketfeed WebSocket and writes ticks to state._live_prices.
Reconnects automatically with exponential backoff on disconnection.

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
# IDX_I segment code for NSE indices in dhanhq is 0
_INSTRUMENTS = [
    (marketfeed.IDX_I, "13", marketfeed.Ticker),      # NIFTY
    (marketfeed.IDX_I, "25", marketfeed.Ticker),      # BANKNIFTY
    (marketfeed.IDX_I, "234613", marketfeed.Ticker),  # India VIX
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
            print("  [ws_feed] connecting to Dhan WebSocket…")
            await asyncio.get_event_loop().run_in_executor(None, feed.run_forever)
        except Exception as exc:
            state._ws_connected = False
            print(f"  [ws_feed] disconnected ({exc}), retrying in {backoff}s…")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
        else:
            # run_forever returned cleanly — reconnect after a short delay
            state._ws_connected = False
            await asyncio.sleep(2)
            backoff = 2
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd nicegui_app && uv run pytest tests/test_ws_feed.py -v
```

Expected:
```
PASSED tests/test_ws_feed.py::test_on_tick_writes_nifty_to_state
PASSED tests/test_ws_feed.py::test_on_tick_writes_banknifty_to_state
PASSED tests/test_ws_feed.py::test_on_tick_writes_vix_to_state
PASSED tests/test_ws_feed.py::test_on_tick_sets_ws_connected_true
PASSED tests/test_ws_feed.py::test_on_tick_unknown_security_ignored
PASSED tests/test_ws_feed.py::test_on_tick_missing_ltp_ignored
PASSED tests/test_ws_feed.py::test_start_ws_feed_sets_disconnected_on_exception
7 passed
```

> **Note:** If `marketfeed.IDX_I` doesn't exist in your version of dhanhq, check the dhanhq docs for the correct segment constant for NSE indices. It may be `marketfeed.NSE_FNO` or an integer like `0`. Update `_INSTRUMENTS` accordingly and re-run the tests.

- [ ] **Step 5: Commit**

```bash
git add nicegui_app/ws_feed.py nicegui_app/tests/test_ws_feed.py
git commit -m "feat: add WebSocket live price feed for NIFTY/BANKNIFTY/VIX"
```

---

## Task 5: Create global_feed.py (TDD)

**Files:**
- Create: `nicegui_app/global_feed.py`
- Create: `nicegui_app/tests/test_global_feed.py`

- [ ] **Step 1: Write the failing tests**

Create `nicegui_app/tests/test_global_feed.py`:

```python
"""Tests for global_feed: yfinance fetching, state writes, error resilience."""
import asyncio
import pandas as pd
import pytest
import state


@pytest.fixture(autouse=True)
def reset_global_state():
    state._global_prices.clear()
    yield
    state._global_prices.clear()


def _make_yf_df(symbols: list[str], price: float = 100.0, prev: float = 99.0) -> pd.DataFrame:
    """Build a minimal yfinance-style DataFrame (2-day close prices)."""
    import numpy as np
    dates = pd.to_datetime(["2026-04-14", "2026-04-15"])
    close_data = {sym: [prev, price] for sym in symbols}
    df = pd.DataFrame(close_data, index=dates)
    df.columns = pd.MultiIndex.from_tuples([("Close", sym) for sym in symbols])
    return df


def test_fetch_global_writes_to_state(mocker):
    """After _fetch_and_store(), state._global_prices should have data."""
    from global_feed import _fetch_and_store, SYMBOLS

    mock_df = _make_yf_df(list(SYMBOLS.keys())[:3], price=100.0, prev=98.0)
    mocker.patch("global_feed.yf.download", return_value=mock_df)

    _fetch_and_store()

    stored = state.get_all_global_prices()
    # At least the symbols present in mock_df should be stored
    assert len(stored) >= 1
    first_key = list(stored.keys())[0]
    entry = stored[first_key]
    assert "name" in entry
    assert "price" in entry
    assert "change_pct" in entry
    assert "flag" in entry


def test_fetch_global_computes_change_pct(mocker):
    """change_pct should be (price - prev) / prev * 100."""
    from global_feed import _fetch_and_store

    mock_df = _make_yf_df(["^GSPC"], price=5200.0, prev=5000.0)
    mocker.patch("global_feed.yf.download", return_value=mock_df)

    _fetch_and_store()

    entry = state.get_all_global_prices().get("^GSPC")
    assert entry is not None
    assert entry["change_pct"] == pytest.approx(4.0, abs=0.01)


def test_fetch_global_skips_failed_symbol(mocker):
    """If yfinance returns NaN for a symbol, it should be silently skipped."""
    import numpy as np
    from global_feed import _fetch_and_store

    # Return a df where ^GSPC has NaN close
    dates = pd.to_datetime(["2026-04-14", "2026-04-15"])
    df = pd.DataFrame(
        {("Close", "^GSPC"): [float("nan"), float("nan")]},
        index=dates,
    )
    mocker.patch("global_feed.yf.download", return_value=df)

    _fetch_and_store()  # should not raise

    stored = state.get_all_global_prices()
    assert "^GSPC" not in stored


def test_fetch_global_handles_download_exception(mocker):
    """If yfinance.download() raises, _fetch_and_store should not propagate."""
    from global_feed import _fetch_and_store
    mocker.patch("global_feed.yf.download", side_effect=Exception("network error"))

    _fetch_and_store()  # should not raise

    assert state.get_all_global_prices() == {}


@pytest.mark.asyncio
async def test_start_global_feed_loops(mocker):
    """start_global_feed should call _fetch_and_store repeatedly."""
    from global_feed import start_global_feed

    calls = []
    def fake_fetch():
        calls.append(1)

    mocker.patch("global_feed._fetch_and_store", side_effect=fake_fetch)

    sleep_count = [0]
    async def fake_sleep(n):
        sleep_count[0] += 1
        if sleep_count[0] >= 2:
            raise asyncio.CancelledError()

    mocker.patch("global_feed.asyncio.sleep", side_effect=fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await start_global_feed()

    assert len(calls) >= 1
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd nicegui_app && uv run pytest tests/test_global_feed.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'global_feed'`

- [ ] **Step 3: Implement global_feed.py**

Create `nicegui_app/global_feed.py`:

```python
"""
Global market data feed using yfinance.

Fetches prices for 13 global indices, commodities, and crypto every 60 s.
Writes results to state._global_prices via set_global_price().

Usage (called once from main.py):
    asyncio.create_task(start_global_feed())
"""
import asyncio

import yfinance as yf

from state import set_global_price, get_all_global_prices  # noqa: F401 (re-exported)

# Symbol → (display name, currency symbol, flag emoji)
SYMBOLS: dict[str, tuple[str, str, str]] = {
    "^GSPC":     ("S&P 500",       "USD", "🇺🇸"),
    "^IXIC":     ("NASDAQ",        "USD", "🇺🇸"),
    "^DJI":      ("Dow Jones",     "USD", "🇺🇸"),
    "^FTSE":     ("FTSE 100",      "GBP", "🇬🇧"),
    "^GDAXI":    ("DAX",           "EUR", "🇩🇪"),
    "^FCHI":     ("CAC 40",        "EUR", "🇫🇷"),
    "^N225":     ("Nikkei 225",    "JPY", "🇯🇵"),
    "^HSI":      ("Hang Seng",     "HKD", "🇭🇰"),
    "000001.SS": ("Shanghai Comp", "CNY", "🇨🇳"),
    "GC=F":      ("Gold",          "USD", "🥇"),
    "CL=F":      ("Crude Oil",     "USD", "🛢️"),
    "BTC-USD":   ("Bitcoin",       "USD", "₿"),
    "ETH-USD":   ("Ethereum",      "USD", "Ξ"),
}

_TICKERS = " ".join(SYMBOLS.keys())


def _fetch_and_store() -> None:
    """Download latest prices via yfinance and write to state._global_prices."""
    try:
        df = yf.download(_TICKERS, period="2d", interval="1d",
                         group_by="ticker", auto_adjust=True, progress=False)
    except Exception as exc:
        print(f"  [global_feed] download failed: {exc}")
        return

    for symbol, (name, currency, flag) in SYMBOLS.items():
        try:
            # yfinance multi-ticker DataFrames have a MultiIndex: (field, symbol)
            close_col = ("Close", symbol)
            if close_col not in df.columns:
                continue
            closes = df[close_col].dropna()
            if len(closes) < 2:
                continue
            prev_close = float(closes.iloc[-2])
            price = float(closes.iloc[-1])
            if prev_close == 0:
                continue
            change_pct = round((price - prev_close) / prev_close * 100, 2)
            set_global_price(symbol, {
                "name": name,
                "price": round(price, 2),
                "change_pct": change_pct,
                "currency": currency,
                "flag": flag,
            })
        except Exception as exc:
            print(f"  [global_feed] skipping {symbol}: {exc}")


async def start_global_feed() -> None:
    """
    Background loop: fetch global prices immediately, then every 60 s.
    Runs forever — errors within a cycle are swallowed; the loop continues.
    """
    while True:
        await asyncio.get_event_loop().run_in_executor(None, _fetch_and_store)
        await asyncio.sleep(60)
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd nicegui_app && uv run pytest tests/test_global_feed.py -v
```

Expected:
```
PASSED tests/test_global_feed.py::test_fetch_global_writes_to_state
PASSED tests/test_global_feed.py::test_fetch_global_computes_change_pct
PASSED tests/test_global_feed.py::test_fetch_global_skips_failed_symbol
PASSED tests/test_global_feed.py::test_fetch_global_handles_download_exception
PASSED tests/test_global_feed.py::test_start_global_feed_loops
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add nicegui_app/global_feed.py nicegui_app/tests/test_global_feed.py
git commit -m "feat: add global market feed via yfinance"
```

---

## Task 6: Wire feeds into main.py

**Files:**
- Modify: `nicegui_app/main.py`

- [ ] **Step 1: Add imports**

At the top of `nicegui_app/main.py`, after the existing imports (around line 20), add:

```python
from ws_feed import start_ws_feed
from global_feed import start_global_feed
```

- [ ] **Step 2: Start background tasks in the startup hook**

In `_start_scheduler()` (around line 109), add two new `asyncio.create_task()` calls after the existing ones:

```python
    asyncio.create_task(start_ws_feed())
    asyncio.create_task(start_global_feed())
```

The full `_start_scheduler` body should now end with:
```python
    asyncio.create_task(_loop())
    asyncio.create_task(run_trading_engine())
    asyncio.create_task(_top_stocks_loop())
    asyncio.create_task(start_ws_feed())
    asyncio.create_task(start_global_feed())
```

- [ ] **Step 3: Verify the app starts without errors**

```bash
cd nicegui_app && timeout 8 uv run python main.py 2>&1 | head -30
```

Expected: no `ImportError` or `AttributeError`. May see `[ws_feed] connecting…` or a connection error (expected outside market hours with no live WS session).

- [ ] **Step 4: Commit**

```bash
git add nicegui_app/main.py
git commit -m "feat: wire WebSocket and global feed into app startup"
```

---

## Task 7: Tests for dashboard price helpers

**Files:**
- Create: `nicegui_app/tests/test_dashboard_prices.py`

- [ ] **Step 1: Write tests for `_compute_synthetic_futures`**

Create `nicegui_app/tests/test_dashboard_prices.py`:

```python
"""Tests for dashboard price helper functions."""
import pandas as pd
import pytest

from pages.dashboard import _compute_synthetic_futures


def _make_chain(strike: int, ce_ltp: float, pe_ltp: float) -> pd.DataFrame:
    return pd.DataFrame([
        {"Strike": strike, "Type": "CE", "LTP": ce_ltp},
        {"Strike": strike, "Type": "PE", "LTP": pe_ltp},
    ])


def test_synthetic_futures_basic():
    """Futures = ATM + CE_LTP - PE_LTP (put-call parity)."""
    df = _make_chain(22500, ce_ltp=200.0, pe_ltp=150.0)
    result = _compute_synthetic_futures(spot=22480.0, df=df, strike_step=50)
    # ATM = round(22480/50)*50 = 22500
    assert result == pytest.approx(22500 + 200.0 - 150.0, abs=0.01)


def test_synthetic_futures_none_spot():
    """Returns None when spot is None."""
    df = _make_chain(22500, 200.0, 150.0)
    assert _compute_synthetic_futures(spot=None, df=df, strike_step=50) is None


def test_synthetic_futures_empty_df():
    """Returns None for empty DataFrame."""
    assert _compute_synthetic_futures(spot=22480.0, df=pd.DataFrame(), strike_step=50) is None


def test_synthetic_futures_none_df():
    """Returns None when df is None."""
    assert _compute_synthetic_futures(spot=22480.0, df=None, strike_step=50) is None


def test_synthetic_futures_missing_ce():
    """Returns None when CE row is missing for ATM."""
    df = pd.DataFrame([{"Strike": 22500, "Type": "PE", "LTP": 150.0}])
    assert _compute_synthetic_futures(spot=22480.0, df=df, strike_step=50) is None


def test_synthetic_futures_missing_pe():
    """Returns None when PE row is missing for ATM."""
    df = pd.DataFrame([{"Strike": 22500, "Type": "CE", "LTP": 200.0}])
    assert _compute_synthetic_futures(spot=22480.0, df=df, strike_step=50) is None
```

- [ ] **Step 2: Run tests — expect all pass**

```bash
cd nicegui_app && uv run pytest tests/test_dashboard_prices.py -v
```

Expected:
```
PASSED tests/test_dashboard_prices.py::test_synthetic_futures_basic
PASSED tests/test_dashboard_prices.py::test_synthetic_futures_none_spot
PASSED tests/test_dashboard_prices.py::test_synthetic_futures_empty_df
PASSED tests/test_dashboard_prices.py::test_synthetic_futures_none_df
PASSED tests/test_dashboard_prices.py::test_synthetic_futures_missing_ce
PASSED tests/test_dashboard_prices.py::test_synthetic_futures_missing_pe
6 passed
```

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/tests/test_dashboard_prices.py
git commit -m "test: add coverage for _compute_synthetic_futures"
```

---

## Task 8: Refactor dashboard price cards to update in-place

**Files:**
- Modify: `nicegui_app/pages/dashboard.py`

This task replaces the "rebuild cards on every refresh" pattern with stable label references updated via `.set_text()`.

- [ ] **Step 1: Update imports in dashboard.py**

At the top of `nicegui_app/pages/dashboard.py`, add to the existing imports:

```python
from state import get_live_price, _ws_connected
```

- [ ] **Step 2: Replace the price card section in `render_dashboard`**

Find the block starting with `# ---- API Status Card ----` (around line 257) through the end of the price cards section (around line 401). Replace it with the following:

```python
        # ---- API Status Bar (two pills) ----
        api_status_container = ui.element("div").classes("w-full mb-4")
        with api_status_container:
            _render_api_status_pills(ws_connected=False, last_tick=None)

        # ---- Section Header ----
        with ui.row().classes("w-full items-center mb-4"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("monitoring", size="22px").classes("text-emerald-500")
                ui.label("Market Overview").classes("text-lg font-semibold text-gray-800")
            ui.space()
            update_time_label = ui.label("").classes("text-xs text-gray-400")

        # ---- Price Cards (created ONCE; labels updated in-place) ----
        _price_labels: dict[str, dict] = {}  # name → {"price": label, "badge": label}
        with ui.element("div").classes("w-full responsive-price-grid"):
            for name in ["NIFTY", "BANKNIFTY"]:
                card_cls = "price-card-nifty" if name == "NIFTY" else "price-card-bnf"
                dot_color = "bg-emerald-500" if name == "NIFTY" else "bg-teal-600"
                for ptype in ["SPOT", "FUT"]:
                    key = f"{name}_{ptype}"
                    with ui.card().classes(
                        f"{card_cls} shadow-sm !rounded-xl"
                    ).style("min-height: 120px; border: 2px solid #d1d5db !important;") as card:
                        with ui.column().classes("w-full h-full justify-center py-4 sm:py-5 pl-4 sm:pl-5"):
                            with ui.row().classes("items-center gap-2"):
                                ui.element("div").classes(f"w-2 h-2 rounded-full {dot_color}")
                                label_text = f"{name} {ptype}"
                                ui.label(label_text).classes(
                                    "text-[11px] font-bold text-gray-500 uppercase tracking-widest"
                                )
                            price_lbl = ui.label("--").classes(
                                "text-xl sm:text-3xl font-bold text-gray-900 mt-2 tracking-tight"
                            )
                            badge_lbl = ui.label("").classes("text-xs font-semibold mt-2")
                    _price_labels[key] = {"price": price_lbl, "badge": badge_lbl, "card": card}
```

- [ ] **Step 3: Add the fast price-update timer inside `render_dashboard`**

After the price card grid (still inside `render_dashboard`, before `page_client = context.client`), add:

```python
        def _update_price_labels():
            """Update price labels in-place from state._live_prices every 2s."""
            import state as _state
            for name in ["NIFTY", "BANKNIFTY"]:
                entry = _state.get_live_price(name)
                if entry is None:
                    continue
                ltp = entry["ltp"]
                change = entry["change"]
                change_pct = entry["change_pct"]
                sign = "+" if change >= 0 else ""
                color_cls = "text-green-700" if change >= 0 else "text-red-700"

                spot_key = f"{name}_SPOT"
                if spot_key in _price_labels:
                    _price_labels[spot_key]["price"].set_text(f"{ltp:,.2f}")
                    _price_labels[spot_key]["badge"].set_text(
                        f"{sign}{change:,.2f} ({sign}{change_pct}%)"
                    )
                    _price_labels[spot_key]["badge"].classes(color_cls, remove="text-green-700 text-red-700")

                # FUT uses REST-fetched value (no live WS for synthetic futures)
                # It will be updated in the existing slow refresh() below

            # Update API status pills
            import state as _state
            last_tick_times = [
                v.get("timestamp") for v in _state._live_prices.values() if v.get("timestamp")
            ]
            last_tick = max(last_tick_times) if last_tick_times else None
            api_status_container.clear()
            with api_status_container:
                _render_api_status_pills(ws_connected=_state._ws_connected, last_tick=last_tick)

        ui.timer(2, _update_price_labels)
```

- [ ] **Step 4: Add `_render_api_status_pills` function**

At the bottom of `dashboard.py`, after the existing `_render_api_status` function, add:

```python
def _render_api_status_pills(ws_connected: bool, last_tick: str | None):
    """Render two status pills: WS connection health + last tick time."""
    with ui.row().classes("w-full gap-3 flex-wrap"):
        # Pill 1: WebSocket status
        if ws_connected:
            pill_cls = "border-green-200 bg-green-50"
            dot_cls = "bg-green-500"
            icon_name = "wifi"
            icon_cls = "text-green-500"
            title = "Dhan WS — Live"
            title_cls = "text-sm font-semibold text-green-700"
        else:
            pill_cls = "border-red-200 bg-red-50"
            dot_cls = "bg-red-500 animate-pulse"
            icon_name = "wifi_off"
            icon_cls = "text-red-500"
            title = "Dhan WS — Disconnected"
            title_cls = "text-sm font-semibold text-red-700"

        with ui.card().classes(
            f"border {pill_cls} rounded-xl shadow-sm px-4 py-2 flex-1 min-w-[200px]"
        ).props("flat"):
            with ui.row().classes("items-center gap-2"):
                ui.icon(icon_name, size="20px").classes(icon_cls)
                ui.label(title).classes(title_cls)
                ui.space()
                ui.element("div").classes(f"w-2 h-2 rounded-full {dot_cls}")

        # Pill 2: Last tick timestamp
        with ui.card().classes(
            "border border-gray-100 bg-gray-50 rounded-xl shadow-sm px-4 py-2 flex-1 min-w-[200px]"
        ).props("flat"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("schedule", size="20px").classes("text-gray-400")
                tick_text = f"Last tick: {last_tick} IST" if last_tick else "Waiting for first tick…"
                ui.label(tick_text).classes("text-sm text-gray-500")
```

- [ ] **Step 5: Run the app briefly and confirm no errors**

```bash
cd nicegui_app && timeout 8 uv run python main.py 2>&1 | grep -E "(Error|Traceback|ok|started)"
```

Expected: No Python tracebacks. The server starts.

- [ ] **Step 6: Commit**

```bash
git add nicegui_app/pages/dashboard.py
git commit -m "feat: price cards update in-place from WebSocket state, new API status pills"
```

---

## Task 9: Add global markets grid section

**Files:**
- Modify: `nicegui_app/pages/dashboard.py`

- [ ] **Step 1: Add the global markets container in `render_dashboard`**

After the ATM charts container declaration (`charts_container = ui.element("div").classes("w-full mt-6")`), add:

```python
        # ---- Global Markets Grid ----
        global_markets_container = ui.element("div").classes("w-full mt-8")
        with global_markets_container:
            _render_global_markets_loading()
```

- [ ] **Step 2: Add `_render_global_markets_loading` helper**

At the bottom of `dashboard.py`, add:

```python
def _render_global_markets_loading():
    with ui.card().classes("w-full border border-gray-100 rounded-xl shadow-sm bg-white px-5 py-3").props("flat"):
        with ui.row().classes("items-center gap-3"):
            ui.spinner("dots", size="sm").classes("text-gray-400")
            ui.label("Loading global markets…").classes("text-sm text-gray-400")
```

- [ ] **Step 3: Add `_render_global_markets_grid` helper**

Still at the bottom of `dashboard.py`, add:

```python
_GLOBAL_GROUPS = [
    ("🌎 US Indices",      ["^GSPC", "^IXIC", "^DJI"]),
    ("🌍 Europe",          ["^FTSE", "^GDAXI", "^FCHI"]),
    ("🌏 Asia",            ["^N225", "^HSI", "000001.SS"]),
    ("⚡ Commodities & Crypto", ["GC=F", "CL=F", "BTC-USD", "ETH-USD"]),
]


def _render_global_markets_grid(prices: dict):
    """Render global market tiles grouped by region."""
    with ui.row().classes("items-center gap-2 mb-4"):
        ui.icon("public", size="22px").classes("text-emerald-500")
        ui.label("Global Markets").classes("text-lg font-semibold text-gray-800")
        ui.space()
        with ui.element("div").classes(
            "text-xs text-gray-400 bg-gray-100 rounded-full px-3 py-0.5"
        ):
            ui.label("Delayed ~15 min")

    for group_label, symbols in _GLOBAL_GROUPS:
        ui.label(group_label).classes("text-xs font-bold text-gray-500 uppercase tracking-wider mt-4 mb-2")
        with ui.element("div").classes("w-full").style(
            "display:grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 0.75rem;"
        ):
            for sym in symbols:
                entry = prices.get(sym)
                if entry is None:
                    continue
                price = entry["price"]
                change_pct = entry["change_pct"]
                flag = entry["flag"]
                name = entry["name"]
                currency = entry["currency"]
                up = change_pct >= 0
                sign = "+" if up else ""
                border_color = "#4ade80" if up else "#f87171"
                badge_cls = "bg-green-50 text-green-700" if up else "bg-red-50 text-red-700"
                arrow = "arrow_drop_up" if up else "arrow_drop_down"

                with ui.card().classes("border shadow-sm !rounded-xl").style(
                    f"border: 1.5px solid {border_color} !important; min-height: 90px;"
                ):
                    with ui.column().classes("w-full h-full justify-center px-3 py-3 gap-0.5"):
                        with ui.row().classes("items-center gap-1"):
                            ui.label(flag).style("font-size: 1rem;")
                            ui.label(name).classes("text-[10px] font-bold text-gray-500 uppercase tracking-wider truncate")
                        ui.label(f"{currency} {price:,.2f}").classes("text-base font-bold text-gray-900 mt-1")
                        with ui.row().classes(
                            f"items-center gap-0 px-1.5 py-0.5 rounded-md {badge_cls}"
                        ).style("width: fit-content"):
                            ui.icon(arrow, size="16px")
                            ui.label(f"{sign}{change_pct}%").classes("text-xs font-semibold")
```

- [ ] **Step 4: Wire the global markets update into the slow `refresh()` coroutine**

Inside the `async def refresh():` function (around line 296), after the price cards update block and before the ATM charts block, add:

```python
        # ---- Global Markets ----
        from state import get_all_global_prices
        global_prices = get_all_global_prices()
        global_markets_container.clear()
        with global_markets_container:
            if global_prices:
                _render_global_markets_grid(global_prices)
            else:
                _render_global_markets_loading()
```

- [ ] **Step 5: Confirm app starts cleanly**

```bash
cd nicegui_app && timeout 8 uv run python main.py 2>&1 | grep -E "(Error|Traceback)"
```

Expected: no output (no errors).

- [ ] **Step 6: Commit**

```bash
git add nicegui_app/pages/dashboard.py
git commit -m "feat: add global markets grid to dashboard (yfinance, delayed)"
```

---

## Task 10: Add the four widgets (sentiment, VIX dial, top movers, calendar)

**Files:**
- Modify: `nicegui_app/pages/dashboard.py`

- [ ] **Step 1: Add widgets container in `render_dashboard`**

After `global_markets_container` declaration, add:

```python
        # ---- Widgets Row ----
        widgets_container = ui.element("div").classes("w-full mt-8")
        with widgets_container:
            _render_widgets_loading()
```

- [ ] **Step 2: Add `_render_widgets_loading` helper**

At the bottom of `dashboard.py`:

```python
def _render_widgets_loading():
    with ui.card().classes("w-full border border-gray-100 rounded-xl shadow-sm bg-white px-5 py-3").props("flat"):
        with ui.row().classes("items-center gap-3"):
            ui.spinner("dots", size="sm").classes("text-gray-400")
            ui.label("Loading market insights…").classes("text-sm text-gray-400")
```

- [ ] **Step 3: Add `_compute_rsi14` helper**

At the bottom of `dashboard.py` (used by the sentiment gauge):

```python
def _compute_rsi14(closes: list[float]) -> float | None:
    """Compute RSI(14) from a list of closing prices. Returns None if insufficient data."""
    if len(closes) < 15:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[-14:]) / 14
    avg_loss = sum(losses[-14:]) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)
```

- [ ] **Step 4: Add the four widget render helpers**

At the bottom of `dashboard.py`:

```python
def _render_sentiment_gauge(rsi: float | None):
    """Market Sentiment: SVG arc needle driven by RSI(14)."""
    if rsi is None:
        score = 50
        label = "Neutral"
        color = "#94a3b8"
    elif rsi < 30:
        score = int(rsi * 100 / 30 * 0.2)         # 0-20 → Extreme Fear
        label = "Extreme Fear"
        color = "#ef4444"
    elif rsi < 40:
        score = int(20 + (rsi - 30) * 2)           # 20-40 → Fear
        label = "Fear"
        color = "#f97316"
    elif rsi < 60:
        score = int(40 + (rsi - 40))               # 40-60 → Neutral
        label = "Neutral"
        color = "#eab308"
    elif rsi < 70:
        score = int(60 + (rsi - 60) * 2)           # 60-80 → Greed
        label = "Greed"
        color = "#22c55e"
    else:
        score = int(80 + (rsi - 70) * 100 / 30 * 0.2)  # 80-100 → Extreme Greed
        label = "Extreme Greed"
        color = "#16a34a"

    score = max(0, min(100, score))
    # Needle angle: 0 → -90deg (left), 100 → +90deg (right)
    angle = -90 + score * 1.8

    svg = f"""
    <svg viewBox="0 0 200 120" width="180" height="110">
      <defs>
        <linearGradient id="arcGrad" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%"   stop-color="#ef4444"/>
          <stop offset="25%"  stop-color="#f97316"/>
          <stop offset="50%"  stop-color="#eab308"/>
          <stop offset="75%"  stop-color="#22c55e"/>
          <stop offset="100%" stop-color="#16a34a"/>
        </linearGradient>
      </defs>
      <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="url(#arcGrad)" stroke-width="14" stroke-linecap="round"/>
      <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="#f1f5f9" stroke-width="5" stroke-linecap="round" opacity="0.4"/>
      <g transform="rotate({angle}, 100, 100)">
        <line x1="100" y1="100" x2="100" y2="30" stroke="#0f172a" stroke-width="3" stroke-linecap="round"/>
        <circle cx="100" cy="100" r="5" fill="#0f172a"/>
      </g>
    </svg>
    """
    with ui.card().classes("border border-gray-200 shadow-sm !rounded-xl p-4").props("flat"):
        with ui.column().classes("items-center gap-1 w-full"):
            ui.label("Market Sentiment").classes("text-xs font-bold text-gray-500 uppercase tracking-wider")
            ui.html(svg)
            ui.label(label).classes("text-sm font-bold mt-1").style(f"color: {color};")
            rsi_text = f"RSI(14): {rsi}" if rsi is not None else "Insufficient data"
            ui.label(rsi_text).classes("text-xs text-gray-400")


def _render_vix_dial(vix: float | None):
    """India VIX circular ring dial."""
    if vix is None:
        display = "--"
        ring_color = "#94a3b8"
        zone_label = "No data"
        zone_cls = "text-gray-400"
    elif vix < 15:
        display = f"{vix:.1f}"
        ring_color = "#22c55e"
        zone_label = "Calm"
        zone_cls = "text-green-600"
    elif vix < 20:
        display = f"{vix:.1f}"
        ring_color = "#eab308"
        zone_label = "Moderate"
        zone_cls = "text-yellow-600"
    else:
        display = f"{vix:.1f}"
        ring_color = "#ef4444"
        zone_label = "Elevated Fear"
        zone_cls = "text-red-600"

    # SVG ring: circumference = 2π×45 ≈ 283; fill proportional to vix (max=40)
    max_vix = 40.0
    fill_ratio = min(float(vix or 0) / max_vix, 1.0)
    circ = 283.0
    dash_len = round(fill_ratio * circ, 1)

    svg = f"""
    <svg viewBox="0 0 120 120" width="110" height="110">
      <circle cx="60" cy="60" r="45" fill="none" stroke="#f1f5f9" stroke-width="12"/>
      <circle cx="60" cy="60" r="45" fill="none" stroke="{ring_color}" stroke-width="12"
              stroke-dasharray="{dash_len} {circ}" stroke-linecap="round"
              transform="rotate(-90 60 60)"/>
      <text x="60" y="55" text-anchor="middle" font-size="20" font-weight="700" fill="#0f172a">{display}</text>
      <text x="60" y="72" text-anchor="middle" font-size="9" fill="#94a3b8">India VIX</text>
    </svg>
    """
    with ui.card().classes("border border-gray-200 shadow-sm !rounded-xl p-4").props("flat"):
        with ui.column().classes("items-center gap-1 w-full"):
            ui.label("India VIX").classes("text-xs font-bold text-gray-500 uppercase tracking-wider")
            ui.html(svg)
            ui.label(zone_label).classes(f"text-sm font-bold {zone_cls}")


def _render_top_movers(all_prices: dict):
    """Table of biggest movers across tracked indices."""
    rows = []
    for sym, entry in all_prices.items():
        rows.append({
            "name": entry["name"],
            "flag": entry["flag"],
            "price": entry["price"],
            "change_pct": entry["change_pct"],
            "currency": entry["currency"],
        })
    # Add Indian indices from live prices
    import state as _state
    for idx_name in ["NIFTY", "BANKNIFTY"]:
        lp = _state.get_live_price(idx_name)
        if lp:
            rows.append({
                "name": idx_name,
                "flag": "🇮🇳",
                "price": lp["ltp"],
                "change_pct": lp["change_pct"],
                "currency": "INR",
            })

    rows.sort(key=lambda r: abs(r["change_pct"]), reverse=True)
    top5 = rows[:5]

    with ui.card().classes("border border-gray-200 shadow-sm !rounded-xl p-4").props("flat"):
        ui.label("Top Movers").classes("text-xs font-bold text-gray-500 uppercase tracking-wider mb-3")
        if not top5:
            ui.label("No data yet").classes("text-sm text-gray-400 italic")
            return
        for row in top5:
            pct = row["change_pct"]
            up = pct >= 0
            sign = "+" if up else ""
            row_bg = "bg-green-50" if up else "bg-red-50"
            pct_cls = "text-green-700 font-semibold" if up else "text-red-700 font-semibold"
            with ui.row().classes(f"w-full items-center justify-between px-2 py-1.5 rounded-lg {row_bg} mb-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(row["flag"]).style("font-size: 0.9rem;")
                    ui.label(row["name"]).classes("text-xs font-bold text-gray-700 truncate").style("max-width: 100px;")
                ui.label(f"{sign}{pct}%").classes(pct_cls).style("font-size: 0.75rem;")


def _render_economic_calendar():
    """Upcoming economic events strip."""
    from economic_calendar import get_upcoming_events
    from datetime import date
    events = get_upcoming_events(n=5)
    today = date.today()

    type_colors = {
        "expiry": ("bg-blue-100 text-blue-700", "Expiry"),
        "rbi":    ("bg-amber-100 text-amber-700", "RBI"),
        "fed":    ("bg-purple-100 text-purple-700", "Fed"),
    }

    with ui.card().classes("border border-gray-200 shadow-sm !rounded-xl p-4").props("flat"):
        ui.label("Economic Calendar").classes("text-xs font-bold text-gray-500 uppercase tracking-wider mb-3")
        if not events:
            ui.label("No upcoming events").classes("text-sm text-gray-400 italic")
            return
        for ev in events:
            delta = (ev["date"] - today).days
            highlight = delta <= 3
            row_cls = "border-l-4 border-amber-400 bg-amber-50 pl-2" if highlight else "border-l-4 border-gray-200 pl-2"
            chip_cls, chip_label = type_colors.get(ev["type"], ("bg-gray-100 text-gray-600", ev["type"]))
            with ui.row().classes(f"w-full items-center gap-3 py-1.5 pr-2 rounded-r-lg {row_cls} mb-1"):
                with ui.element("div").classes(
                    "text-xs font-bold text-gray-500 bg-white border border-gray-200 rounded-lg px-2 py-1 text-center"
                ).style("min-width: 52px;"):
                    ui.label(ev["date"].strftime("%d %b")).classes("text-gray-800 font-bold text-xs")
                ui.label(ev["label"]).classes("text-sm text-gray-700 flex-1")
                with ui.element("span").classes(f"text-[10px] font-bold px-2 py-0.5 rounded-full {chip_cls}"):
                    ui.label(chip_label)
```

- [ ] **Step 5: Wire widgets into the slow `refresh()` coroutine**

Inside `async def refresh()`, after the global markets block, add:

```python
        # ---- Widgets ----
        nifty_entry = get_live_price("NIFTY")
        vix_entry = get_live_price("VIX")

        # Compute RSI(14) from cached NIFTY candles for sentiment
        nifty_candles = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _fetch_any_index_candles("13")
        )
        rsi_value = None
        if nifty_candles is not None and not nifty_candles.empty and "close" in nifty_candles.columns:
            closes = [float(c) for c in nifty_candles["close"].tolist()]
            rsi_value = _compute_rsi14(closes)

        vix_value = vix_entry["ltp"] if vix_entry else None
        global_snapshot = get_all_global_prices()

        if page_client._deleted:
            return

        widgets_container.clear()
        with widgets_container:
            with ui.row().classes("items-center gap-2 mb-4"):
                ui.icon("insights", size="22px").classes("text-emerald-500")
                ui.label("Market Insights").classes("text-lg font-semibold text-gray-800")
            with ui.element("div").style(
                "display:grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1rem;"
            ).classes("w-full"):
                _render_sentiment_gauge(rsi_value)
                _render_vix_dial(vix_value)
                _render_top_movers(global_snapshot)
                _render_economic_calendar()
```

Add the missing import at the top of the `refresh()` function (add alongside existing imports within the function or at the top of `dashboard.py`):

```python
from state import get_live_price, get_all_global_prices
```

- [ ] **Step 6: Confirm app starts cleanly**

```bash
cd nicegui_app && timeout 8 uv run python main.py 2>&1 | grep -E "(Error|Traceback)"
```

Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add nicegui_app/pages/dashboard.py
git commit -m "feat: add sentiment gauge, VIX dial, top movers, and economic calendar widgets"
```

---

## Task 11: Run full test suite and verify

- [ ] **Step 1: Run all tests**

```bash
cd nicegui_app && uv run pytest tests/ -v --tb=short
```

Expected: all tests pass. The suite should include:
- `test_config.py`
- `test_state.py`
- `test_algo_strategies.py`
- `test_data.py`
- `test_charts.py`
- `test_economic_calendar.py` (5 tests)
- `test_ws_feed.py` (7 tests)
- `test_global_feed.py` (5 tests)
- `test_dashboard_prices.py` (6 tests)

- [ ] **Step 2: Fix any failures before proceeding**

If any test fails, read the error carefully. The most likely issues:
- `marketfeed.IDX_I` not found → check `dir(marketfeed)` and use the correct constant
- Import path issues → ensure `conftest.py` adds `nicegui_app/` to sys.path (check existing tests for the pattern)

- [ ] **Step 3: Final commit**

```bash
git add -u
git commit -m "test: all dashboard tests passing"
```
