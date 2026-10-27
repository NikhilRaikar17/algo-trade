"""
Moving-average strategy tabs (EMA 100, SMA 100, SMA 200, EMA 50/100 cross — algo_strategies.MA_STRATEGIES).
Fetches three weeks of 15-min candles so the long averages have warmed up, and backtests the signals
of the last 7 days (the window the other strategies use).
"""

import asyncio
import traceback
from nicegui import ui

import pandas as pd

from config import now_ist
from data import fetch_stock_candles_history
from db import get_active_top_stocks
from algo_strategies import BACKTEST_WINDOW_DAYS, MA_HISTORY_DAYS, backtest_ma_window, ma_lines, ma_warmup
from backtest_metrics import DEFAULT_SIZING, inr, net_rupees, rupees_text
from tv_charts import render_tv_ma_chart, flush_pending_js


def _build_stock_options(stocks: list[dict]) -> dict[str, str]:
    return {
        f"EQ:{s['security_id']}:{s['name']}": s["name"]
        for s in stocks
    }


def render_ma_tab(container, key):
    """Build the scanner tab of moving-average strategy `key`. Returns an async refresh() closure."""
    lines = ma_lines(key)
    title = " / ".join(lbl for _, lbl in lines) + (" Crossover" if len(lines) > 1 else "")
    rule = (f"BUY when {lines[0][1]} crosses above {lines[1][1]} | SELL when it crosses below"
            if len(lines) > 1 else
            f"BUY when price crosses above {lines[0][1]} | SELL when price crosses below {lines[0][1]}")

    selected: dict = {"security_id": None, "label": None}

    with container:
        ui.label(f"{title} Scanner").classes("text-xl font-bold mb-2")
        with ui.element("div").classes(
            "rounded-lg px-4 py-2 mb-3"
        ).style("background:rgba(255,176,32,0.08); border:1px solid rgba(255,176,32,0.25);"):
            ui.label(
                f"Strategy: {rule} | Target: 2% | SL: 1% | 15-min candles | last {BACKTEST_WINDOW_DAYS} days "
                f"(averages warmed up on {MA_HISTORY_DAYS} days)"
            ).classes("text-sm").style("color:var(--at-warn);")

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
            ui.label(f"Loading {label} data...").classes(
                "text-gray-500 text-center w-full"
            )

        try:
            _, sec_id, _ = security_id.split(":", 2)
            candles = await asyncio.get_event_loop().run_in_executor(
                None, lambda: fetch_stock_candles_history(sec_id, interval=15, days=MA_HISTORY_DAYS)
            )
            if content_container.client._deleted:
                return
            try:
                _build_ma_content(content_container, label, candles, key)
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
            print(f"  [{key}:{label}] error:\n{traceback.format_exc()}")

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


def _build_ma_content(container, label, candles, key):
    """Run backtest and render chart + summary + trade log."""
    lines = ma_lines(key)
    container.clear()
    with container:
        if candles.empty:
            ui.label(f"No candle data available for {label}.").classes(
                "text-orange-500"
            )
            return

        since = pd.Timestamp(now_ist().date(), tz="Asia/Kolkata") - pd.Timedelta(days=BACKTEST_WINDOW_DAYS)
        signals, df_ind, trades = backtest_ma_window(candles, key, since)
        shown = candles[candles["timestamp"] >= since].reset_index(drop=True)
        df_ind = df_ind[df_ind["timestamp"] >= since].reset_index(drop=True)

        # ---- Chart ----
        ui.label(
            f"{label} — Last: {candles['close'].iloc[-1]:,.2f} | "
            f"{len(shown)} candles (15-min, {BACKTEST_WINDOW_DAYS} days)"
        ).classes("text-md font-semibold mb-2")
        chart_id = render_tv_ma_chart(shown, df_ind, signals, lines)

        # ---- Summary ----
        if len(candles) <= ma_warmup(key):
            ui.label(f"Only {len(candles)} bars: not enough for {lines[-1][1]}.").classes("text-orange-500 mt-4")
            return
        if not trades:
            ui.label(f"No {' / '.join(lbl for _, lbl in lines)} signals in this period.").classes(
                "text-gray-500 italic mt-4"
            )
            return

        completed   = [t for t in trades if t["status"] != "Open"]
        open_trades = [t for t in trades if t["status"] == "Open"]
        for t in trades:
            t["pnl_rs"] = net_rupees(t)  # risk the max loss at the stop, after charges
        total_pnl   = sum(t["pnl_rs"] or 0 for t in completed)
        winners     = sum(1 for t in completed if (t["pnl_rs"] or 0) > 0)
        losers      = sum(1 for t in completed if (t["pnl_rs"] or 0) < 0)

        ui.separator().classes("my-4")
        with ui.row().classes("gap-6 flex-wrap items-center"):
            _stat_card("Total Trades",     str(len(trades)))
            _stat_card("Completed",        str(len(completed)))
            _stat_card("Open",             str(len(open_trades)))
            _stat_card("Winners / Losers", f"{winners}W / {losers}L")
            pnl_color = "text-green-700" if total_pnl >= 0 else "text-red-700"
            _stat_card(
                f"Net P&L · ₹{inr(DEFAULT_SIZING['risk'])} risk/trade",
                rupees_text(total_pnl),
                value_class=pnl_color,
            )

        # ---- Trade Log ----
        ui.separator().classes("my-4")
        with ui.row().classes("items-center gap-3 mb-2"):
            ui.label("Trade Log").classes("text-lg font-semibold")
            ui.label("Click a row to highlight signal on chart").classes("text-xs text-gray-400 italic")

        rows = []
        for i, t in enumerate(trades):
            time_str = (
                t["time"].strftime("%d %b %H:%M")
                if hasattr(t["time"], "strftime") else str(t["time"])
            )
            exit_str = ""
            if t["exit_time"] is not None:
                exit_str = (
                    t["exit_time"].strftime("%d %b %H:%M")
                    if hasattr(t["exit_time"], "strftime") else str(t["exit_time"])
                )
            rows.append({
                "_idx":       i,
                "Entry Time": time_str,
                "Signal":     t["signal"],
                "Entry":      t["entry"],
                "Target":     t["target"],
                "SL":         t["stop_loss"],
                **{lbl: t[col] for col, lbl in lines},
                "Exit":       round(t["exit_price"], 2) if t["exit_price"] else "—",
                "Exit Time":  exit_str or "—",
                "P&L":        round(t["pnl_rs"]) if t["pnl_rs"] is not None else "—",
                "Status":     t["status"],
            })

        columns = [
            {"name": "entry_time", "label": "Entry Time", "field": "Entry Time", "sortable": True, "align": "left"},
            {"name": "signal",     "label": "Signal",     "field": "Signal",     "sortable": True, "align": "left"},
            {"name": "entry",      "label": "Entry",      "field": "Entry",      "sortable": True, "align": "left"},
            {"name": "target",     "label": "Target",     "field": "Target",     "sortable": True, "align": "left"},
            {"name": "sl",         "label": "SL",         "field": "SL",         "sortable": True, "align": "left"},
            *({"name": col, "label": lbl, "field": lbl, "sortable": True, "align": "left"} for col, lbl in lines),
            {"name": "exit",       "label": "Exit",       "field": "Exit",       "sortable": True, "align": "left"},
            {"name": "exit_time",  "label": "Exit Time",  "field": "Exit Time",  "sortable": True, "align": "left"},
            {"name": "pnl",        "label": "P&L ₹",      "field": "P&L",        "sortable": True, "align": "left"},
            {"name": "status",     "label": "Status",     "field": "Status",     "sortable": True, "align": "left"},
        ]
        _cid = chart_id

        table = ui.table(columns=columns, rows=rows, row_key="Entry Time").classes("w-full cursor-pointer")

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
                    {{ typeof props.value === 'number' ? (props.value > 0 ? '+' : props.value < 0 ? '−' : '') + '₹' + Math.abs(props.value).toLocaleString('en-IN') : props.value }}
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
