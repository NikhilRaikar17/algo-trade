"""
P&L summary tab — day-wise breakdown with strategy filter.
"""

from collections import defaultdict

from nicegui import ui

from config import now_ist
from pnl import collect_all_trades
from state import load_trade_history
from ui_components import build_trade_table

_ALL_STRATEGIES = ["ABCD", "Double Top", "Double Bottom", "EMA10", "SMA50"]


def render_pnl_tab(container):
    """Build the P&L summary tab. Returns an async refresh() closure."""

    with container:
        ui.label("Profit / Loss — All Strategies").classes("text-xl font-bold mb-3")
        filter_row = ui.element("div").classes("w-full mb-2")
        summary_container = ui.element("div").classes("w-full")

    # Mutable filter state shared between refresh() and event handlers
    _state = {"strategy": "All", "date": "All"}
    # Latest fetched data (updated each refresh cycle)
    _data = {"completed": [], "active": []}

    # ── helpers ──────────────────────────────────────────────────────────────

    def _merge_completed(mem_completed, hist_completed):
        """Return hist as primary; append any in-memory trades not yet persisted."""
        today = now_ist().strftime("%Y-%m-%d")
        result = list(hist_completed)
        for t in mem_completed:
            strat = t.get("strategy", "Unknown")
            signal = str(t.get("signal", ""))
            entry = float(t.get("entry", 0))
            already = any(
                r.get("strategy") == strat
                and r.get("signal") == signal
                and abs(float(r.get("entry", 0)) - entry) < 0.01
                for r in hist_completed
            )
            if not already:
                result.append({
                    "trade_date": today,
                    "strategy": strat,
                    "signal": signal,
                    "entry": entry,
                    "exit_price": float(t.get("exit_price", 0)),
                    "pnl": float(t.get("pnl", 0)),
                    "status": str(t.get("status", "")),
                })
        return result

    def _apply_filters(completed):
        out = completed
        if _state["strategy"] != "All":
            out = [t for t in out if t.get("strategy") == _state["strategy"]]
        if _state["date"] != "All":
            out = [t for t in out if t.get("trade_date") == _state["date"]]
        return out

    # ── main render ──────────────────────────────────────────────────────────

    def _render():
        completed = _data["completed"]
        active = _data["active"]
        filtered = _apply_filters(completed)

        summary_container.clear()
        with summary_container:

            # ── Summary cards ──────────────────────────────────────────────
            total_pnl = sum(t.get("pnl", 0) for t in filtered)
            total_trades = len(filtered)
            winners = sum(1 for t in filtered if t.get("pnl", 0) > 0)
            losers = sum(1 for t in filtered if t.get("pnl", 0) < 0)
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
                    ui.label(f"{win_rate:.0f}%").classes("text-2xl font-bold text-emerald-600")
                with ui.card().classes("p-3 min-w-[120px] flex-1"):
                    ui.label("W / L").classes("text-sm text-gray-500")
                    ui.label(f"{winners} / {losers}").classes("text-2xl font-bold")

            # ── Per-strategy breakdown cards ───────────────────────────────
            ui.label("Strategy Breakdown").classes("text-base font-semibold mb-1")
            date_filter_active = _state["date"] != "All"
            with ui.row().classes("gap-3 flex-wrap mb-4"):
                for strat in _ALL_STRATEGIES:
                    strat_trades = [t for t in completed if t.get("strategy") == strat]
                    if date_filter_active:
                        strat_trades = [t for t in strat_trades if t.get("trade_date") == _state["date"]]
                    spnl = sum(t.get("pnl", 0) for t in strat_trades)
                    sw = sum(1 for t in strat_trades if t.get("pnl", 0) > 0)
                    sl_c = sum(1 for t in strat_trades if t.get("pnl", 0) < 0)
                    swr = f"{sw / len(strat_trades) * 100:.0f}%" if strat_trades else "—"
                    scolor = "text-green-600" if spnl >= 0 else "text-red-600"
                    is_active_filter = _state["strategy"] == strat
                    card_border = "border-2 border-emerald-500" if is_active_filter else ""
                    with ui.card().classes(f"p-3 w-[180px] {card_border}"):
                        ui.label(strat).classes("text-sm font-bold text-gray-600 mb-1")
                        ui.label(f"{spnl:+.2f}").classes(f"text-xl font-bold {scolor}")
                        ui.label(f"{len(strat_trades)} trades · {sw}W/{sl_c}L · WR {swr}").classes(
                            "text-xs text-gray-500"
                        )

            ui.separator().classes("my-3")

            # ── Day-wise P&L table ─────────────────────────────────────────
            ui.label("Day-wise P&L").classes("text-base font-semibold mb-2")
            # Group by date using strategy filter but ignore date filter here
            day_trades = completed
            if _state["strategy"] != "All":
                day_trades = [t for t in day_trades if t.get("strategy") == _state["strategy"]]

            date_groups: dict[str, list] = defaultdict(list)
            for t in day_trades:
                date_groups[t.get("trade_date", "Unknown")].append(t)

            if not date_groups:
                ui.label("No trade history yet.").classes("text-gray-500 italic")
            else:
                day_rows = []
                for date in sorted(date_groups.keys(), reverse=True):
                    dtrades = date_groups[date]
                    dpnl = sum(t.get("pnl", 0) for t in dtrades)
                    dw = sum(1 for t in dtrades if t.get("pnl", 0) > 0)
                    dl = sum(1 for t in dtrades if t.get("pnl", 0) < 0)
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

            ui.separator().classes("my-3")

            # ── Completed trade details ────────────────────────────────────
            filter_label = (
                f"{_state['strategy']}" if _state["strategy"] != "All" else "All Strategies"
            )
            date_label = f" · {_state['date']}" if _state["date"] != "All" else ""
            ui.label(f"Completed Trades ({filter_label}{date_label})").classes(
                "text-base font-semibold mb-2"
            )

            def _fmt(t_val):
                if t_val is None:
                    return "—"
                if hasattr(t_val, "strftime"):
                    return t_val.strftime("%d %b %H:%M")
                return str(t_val)

            def _make_rows(trades):
                return [
                    {
                        "Date":      t.get("trade_date", ""),
                        "Strategy":  t.get("strategy", ""),
                        "Signal":    t.get("signal", ""),
                        "Entry":     t.get("entry", 0),
                        "Target":    round(t.get("target", 0), 2) if t.get("target") else "—",
                        "SL":        round(t.get("stop_loss", 0), 2) if t.get("stop_loss") else "—",
                        "Exit":      round(t.get("exit_price", 0), 2),
                        "Entry Time": _fmt(t.get("time")),
                        "Exit Time":  _fmt(t.get("exit_time")),
                        "P&L":       t.get("pnl", 0),
                        "Status":    t.get("status", ""),
                    }
                    for t in trades
                ]

            profits = [t for t in filtered if t.get("pnl", 0) > 0]
            losses = [t for t in filtered if t.get("pnl", 0) <= 0]

            with ui.tabs().classes("w-full") as trade_tabs:
                profits_tab = ui.tab(f"Profits ({len(profits)})").classes("text-green-600")
                losses_tab = ui.tab(f"Losses ({len(losses)})").classes("text-red-600")

            with ui.tab_panels(trade_tabs, value=profits_tab).classes("w-full"):
                with ui.tab_panel(profits_tab):
                    if not profits:
                        ui.label("No profitable trades for this filter.").classes("text-gray-500 italic")
                    else:
                        build_trade_table(ui.element("div").classes("w-full"), _make_rows(profits), "P&L")
                with ui.tab_panel(losses_tab):
                    if not losses:
                        ui.label("No losing trades for this filter.").classes("text-gray-500 italic")
                    else:
                        build_trade_table(ui.element("div").classes("w-full"), _make_rows(losses), "P&L")

            # ── Active trades ──────────────────────────────────────────────
            ui.separator().classes("my-3")
            ui.label("Active Trades").classes("text-base font-semibold mb-2")

            active_filtered = active
            if _state["strategy"] != "All":
                active_filtered = [t for t in active if t.get("strategy") == _state["strategy"]]

            if not active_filtered:
                ui.label("No active trades.").classes("text-gray-500 italic")
            else:
                total_unreal = sum(t.get("unrealized_pnl", 0) for t in active_filtered)
                ucolor = "text-green-600" if total_unreal >= 0 else "text-red-600"
                ui.label(f"Unrealized P&L: {total_unreal:+.2f}").classes(
                    f"text-base font-bold {ucolor} mb-2"
                )
                def _fmt_t(t_val):
                    if t_val is None:
                        return "—"
                    if hasattr(t_val, "strftime"):
                        return t_val.strftime("%d %b %H:%M")
                    return str(t_val)

                rows = [
                    {
                        "Strategy":   t.get("strategy", ""),
                        "Signal":     t.get("signal", ""),
                        "Entry":      t.get("entry", 0),
                        "Target":     t.get("target", 0),
                        "Stop Loss":  t.get("stop_loss", 0),
                        "Entry Time": _fmt_t(t.get("time")),
                        "Unreal. P&L": t.get("unrealized_pnl", 0),
                    }
                    for t in active_filtered
                ]
                build_trade_table(ui.element("div").classes("w-full"), rows, "Unreal. P&L")

    # ── filter row builder ────────────────────────────────────────────────────

    def _build_filter_row(strategies, dates):
        filter_row.clear()
        with filter_row:
            with ui.row().classes("gap-4 items-center flex-wrap"):
                ui.label("Strategy:").classes("text-sm font-medium")
                strat_select = ui.select(
                    ["All"] + strategies,
                    value=_state["strategy"],
                    label="Strategy",
                ).classes("w-36")

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

    # ── refresh (called by main loop) ─────────────────────────────────────────

    async def refresh():
        all_active, mem_completed = collect_all_trades()
        hist_completed = load_trade_history()
        all_completed = _merge_completed(mem_completed, hist_completed)

        _data["completed"] = all_completed
        _data["active"] = all_active

        strategies = sorted(set(t.get("strategy", "Unknown") for t in all_completed))
        dates = sorted(
            set(t.get("trade_date", "Unknown") for t in all_completed),
            reverse=True,
        )

        # Reset stale filter values if they no longer exist in data
        if _state["strategy"] not in (["All"] + strategies):
            _state["strategy"] = "All"
        if _state["date"] not in (["All"] + dates):
            _state["date"] = "All"

        _build_filter_row(strategies, dates)
        _render()

    return refresh
