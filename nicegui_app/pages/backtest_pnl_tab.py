"""
Backtest P&L — consolidated P&L across all strategies for any selected instrument.
Follows the same layout as the live P&L tab.
"""

import asyncio
import traceback
from collections import defaultdict

from nicegui import ui

from data import MARKET_WATCH_GROUPS, STOCK_WATCH_GROUPS, _fetch_any_index_candles, _fetch_any_stock_candles
from algo_strategies import (
    find_swing_points, detect_abcd_patterns, backtest_abcd,
    detect_rsi_only_signals, backtest_rsi_only,
    detect_double_top_signals, backtest_double_top,
    detect_double_bottom_signals, backtest_double_bottom,
    detect_channel_down_signals, backtest_channel_down,
    detect_channel_breakout_signals, backtest_channel_breakout, CB_PERIOD,
    detect_sma50_signals, backtest_sma50,
)
from ui_components import build_trade_table


# ── Instrument options (same as other strategy pages) ────────────────────────

_OPTION_GROUPS: dict[str, dict[str, str]] = {}
for _g in MARKET_WATCH_GROUPS:
    _OPTION_GROUPS[_g["group"]] = {
        idx["security_id"]: idx["name"]
        for idx in _g["indices"]
    }
for _g in STOCK_WATCH_GROUPS:
    _key = f"Stocks – {_g['group']}"
    _OPTION_GROUPS[_key] = {
        f"EQ:{s['security_id']}:{s['name']}": s["name"]
        for s in _g["stocks"]
    }

_ALL_OPTIONS: dict[str, str] = {
    k: v for group_opts in _OPTION_GROUPS.values() for k, v in group_opts.items()
}
_DEFAULT_SEC_ID = "13"   # NIFTY 50
_DEFAULT_LABEL = _ALL_OPTIONS[_DEFAULT_SEC_ID]

_ALL_STRATEGIES = [
    "ABCD",
    "RSI Only",
    "Double Top",
    "Double Bottom",
    "Channel Breakout",
    "Channel Down",
    "SMA 50",
]


def _parse_option_value(value: str):
    if value.startswith("EQ:"):
        _, sec_id, _ = value.split(":", 2)
        return sec_id, True
    return value, False


# ── Backtest runner ───────────────────────────────────────────────────────────

def _run_all_backtests(candles):
    """Run every strategy on candles. Returns completed trades tagged with strategy."""
    all_trades = []

    def _tag(trades, strategy):
        for t in trades:
            t["strategy"] = strategy
            entry_time = t.get("time")
            t["trade_date"] = (
                entry_time.strftime("%Y-%m-%d")
                if hasattr(entry_time, "strftime")
                else str(entry_time)[:10]
            )
        return trades

    runners = [
        ("ABCD",             _run_abcd),
        ("RSI Only",         _run_rsi_only),
        ("Double Top",       _run_double_top),
        ("Double Bottom",    _run_double_bottom),
        ("Channel Breakout", _run_channel_breakout),
        ("Channel Down",     _run_channel_down),
        ("SMA 50",           _run_sma50),
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

def _run_rsi_only(candles):
    signals, _ = detect_rsi_only_signals(candles)
    return backtest_rsi_only(signals, candles)

def _run_double_top(candles):
    signals = detect_double_top_signals(candles)
    return backtest_double_top(signals, candles)

def _run_double_bottom(candles):
    signals = detect_double_bottom_signals(candles)
    return backtest_double_bottom(signals, candles)

def _run_channel_breakout(candles):
    signals, _ = detect_channel_breakout_signals(candles)
    return backtest_channel_breakout(signals, candles)

def _run_channel_down(candles):
    signals = detect_channel_down_signals(candles)
    return backtest_channel_down(signals, candles)

def _run_sma50(candles):
    signals, _ = detect_sma50_signals(candles)
    return backtest_sma50(signals, candles)


# ── Page renderer ─────────────────────────────────────────────────────────────

def render_backtest_pnl_tab(container):
    """Build the Backtest P&L tab. Returns an async refresh() closure."""

    selected = {"security_id": _DEFAULT_SEC_ID, "label": _DEFAULT_LABEL}
    _state = {"strategy": "All", "date": "All"}
    _data = {"trades": []}

    with container:
        ui.label("Backtest P&L — All Strategies").classes("text-xl font-bold mb-2")
        with ui.element("div").classes(
            "bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-2 mb-3"
        ):
            ui.label(
                "Consolidated backtest P&L · All strategies · "
                "15-min candles · 5 days · Completed trades only"
            ).classes("text-sm text-indigo-700")

        with ui.row().classes("items-center gap-3 mb-4"):
            ui.label("Index / Stock:").classes("text-sm font-medium text-gray-700")
            ui.select(
                options=_ALL_OPTIONS,
                value=_DEFAULT_SEC_ID,
                label="",
                on_change=lambda e: asyncio.ensure_future(
                    _load(e.value, _ALL_OPTIONS.get(e.value, e.value))
                ),
            ).props("outlined dense use-input input-debounce=0").classes("w-64")

        filter_row = ui.element("div").classes("w-full mb-2")
        content_container = ui.element("div").classes("w-full")

        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            ui.label(f"Loading {_DEFAULT_LABEL} backtest data...").classes(
                "text-gray-500 text-center w-full"
            )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _apply_filters(trades):
        out = trades
        if _state["strategy"] != "All":
            out = [t for t in out if t.get("strategy") == _state["strategy"]]
        if _state["date"] != "All":
            out = [t for t in out if t.get("trade_date") == _state["date"]]
        return out

    def _render():
        trades = _data["trades"]
        filtered = _apply_filters(trades)

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
            losers = sum(1 for t in filtered if t["pnl"] < 0)
            win_rate = (winners / total_trades * 100) if total_trades else 0

            with ui.row().classes("gap-4 flex-wrap mb-4"):
                with ui.card().classes("p-3 min-w-[120px] flex-1"):
                    ui.label("Total P&L").classes("text-sm text-gray-500")
                    color = "text-green-600" if total_pnl >= 0 else "text-red-600"
                    ui.label(f"{total_pnl:+.2f}").classes(f"text-2xl font-bold {color}")
                with ui.card().classes("p-3 min-w-[120px] flex-1"):
                    ui.label("Trades").classes("text-sm text-gray-500")
                    ui.label(str(total_trades)).classes("text-2xl font-bold")
                with ui.card().classes("p-3 min-w-[120px] flex-1"):
                    ui.label("Win Rate").classes("text-sm text-gray-500")
                    ui.label(f"{win_rate:.0f}%").classes("text-2xl font-bold text-blue-600")
                with ui.card().classes("p-3 min-w-[120px] flex-1"):
                    ui.label("W / L").classes("text-sm text-gray-500")
                    ui.label(f"{winners} / {losers}").classes("text-2xl font-bold")

            # ── Strategy breakdown cards ───────────────────────────────────
            ui.label("Strategy Breakdown").classes("text-base font-semibold mb-1")
            date_filter_active = _state["date"] != "All"
            with ui.row().classes("gap-3 flex-wrap mb-4"):
                for strat in _ALL_STRATEGIES:
                    strat_trades = [t for t in trades if t.get("strategy") == strat]
                    if date_filter_active:
                        strat_trades = [
                            t for t in strat_trades
                            if t.get("trade_date") == _state["date"]
                        ]
                    spnl = sum(t["pnl"] for t in strat_trades)
                    sw = sum(1 for t in strat_trades if t["pnl"] > 0)
                    sl_c = sum(1 for t in strat_trades if t["pnl"] < 0)
                    swr = f"{sw / len(strat_trades) * 100:.0f}%" if strat_trades else "—"
                    scolor = "text-green-600" if spnl >= 0 else "text-red-600"
                    border = "border-2 border-blue-400" if _state["strategy"] == strat else ""
                    with ui.card().classes(f"p-3 min-w-[130px] flex-1 {border}"):
                        ui.label(strat).classes("text-sm font-bold text-gray-600 mb-1")
                        ui.label(f"{spnl:+.2f}").classes(f"text-xl font-bold {scolor}")
                        ui.label(
                            f"{len(strat_trades)} trades · {sw}W/{sl_c}L · WR {swr}"
                        ).classes("text-xs text-gray-500")

            ui.separator().classes("my-3")

            # ── Day-wise P&L table ─────────────────────────────────────────
            ui.label("Day-wise P&L").classes("text-base font-semibold mb-2")
            day_trades = trades
            if _state["strategy"] != "All":
                day_trades = [t for t in day_trades if t.get("strategy") == _state["strategy"]]

            date_groups: dict = defaultdict(list)
            for t in day_trades:
                date_groups[t.get("trade_date", "Unknown")].append(t)

            if date_groups:
                day_rows = []
                for date in sorted(date_groups.keys(), reverse=True):
                    dtrades = date_groups[date]
                    dpnl = sum(t["pnl"] for t in dtrades)
                    dw = sum(1 for t in dtrades if t["pnl"] > 0)
                    dl = sum(1 for t in dtrades if t["pnl"] < 0)
                    dwr = f"{dw / len(dtrades) * 100:.0f}%" if dtrades else "0%"
                    day_rows.append({
                        "Date": date,
                        "Trades": len(dtrades),
                        "Winners": dw,
                        "Losers": dl,
                        "Win %": dwr,
                        "P&L": round(dpnl, 2),
                    })
                build_trade_table(ui.element("div").classes("w-full"), day_rows, "P&L")
            else:
                ui.label("No data.").classes("text-gray-500 italic")

            ui.separator().classes("my-3")

            # ── Trade details ──────────────────────────────────────────────
            filter_label = (
                _state["strategy"] if _state["strategy"] != "All" else "All Strategies"
            )
            date_label = f" · {_state['date']}" if _state["date"] != "All" else ""
            ui.label(f"Trade Details ({filter_label}{date_label})").classes(
                "text-base font-semibold mb-2"
            )
            if not filtered:
                ui.label("No trades match this filter.").classes("text-gray-500 italic")
            else:
                rows = [
                    {
                        "Date": t.get("trade_date", ""),
                        "Strategy": t.get("strategy", ""),
                        "Signal": t.get("signal", ""),
                        "Type": t.get("type", ""),
                        "Entry": t.get("entry", 0),
                        "Exit": round(t["exit_price"], 2) if t.get("exit_price") is not None else "—",
                        "P&L": t.get("pnl", 0),
                        "Status": t.get("status", ""),
                    }
                    for t in filtered
                ]
                build_trade_table(ui.element("div").classes("w-full"), rows, "P&L")

    # ── filter row ────────────────────────────────────────────────────────────

    def _build_filter_row(strategies, dates):
        filter_row.clear()
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

        def on_strat(e):
            _state["strategy"] = e.value
            _render()

        def on_date(e):
            _state["date"] = e.value
            _render()

        strat_select.on_value_change(on_strat)
        date_select.on_value_change(on_date)

    # ── data loader ───────────────────────────────────────────────────────────

    async def _load(security_id: str, label: str):
        selected["security_id"] = security_id
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
            sec_id, is_equity = _parse_option_value(security_id)
            fetch_fn = _fetch_any_stock_candles if is_equity else _fetch_any_index_candles
            candles = await asyncio.get_event_loop().run_in_executor(
                None, lambda: fetch_fn(sec_id)
            )
            if content_container.client._deleted:
                return

            all_trades = await asyncio.get_event_loop().run_in_executor(
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

            if _state["strategy"] not in (["All"] + strategies):
                _state["strategy"] = "All"
            if _state["date"] not in (["All"] + dates):
                _state["date"] = "All"

            try:
                _build_filter_row(strategies, dates)
                _render()
            except RuntimeError:
                return  # container was cleared by a concurrent build_ui()

        except Exception as e:
            if content_container.client._deleted:
                return
            try:
                content_container.clear()
                with content_container:
                    ui.label(f"Error: {e}").classes("text-red-500")
            except RuntimeError:
                return  # container was cleared by a concurrent build_ui()
            print(f"  [backtest_pnl:{label}] error:\n{traceback.format_exc()}")

    async def refresh():
        await _load(selected["security_id"], selected["label"])

    return refresh
