# Double Top Rename + Standard Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename existing Double Top strategy to "Double Top Customized" (key `dtc`) and add a new "Double Top Standard" strategy (key `dts`) with classic textbook rules.

**Architecture:** Rename all `dt` keys/identifiers to `dtc` across the codebase, then add parallel `dts` detection/backtest functions, a new page file, new TV chart function, and wire everything into `main.py`, `sidebar.py`, `auth.py`, `pnl.py`, and `trading_engine.py`.

**Tech Stack:** Python, NiceGUI, LightweightCharts (TV charts), SQLite via SQLAlchemy

---

## Files Modified / Created

| File | Action | What changes |
|------|--------|-------------|
| `nicegui_app/algo_strategies.py` | Modify | Rename `detect_double_top_signals` → `detect_double_top_custom_signals`, `backtest_double_top` → `backtest_double_top_custom`; add `detect_double_top_standard_signals`, `backtest_double_top_standard`, `classify_double_top_standard_trades` |
| `nicegui_app/tv_charts.py` | Modify | Rename `render_tv_double_top_chart` → `render_tv_double_top_custom_chart`; add `render_tv_double_top_standard_chart` |
| `nicegui_app/pages/double_top_only.py` | Modify | Update imports to use `*_custom_*` names; rename render fn to `render_double_top_custom_tab`; update display strings to "Double Top Customized" |
| `nicegui_app/pages/double_top_standard_only.py` | Create | New page mirroring `double_top_only.py` but using standard detect/backtest/chart |
| `nicegui_app/pages/__init__.py` | Modify | Export `render_double_top_custom_tab` and `render_double_top_standard_tab` |
| `nicegui_app/main.py` | Modify | Import new render fns; add `dts_only` page container; wire both `dtc_only` and `dts_only` into build_ui |
| `nicegui_app/sidebar.py` | Modify | Rename `dt_only` nav to `dtc_only` "Double Top Custom"; add `dts_only` nav entry "Double Top Standard" |
| `nicegui_app/auth.py` | Modify | Rename `dt` seed to `dtc` "Double Top Customized"; add `dts` "Double Top Standard" seed |
| `nicegui_app/pnl.py` | Modify | Rename `dt_` prefix entry to `dtc_`; add `dts_` entry |
| `nicegui_app/trading_engine.py` | Modify | Replace `detect_double_top_signals` / `classify_double_top_trades` with `*_custom_*`; add parallel `dts` block |
| `nicegui_app/pages/algo.py` | Modify | Replace imports/calls with `*_custom_*` names |
| `nicegui_app/pages/backtest_pnl_tab.py` | Modify | Rename `_run_double_top` to `_run_double_top_custom`; add `_run_double_top_standard` |

---

## Task 1: Rename detection + backtest functions in `algo_strategies.py`

**Files:**
- Modify: `nicegui_app/algo_strategies.py`

- [ ] **Step 1: Rename `detect_double_top_signals` to `detect_double_top_custom_signals`**

In `nicegui_app/algo_strategies.py`, change the function signature at line ~408:

```python
def detect_double_top_custom_signals(candles, max_peak_diff_pct=0.0015, min_bars_between=5):
```

- [ ] **Step 2: Rename `backtest_double_top` to `backtest_double_top_custom`**

At line ~494:

```python
def backtest_double_top_custom(signals, candles):
```

- [ ] **Step 3: Rename `classify_double_top_trades` to `classify_double_top_custom_trades`**

At line ~991:

```python
def classify_double_top_custom_trades(signals, current_price, contract_name=""):
    return _classify_generic(signals, current_price, contract_name, "Double Top Customized", "dtc",
```

Note: also update the `"dt"` string inside `_classify_generic` call to `"dtc"` and the display name to `"Double Top Customized"`.

- [ ] **Step 4: Add `detect_double_top_standard_signals` after the customized version**

Append after `backtest_double_top_custom`:

```python
# ================= DOUBLE TOP STANDARD =================


def detect_double_top_standard_signals(candles, max_peak_diff_pct=0.01, min_bars_between=5):
    """
    Detect double top bearish reversal patterns — textbook rules.

    Two swing highs within 1% of each other, with a trough (neckline) between them.
    Entry confirmed when price closes below the neckline after the second peak.
    Signal: SELL | Target: neckline − height | SL: above highest peak
    No resistance void check (unlike the customized variant).
    Strictly intraday: P1 and P2 must be on the same calendar date.
    """
    all_signals = []

    candles = candles.copy()
    candles["_date"] = candles["timestamp"].dt.date
    for date, day_candles in candles.groupby("_date"):
        day_candles = day_candles.reset_index(drop=True)
        swings = find_swing_points(day_candles, order=3)
        swing_highs = [s for s in swings if s["type"] == "high"]

        used_p2_indices = set()
        for j in range(1, len(swing_highs)):
            p2 = swing_highs[j]
            for i in range(j - 1, -1, -1):
                p1 = swing_highs[i]

                if p2["index"] - p1["index"] < min_bars_between:
                    continue

                avg_price = (p1["price"] + p2["price"]) / 2
                if abs(p1["price"] - p2["price"]) / avg_price > max_peak_diff_pct:
                    continue

                # Neckline = lowest low between the two peaks
                between = day_candles.iloc[p1["index"]: p2["index"] + 1]
                neckline = float(between["low"].min())

                # Signal confirmed on first close below neckline after peak2
                resistance = float(max(p1["price"], p2["price"]))
                after_p2 = day_candles.iloc[p2["index"] + 1:]
                signal_found = False
                for _, bar in after_p2.iterrows():
                    if bar["timestamp"].time() >= _NO_NEW_TRADE_AFTER:
                        break
                    if float(bar["close"]) < neckline:
                        entry = float(neckline)        # entry AT neckline break close
                        height = resistance - neckline
                        sl = float(resistance) + 1.0   # SL one point above highest peak
                        target = float(neckline - height)  # 1× height projected down
                        all_signals.append({
                            "time": bar["timestamp"],
                            "signal": "SELL — Double Top Standard neckline break",
                            "entry": round(entry, 2),
                            "target": round(target, 2),
                            "stop_loss": round(sl, 2),
                            "peak1": round(float(p1["price"]), 2),
                            "peak1_time": p1["time"],
                            "peak2": round(float(p2["price"]), 2),
                            "peak2_time": p2["time"],
                            "neckline": round(neckline, 2),
                        })
                        signal_found = True
                        break
                if signal_found:
                    used_p2_indices.add(j)
                    break

    seen = set()
    unique = []
    for s in all_signals:
        key = str(s["time"])
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique
```

- [ ] **Step 5: Add `backtest_double_top_standard` after the detect function**

```python
def backtest_double_top_standard(signals, candles):
    """Walk through same-day candles after each double top standard signal. Force-close at 3:30 PM."""
    trades = []
    for s in signals:
        entry = s["entry"]
        target = s["target"]
        sl = s["stop_loss"]
        signal_time = s["time"]
        future = _same_day_candles(candles[candles["timestamp"] > signal_time], signal_time)
        result = {"status": "No Fill", "exit_price": None, "exit_time": None, "pnl": 0.0}
        filled = False
        last_bar = None
        for _, bar in future.iterrows():
            last_bar = bar
            if not filled:
                if float(bar["high"]) >= entry:
                    filled = True
                    if float(bar["high"]) >= sl:
                        result = {
                            "status": "SL Hit",
                            "exit_price": round(float(sl), 2),
                            "exit_time": bar["timestamp"],
                            "pnl": round(float(entry - sl), 2),
                        }
                        break
            if filled:
                if float(bar["low"]) <= target:
                    result = {
                        "status": "Target Hit",
                        "exit_price": round(float(target), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(entry - target), 2),
                    }
                    break
                if float(bar["high"]) >= sl:
                    result = {
                        "status": "SL Hit",
                        "exit_price": round(float(sl), 2),
                        "exit_time": bar["timestamp"],
                        "pnl": round(float(entry - sl), 2),
                    }
                    break
        if filled and result["status"] == "No Fill" and last_bar is not None:
            exit_px = round(float(last_bar["close"]), 2)
            result = {
                "status": "Day Close",
                "exit_price": exit_px,
                "exit_time": last_bar["timestamp"],
                "pnl": round(float(entry - exit_px), 2),
            }
        trades.append({**s, **result})
    return trades
```

- [ ] **Step 6: Add `classify_double_top_standard_trades` after backtest function**

```python
def classify_double_top_standard_trades(signals, current_price, contract_name=""):
    return _classify_generic(signals, current_price, contract_name, "Double Top Standard", "dts",
                             lambda s: s["entry"])
```

- [ ] **Step 7: Commit**

```bash
git add nicegui_app/algo_strategies.py
git commit -m "feat: rename DT functions to *_custom_*; add DT standard detect/backtest/classify"
```

---

## Task 2: Update TV chart function names

**Files:**
- Modify: `nicegui_app/tv_charts.py`

- [ ] **Step 1: Rename `render_tv_double_top_chart` to `render_tv_double_top_custom_chart`**

In `nicegui_app/tv_charts.py` at line ~481, change:

```python
def render_tv_double_top_custom_chart(candles, signals, height: int = 500) -> str:
```

Also update the internal JS function name prefix from `initDT_` — no change needed there (it uses `chart_id` which is uuid-based).

- [ ] **Step 2: Add `render_tv_double_top_standard_chart` after the customized version**

Copy the customized chart function body and add directly after it:

```python
def render_tv_double_top_standard_chart(candles, signals, height: int = 500) -> str:
    """Render a candlestick chart with double top standard pattern overlays."""
    chart_id = f"tv_{uuid.uuid4().hex[:10]}"

    ohlc = _candles_to_tv(candles)

    per_signal: list[dict] = []
    for s in signals:
        mkrs = _dedup_markers([
            {"time": _to_unix(s["peak1_time"]), "position": "aboveBar", "color": "#ef5350", "shape": "arrowDown", "text": "P1", "size": 1.0},
            {"time": _to_unix(s["peak2_time"]), "position": "aboveBar", "color": "#ef5350", "shape": "arrowDown", "text": "P2", "size": 1.0},
            {"time": _to_unix(s["time"]),       "position": "aboveBar", "color": "#b91c1c", "shape": "arrowDown", "text": "S",  "size": 1.4},
        ])
        per_signal.append({
            "markers":   mkrs,
            "neckline":  float(s["neckline"]),
            "target":    float(s["target"]),
            "stop_loss": float(s["stop_loss"]),
            "from_time": _to_unix(s["peak1_time"]) - 3600,
            "to_time":   _to_unix(s["time"]) + 7200,
        })

    ui.html(f'<div class="at-chart-wrap"><div id="{chart_id}" style="width:100%; height:{height}px;"></div></div>', sanitize=False)

    opts = dict(_BASE_OPTS)
    opts["height"] = height

    js = f"""
    (function initDTS_{chart_id}() {{
        var el = document.getElementById('{chart_id}');
        if (!el) {{ return; }}
        var opts = {json.dumps(opts)};
        opts.width = _tvElWidth(el);
        var chart = LightweightCharts.createChart(el, opts);
        window._tvChartInstances.push(chart);
        chart.applyOptions(window._tvThemeOpts(document.body.classList.contains('at-light-theme')));

        var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
        cs.setData({json.dumps(ohlc)});
        cs.setMarkers([]);

        var perSignal = {json.dumps(per_signal)};
        var _activePriceLines = [];

        window._tvShowTrade_{chart_id} = function(idx) {{
            cs.setMarkers([]);
            _activePriceLines.forEach(function(pl) {{ try {{ cs.removePriceLine(pl); }} catch(e) {{}} }});
            _activePriceLines = [];
            if (idx < 0 || idx >= perSignal.length) return;
            var s = perSignal[idx];
            cs.setMarkers(s.markers);
            _activePriceLines.push(cs.createPriceLine({{ price: s.neckline,  color: '#f59e0b', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'Neck ' + s.neckline.toFixed(0) }}));
            _activePriceLines.push(cs.createPriceLine({{ price: s.target,    color: '#26a69a', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'T ' + s.target.toFixed(0) }}));
            _activePriceLines.push(cs.createPriceLine({{ price: s.stop_loss, color: '#ef5350', lineWidth: 1, lineStyle: {_LS_DASHED}, axisLabelVisible: true, title: 'SL ' + s.stop_loss.toFixed(0) }}));
            chart.timeScale().setVisibleRange({{ from: s.from_time, to: s.to_time }});
        }};

        {_ohlc_tooltip_js("chart", "cs", "el")}
        chart.timeScale().fitContent();
        {_resize_listener("chart", "el")}
    }})();
    """
    _schedule_js(js)
    return chart_id
```

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/tv_charts.py
git commit -m "feat: rename TV chart fn to *_custom_*; add render_tv_double_top_standard_chart"
```

---

## Task 3: Update `pages/double_top_only.py` (rename to customized)

**Files:**
- Modify: `nicegui_app/pages/double_top_only.py`

- [ ] **Step 1: Update imports**

Replace the import line:

```python
from algo_strategies import detect_double_top_custom_signals, backtest_double_top_custom
from tv_charts import render_tv_double_top_custom_chart, flush_pending_js
```

- [ ] **Step 2: Rename render function and update display strings**

Change `render_double_top_tab` → `render_double_top_custom_tab`.

Change label text:
```python
ui.label("Double Top Customized Scanner").classes("text-xl font-bold mb-2")
```

Change strategy description label:
```python
ui.label(
    "Strategy: Double Top Customized bearish reversal | "
    "Entry: Neckline − 1pt | Target: Neckline − 2×Height | SL: Neckline + 70% Height | 5-min candles | 5 days"
).classes("text-sm").style("color:var(--at-down);")
```

Change loading label:
```python
ui.label(f"Loading {label} Double Top Customized data...").classes(
```

- [ ] **Step 3: Update internal function calls**

In `_build_double_top_content`, update:
```python
signals = detect_double_top_custom_signals(candles)
trades = backtest_double_top_custom(signals, candles)
```
```python
chart_id = render_tv_double_top_custom_chart(candles, signals)
```

Update the patterns label text:
```python
f"{len(signals)} double top customized pattern{'s' if len(signals) != 1 else ''}"
```

Update "no patterns" label:
```python
ui.label("No double top customized patterns detected in this period.").classes(
```

Update error print:
```python
print(f"  [double_top_custom:{label}] error:\n{traceback.format_exc()}")
```

- [ ] **Step 4: Commit**

```bash
git add nicegui_app/pages/double_top_only.py
git commit -m "feat: rename double_top page fn/labels to customized variant"
```

---

## Task 4: Create `pages/double_top_standard_only.py`

**Files:**
- Create: `nicegui_app/pages/double_top_standard_only.py`

- [ ] **Step 1: Create the file**

```python
"""
Double Top Standard historical backtest tab page.
Fetches 5-min candles for top stocks, detects standard double top patterns, backtests.
"""

import asyncio
import traceback
from nicegui import ui

from data import _fetch_any_stock_candles
from db import get_active_top_stocks
from algo_strategies import detect_double_top_standard_signals, backtest_double_top_standard
from tv_charts import render_tv_double_top_standard_chart, flush_pending_js


def _build_stock_options(stocks: list[dict]) -> dict[str, str]:
    return {
        f"EQ:{s['security_id']}:{s['name']}": s["name"]
        for s in stocks
    }


def render_double_top_standard_tab(container):
    """Build the Double Top Standard historical backtester tab. Returns an async refresh() closure."""

    selected: dict = {"security_id": None, "label": None}

    with container:
        ui.label("Double Top Standard Scanner").classes("text-xl font-bold mb-2")
        with ui.element("div").classes(
            "rounded-lg px-4 py-2 mb-3"
        ).style("background:rgba(255,77,94,0.08); border:1px solid rgba(255,77,94,0.25);"):
            ui.label(
                "Strategy: Double Top Standard bearish reversal | "
                "Entry: Neckline break close | Target: Neckline − Height | SL: Above highest peak | 5-min candles | 5 days"
            ).classes("text-sm").style("color:var(--at-down);")

        with ui.row().classes("items-center gap-3 mb-4"):
            ui.label("Stock:").classes("text-sm font-medium text-gray-700")
            select_widget = ui.select(
                options={},
                value=None,
                label="",
                on_change=lambda e: asyncio.ensure_future(
                    _load(e.value, e.value.split(":", 2)[2] if e.value else "")
                ) if e.value else None,
            ).props("outlined dense use-input input-debounce=0").classes("w-64")

        content_container = ui.element("div").classes("w-full")
        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            ui.label("Loading top stocks...").classes(
                "text-gray-500 text-center w-full"
            )

    async def _load(security_id: str, label: str):
        selected["security_id"] = security_id
        selected["label"] = label

        if content_container.client._deleted:
            return

        content_container.clear()
        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            ui.label(f"Loading {label} Double Top Standard data...").classes(
                "text-gray-500 text-center w-full"
            )

        try:
            _, sec_id, _ = security_id.split(":", 2)
            candles = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _fetch_any_stock_candles(sec_id, interval=5)
            )
            if content_container.client._deleted:
                return
            try:
                _build_double_top_standard_content(content_container, label, candles)
                await flush_pending_js()
            except RuntimeError:
                return
        except Exception as e:
            if content_container.client._deleted:
                return
            try:
                content_container.clear()
                with content_container:
                    ui.label(f"Error: {e}").classes("text-red-500")
            except RuntimeError:
                return
            print(f"  [double_top_standard:{label}] error:\n{traceback.format_exc()}")

    async def refresh():
        top_stocks = await asyncio.get_event_loop().run_in_executor(None, get_active_top_stocks)
        options = _build_stock_options(top_stocks)
        if not select_widget.client._deleted:
            select_widget.options = options
            select_widget.update()

        if selected["security_id"] not in options and options:
            first_key = next(iter(options))
            first_label = options[first_key]
            select_widget.value = first_key
            select_widget.update()
            await _load(first_key, first_label)
        elif selected["security_id"] in options:
            await _load(selected["security_id"], selected["label"])

    return refresh


def _build_double_top_standard_content(container, label, candles):
    """Detect patterns, backtest, render charts and tables from pre-fetched candles."""
    container.clear()
    with container:
        if candles.empty:
            ui.label(f"No candle data available for {label}.").classes(
                "text-orange-500"
            )
            return

        signals = detect_double_top_standard_signals(candles)
        trades = backtest_double_top_standard(signals, candles)

        ui.label(
            f"{label} — Last: {candles['close'].iloc[-1]:,.2f} | "
            f"{len(candles)} candles (5-min, 5 days) | "
            f"{len(signals)} double top standard pattern{'s' if len(signals) != 1 else ''}"
        ).classes("text-md font-semibold mb-2")
        chart_id = render_tv_double_top_standard_chart(candles, signals)

        if not trades:
            ui.label("No double top standard patterns detected in this period.").classes(
                "text-gray-500 italic mt-4"
            )
            return

        completed = [t for t in trades if t["status"] != "Open"]
        open_trades = [t for t in trades if t["status"] == "Open"]
        total_pnl = sum(t["pnl"] for t in completed)
        winners = sum(1 for t in completed if t["pnl"] > 0)
        losers = sum(1 for t in completed if t["pnl"] < 0)

        ui.separator().classes("my-4")
        with ui.row().classes("gap-6 flex-wrap items-center"):
            _stat_card("Patterns", str(len(signals)))
            _stat_card("Completed", str(len(completed)))
            _stat_card("Open", str(len(open_trades)))
            _stat_card("Winners / Losers", f"{winners}W / {losers}L")
            pnl_color = "text-green-700" if total_pnl >= 0 else "text-red-700"
            _stat_card(
                "Total P&L",
                f"{'+' if total_pnl >= 0 else ''}{total_pnl:.2f} pts",
                value_class=pnl_color,
            )

        ui.separator().classes("my-4")
        with ui.row().classes("items-center gap-3 mb-2"):
            ui.label("Trade Log").classes("text-lg font-semibold")
            ui.label("Click a row to highlight pattern on chart").classes("text-xs text-gray-400 italic")

        rows = []
        for i, t in enumerate(trades):
            time_str = (
                t["time"].strftime("%d %b %H:%M")
                if hasattr(t["time"], "strftime")
                else str(t["time"])
            )
            exit_str = ""
            if t["exit_time"] is not None:
                exit_str = (
                    t["exit_time"].strftime("%d %b %H:%M")
                    if hasattr(t["exit_time"], "strftime")
                    else str(t["exit_time"])
                )
            peak1_time_str = (
                t["peak1_time"].strftime("%d %b %H:%M")
                if hasattr(t.get("peak1_time"), "strftime")
                else str(t.get("peak1_time", "—"))
            )
            peak2_time_str = (
                t["peak2_time"].strftime("%d %b %H:%M")
                if hasattr(t.get("peak2_time"), "strftime")
                else str(t.get("peak2_time", "—"))
            )
            rows.append(
                {
                    "_idx": i,
                    "Entry Time": time_str,
                    "Signal": t["signal"],
                    "Peak1": t["peak1"],
                    "Peak1 Time": peak1_time_str,
                    "Peak2": t["peak2"],
                    "Peak2 Time": peak2_time_str,
                    "Neckline": t["neckline"],
                    "Entry": t["entry"],
                    "Target": t["target"],
                    "SL": t["stop_loss"],
                    "Exit": round(t["exit_price"], 2) if t["exit_price"] else "—",
                    "Exit Time": exit_str or "—",
                    "P&L": t["pnl"],
                    "Status": t["status"],
                }
            )

        columns = [
            {"name": "entry_time", "label": "Entry Time", "field": "Entry Time", "sortable": True, "align": "left"},
            {"name": "signal",     "label": "Signal",     "field": "Signal",     "sortable": True, "align": "left"},
            {"name": "peak1",      "label": "Peak 1",     "field": "Peak1",      "sortable": True, "align": "left"},
            {"name": "peak1_time", "label": "Peak 1 Time","field": "Peak1 Time", "sortable": True, "align": "left"},
            {"name": "peak2",      "label": "Peak 2",     "field": "Peak2",      "sortable": True, "align": "left"},
            {"name": "peak2_time", "label": "Peak 2 Time","field": "Peak2 Time", "sortable": True, "align": "left"},
            {"name": "neckline",   "label": "Neckline",   "field": "Neckline",   "sortable": True, "align": "left"},
            {"name": "entry",      "label": "Entry",      "field": "Entry",      "sortable": True, "align": "left"},
            {"name": "target",     "label": "Target",     "field": "Target",     "sortable": True, "align": "left"},
            {"name": "sl",         "label": "SL",         "field": "SL",         "sortable": True, "align": "left"},
            {"name": "exit",       "label": "Exit",       "field": "Exit",       "sortable": True, "align": "left"},
            {"name": "exit_time",  "label": "Exit Time",  "field": "Exit Time",  "sortable": True, "align": "left"},
            {"name": "pnl",        "label": "P&L",        "field": "P&L",        "sortable": True, "align": "left"},
            {"name": "status",     "label": "Status",     "field": "Status",     "sortable": True, "align": "left"},
        ]
        _cid = chart_id

        table = ui.table(
            columns=columns, rows=rows, row_key="Entry Time",
        ).classes("w-full cursor-pointer")

        def _on_row_click(e):
            idx = e.args[1].get("_idx", -1)
            ui.run_javascript(f"window._tvShowTrade_{_cid}({idx})")

        table.on("rowClick", _on_row_click)
        table.props("dense flat bordered")

        table.add_slot(
            "body-cell-pnl",
            r"""
            <q-td :props="props">
                <span :style="{
                    color: props.value > 0 ? '#15803d' : props.value < 0 ? '#b91c1c' : '',
                    fontWeight: 'bold'
                }">
                    {{ props.value > 0 ? '+' : '' }}{{ props.value }}
                </span>
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-status",
            r"""
            <q-td :props="props">
                <q-badge :color="props.value === 'Target Hit' ? 'green' : props.value === 'SL Hit' ? 'red' : props.value === 'Day Close' ? 'orange' : props.value === 'No Fill' ? 'blue-grey' : 'grey'"
                         :label="props.value" />
            </q-td>
            """,
        )


def _stat_card(label, value, value_class="text-gray-900"):
    with ui.card().classes("px-4 py-3").props("flat bordered"):
        ui.label(label).classes("text-xs text-gray-500 uppercase tracking-wide")
        ui.label(value).classes(f"text-lg font-bold {value_class}")
```

- [ ] **Step 2: Commit**

```bash
git add nicegui_app/pages/double_top_standard_only.py
git commit -m "feat: add double_top_standard_only page"
```

---

## Task 5: Update `pages/__init__.py`

**Files:**
- Modify: `nicegui_app/pages/__init__.py`

- [ ] **Step 1: Update exports**

Replace the existing double top export line:

```python
from pages.double_top_only import render_double_top_custom_tab
from pages.double_top_standard_only import render_double_top_standard_tab
```

- [ ] **Step 2: Commit**

```bash
git add nicegui_app/pages/__init__.py
git commit -m "feat: export render_double_top_custom_tab and render_double_top_standard_tab"
```

---

## Task 6: Update `main.py`

**Files:**
- Modify: `nicegui_app/main.py`

- [ ] **Step 1: Update import**

Replace:
```python
render_double_top_tab,
```
With:
```python
render_double_top_custom_tab,
render_double_top_standard_tab,
```

- [ ] **Step 2: Rename page id in `ALL_PAGE_IDS` and add new one**

Find `"dt_only"` in `ALL_PAGE_IDS` list and replace with:
```python
"dtc_only",
"dts_only",
```

- [ ] **Step 3: Update nav page list**

Find the list containing `"abcd_only", "dt_only", ...` and replace `"dt_only"` with `"dtc_only", "dts_only"`.

- [ ] **Step 4: Update `build_ui` render map**

Replace:
```python
"dt_only":       lambda: render_double_top_tab(page_containers["dt_only"]),
```
With:
```python
"dtc_only":      lambda: render_double_top_custom_tab(page_containers["dtc_only"]),
"dts_only":      lambda: render_double_top_standard_tab(page_containers["dts_only"]),
```

- [ ] **Step 5: Update `_BACKTEST_PAGES` set**

Replace `"dt_only"` with `"dtc_only", "dts_only"`:
```python
_BACKTEST_PAGES = {"abcd_only", "dtc_only", "dts_only", "db_only", "sma50", "ema10"}
```

- [ ] **Step 6: Commit**

```bash
git add nicegui_app/main.py
git commit -m "feat: wire dtc_only and dts_only page containers in main.py"
```

---

## Task 7: Update `sidebar.py`

**Files:**
- Modify: `nicegui_app/sidebar.py`

- [ ] **Step 1: Rename existing nav button and add new one**

Find:
```python
_nav_button("dt_only",   "Double Top",        "moving",             indent=True, icon_color="icon-purple")
```

Replace with:
```python
_nav_button("dtc_only",  "Double Top Custom", "moving",             indent=True, icon_color="icon-purple")
_nav_button("dts_only",  "Double Top Std",    "moving",             indent=True, icon_color="icon-purple")
```

- [ ] **Step 2: Commit**

```bash
git add nicegui_app/sidebar.py
git commit -m "feat: add DT Standard nav button in sidebar"
```

---

## Task 8: Update `auth.py`

**Files:**
- Modify: `nicegui_app/auth.py`

- [ ] **Step 1: Rename `dt` seed and add `dts`**

Replace:
```python
("dt",    "Double Top",    "Double Top",    2),
```
With:
```python
("dtc",   "Double Top Customized", "Double Top Customized", 2),
("dts",   "Double Top Standard",   "Double Top Standard",   3),
```

And bump sort orders for `db`, `ema10`, `sma50` by 1 (they follow `dt`):
```python
("db",    "Double Bottom", "Double Bottom", 4),
("ema10", "EMA 10",        "EMA 10",        5),
("sma50", "SMA 50",        "SMA 50",        6),
```

> **Note:** The seed is idempotent (checks by key), so old `dt` rows in DB won't be touched. You may need to manually rename the `dt` row in the DB or run a migration if trades have been recorded under `dt`. For a dev/paper-trading environment, deleting and re-seeding is fine.

- [ ] **Step 2: Commit**

```bash
git add nicegui_app/auth.py
git commit -m "feat: seed dtc and dts strategies; bump sort orders"
```

---

## Task 9: Update `pnl.py`

**Files:**
- Modify: `nicegui_app/pnl.py`

- [ ] **Step 1: Update prefix entry**

Find:
```python
("dt_",    "Double Top"),
```
Replace with:
```python
("dtc_",   "Double Top Customized"),
("dts_",   "Double Top Standard"),
```

- [ ] **Step 2: Update Telegram summary string if it hardcodes strategy names**

Find (line ~186):
```python
f"Strategies: ABCD | Double Top | Double Bottom | EMA10 | SMA50\n"
```
Replace with:
```python
f"Strategies: ABCD | Double Top Custom | Double Top Std | Double Bottom | EMA10 | SMA50\n"
```

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/pnl.py
git commit -m "feat: update pnl.py to recognize dtc_ and dts_ prefixes"
```

---

## Task 10: Update `trading_engine.py`

**Files:**
- Modify: `nicegui_app/trading_engine.py`

- [ ] **Step 1: Update imports**

Replace:
```python
detect_double_top_signals,
classify_double_top_trades,
```
With:
```python
detect_double_top_custom_signals,
classify_double_top_custom_trades,
detect_double_top_standard_signals,
classify_double_top_standard_trades,
```

- [ ] **Step 2: Update existing `dt` dispatch block**

Find the `# Double Top` block (~line 43):
```python
    # Double Top
    ...
        signals = detect_double_top_signals(candles)
        active, completed = classify_double_top_trades(signals, current_price, contract_name)
```
Replace with:
```python
    # Double Top Customized
    if "dtc" in active_strategy_keys:
        signals = detect_double_top_custom_signals(candles)
        active, completed = classify_double_top_custom_trades(signals, current_price, contract_name)
        ...

    # Double Top Standard
    if "dts" in active_strategy_keys:
        signals = detect_double_top_standard_signals(candles)
        active, completed = classify_double_top_standard_trades(signals, current_price, contract_name)
        ...
```

> Keep the existing `active`/`completed` handling pattern identical to what the `dtc` block does — just duplicated for `dts`.

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/trading_engine.py
git commit -m "feat: wire dtc and dts in trading_engine dispatch"
```

---

## Task 11: Update `pages/algo.py`

**Files:**
- Modify: `nicegui_app/pages/algo.py`

- [ ] **Step 1: Update imports**

Replace:
```python
detect_double_top_signals,
classify_double_top_trades,
```
```python
render_tv_double_top_chart,
```
With:
```python
detect_double_top_custom_signals,
classify_double_top_custom_trades,
```
```python
render_tv_double_top_custom_chart,
```

- [ ] **Step 2: Update all call sites**

Replace every call to `detect_double_top_signals` with `detect_double_top_custom_signals`, `classify_double_top_trades` with `classify_double_top_custom_trades`, and `render_tv_double_top_chart` with `render_tv_double_top_custom_chart`.

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/pages/algo.py
git commit -m "feat: update algo.py to use dtc function names"
```

---

## Task 12: Update `pages/backtest_pnl_tab.py`

**Files:**
- Modify: `nicegui_app/pages/backtest_pnl_tab.py`

- [ ] **Step 1: Update imports**

Replace:
```python
detect_double_top_signals, backtest_double_top,
```
With:
```python
detect_double_top_custom_signals, backtest_double_top_custom,
detect_double_top_standard_signals, backtest_double_top_standard,
```

- [ ] **Step 2: Rename existing runner and add standard runner**

Replace:
```python
("Double Top",       _run_double_top),
```
With:
```python
("Double Top Customized", _run_double_top_custom),
("Double Top Standard",   _run_double_top_standard),
```

Replace:
```python
def _run_double_top(candles):
    signals = detect_double_top_signals(candles)
    return backtest_double_top(signals, candles)
```
With:
```python
def _run_double_top_custom(candles):
    signals = detect_double_top_custom_signals(candles)
    return backtest_double_top_custom(signals, candles)


def _run_double_top_standard(candles):
    signals = detect_double_top_standard_signals(candles)
    return backtest_double_top_standard(signals, candles)
```

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/pages/backtest_pnl_tab.py
git commit -m "feat: add DT Standard runner in backtest_pnl_tab"
```

---

## Task 13: Smoke test

- [ ] **Step 1: Start app**

```bash
cd nicegui_app
uv run python main.py
```

Expected: app starts without import errors at `http://0.0.0.0:8501`

- [ ] **Step 2: Verify sidebar shows both entries**

Navigate to sidebar — confirm "Double Top Custom" and "Double Top Std" nav buttons appear.

- [ ] **Step 3: Verify both pages load**

Click "Double Top Custom" — scanner loads, chart renders.
Click "Double Top Std" — scanner loads, chart renders.

- [ ] **Step 4: Confirm no `dt` key references remain (except DB migration note)**

```bash
grep -rn '"dt"' nicegui_app/ --include="*.py"
```

Expected: no hits in Python files (only possibly in `.json` or migration notes).

- [ ] **Step 5: Commit final**

```bash
git add -A
git commit -m "chore: smoke test passed — DT Custom and DT Standard live"
```
