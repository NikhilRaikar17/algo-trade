"""
Backtest P&L — consolidated P&L across all strategies for any selected instrument.
Follows the same layout as the live P&L tab.
"""

import asyncio
import traceback
from collections import defaultdict

from nicegui import ui

from data import _fetch_any_stock_candles
from db import get_active_top_stocks
from algo_strategies import (
    find_swing_points, detect_abcd_patterns, backtest_abcd,
    detect_double_top_signals, backtest_double_top,
    detect_double_bottom_signals, backtest_double_bottom,
    detect_sma50_signals, backtest_sma50,
    detect_ema10_signals, backtest_ema10,
)
from ui_components import build_trade_table
from strategy_registry import get_strategy_short_names
from brokerage import charges_for_trades


_ALL_STRATEGIES = get_strategy_short_names()

_ALL_KEY = "ALL:ALL:ALL"


def _build_stock_options(stocks: list[dict]) -> dict[str, str]:
    options = {"ALL:ALL:ALL": "ALL (All Stocks)"}
    for s in stocks:
        options[f"EQ:{s['security_id']}:{s['name']}"] = s["name"]
    return options


# ── Backtest runner ───────────────────────────────────────────────────────────

_REQUIRED_COLS = {"timestamp", "open", "high", "low", "close"}

def _run_all_backtests(candles, stock_name: str = ""):
    """Run every strategy on candles. Returns completed trades tagged with strategy."""
    if candles is None or candles.empty or not _REQUIRED_COLS.issubset(candles.columns):
        return []
    all_trades = []

    def _tag(trades, strategy):
        for t in trades:
            t["strategy"] = strategy
            if stock_name:
                t["stock"] = stock_name
            entry_time = t.get("time")
            t["trade_date"] = (
                entry_time.strftime("%Y-%m-%d")
                if hasattr(entry_time, "strftime")
                else str(entry_time)[:10]
            )
        return trades

    runners = [
        ("ABCD",             _run_abcd),
        ("Double Top",       _run_double_top),
        ("Double Bottom",    _run_double_bottom),
        ("SMA 50",           _run_sma50),
        ("EMA 10",           _run_ema10),
    ]
    for name, fn in runners:
        try:
            trades = fn(candles)
            all_trades.extend(_tag([t for t in trades if t["status"] != "Open"], name))
        except Exception as e:
            print(f"  [backtest_pnl] {name} error: {e}")

    return all_trades


def _run_abcd(candles):
    swings = find_swing_points(candles, order=2)
    patterns = detect_abcd_patterns(swings)
    return backtest_abcd(patterns, candles)

def _run_double_top(candles):
    signals = detect_double_top_signals(candles)
    return backtest_double_top(signals, candles)

def _run_double_bottom(candles):
    signals = detect_double_bottom_signals(candles)
    return backtest_double_bottom(signals, candles)

def _run_sma50(candles):
    signals, _ = detect_sma50_signals(candles)
    return backtest_sma50(signals, candles)

def _run_ema10(candles):
    signals, _ = detect_ema10_signals(candles)
    return backtest_ema10(signals, candles)


def _fetch_all_stocks_trades(stocks: list[dict]) -> list[dict]:
    """Fetch candles for every stock and run all backtests. Returns merged trade list."""
    all_trades = []
    for stock in stocks:
        try:
            candles = _fetch_any_stock_candles(stock["security_id"])
            trades = _run_all_backtests(candles, stock_name=stock["name"])
            all_trades.extend(trades)
        except Exception as e:
            print(f"  [backtest_pnl ALL] {stock['name']} error: {e}")
    return all_trades


# ── Page renderer ─────────────────────────────────────────────────────────────

def render_backtest_pnl_tab(container):
    """Build the Backtest P&L tab. Returns an async refresh() closure."""

    selected = {"key": None, "label": None}
    _state = {"strategy": "All", "date": "All", "stock": "All", "quantity": 1}
    _data = {"trades": [], "stocks": []}

    with container:
        ui.label("Backtest P&L — All Strategies").classes("text-xl font-bold mb-2")
        with ui.element("div").classes(
            "bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-2 mb-3"
        ):
            ui.label(
                "Consolidated backtest P&L · All strategies · "
                "15-min candles · 5 days · Completed trades only"
            ).classes("text-sm text-emerald-700")

        with ui.row().classes("items-center gap-3 mb-4"):
            ui.label("Stock:").classes("text-sm font-medium text-gray-700")
            select_widget = ui.select(
                options={},
                value=None,
                label="",
                on_change=lambda e: asyncio.ensure_future(
                    _load(e.value, (e.sender.options or {}).get(e.value, "") if e.value else "")
                ) if e.value else None,
            ).props("outlined dense use-input input-debounce=0").classes("w-64")

        filter_row = ui.element("div").classes("w-full mb-2")
        content_container = ui.element("div").classes("w-full")

        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            ui.label("Loading top stocks...").classes(
                "text-gray-500 text-center w-full"
            )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _apply_filters(trades):
        out = trades
        if _state["strategy"] != "All":
            out = [t for t in out if t.get("strategy") == _state["strategy"]]
        if _state["date"] != "All":
            out = [t for t in out if t.get("trade_date") == _state["date"]]
        if _state["stock"] != "All":
            out = [t for t in out if t.get("stock") == _state["stock"]]
        return out

    def _render():
        trades = _data["trades"]
        filtered = _apply_filters(trades)
        quantity = _state["quantity"]
        is_all_mode = selected["key"] == _ALL_KEY

        content_container.clear()
        with content_container:
            if not trades:
                ui.label(
                    "No completed trades found for this instrument in the last 5 days."
                ).classes("text-gray-500 italic mt-4")
                return

            # ── Summary cards ──────────────────────────────────────────────
            total_pnl = sum(t["pnl"] for t in filtered)
            total_trades = len(filtered)
            winners = sum(1 for t in filtered if t["pnl"] > 0)
            losers_count = sum(1 for t in filtered if t["pnl"] < 0)
            win_rate = (winners / total_trades * 100) if total_trades else 0

            # Equity intraday charges: lot_size=1 (shares, not F&O lots)
            charges = charges_for_trades(filtered, lot_size=1, quantity=quantity, segment="equity_intraday")
            gross_pnl = charges["gross_pnl"]
            total_charges = charges["total_charges"]
            net_pnl = charges["net_pnl"]

            # Capital invested = sum of (entry_price × quantity) per trade
            capital_invested = sum(
                float(t.get("entry", 0) or 0) * quantity
                for t in filtered
                if t.get("entry")
            )

            with ui.row().classes("gap-4 flex-wrap mb-4"):
                with ui.card().classes("p-3 min-w-[120px] flex-1"):
                    ui.label("Gross P&L").classes("text-sm text-gray-500")
                    color = "text-green-600" if gross_pnl >= 0 else "text-red-600"
                    ui.label(f"₹{gross_pnl:+,.2f}").classes(f"text-2xl font-bold {color}")
                    ui.label(f"Raw: {total_pnl:+.2f} pts").classes("text-xs text-gray-400")
                with ui.card().classes("p-3 min-w-[120px] flex-1 border border-orange-200"):
                    ui.label("Brokerage & Taxes").classes("text-sm text-gray-500")
                    ui.label(f"₹{total_charges:,.2f}").classes("text-2xl font-bold text-orange-500")
                    ui.label(
                        f"Avg ₹{charges['per_trade_avg_charges']:.0f}/trade"
                    ).classes("text-xs text-gray-400")
                with ui.card().classes("p-3 min-w-[120px] flex-1 border border-blue-200"):
                    ui.label("Net P&L").classes("text-sm text-gray-500")
                    net_color = "text-green-600" if net_pnl >= 0 else "text-red-600"
                    ui.label(f"₹{net_pnl:+,.2f}").classes(f"text-2xl font-bold {net_color}")
                    ui.label("After all charges").classes("text-xs text-gray-400")
                with ui.card().classes("p-3 min-w-[120px] flex-1 border border-purple-200"):
                    ui.label("Capital Invested").classes("text-sm text-gray-500")
                    ui.label(f"₹{capital_invested:,.2f}").classes("text-2xl font-bold text-purple-600")
                    ui.label(f"{quantity} share(s) × entry price").classes("text-xs text-gray-400")
                with ui.card().classes("p-3 min-w-[120px] flex-1"):
                    ui.label("Trades").classes("text-sm text-gray-500")
                    ui.label(str(total_trades)).classes("text-2xl font-bold")
                with ui.card().classes("p-3 min-w-[120px] flex-1"):
                    ui.label("Win Rate").classes("text-sm text-gray-500")
                    ui.label(f"{win_rate:.0f}%").classes("text-2xl font-bold text-emerald-600")
                with ui.card().classes("p-3 min-w-[120px] flex-1"):
                    ui.label("W / L").classes("text-sm text-gray-500")
                    ui.label(f"{winners} / {losers_count}").classes("text-2xl font-bold")

            # ── Brokerage breakdown (collapsible) ─────────────────────────
            with ui.expansion("Charges Breakdown", icon="receipt_long").classes(
                "w-full bg-gray-50 rounded mb-3 text-sm"
            ):
                with ui.row().classes("gap-6 flex-wrap px-4 py-2"):
                    for label, key in [
                        ("Brokerage", "brokerage"),
                        ("STT", "stt"),
                        ("Exchange", "exchange"),
                        ("GST", "gst"),
                        ("SEBI", "sebi"),
                        ("Stamp", "stamp"),
                    ]:
                        with ui.element("div").classes("flex flex-col"):
                            ui.label(label).classes("text-xs text-gray-500")
                            ui.label(f"₹{charges[key]:.2f}").classes("text-sm font-semibold")

            # ── Strategy breakdown cards ───────────────────────────────────
            ui.label("Strategy Breakdown").classes("text-base font-semibold mb-1")
            date_filter_active = _state["date"] != "All"
            stock_filter_active = _state["stock"] != "All"
            with ui.row().classes("gap-3 flex-wrap mb-4"):
                for strat in _ALL_STRATEGIES:
                    strat_trades = [t for t in trades if t.get("strategy") == strat]
                    if date_filter_active:
                        strat_trades = [t for t in strat_trades if t.get("trade_date") == _state["date"]]
                    if stock_filter_active:
                        strat_trades = [t for t in strat_trades if t.get("stock") == _state["stock"]]
                    spnl_pts = sum(t["pnl"] for t in strat_trades)
                    spnl_rs = spnl_pts * quantity
                    sw = sum(1 for t in strat_trades if t["pnl"] > 0)
                    sl_c = sum(1 for t in strat_trades if t["pnl"] < 0)
                    swr = f"{sw / len(strat_trades) * 100:.0f}%" if strat_trades else "—"
                    scolor = "text-green-600" if spnl_rs >= 0 else "text-red-600"
                    border = "border-2 border-emerald-500" if _state["strategy"] == strat else ""
                    with ui.card().classes(f"p-3 min-w-[130px] flex-1 {border}"):
                        ui.label(strat).classes("text-sm font-bold text-gray-600 mb-1")
                        ui.label(f"₹{spnl_rs:+,.2f}").classes(f"text-xl font-bold {scolor}")
                        ui.label(
                            f"{len(strat_trades)} trades · {sw}W/{sl_c}L · WR {swr}"
                        ).classes("text-xs text-gray-500")

            ui.separator().classes("my-3")

            # ── Day-wise P&L table ─────────────────────────────────────────
            ui.label("Day-wise P&L").classes("text-base font-semibold mb-2")
            day_trades = trades
            if _state["strategy"] != "All":
                day_trades = [t for t in day_trades if t.get("strategy") == _state["strategy"]]
            if stock_filter_active:
                day_trades = [t for t in day_trades if t.get("stock") == _state["stock"]]

            date_groups: dict = defaultdict(list)
            for t in day_trades:
                date_groups[t.get("trade_date", "Unknown")].append(t)

            if date_groups:
                day_rows = []
                for date in sorted(date_groups.keys(), reverse=True):
                    dtrades = date_groups[date]
                    dpnl_rs = sum(t["pnl"] for t in dtrades) * quantity
                    dw = sum(1 for t in dtrades if t["pnl"] > 0)
                    dl = sum(1 for t in dtrades if t["pnl"] < 0)
                    dwr = f"{dw / len(dtrades) * 100:.0f}%" if dtrades else "0%"
                    day_rows.append({
                        "Date": date,
                        "Trades": len(dtrades),
                        "Winners": dw,
                        "Losers": dl,
                        "Win %": dwr,
                        "P&L (₹)": round(dpnl_rs, 2),
                    })
                build_trade_table(ui.element("div").classes("w-full"), day_rows, "P&L (₹)")
            else:
                ui.label("No data.").classes("text-gray-500 italic")

            ui.separator().classes("my-3")

            # ── Trade details ──────────────────────────────────────────────
            filter_label = (
                _state["strategy"] if _state["strategy"] != "All" else "All Strategies"
            )
            date_label = f" · {_state['date']}" if _state["date"] != "All" else ""
            stock_label = f" · {_state['stock']}" if _state["stock"] != "All" else ""
            ui.label(f"Trade Details ({filter_label}{date_label}{stock_label})").classes(
                "text-base font-semibold mb-2"
            )
            if not filtered:
                ui.label("No trades match this filter.").classes("text-gray-500 italic")
            else:
                rows = []
                for t in filtered:
                    pnl_pts = float(t.get("pnl", 0))
                    row = {
                        "Date": t.get("trade_date", ""),
                        "Strategy": t.get("strategy", ""),
                        "Signal": t.get("signal", ""),
                        "Type": t.get("type", ""),
                        "Entry": t.get("entry", 0),
                        "Exit": round(t["exit_price"], 2) if t.get("exit_price") is not None else "—",
                        "P&L (pts)": round(pnl_pts, 2),
                        "P&L (₹)": round(pnl_pts * quantity, 2),
                        "Status": t.get("status", ""),
                    }
                    if is_all_mode:
                        row["Stock"] = t.get("stock", "")
                    rows.append(row)
                build_trade_table(ui.element("div").classes("w-full"), rows, "P&L (₹)")

    # ── filter row ────────────────────────────────────────────────────────────

    def _build_filter_row(strategies, dates, stock_names):
        filter_row.clear()
        is_all_mode = selected["key"] == _ALL_KEY
        with filter_row:
            with ui.row().classes("gap-4 items-center flex-wrap"):
                ui.label("Strategy:").classes("text-sm font-medium")
                strat_select = ui.select(
                    ["All"] + strategies,
                    value=_state["strategy"],
                    label="Strategy",
                ).classes("w-40")

                ui.label("Date:").classes("text-sm font-medium")
                date_select = ui.select(
                    ["All"] + dates,
                    value=_state["date"],
                    label="Date",
                ).classes("w-36")

                if is_all_mode and stock_names:
                    ui.label("Stock:").classes("text-sm font-medium")
                    stock_select = ui.select(
                        ["All"] + stock_names,
                        value=_state["stock"],
                        label="Stock",
                    ).classes("w-40")
                    stock_select.on_value_change(lambda e: (_state.update({"stock": e.value}), _render()))
                else:
                    _state["stock"] = "All"

                ui.separator().props("vertical").classes("mx-1 h-8")

                qty_input = ui.number(
                    label="Quantity (shares)", value=_state["quantity"], min=1, max=10000, step=1
                ).classes("w-36").props("dense outlined")

        def on_strat(e):
            _state["strategy"] = e.value
            _render()

        def on_date(e):
            _state["date"] = e.value
            _render()

        def on_qty(e):
            try:
                _state["quantity"] = max(1, int(e.value or 1))
            except (TypeError, ValueError):
                _state["quantity"] = 1
            _render()

        strat_select.on_value_change(on_strat)
        date_select.on_value_change(on_date)
        qty_input.on_value_change(on_qty)

    # ── data loader ───────────────────────────────────────────────────────────

    async def _load(key: str, label: str):
        selected["key"] = key
        selected["label"] = label

        if content_container.client._deleted:
            return

        content_container.clear()
        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            ui.label(f"Running all backtests for {label}...").classes(
                "text-gray-500 text-center w-full"
            )

        try:
            loop = asyncio.get_event_loop()

            if key == _ALL_KEY:
                stocks = _data["stocks"]
                all_trades = await loop.run_in_executor(
                    None, lambda: _fetch_all_stocks_trades(stocks)
                )
            else:
                _, sec_id, _ = key.split(":", 2)
                candles = await loop.run_in_executor(
                    None, lambda: _fetch_any_stock_candles(sec_id)
                )
                all_trades = await loop.run_in_executor(
                    None, lambda: _run_all_backtests(candles)
                )

            if content_container.client._deleted:
                return

            _data["trades"] = all_trades

            strategies = sorted(set(t.get("strategy", "") for t in all_trades if t.get("strategy")))
            dates = sorted(
                set(t.get("trade_date", "") for t in all_trades if t.get("trade_date")),
                reverse=True,
            )
            stock_names = sorted(set(t.get("stock", "") for t in all_trades if t.get("stock")))

            if _state["strategy"] not in (["All"] + strategies):
                _state["strategy"] = "All"
            if _state["date"] not in (["All"] + dates):
                _state["date"] = "All"
            if _state["stock"] not in (["All"] + stock_names):
                _state["stock"] = "All"

            try:
                _build_filter_row(strategies, dates, stock_names)
                _render()
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
            print(f"  [backtest_pnl:{label}] error:\n{traceback.format_exc()}")

    async def refresh():
        top_stocks = await asyncio.get_event_loop().run_in_executor(None, get_active_top_stocks)
        _data["stocks"] = top_stocks
        options = _build_stock_options(top_stocks)
        if not select_widget.client._deleted:
            select_widget.options = options
            select_widget.update()

        if selected["key"] is None and options:
            # Default to ALL on first load
            select_widget.value = _ALL_KEY
            select_widget.update()
            await _load(_ALL_KEY, "ALL (All Stocks)")
        elif selected["key"] not in options and options:
            first_key = next(iter(options))
            first_label = options[first_key]
            select_widget.value = first_key
            select_widget.update()
            await _load(first_key, first_label)
        elif selected["key"] in options:
            await _load(selected["key"], selected["label"])

    return refresh
