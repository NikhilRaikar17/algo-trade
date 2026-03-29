# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
cd nicegui_app
uv run python main.py
```

Starts the NiceGUI web dashboard at `http://0.0.0.0:8501` with hot-reload. The app auto-reloads on file saves.

## Installing Dependencies

```bash
uv sync
```

Configured via `pyproject.toml`. Uses `uv` as the package manager. No separate `requirements.txt`.

## Architecture Overview

This is an algorithmic options trading platform for NIFTY and BANKNIFTY indices. All active development lives in `nicegui_app/`.

### Data Flow

```
Browser → main.py (refresh every 120s) → data.py → Dhan REST API
                                        → algo_strategies.py → state._trade_store
                                        → charts.py → Plotly figures
                                        → pnl.py → Telegram alerts
```

### Key Files in `nicegui_app/`

| File | Role |
|------|------|
| `main.py` | NiceGUI entry point; page containers, refresh timer loop, market status |
| `sidebar.py` | Left drawer navigation — called from `main.py` after page containers exist |
| `config.py` | IST timezone, market hours (9:15–15:30), NSE holidays, algo params (RSI=14, SMA fast=9/slow=21) |
| `state.py` | In-memory cache (90s TTL), `_trade_store`, `is_market_open()`, Telegram dedup |
| `data.py` | Dhan API calls: option chains, 15-min index candles, 5-min option candles |
| `algo_strategies.py` | Signal detection: ABCD harmonic patterns, RSI+SMA crossover, RSI-only |
| `charts.py` | Plotly candlestick builders — all values must be native Python types (no numpy/pandas) |
| `pnl.py` | P&L collection; sends Telegram summaries at 9 AM and 3:30 PM IST |
| `ui_components.py` | Reusable NiceGUI widgets |

### Page Structure (`nicegui_app/pages/`)

Each page has a `render_*_tab(container, ...)` function that returns an async `refresh()` closure registered in `main.py`'s `build_ui()`. Pages are created once; visibility is toggled via `container.set_visibility()`.

| Page | Description |
|------|-------------|
| `dashboard.py` | Dual clocks (IST/CEST), NIFTY/BANKNIFTY spot prices |
| `option_chain.py` | ATM option chain with Greeks, IV, LTP, and trend (UP/DOWN/FLAT) |
| `algo.py` | Live trading UI — only rendered when market is open |
| `rsi_only.py` | Historical RSI backtest (15-min candles, 5-day window) |
| `abcd_only.py` | Historical ABCD harmonic backtest (15-min candles, 5-day window) |
| `pnl_tab.py` | Realized & unrealized P&L with win-rate stats |
| `market_closed.py` | Placeholder shown in place of live algo pages when market is closed |

### Strategies

**ABCD Harmonic Pattern** (`detect_abcd_patterns`): Finds 4-swing sequences (A→B→C→D) where BC retraces 61.8–78.6% of AB and CD/AB ratio is 100–161.8%. Bullish pattern signals a buy at D; bearish signals a sell.

**RSI + SMA** (`detect_rsi_sma_signals`): Fast SMA(9) crosses above Slow SMA(21) with RSI > 30 → BUY; fast crosses below slow with RSI < 70 → SELL.

**RSI Only** (`detect_rsi_only_signals`): RSI(14) exits below 30 back above → BUY; exits above 70 back below → SELL. Used for index-level historical backtesting only.

### Dhan API Constraints

- `dhan.intraday_minute_data(sec_id, segment, instrument_type, from_date, to_date, interval)` — supported intervals: **1, 5, 15, 25, 60** (30 is NOT supported)
- Max 5 trading days per intraday request
- NIFTY: `security_id="13"`, BANKNIFTY: `security_id="25"`, `segment="IDX_I"`, `instrument_type="INDEX"`

## Critical NiceGUI Gotchas

**JSON serialization**: NiceGUI uses `orjson` which rejects `numpy.float64` and `pandas.Timestamp`. In `charts.py` and `algo_strategies.py`, always convert:
- Floats: wrap with `float()`
- Timestamps: use `.dt.strftime()` or `.strftime()` to convert to strings
- Arrays: use `.tolist()`

**No `.text()` on elements**: `ui.element()` does not have a `.text()` method. Use `with element: ui.label(value)` instead.

**Page visibility pattern**: Containers are created once in `main.py`, then hidden/shown. Do not recreate them — call `container.clear()` then rebuild content inside.

**Sidebar must be built after page_containers**: `build_sidebar(drawer, active_page, nav_btn_refs, page_containers)` is called after the main content area is set up because the sidebar's nav buttons reference `page_containers`.

## Environment Variables (`.env`)

```
DHAN_CLIENT_CODE=...
DHAN_TOKEN_ID=...         # JWT for Dhan API
DHAN_BOT_TOKEN=...        # Telegram bot token
DHAN_PAPER_TRADING=True   # Toggle paper vs live orders
GMAIL_USERNAME=...
APP_PASSWORD=...
RECEIVER_EMAIL=...
```

## Legacy / Unused Directories

- `zerodha_kite/` — legacy Zerodha integration, not actively used
- `dhan_websockets/` — WebSocket streaming, mostly unused; REST API is used instead
- `dhan_trade.py` — standalone legacy trading loop
