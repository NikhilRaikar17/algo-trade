"""
Channel Breakout (Donchian) historical backtest tab page.
Fetches index 15-min candles, detects Donchian channel breakouts, backtests, shows chart + results.
"""

import asyncio
import traceback
from nicegui import ui

from data import fetch_index_15min_candles
from algo_strategies import detect_channel_breakout_signals, backtest_channel_breakout, CB_PERIOD
from tv_charts import render_tv_channel_breakout_chart


def render_channel_breakout_tab(container, index_name="NIFTY"):
    """Build the Channel Breakout historical backtester tab for given index."""
    with container:
        ui.label(f"Channel Breakout Scanner — {index_name} 15-min").classes(
            "text-xl font-bold mb-2"
        )
        with ui.element("div").classes(
            "bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-2 mb-3"
        ):
            ui.label(
                f"Strategy: Donchian Channel Breakout | "
                f"Period: {CB_PERIOD} bars | Target: 1.5% | SL: 1% | "
                "BUY above upper band, SELL below lower band | 15-min candles | 5 days"
            ).classes("text-sm text-indigo-700")
        content_container = ui.element("div").classes("w-full")
        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            ui.label(f"Loading {index_name} Channel Breakout data...").classes(
                "text-gray-500 text-center w-full"
            )

    async def refresh():
        try:
            candles = await asyncio.get_event_loop().run_in_executor(
                None, lambda: fetch_index_15min_candles(index_name)
            )
            if content_container.client._deleted:
                return
            _build_channel_breakout_content(content_container, index_name, candles)
        except Exception as e:
            if content_container.client._deleted:
                return
            content_container.clear()
            with content_container:
                ui.label(f"Error: {e}").classes("text-red-500")
            print(f"  [channel_breakout:{index_name}] error:\n{traceback.format_exc()}")

    return refresh


def _build_channel_breakout_content(container, index_name, candles):
    """Detect breakouts, backtest, render charts and tables from pre-fetched candles."""
    container.clear()
    with container:
        if candles.empty:
            ui.label(f"No {index_name} 15-min candle data available.").classes(
                "text-orange-500"
            )
            return

        signals, df_ind = detect_channel_breakout_signals(candles)
        trades = backtest_channel_breakout(signals, candles)

        # --- Chart ---
        ui.label(
            f"{index_name} — Last: {candles['close'].iloc[-1]:,.2f} | "
            f"{len(candles)} candles (15-min, 5 days) | "
            f"{len(signals)} breakout signal{'s' if len(signals) != 1 else ''}"
        ).classes("text-md font-semibold mb-2")
        render_tv_channel_breakout_chart(candles, df_ind, signals)

        # --- Summary ---
        if not trades:
            ui.label("No channel breakout signals in this period.").classes(
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
            _stat_card("Total Trades", str(len(trades)))
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
                    "Signal": t["signal"],
                    "Entry": t["entry"],
                    "Upper": t["upper"],
                    "Lower": t["lower"],
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
            {"name": "entry",      "label": "Entry",      "field": "Entry",      "sortable": True, "align": "left"},
            {"name": "upper",      "label": "Upper Band", "field": "Upper",      "sortable": True, "align": "left"},
            {"name": "lower",      "label": "Lower Band", "field": "Lower",      "sortable": True, "align": "left"},
            {"name": "target",     "label": "Target",     "field": "Target",     "sortable": True, "align": "left"},
            {"name": "sl",         "label": "SL",         "field": "SL",         "sortable": True, "align": "left"},
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
            "body-cell-signal",
            r"""
            <q-td :props="props">
                <q-badge :color="props.value.startsWith('BUY') ? 'green' : 'red'"
                         :label="props.value" />
            </q-td>
            """,
        )


def _stat_card(label, value, value_class="text-gray-900"):
    with ui.card().classes("px-4 py-3").props("flat bordered"):
        ui.label(label).classes("text-xs text-gray-500 uppercase tracking-wide")
        ui.label(value).classes(f"text-lg font-bold {value_class}")
