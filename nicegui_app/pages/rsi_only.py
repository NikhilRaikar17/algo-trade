"""
RSI-only algo trading tab page.
Fetches index daily candles, computes RSI, backtests signals, shows chart + results.
"""

import traceback
import pandas as pd
from nicegui import ui

from data import fetch_index_15min_candles
from algo_strategies import (
    compute_rsi,
    detect_rsi_only_signals,
    backtest_rsi_only,
)
from charts import build_candlestick_with_rsi_only


def render_rsi_only_tab(container, index_name="NIFTY"):
    """Build the RSI-only backtester tab for given index."""
    with container:
        ui.label(f"RSI-Only Scanner — {index_name} Daily").classes(
            "text-xl font-bold mb-2"
        )
        with ui.element("div").classes(
            "bg-purple-50 border border-purple-200 rounded-lg px-4 py-2 mb-3"
        ):
            ui.label(
                "Strategy: Trade on RSI overbought/oversold crossings | "
                "Target: 1.5% | SL: 1% | RSI Period: 14 | 15-min candles | 5 days"
            ).classes("text-sm text-purple-700")
        content_container = ui.element("div").classes("w-full")
        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            ui.label(f"Loading {index_name} RSI data...").classes(
                "text-gray-500 text-center w-full"
            )

    async def refresh():
        try:
            _build_rsi_only_content(content_container, index_name)
        except Exception as e:
            content_container.clear()
            with content_container:
                ui.label(f"Error: {e}").classes("text-red-500")
            print(f"  [rsi_only:{index_name}] error:\n{traceback.format_exc()}")

    return refresh


def _build_rsi_only_content(container, index_name="NIFTY"):
    """Fetch data, run backtest, render charts and tables."""
    candles = fetch_index_15min_candles(index_name)

    container.clear()
    with container:
        if candles.empty:
            ui.label(f"No {index_name} daily candle data available.").classes(
                "text-orange-500"
            )
            return

        # Detect signals and backtest
        signals, df_ind = detect_rsi_only_signals(candles)
        trades = backtest_rsi_only(signals, candles)

        # --- Charts ---
        fig, fig_rsi = build_candlestick_with_rsi_only(candles, df_ind, signals)
        ui.label(
            f"{index_name} — Last: {candles['close'].iloc[-1]:,.2f} | "
            f"{len(candles)} candles (15-min, 5 days)"
        ).classes("text-md font-semibold mb-2")
        ui.plotly(fig).classes("w-full")
        if not df_ind.empty:
            ui.plotly(fig_rsi).classes("w-full")

        # --- Summary ---
        if not trades:
            ui.label("No RSI signals in this period.").classes(
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
            _stat_card(
                "Winners / Losers",
                f"{winners}W / {losers}L",
            )
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
                t["time"].strftime("%d %b %Y")
                if hasattr(t["time"], "strftime")
                else str(t["time"])
            )
            exit_str = ""
            if t["exit_time"] is not None:
                exit_str = (
                    t["exit_time"].strftime("%d %b %Y")
                    if hasattr(t["exit_time"], "strftime")
                    else str(t["exit_time"])
                )
            rows.append(
                {
                    "Date": time_str,
                    "Signal": t["signal"],
                    "Entry": t["entry"],
                    "Target": t["target"],
                    "SL": t["stop_loss"],
                    "RSI": t["rsi"],
                    "Exit": round(t["exit_price"], 2) if t["exit_price"] else "—",
                    "Exit Date": exit_str or "—",
                    "P&L": t["pnl"],
                    "Status": t["status"],
                }
            )

        columns = [
            {"name": k, "label": k, "field": k, "sortable": True, "align": "left"}
            for k in rows[0].keys()
        ]
        table = ui.table(
            columns=columns, rows=rows, row_key="Date"
        ).classes("w-full")
        table.props("dense flat bordered")

        # Color P&L cells
        table.add_slot(
            "body-cell-P&L",
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
            "body-cell-Status",
            r"""
            <q-td :props="props">
                <q-badge :color="props.value === 'Target Hit' ? 'green' : props.value === 'SL Hit' ? 'red' : 'grey'"
                         :label="props.value" />
            </q-td>
            """,
        )


def _stat_card(label, value, value_class="text-gray-900"):
    """Small stat card for the summary row."""
    with ui.card().classes("px-4 py-3").props("flat bordered"):
        ui.label(label).classes("text-xs text-gray-500 uppercase tracking-wide")
        ui.label(value).classes(f"text-lg font-bold {value_class}")
