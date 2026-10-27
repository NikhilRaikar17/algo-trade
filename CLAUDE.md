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

### Live algo engine (feed-driven)

Live trading runs on the Dhan websocket feed, not REST polling:
- `ws_feed.py` — one equity feed for the union of `watch(source, …)` lists ("engine", "positions", "algo"); every tick goes to `live_candles.on_tick()`.
- `live_candles.py` — 5-min bars built from ticks; bars from before a stock was subscribed are seeded once from REST (`seed()`), re-seeded only if its ticks stop.
- `trading_engine.py` — runs strategies just after each 5-min bar closes, on finished bars at the live price; `run_position_monitor()` closes open trades at target/stop on ticks.
- `account.py` — the paper account's book (`.live_book.json`): each signal is TAKEN or SKIPPED once (`trade_desk.check()`), only taken trades are alerted and counted. Limits in `config.RISK_LIMITS`.
- The Live Algos page only displays (classifiers called with `book=False`).
- `options_engine.py` — the same loop for NIFTY / BANKNIFTY options in a second paper account (`account.OPTIONS`, limits `config.OPTIONS_LIMITS`): `option_contracts.py` picks a CE and a PE per index (next-to-next expiry, near-ATM, liquid, affordable; `config.OPTIONS_SELECTION`), the strategies run on the option premium charts (feed keys `"2:<id>"`, see `ws_feed.feed_key`), only BUY signals are traded, in whole lots. Classifiers book into it with `book=OPTIONS`. Shown on Live P&L Options (`render_pnl_tab(..., acct=OPTIONS)`, sidebar OPTIONS section).

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

**Moving averages** (`algo_strategies.MA_STRATEGIES`: EMA 100, SMA 100, SMA 200 price crosses; EMA 50/100 cross): one generic detector, classifier, chart (`render_tv_ma_chart`) and backtest page (`pages/ma_only.py`). The averages need earlier days to warm up (a day has ~72 five-minute bars): live code passes `live_candles.candles(..., history=True)` through `trading_engine.detect_signals()` and keeps today's signals; backtests fetch `MA_HISTORY_DAYS` of 15-min bars and score the 7-day window (`backtest_ma_window`). A new MA strategy is one line in `MA_STRATEGIES` plus its entries in `STRATEGY_NAMES`, `LIVE_STRATEGY_ENABLED`, `auth._SEED_STRATEGIES`, `pages/strategies.py`, `BACKTEST_PAGES` and the backtest `_RUNNERS`.

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
