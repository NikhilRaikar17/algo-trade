# Swing Trades Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Swing Trades" page under the Markets section that scans NIFTY, BANKNIFTY, and top stocks for bullish/bearish momentum candidates using SMA crossover + RSI on 15-min candles, showing entry/target/stop-loss for each.

**Architecture:** A new `detect_swing_trade_signals(df)` function in `algo_strategies.py` applies the signal logic; a new `nicegui_app/pages/swing_trades.py` page renders the scanner UI following the same `render_*_tab(container)` pattern as `sma50_only.py`; `main.py`, `pages/__init__.py`, and `sidebar.py` are wired up to integrate the page.

**Tech Stack:** Python, NiceGUI, talib (RSI), numpy (SMA), dhanhq REST API via existing `_fetch_any_stock_candles` and `dhan.intraday_minute_data`.

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Modify | `nicegui_app/config.py` | Add `SWING_RSI_BULL = 55` and `SWING_RSI_BEAR = 45` constants |
| Modify | `nicegui_app/algo_strategies.py` | Add `detect_swing_trade_signals(df)` function |
| Create | `nicegui_app/pages/swing_trades.py` | New scanner page |
| Modify | `nicegui_app/pages/__init__.py` | Export `render_swing_trades_tab` |
| Modify | `nicegui_app/main.py` | Add `swing_trades` to `ALL_PAGE_IDS`, import and register page, add to `build_ui()` |
| Modify | `nicegui_app/sidebar.py` | Add nav button after `top_stocks` in Markets section |

---

## Task 1: Add SWING_RSI constants to config.py

**Files:**
- Modify: `nicegui_app/config.py` (after line 151, after `RSI_OVERBOUGHT = 70`)

- [ ] **Step 1: Open `nicegui_app/config.py` and add two constants after `RSI_OVERBOUGHT`**

Current code around line 150:
```python
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
```

Replace with:
```python
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# Swing trade momentum thresholds (SMA crossover + RSI filter)
SWING_RSI_BULL = 55   # RSI must be above this for a bullish swing candidate
SWING_RSI_BEAR = 45   # RSI must be below this for a bearish swing candidate
```

- [ ] **Step 2: Verify the file parses without error**

Run:
```bash
cd nicegui_app && uv run python -c "from config import SWING_RSI_BULL, SWING_RSI_BEAR; print(SWING_RSI_BULL, SWING_RSI_BEAR)"
```
Expected output: `55 45`

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/config.py
git commit -m "feat: add SWING_RSI_BULL and SWING_RSI_BEAR constants to config"
```

---

## Task 2: Add `detect_swing_trade_signals` to algo_strategies.py

**Files:**
- Modify: `nicegui_app/algo_strategies.py` (append at end of file)

- [ ] **Step 1: Append the new function to `nicegui_app/algo_strategies.py`**

Add at the very end of the file:
```python

# ================= SWING TRADE SIGNAL DETECTION =================

def detect_swing_trade_signals(df) -> dict | None:
    """
    Detect whether a stock/index qualifies as a swing trade candidate on its
    most recent 15-min candle data.

    BULLISH: SMA(9) > SMA(21) AND RSI(14) > SWING_RSI_BULL (55)
    BEARISH: SMA(9) < SMA(21) AND RSI(14) < SWING_RSI_BEAR (45)

    Returns a dict with signal details, or None if no signal.
    Keys: direction, price, rsi, sma_fast, sma_slow, entry, target, sl
    """
    from config import RSI_PERIOD, SMA_FAST, SMA_SLOW, SWING_RSI_BULL, SWING_RSI_BEAR

    if df is None or len(df) < max(RSI_PERIOD, SMA_SLOW) + 1:
        return None

    closes = df["close"].values.astype(float)

    rsi_arr = talib.RSI(closes, timeperiod=RSI_PERIOD)
    sma_fast_arr = talib.SMA(closes, timeperiod=SMA_FAST)
    sma_slow_arr = talib.SMA(closes, timeperiod=SMA_SLOW)

    rsi = float(rsi_arr[-1])
    sma_fast = float(sma_fast_arr[-1])
    sma_slow = float(sma_slow_arr[-1])
    price = float(closes[-1])

    if np.isnan(rsi) or np.isnan(sma_fast) or np.isnan(sma_slow):
        return None

    if sma_fast > sma_slow and rsi > SWING_RSI_BULL:
        direction = "BULLISH"
        entry = price
        target = round(entry * 1.02, 2)
        sl = round(entry * 0.99, 2)
    elif sma_fast < sma_slow and rsi < SWING_RSI_BEAR:
        direction = "BEARISH"
        entry = price
        target = round(entry * 0.98, 2)
        sl = round(entry * 1.01, 2)
    else:
        return None

    return {
        "direction": direction,
        "price": round(price, 2),
        "rsi": round(rsi, 1),
        "sma_fast": round(sma_fast, 2),
        "sma_slow": round(sma_slow, 2),
        "entry": round(entry, 2),
        "target": target,
        "sl": sl,
    }
```

- [ ] **Step 2: Verify the function imports and runs without error**

Run:
```bash
cd nicegui_app && uv run python -c "from algo_strategies import detect_swing_trade_signals; print('OK')"
```
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/algo_strategies.py
git commit -m "feat: add detect_swing_trade_signals to algo_strategies"
```

---

## Task 3: Create swing_trades.py page

**Files:**
- Create: `nicegui_app/pages/swing_trades.py`

- [ ] **Step 1: Create `nicegui_app/pages/swing_trades.py` with this content**

```python
"""
Swing Trades Scanner page.
Scans NIFTY, BANKNIFTY, and all active top stocks for bullish/bearish
momentum candidates using SMA(9/21) crossover + RSI(14) on 15-min candles.
"""

import asyncio
import traceback
from nicegui import ui

from config import dhan, SWING_RSI_BULL, SWING_RSI_BEAR
from data import _fetch_any_stock_candles
from db import get_active_top_stocks
from algo_strategies import detect_swing_trade_signals


# Indices to scan — (display_name, security_id, segment)
_INDICES = [
    ("NIFTY",     "13", "IDX_I"),
    ("BANKNIFTY", "25", "IDX_I"),
]


def _fetch_index_candles(security_id: str, segment: str):
    """Fetch 15-min candles for an index via Dhan intraday API."""
    import pandas as pd
    from config import now_ist
    today     = now_ist().strftime("%Y-%m-%d")
    from_date = (pd.Timestamp(now_ist().date()) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    r = dhan.intraday_minute_data(
        security_id=security_id,
        exchange_segment=segment,
        instrument_type="INDEX",
        interval=15,
        from_date=from_date,
        to_date=today,
    )
    if not isinstance(r, dict) or r.get("status") != "success":
        return None
    data = r.get("data", {})
    timestamps = data.get("timestamp", [])
    if not timestamps:
        return None
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(timestamps, unit="s", utc=True)
                       .tz_convert("Asia/Kolkata"),
        "open":   data.get("open",   []),
        "high":   data.get("high",   []),
        "low":    data.get("low",    []),
        "close":  data.get("close",  []),
        "volume": data.get("volume", []),
    })
    return df


def render_swing_trades_tab(container):
    """Build the Swing Trades Scanner page. Returns an async refresh() closure."""

    with container:
        ui.label("Swing Trades Scanner").classes("text-xl font-bold mb-2")
        with ui.element("div").classes(
            "bg-orange-50 border border-orange-200 rounded-lg px-4 py-2 mb-3"
        ):
            ui.label(
                f"Strategy: SMA(9) × SMA(21) crossover + RSI(14) filter | "
                f"Bullish: RSI > {SWING_RSI_BULL} | Bearish: RSI < {SWING_RSI_BEAR} | "
                f"Target: 2% | SL: 1% | 15-min candles | 5 days"
            ).classes("text-sm text-orange-700")

        with ui.row().classes("items-center gap-3 mb-4"):
            scan_btn = ui.button(
                "Scan All",
                icon="search",
                on_click=lambda: asyncio.ensure_future(_run_scan()),
            ).props("no-caps color=orange").classes("font-semibold")

        progress_row = ui.row().classes("items-center gap-3 mb-2")
        with progress_row:
            progress_spinner = ui.spinner("dots", size="sm")
            progress_label = ui.label("").classes("text-sm text-gray-500")
        progress_row.set_visibility(False)

        results_container = ui.element("div").classes("w-full")
        with results_container:
            ui.label("Click 'Scan All' to find swing trade candidates.").classes(
                "text-gray-400 text-sm"
            )

    async def _run_scan():
        scan_btn.disable()
        progress_row.set_visibility(True)
        results_container.clear()

        candidates = []
        stocks = []
        try:
            stocks = get_active_top_stocks() or []
        except Exception:
            pass

        total = len(_INDICES) + len(stocks)
        count = 0

        # Scan indices
        for display_name, sec_id, seg in _INDICES:
            count += 1
            progress_label.set_text(f"Scanning {display_name}... {count}/{total}")
            await asyncio.sleep(0)  # yield to event loop so UI updates
            try:
                df = await asyncio.get_event_loop().run_in_executor(
                    None, lambda s=sec_id, sg=seg: _fetch_index_candles(s, sg)
                )
                signal = detect_swing_trade_signals(df)
                if signal:
                    candidates.append({"name": display_name, **signal})
            except Exception as e:
                print(f"  [swing scan] {display_name} error: {e}")

        # Scan stocks
        for stock in stocks:
            count += 1
            name = stock.get("name", stock.get("security_id", "?"))
            sec_id = stock.get("security_id", "")
            progress_label.set_text(f"Scanning {name}... {count}/{total}")
            await asyncio.sleep(0)
            try:
                df = await asyncio.get_event_loop().run_in_executor(
                    None, lambda s=sec_id: _fetch_any_stock_candles(s, interval=15)
                )
                signal = detect_swing_trade_signals(df)
                if signal:
                    candidates.append({"name": name, **signal})
            except Exception as e:
                print(f"  [swing scan] {name} error: {e}")

        progress_row.set_visibility(False)
        scan_btn.enable()

        with results_container:
            if not candidates:
                ui.label("No swing trade candidates found.").classes(
                    "text-gray-400 text-sm mt-4"
                )
                return

            ui.label(f"{len(candidates)} candidate(s) found").classes(
                "text-sm font-semibold text-gray-600 mb-2"
            )

            columns = [
                {"name": "name",      "label": "Stock / Index", "field": "name",      "align": "left",   "sortable": True},
                {"name": "direction", "label": "Direction",     "field": "direction", "align": "center", "sortable": True},
                {"name": "price",     "label": "Price",         "field": "price",     "align": "right",  "sortable": True},
                {"name": "rsi",       "label": "RSI(14)",       "field": "rsi",       "align": "right",  "sortable": True},
                {"name": "sma_fast",  "label": "SMA(9)",        "field": "sma_fast",  "align": "right",  "sortable": True},
                {"name": "sma_slow",  "label": "SMA(21)",       "field": "sma_slow",  "align": "right",  "sortable": True},
                {"name": "entry",     "label": "Entry",         "field": "entry",     "align": "right"},
                {"name": "target",    "label": "Target",        "field": "target",    "align": "right"},
                {"name": "sl",        "label": "Stop-Loss",     "field": "sl",        "align": "right"},
            ]
            rows = [{"id": i, **c} for i, c in enumerate(candidates)]

            tbl = ui.table(columns=columns, rows=rows, row_key="id").classes("w-full")
            tbl.add_slot("body-cell-direction", """
                <q-td :props="props">
                    <q-badge
                        :color="props.value === 'BULLISH' ? 'green' : 'red'"
                        :label="props.value"
                        class="text-xs font-bold"
                    />
                </q-td>
            """)

    async def refresh():
        pass  # scanner is on-demand; no periodic refresh needed

    return refresh
```

- [ ] **Step 2: Verify the file parses without syntax error**

Run:
```bash
cd nicegui_app && uv run python -c "from pages.swing_trades import render_swing_trades_tab; print('OK')"
```
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/pages/swing_trades.py
git commit -m "feat: add swing_trades scanner page"
```

---

## Task 4: Export from pages/__init__.py

**Files:**
- Modify: `nicegui_app/pages/__init__.py`

- [ ] **Step 1: Add the import to `nicegui_app/pages/__init__.py`**

Append this line at the end of the file:
```python
from pages.swing_trades import render_swing_trades_tab
```

- [ ] **Step 2: Verify the import works**

Run:
```bash
cd nicegui_app && uv run python -c "from pages import render_swing_trades_tab; print('OK')"
```
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/pages/__init__.py
git commit -m "feat: export render_swing_trades_tab from pages __init__"
```

---

## Task 5: Register page in main.py

**Files:**
- Modify: `nicegui_app/main.py`

- [ ] **Step 1: Add `"swing_trades"` to `ALL_PAGE_IDS` in `main.py`**

Find:
```python
ALL_PAGE_IDS = [
    "dashboard",
    "markets",
    "market_news",
    "top_stocks",
```

Replace with:
```python
ALL_PAGE_IDS = [
    "dashboard",
    "markets",
    "market_news",
    "top_stocks",
    "swing_trades",
```

- [ ] **Step 2: Add the import for `render_swing_trades_tab` in `main.py`**

Find the existing import block:
```python
from pages import (
    render_dashboard,
    render_markets_tab,
    render_index_tab,
    render_algo_tab,
    render_abcd_only_tab,
    render_double_top_tab,
    render_double_bottom_tab,
    render_sma50_tab,
    render_ema10_tab,
    render_pnl_tab,
    render_backtest_pnl_tab,
    render_market_closed,
    render_market_news_tab,
    render_top_stocks_tab,
)
```

Replace with:
```python
from pages import (
    render_dashboard,
    render_markets_tab,
    render_index_tab,
    render_algo_tab,
    render_abcd_only_tab,
    render_double_top_tab,
    render_double_bottom_tab,
    render_sma50_tab,
    render_ema10_tab,
    render_pnl_tab,
    render_backtest_pnl_tab,
    render_market_closed,
    render_market_news_tab,
    render_top_stocks_tab,
    render_swing_trades_tab,
)
```

- [ ] **Step 3: Register the page in `build_ui()` in `main.py`**

Find:
```python
        refresh_fns["top_stocks"]   = render_top_stocks_tab(page_containers["top_stocks"])
```

Add the following line immediately after it:
```python
        refresh_fns["swing_trades"] = render_swing_trades_tab(page_containers["swing_trades"])
```

- [ ] **Step 4: Verify main.py parses without error**

Run:
```bash
cd nicegui_app && uv run python -c "import main; print('OK')"
```
Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add nicegui_app/main.py
git commit -m "feat: register swing_trades page in main.py"
```

---

## Task 6: Add sidebar nav button

**Files:**
- Modify: `nicegui_app/sidebar.py`

- [ ] **Step 1: Add the nav button in `build_sidebar()` in `sidebar.py`**

Find:
```python
        _nav_button("top_stocks",   "Top Stocks",   "rocket_launch", icon_color="icon-amber")
```

Replace with:
```python
        _nav_button("top_stocks",   "Top Stocks",   "rocket_launch", icon_color="icon-amber")
        _nav_button("swing_trades", "Swing Trades", "trending_up",   icon_color="icon-orange")
```

- [ ] **Step 2: Verify sidebar.py parses without error**

Run:
```bash
cd nicegui_app && uv run python -c "from sidebar import build_sidebar; print('OK')"
```
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/sidebar.py
git commit -m "feat: add Swing Trades nav button to sidebar Markets section"
```

---

## Task 7: Manual smoke test

- [ ] **Step 1: Start the app**

Run:
```bash
cd nicegui_app && uv run python main.py
```

- [ ] **Step 2: Open browser at `http://0.0.0.0:8501`**

- [ ] **Step 3: Verify "Swing Trades" appears in the sidebar under the Markets section, between "Top Stocks" and the separator**

- [ ] **Step 4: Click "Swing Trades" — the page should load with the orange info banner and a "Scan All" button**

- [ ] **Step 5: Click "Scan All" — verify progress indicator appears ("Scanning NIFTY... 1/N"), then disappears when complete**

- [ ] **Step 6: Verify results table shows columns: Stock/Index | Direction | Price | RSI(14) | SMA(9) | SMA(21) | Entry | Target | Stop-Loss**

- [ ] **Step 7: Verify BULLISH rows show a green badge, BEARISH rows show a red badge**

- [ ] **Step 8: If no candidates found, verify the "No swing trade candidates found." empty state message appears**
