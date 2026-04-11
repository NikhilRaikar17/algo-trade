"""
Double Top historical backtest tab page.
Fetches 5-min candles for top stocks, detects double top patterns, backtests.
"""

import asyncio
import traceback
from nicegui import ui

from data import _fetch_any_stock_candles
from db import get_active_top_stocks
from algo_strategies import detect_double_top_signals, backtest_double_top
from tv_charts import render_tv_double_top_chart, flush_pending_js


def _build_stock_options(stocks: list[dict]) -> dict[str, str]:
    return {
        f"EQ:{s['security_id']}:{s['name']}": s["name"]
        for s in stocks
    }


def render_double_top_tab(container):
    """Build the Double Top historical backtester tab. Returns an async refresh() closure."""

    selected: dict = {"security_id": None, "label": None}

    with container:
        ui.label("Double Top Scanner").classes("text-xl font-bold mb-2")
        with ui.element("div").classes(
            "bg-red-50 border border-red-200 rounded-lg px-4 py-2 mb-3"
        ):
            ui.label(
                "Strategy: Double Top bearish reversal | "
                "Entry: Neckline break close | Target: Neckline − Height | SL: Above 2nd Peak | 5-min candles | 5 days"
            ).classes("text-sm text-red-700")

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
            ui.label(f"Loading {label} Double Top data...").classes(
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
                _build_double_top_content(content_container, label, candles)
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
            print(f"  [double_top:{label}] error:\n{traceback.format_exc()}")

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


def _build_double_top_content(container, label, candles):
    """Detect patterns, backtest, render charts and tables from pre-fetched candles."""
    container.clear()
    with container:
        if candles.empty:
            ui.label(f"No candle data available for {label}.").classes(
                "text-orange-500"
            )
            return

        signals = detect_double_top_signals(candles)
        trades = backtest_double_top(signals, candles)

        # --- Chart ---
        ui.label(
            f"{label} — Last: {candles['close'].iloc[-1]:,.2f} | "
            f"{len(candles)} candles (5-min, 5 days) | "
            f"{len(signals)} double top pattern{'s' if len(signals) != 1 else ''}"
        ).classes("text-md font-semibold mb-2")
        chart_id = render_tv_double_top_chart(candles, signals)

        # --- Summary ---
        if not trades:
            ui.label("No double top patterns detected in this period.").classes(
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

        # --- Trade Table ---
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
            {"name": "peak1",       "label": "Peak 1",      "field": "Peak1",      "sortable": True, "align": "left"},
            {"name": "peak1_time", "label": "Peak 1 Time", "field": "Peak1 Time", "sortable": True, "align": "left"},
            {"name": "peak2",      "label": "Peak 2",      "field": "Peak2",      "sortable": True, "align": "left"},
            {"name": "peak2_time", "label": "Peak 2 Time", "field": "Peak2 Time", "sortable": True, "align": "left"},
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
                <q-badge :color="props.value === 'Target Hit' ? 'green' : props.value === 'SL Hit' ? 'red' : props.value === 'Day Close' ? 'orange' : 'grey'"
                         :label="props.value" />
            </q-td>
            """,
        )


def _stat_card(label, value, value_class="text-gray-900"):
    with ui.card().classes("px-4 py-3").props("flat bordered"):
        ui.label(label).classes("text-xs text-gray-500 uppercase tracking-wide")
        ui.label(value).classes(f"text-lg font-bold {value_class}")
