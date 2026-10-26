"""
Live P&L — what the live engine's trades made, after charges, for the strategies switched on for Live.

Trades come from live_trades.load_live_trades(); the maths is the same as Backtest P&L
(backtest_metrics): one position per stock and strategy, sized by ₹ per trade or shares, net of
Dhan's intraday charges.
"""

from datetime import datetime
from html import escape

from nicegui import ui

from backtest_metrics import DEFAULT_SIZING, group_by, size_trades, summarize
from brokerage import is_short
from config import now_ist
from live_trades import load_live_trades
from pages.pnl_widgets import (
    CSS, charges_html, equity_figure, kpi_tiles, rs, sizing_controls, strategy_table, summary_table, td, tone,
    trades_table,
)
from strategy_registry import get_live_strategy_names


def _positions_table(positions: list[dict], mode: str, amount: float) -> tuple[str, float]:
    """(table html, total unrealised ₹ before charges)."""
    rows, total = [], 0.0
    for t in positions:
        entry = float(t["entry"])
        qty = int(amount // entry) if mode == "capital" else int(amount)
        if qty < 1:
            continue
        short = is_short(t)
        upts = float(t.get("unrealized_pnl", 0) or 0)
        ltp = entry - upts if short else entry + upts
        u = upts * qty
        total += u
        side = "SELL" if short else "BUY"
        rows.append(
            "<tr>"
            + td("Stock", f'{escape(t["stock"])} <span class="bt-dim">· {escape(t["strategy"])}</span>', "wide")
            + td("Side", f'<b class="{"bt-down" if short else "bt-up"}">{side}</b>')
            + td("Since", t["time"].strftime("%H:%M"), "n")
            + td("Qty", f"{qty:,}", "n")
            + td("Entry ₹", f"{entry:,.2f}", "n")
            + td("Now ₹", f"{ltp:,.2f}", "n")
            + td("Target", f'{float(t["target"]):,.2f}' if t.get("target") else "—", "n bt-dim")
            + td("Stop", f'{float(t["stop_loss"]):,.2f}' if t.get("stop_loss") else "—", "n bt-dim")
            + td("Unrealised", f"<b>{rs(u, sign=True)}</b>", f"n {tone(u)}")
            + "</tr>"
        )
    head = ('<tr><th>Stock</th><th>Side</th><th class="n">Since</th><th class="n">Qty</th><th class="n">Entry ₹</th>'
            '<th class="n">Now ₹</th><th class="n">Target</th><th class="n">Stop</th><th class="n">Unrealised</th></tr>')
    html = f'<div class="bt-wrap"><table class="bt-table"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'
    return html, total


def render_pnl_tab(container):
    """Build the Live P&L tab. Returns an async refresh() closure."""

    st = {"strategy": "All", "date": "All", "stock": "All", "view": "strategy",
          "mode": "capital", "amount": DEFAULT_SIZING["capital"]}
    data = {"completed": [], "active": [], "notes": {}, "at": None}

    with container:
        ui.add_head_html(CSS)
        with ui.row().classes("w-full items-end justify-between gap-2 mb-1"):
            with ui.column().classes("gap-0"):
                ui.label("Live P&L").classes("text-xl font-bold")
                ui.label("Trades from the live engine · strategies switched on for Live · "
                         "after Dhan intraday charges · nothing here is a real order").classes("bt-sub")
            refresh_btn = ui.button("Refresh", icon="refresh").props("flat dense no-caps")

        with ui.element("div").classes("bt-bar w-full mt-3"):
            strat_sel = ui.select(["All"], value="All", label="Strategy").props("outlined dense")
            date_sel = ui.select(["All"], value="All", label="Day").props("outlined dense")
            stock_sel = ui.select(["All"], value="All", label="Stock").props("outlined dense")
            sizing_controls(st, lambda: _render())
        status = ui.html("").classes("bt-status mt-2 mb-3")
        body = ui.element("div").classes("w-full")

    def _filtered(trades, *, strategy=True, date=True):
        out = trades
        if strategy and st["strategy"] != "All":
            out = [t for t in out if t["strategy"] == st["strategy"]]
        if date and st["date"] != "All":
            out = [t for t in out if t["trade_date"] == st["date"]]
        if st["stock"] != "All":
            out = [t for t in out if t["stock"] == st["stock"]]
        return out

    def _status_line():
        n, parts = data["notes"], []
        parts.append(f"<b>{len(data['completed'])}</b> closed trades counted")
        skipped = [f"{v} {what}" for what, v in (("overlapping an open position", n.get("overlap", 0)),
                                                  ("with no exit price", n.get("broken", 0))) if v]
        if skipped:
            parts.append("not counted: " + ", ".join(skipped))
        if n.get("approx"):
            parts.append(f"{n['approx']} older trades saved without times")
        if data["at"]:
            parts.append(f"updated {data['at'].strftime('%H:%M')}")
        status.set_content(" · ".join(parts))

    def _render():
        _status_line()
        body.clear()
        with body:
            if not get_live_strategy_names():
                ui.html('<div class="bt-card bt-empty">No strategies are switched on for Live. '
                        'Turn some on in <b>Strategies</b>.</div>')
                return

            positions = _filtered(data["active"], date=False)
            if positions:
                html, unreal = _positions_table(positions, st["mode"], st["amount"])
                with ui.element("div").classes("bt-card w-full mb-3"):
                    ui.html(f'<div class="bt-h">Open now · <span class="{tone(unreal)}">{rs(unreal, sign=True)}</span> '
                            f'unrealised</div><div class="bt-hs">{len(positions)} position'
                            f'{"s" if len(positions) != 1 else ""}, before charges. Not in the totals below until closed.</div>')
                    ui.html(html)

            if not data["completed"]:
                ui.html('<div class="bt-card bt-empty">No closed live trades yet.</div>')
                return

            sized_all = size_trades(data["completed"], st["mode"], st["amount"])
            trades = _filtered(sized_all)
            s = summarize(trades)
            ui.html(kpi_tiles(s))
            ui.html(charges_html(s))
            if not trades:
                ui.html('<div class="bt-card bt-empty mt-3">No trades match these filters.</div>')
                return

            with ui.element("div").classes("bt-card w-full mt-3"):
                ui.html('<div class="bt-h">Equity curve</div>'
                        '<div class="bt-hs">Cumulative net P&amp;L, one point per closed trade. Hover a point for the trade.</div>')
                ui.plotly(equity_figure(trades)).classes("w-full")

            with ui.row().classes("w-full items-center justify-between mt-4 mb-2 gap-2"):
                ui.label("Breakdown").classes("bt-h")
                ui.toggle({"strategy": "By strategy", "day": "By day", "stock": "By stock", "trades": "Trades"},
                          value=st["view"], on_change=lambda e: (st.update(view=e.value), _render())) \
                    .props("dense no-caps unelevated toggle-color=primary").classes("bt-seg")

            if st["view"] == "strategy":
                groups = dict(group_by(_filtered(sized_all, strategy=False), "strategy"))
                strategy_table(groups, get_live_strategy_names(), st["strategy"], _pick_strategy)
            elif st["view"] == "day":
                groups = sorted(group_by(trades, "trade_date"), key=lambda kv: kv[0], reverse=True)
                ui.html(summary_table([(datetime.strptime(d, "%Y-%m-%d").strftime("%a %d %b"), g) for d, g in groups], "Day"))
            elif st["view"] == "stock":
                ui.html(summary_table(group_by(trades, "stock"), "Stock"))
            else:
                ui.html(trades_table(trades, show_stock=True))

    def _pick_strategy(name):
        strat_sel.set_value("All" if st["strategy"] == name else name)  # fires _on_filter → _render

    def _on_filter(key, value):
        if value is None or st[key] == value:
            return
        st[key] = value
        _render()

    strat_sel.on_value_change(lambda e: _on_filter("strategy", e.value))
    date_sel.on_value_change(lambda e: _on_filter("date", e.value))
    stock_sel.on_value_change(lambda e: _on_filter("stock", e.value))

    async def refresh():
        if body.client._deleted:
            return
        live_names = get_live_strategy_names()
        completed, positions, notes = load_live_trades()
        data.update(completed=completed, active=positions, at=now_ist(), notes=notes)

        everything = completed + positions
        for sel, key, opts in (
            (strat_sel, "strategy", ["All"] + list(live_names)),
            (date_sel, "date", ["All"] + sorted({t["trade_date"] for t in completed}, reverse=True)),
            (stock_sel, "stock", ["All"] + sorted({t["stock"] for t in everything if t["stock"]})),
        ):
            if st[key] not in opts:
                st[key] = "All"
            sel.set_options(opts, value=st[key])
        _render()

    refresh_btn.on_click(refresh)
    return refresh
