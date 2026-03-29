"""
ABCD Harmonic historical backtest tab page.
Fetches index 15-min candles, detects ABCD patterns, backtests, shows chart + results.
"""

import traceback
from nicegui import ui

from data import fetch_index_15min_candles
from algo_strategies import find_swing_points, detect_abcd_patterns, backtest_abcd
from charts import build_candlestick_with_abcd_hist


def render_abcd_only_tab(container, index_name="NIFTY"):
    """Build the ABCD historical backtester tab for given index."""
    with container:
        ui.label(f"ABCD Harmonic Scanner — {index_name} 15-min").classes(
            "text-xl font-bold mb-2"
        )
        with ui.element("div").classes(
            "bg-blue-50 border border-blue-200 rounded-lg px-4 py-2 mb-3"
        ):
            ui.label(
                "Strategy: ABCD harmonic pattern detection | "
                "Target: D + AB | SL: Point C | 15-min candles | 5 days"
            ).classes("text-sm text-blue-700")
        content_container = ui.element("div").classes("w-full")
        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            ui.label(f"Loading {index_name} ABCD data...").classes(
                "text-gray-500 text-center w-full"
            )

    async def refresh():
        try:
            _build_abcd_content(content_container, index_name)
        except Exception as e:
            content_container.clear()
            with content_container:
                ui.label(f"Error: {e}").classes("text-red-500")
            print(f"  [abcd_hist:{index_name}] error:\n{traceback.format_exc()}")

    return refresh


def _build_abcd_content(container, index_name="NIFTY"):
    """Fetch data, detect patterns, backtest, render charts and tables."""
    candles = fetch_index_15min_candles(index_name)

    container.clear()
    with container:
        if candles.empty:
            ui.label(f"No {index_name} 15-min candle data available.").classes(
                "text-orange-500"
            )
            return

        # Detect swing points and ABCD patterns
        swings = find_swing_points(candles, order=2)
        patterns = detect_abcd_patterns(swings)
        trades = backtest_abcd(patterns, candles)

        # --- Chart ---
        fig = build_candlestick_with_abcd_hist(candles, swings, patterns)
        ui.label(
            f"{index_name} — Last: {candles['close'].iloc[-1]:,.2f} | "
            f"{len(candles)} candles (15-min, 5 days) | "
            f"{len(swings)} swings | {len(patterns)} patterns"
        ).classes("text-md font-semibold mb-2")
        ui.plotly(fig).classes("w-full")

        # --- Summary ---
        if not trades:
            ui.label("No ABCD patterns detected in this period.").classes(
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
            _stat_card("Patterns", str(len(patterns)))
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
        ui.label("Trade Log").classes("text-lg font-semibold mb-2")

        rows = []
        for t in trades:
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
            rows.append(
                {
                    "Entry Time": time_str,
                    "Type": t["type"],
                    "Signal": t["signal"],
                    "Entry (D)": t["entry"],
                    "Target": t["target"],
                    "SL (C)": t["stop_loss"],
                    "BC Ret.": t["BC_retrace"],
                    "CD/AB": t["CD_AB_ratio"],
                    "Exit": round(t["exit_price"], 2) if t["exit_price"] else "—",
                    "Exit Time": exit_str or "—",
                    "P&L": t["pnl"],
                    "Status": t["status"],
                }
            )

        columns = [
            {"name": "entry_time", "label": "Entry Time", "field": "Entry Time", "sortable": True, "align": "left"},
            {"name": "type",       "label": "Type",       "field": "Type",       "sortable": True, "align": "left"},
            {"name": "signal",     "label": "Signal",     "field": "Signal",     "sortable": True, "align": "left"},
            {"name": "entry_d",    "label": "Entry (D)",  "field": "Entry (D)",  "sortable": True, "align": "left"},
            {"name": "target",     "label": "Target",     "field": "Target",     "sortable": True, "align": "left"},
            {"name": "sl_c",       "label": "SL (C)",     "field": "SL (C)",     "sortable": True, "align": "left"},
            {"name": "bc_ret",     "label": "BC Ret.",    "field": "BC Ret.",    "sortable": True, "align": "left"},
            {"name": "cd_ab",      "label": "CD/AB",      "field": "CD/AB",      "sortable": True, "align": "left"},
            {"name": "exit",       "label": "Exit",       "field": "Exit",       "sortable": True, "align": "left"},
            {"name": "exit_time",  "label": "Exit Time",  "field": "Exit Time",  "sortable": True, "align": "left"},
            {"name": "pnl",        "label": "P&L",        "field": "P&L",        "sortable": True, "align": "left"},
            {"name": "status",     "label": "Status",     "field": "Status",     "sortable": True, "align": "left"},
        ]
        table = ui.table(
            columns=columns, rows=rows, row_key="Entry Time"
        ).classes("w-full")
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
        table.add_slot(
            "body-cell-type",
            r"""
            <q-td :props="props">
                <q-badge :color="props.value === 'Bullish' ? 'orange' : 'purple'"
                         :label="props.value" />
            </q-td>
            """,
        )


def _stat_card(label, value, value_class="text-gray-900"):
    with ui.card().classes("px-4 py-3").props("flat bordered"):
        ui.label(label).classes("text-xs text-gray-500 uppercase tracking-wide")
        ui.label(value).classes(f"text-lg font-bold {value_class}")
