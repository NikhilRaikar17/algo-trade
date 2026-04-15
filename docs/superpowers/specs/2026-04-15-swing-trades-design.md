# Swing Trades Scanner — Design Spec

**Date:** 2026-04-15  
**Status:** Approved

---

## Overview

A new sidebar page called **Swing Trades** that scans NIFTY, BANKNIFTY, and all active top stocks for multi-day momentum signals. Each candidate is classified as BULLISH or BEARISH based on SMA crossover + RSI thresholds on 15-min candles (last 5 trading days), with suggested entry, target, and stop-loss levels.

---

## Definition of a Swing Trade Candidate

A swing trade candidate is a stock or index showing sustained directional momentum across recent sessions, identified by the alignment of a moving average crossover and RSI strength.

### BULLISH signal
- Fast SMA(9) > Slow SMA(21) on the latest candle **and** RSI(14) > 55

### BEARISH signal
- Fast SMA(9) < Slow SMA(21) on the latest candle **and** RSI(14) < 45

### Entry / Target / Stop-Loss
| Direction | Entry        | Target          | Stop-Loss       |
|-----------|-------------|-----------------|-----------------|
| BULLISH   | Last close  | Entry × 1.02    | Entry × 0.99    |
| BEARISH   | Last close  | Entry × 0.98    | Entry × 1.01    |

Thresholds reuse existing `config.py` constants (`RSI_PERIOD=14`, `SMA_FAST=9`, `SMA_SLOW=21`) plus two new constants:
- `SWING_RSI_BULL = 55`
- `SWING_RSI_BEAR = 45`

---

## Sidebar

- **Location:** "Markets" section, after "Top Stocks"
- **Entry:** `_nav_button("swing_trades", "Swing Trades", "trending_up", icon_color="icon-orange")`
- **Container:** registered in `main.py` alongside all other page containers

---

## Page Layout

**File:** `nicegui_app/pages/swing_trades.py`  
**Function:** `render_swing_trades_tab(container)` → returns async `refresh()` closure

### UI elements (top to bottom)
1. **Title:** "Swing Trades Scanner" (`text-xl font-bold`)
2. **Info banner:** strategy description in a styled box (matches existing pages)
3. **"Scan All" button:** triggers sequential scan
4. **Progress indicator:** spinner + label ("Scanning RELIANCE... 3/25") shown during scan, hidden after
5. **Results table** with columns:
   - Stock | Direction | Price | RSI | SMA Fast | SMA Slow | Entry | Target | SL
   - BULLISH rows: green highlight
   - BEARISH rows: red highlight
   - Empty state: "No swing trade candidates found"

---

## Data Flow

```
render_swing_trades_tab
  └── "Scan All" clicked
        ├── NIFTY (security_id="13", segment="IDX_I") → dhan.intraday_minute_data(interval=15)
        ├── BANKNIFTY (security_id="25", segment="IDX_I") → dhan.intraday_minute_data(interval=15)
        └── Top stocks → _fetch_any_stock_candles() [from data.py]
              └── each df → detect_swing_trade_signals(df) [new, in algo_strategies.py]
                    └── returns: {direction, price, rsi, sma_fast, sma_slow, entry, target, sl} or None
```

---

## New Code

### `algo_strategies.py` — new function
```python
def detect_swing_trade_signals(df) -> dict | None:
    """
    Returns a signal dict if the latest candle qualifies as a swing trade candidate,
    else None.
    Signal keys: direction, price, rsi, sma_fast, sma_slow, entry, target, sl
    """
```

### `config.py` — two new constants
```python
SWING_RSI_BULL = 55
SWING_RSI_BEAR = 45
```

### `nicegui_app/pages/swing_trades.py` — new page
Follows the same `render_*_tab(container)` pattern as `sma50_only.py`.

### `sidebar.py` — one new nav button
Added after the `top_stocks` button in the Markets section.

### `main.py` — container registration
`swing_trades` container created and registered in `build_ui()`.

---

## Out of Scope

- Charting / candlestick visualization (can be added later)
- Storing scan results in DB
- Auto-refresh / scheduled scanning
- Multi-timeframe confirmation
