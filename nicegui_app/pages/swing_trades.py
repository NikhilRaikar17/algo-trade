"""
Swing Trades Scanner page.
Scans NIFTY, BANKNIFTY, and all active top stocks for bullish/bearish
momentum candidates using SMA(9/21) crossover + RSI(14) on 15-min candles.
"""

import asyncio
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
            stocks = await asyncio.get_event_loop().run_in_executor(None, get_active_top_stocks) or []
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
