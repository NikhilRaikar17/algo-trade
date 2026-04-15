# Dashboard Page Redesign — Design Spec
**Date:** 2026-04-15  
**Branch:** migrate  

---

## Overview

Enhance the existing NiceGUI dashboard page with true live prices for Indian indices (via Dhan WebSocket), a global markets grid (via yfinance), and four new cool-feature widgets: market sentiment gauge, India VIX dial, top movers table, and economic calendar strip.

---

## Architecture & Data Flow

```
App startup (main.py)
  └─ asyncio.create_task(start_ws_feed())
       └─ DhanFeed WebSocket (dhanhq.marketfeed)
            └─ on_tick() → state._live_prices["NIFTY"] / ["BANKNIFTY"]
                         → state._ws_connected = True/False

  └─ asyncio.create_task(start_global_feed())
       └─ yfinance.download() every 60s
            └─ state._global_prices["^GSPC"] / ["BTC-USD"] / etc.

Dashboard page (dashboard.py)
  └─ ui.timer(2s)  → reads state._live_prices  → .set_text() on price labels
  └─ ui.timer(60s) → reads state._global_prices → rebuilds global markets grid
  └─ ui.timer(30s) → reads state._live_prices + VIX → updates 4 widget cards
```

**No REST polling for NIFTY/BANKNIFTY prices** — the WebSocket is the sole source. REST (`fetch_dashboard_prices`) is retained only for initial page load while the WebSocket warms up.

---

## New Files

| File | Purpose |
|------|---------|
| `nicegui_app/ws_feed.py` | WebSocket lifecycle: connect, subscribe, reconnect, write to state |
| `nicegui_app/global_feed.py` | yfinance background loop, writes to state |
| `nicegui_app/economic_calendar.py` | Hardcoded NSE expiries + RBI/Fed dates, `get_upcoming_events(n)` |
| `nicegui_app/tests/test_ws_feed.py` | Unit tests for WebSocket feed |
| `nicegui_app/tests/test_global_feed.py` | Unit tests for global feed |
| `nicegui_app/tests/test_economic_calendar.py` | Unit tests for calendar logic |
| `nicegui_app/tests/test_dashboard_prices.py` | Tests for existing price helpers |

---

## State Changes (`state.py`)

Two new top-level dicts and one bool added:

```python
_live_prices: dict  
# e.g. {"NIFTY": {"ltp": 22450.5, "prev_close": 22300.0, 
#                 "change": 150.5, "change_pct": 0.67, "timestamp": "14:32:05"}}

_global_prices: dict  
# e.g. {"^GSPC": {"name": "S&P 500", "price": 5200.1, "change_pct": 0.34,
#                 "currency": "USD", "flag": "🇺🇸"}}

_ws_connected: bool  # True when Dhan WebSocket has an active connection
```

---

## `ws_feed.py` — WebSocket Feed

- `async def start_ws_feed()` — entry point, called once from `main.py`
- Subscribes NIFTY (`security_id="13"`) and BANKNIFTY (`security_id="25"`) on `IDX_I` segment with `Ticker` subscription type
- On each tick: updates `state._live_prices[name]` with ltp, prev_close, change, change_pct, timestamp
- On disconnect/exception: sets `state._ws_connected = False`, reconnects with exponential backoff: 2s → 4s → 8s → … → max 60s
- On reconnect success: sets `state._ws_connected = True`

---

## `global_feed.py` — Global Markets Feed

- `async def start_global_feed()` — background loop, `asyncio.sleep(60)` between cycles
- Fetches via `yfinance.download(tickers, period="2d", interval="1d")` to get prev close + latest price
- Symbols tracked:

| Group | Symbols |
|-------|---------|
| US Indices | `^GSPC` (S&P 500), `^IXIC` (NASDAQ), `^DJI` (Dow Jones) |
| Europe | `^FTSE` (FTSE 100), `^GDAXI` (DAX), `^FCHI` (CAC 40) |
| Asia | `^N225` (Nikkei 225), `^HSI` (Hang Seng), `000001.SS` (Shanghai) |
| Commodities | `GC=F` (Gold), `CL=F` (Crude Oil) |
| Crypto | `BTC-USD` (Bitcoin), `ETH-USD` (Ethereum) |

- Failed symbols are silently skipped (network error, market closed, weekend)
- Section header shows "Delayed ~15 min" badge

---

## `economic_calendar.py` — Economic Calendar

- Hardcoded NSE weekly and monthly expiry dates for 2026
- Hardcoded RBI MPC dates and US Fed meeting dates for 2026
- `get_upcoming_events(n=5) -> list[dict]` — returns next N future events sorted by date
- Each event: `{date, label, type}` where type is `"expiry"` | `"rbi"` | `"fed"`

---

## Dashboard Layout (top to bottom)

### 1. Clocks — Unchanged
IST and CEST analog + digital clocks. No modifications.

### 2. API Status Bar — Enhanced
Two status pills side by side (instead of one card):
- **Dhan WS** — green "Live" with pulsing dot / red "Disconnected" — driven by `state._ws_connected`
- **Last Tick** — timestamp of the most recent price update from WebSocket

### 3. Indian Markets — Live Price Cards
Same 2×2 grid (NIFTY SPOT | NIFTY FUT | BANKNIFTY SPOT | BANKNIFTY FUT).

**Key change:** Price labels are created once and updated in-place via `.set_text()` on a `ui.timer(2s)`. No card rebuild on each tick. Initial values come from REST (`fetch_dashboard_prices`) while WebSocket warms up; subsequent updates come from `state._live_prices`.

### 4. Global Markets Grid — New Section
- 4-column grid on desktop, 2-column on mobile
- Grouped by region: US | Europe | Asia | Commodities & Crypto
- Each tile: flag emoji, market name, price, daily change % (green/red badge)
- Section header: "Global Markets · Delayed ~15 min"
- Refreshes every 60s

### 5. Widgets Row — New Section
Four cards in a horizontal row (2×2 on mobile):

**a) Market Sentiment Gauge**  
SVG arc needle, Bearish → Neutral → Bullish. Score derived from NIFTY RSI(14) mapped to 0–100. Labels: Extreme Fear / Fear / Neutral / Greed / Extreme Greed. Color: red → yellow → green.

**b) India VIX Dial**  
Circular progress ring. Color zones: green (<15, calm), yellow (15–20, moderate), red (>20, elevated fear). India VIX (`security_id="234613"`, segment `IDX_I`) is added as a third WebSocket subscription in `ws_feed.py` and stored in `state._live_prices["VIX"]["ltp"]`. Numeric value displayed in center of the dial.

**c) Top Movers Table**  
5-row table: all tracked indices + NIFTY + BANKNIFTY sorted by absolute % change. Columns: Name, Price, Change %. Green row for gainers, red for losers.

**d) Economic Calendar Strip**  
Next 5 upcoming events shown as a vertical list. Each row: date badge, event label, event type chip (Expiry / RBI / Fed). Events within 3 days highlighted in amber.

---

## Tests

| Test file | What it covers |
|-----------|---------------|
| `test_ws_feed.py` | Mock `DhanFeed`; assert `_live_prices` populated on tick; assert `_ws_connected` flips False on disconnect and True on reconnect |
| `test_global_feed.py` | Mock `yfinance.download`; assert `_global_prices` populated; assert failed symbol skipped gracefully |
| `test_dashboard_prices.py` | `_compute_synthetic_futures` with valid/empty/None inputs; `fetch_dashboard_prices` cache hit/miss |
| `test_economic_calendar.py` | `get_upcoming_events` returns only future events, sorted ascending, limited to n |

All tests use `pytest`. No live network calls in tests — all external dependencies mocked.

---

## Dependencies to Add

```toml
# pyproject.toml
yfinance = ">=0.2"
```

`dhanhq` (WebSocket) is already installed.

---

## Out of Scope

- Order placement from the dashboard
- Push notifications / alerts for global market moves
- Historical charts for global indices
- Modifying the clocks section
