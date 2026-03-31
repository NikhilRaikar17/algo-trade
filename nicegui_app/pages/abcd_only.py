"""
ABCD Harmonic historical backtest tab page.
Fetches 15-min candles for any NSE index or stock, detects ABCD patterns, backtests.
"""

import asyncio
import traceback
from nicegui import ui

from data import MARKET_WATCH_GROUPS, STOCK_WATCH_GROUPS, _fetch_any_index_candles, _fetch_any_stock_candles, fetch_atm_option_15min_candles
from ui_components import build_grouped_options_dict, resolve_option_labels_in_dropdown
from algo_strategies import find_swing_points, detect_abcd_patterns, backtest_abcd
from tv_charts import render_tv_abcd_chart


# Build option groups: {group_label: {value: display_name}}
_OPTION_GROUPS: dict[str, dict[str, str]] = {}
for _g in MARKET_WATCH_GROUPS:
    _OPTION_GROUPS[_g["group"]] = {
        idx["security_id"]: idx["name"]
        for idx in _g["indices"]
    }
for _g in STOCK_WATCH_GROUPS:
    key = f"Stocks – {_g['group']}"
    _OPTION_GROUPS[key] = {
        f"EQ:{s['security_id']}:{s['name']}": s["name"]
        for s in _g["stocks"]
    }

_OPTION_GROUPS["NIFTY Weekly Options"] = {
    f"OPT:NIFTY:{i}:CE": f"NIFTY Weekly +{i} CE (ATM)"
    for i in range(3)
} | {
    f"OPT:NIFTY:{i}:PE": f"NIFTY Weekly +{i} PE (ATM)"
    for i in range(3)
}
_OPTION_GROUPS["BANKNIFTY Monthly Options"] = {
    f"OPT:BANKNIFTY:{i}:CE": f"BANKNIFTY Monthly +{i} CE (ATM)"
    for i in range(3)
} | {
    f"OPT:BANKNIFTY:{i}:PE": f"BANKNIFTY Monthly +{i} PE (ATM)"
    for i in range(3)
}

_ALL_OPTIONS: dict[str, str] = {
    k: v
    for group_opts in _OPTION_GROUPS.values()
    for k, v in group_opts.items()
}

_DEFAULT_SEC_ID = "13"   # NIFTY 50
_DEFAULT_LABEL  = _ALL_OPTIONS[_DEFAULT_SEC_ID]


def _parse_option_value(value: str):
    """Return (security_id, is_equity, is_option) from the dropdown value key."""
    if value.startswith("EQ:"):
        _, sec_id, _ = value.split(":", 2)
        return sec_id, True, False
    if value.startswith("OPT:"):
        return value, False, True
    return value, False, False


def render_abcd_only_tab(container):
    """Build the ABCD historical backtester tab. Returns an async refresh() closure."""

    selected = {"security_id": _DEFAULT_SEC_ID, "label": _DEFAULT_LABEL}

    with container:
        ui.label("ABCD Harmonic Scanner").classes("text-xl font-bold mb-2")
        with ui.element("div").classes(
            "bg-blue-50 border border-blue-200 rounded-lg px-4 py-2 mb-3"
        ):
            ui.label(
                "Strategy: ABCD harmonic pattern detection | "
                "Target: D + AB | SL: Point C | 15-min candles | 5 days"
            ).classes("text-sm text-blue-700")

        # ---- Instrument selector ----
        # Start with static names; real option labels resolved async below
        live_options = dict(_ALL_OPTIONS)
        grouped_options = build_grouped_options_dict(_OPTION_GROUPS)
        with ui.row().classes("items-center gap-3 mb-4"):
            ui.label("Index / Stock:").classes("text-sm font-medium text-gray-700")
            select_widget = ui.select(
                options=grouped_options,
                value=_DEFAULT_SEC_ID,
                label="",
                on_change=lambda e: asyncio.ensure_future(
                    _load(e.value, live_options.get(e.value, e.value))
                ) if not str(e.value).startswith("__hdr_") else None,
            ).props("outlined dense use-input input-debounce=0").classes("w-64")

        content_container = ui.element("div").classes("w-full")
        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            ui.label(f"Loading {_DEFAULT_LABEL} ABCD data...").classes(
                "text-gray-500 text-center w-full"
            )

    async def _load(security_id: str, label: str):
        selected["security_id"] = security_id
        selected["label"] = label

        if content_container.client._deleted:
            return

        sec_id, is_equity, is_option = _parse_option_value(security_id)
        if is_option:
            _, index_name, expiry_idx_str, opt_type = sec_id.split(":")
            loading_label = f"Resolving {index_name} expiry +{expiry_idx_str} {opt_type} contract..."
        else:
            loading_label = f"Loading {label} ABCD data..."

        content_container.clear()
        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            ui.label(loading_label).classes("text-gray-500 text-center w-full")

        try:
            if is_option:
                _, index_name, expiry_idx_str, opt_type = sec_id.split(":")
                expiry_idx = int(expiry_idx_str)
                resolved_label, candles = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: fetch_atm_option_15min_candles(index_name, expiry_idx, opt_type)
                )
                selected["label"] = resolved_label
            else:
                fetch_fn = _fetch_any_stock_candles if is_equity else _fetch_any_index_candles
                candles = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: fetch_fn(sec_id)
                )
                resolved_label = label
            if content_container.client._deleted:
                return
            try:
                _build_abcd_content(content_container, resolved_label, candles)
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
            print(f"  [abcd_hist:{label}] error:\n{traceback.format_exc()}")

    async def refresh():
        await _load(selected["security_id"], selected["label"])
        await resolve_option_labels_in_dropdown(select_widget, _OPTION_GROUPS, live_options)

    return refresh


def _build_abcd_content(container, label, candles):
    """Detect patterns, backtest, render charts and tables from pre-fetched candles."""
    container.clear()
    with container:
        if candles.empty:
            ui.label(f"No candle data available for {label}.").classes(
                "text-orange-500"
            )
            return

        # Detect swing points and ABCD patterns
        swings = find_swing_points(candles, order=2)
        patterns = detect_abcd_patterns(swings)
        trades = backtest_abcd(patterns, candles)

        # --- Chart ---
        ui.label(
            f"{label} — Last: {candles['close'].iloc[-1]:,.2f} | "
            f"{len(candles)} candles (15-min, 5 days) | "
            f"{len(swings)} swings | {len(patterns)} patterns"
        ).classes("text-md font-semibold mb-2")
        render_tv_abcd_chart(candles, swings, patterns)

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
