"""
Live P&L — what the live engine's trades made, after charges, for the strategies switched on for Live.

Trades come from live_trades.load_live_trades() and are run through the paper account (account.py):
it starts with RISK_LIMITS["funds"], compounds every closed trade's net P&L after brokerage and taxes,
sizes each trade to risk the max loss at the stop and cuts it to the free balance.
"""

from datetime import datetime
from html import escape

from nicegui import app, ui

from account import account_state, reset_account
from backtest_metrics import DEFAULT_MODE, DEFAULT_SIZING, group_by, size_open_positions, sizing_label, summarize
from brokerage import is_short
from config import RISK_LIMITS, now_ist
from live_trades import load_live_trades
from pages.pnl_widgets import (
    CSS, account_card, charges_html, equity_figure, kpi_tiles, rs, strategy_table, summary_table, td, tone,
    trades_table,
)
from strategy_registry import get_live_strategy_names


def _positions_table(positions: list[dict], mode: str, amount: float, funds: float) -> tuple[str, float, int]:
    """(table html, total unrealised ₹ before charges, positions with no funds left for them)."""
    rows, total, unfunded = [], 0.0, 0
    for t, qty in size_open_positions(positions, mode, amount, funds):
        entry = float(t["entry"])
        if qty < 1:
            unfunded += 1
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
    return html, total, unfunded


def render_pnl_tab(container):
    """Build the Live P&L tab. Returns an async refresh() closure."""

    st = {"strategy": "All", "date": "All", "stock": "All", "view": "strategy",
          "mode": DEFAULT_MODE, "amount": DEFAULT_SIZING[DEFAULT_MODE]}
    data = {"completed": [], "active": [], "notes": {}, "at": None, "account": None}
    is_admin = app.storage.user.get("username") == "nikhil"

    with container:
        ui.add_head_html(CSS)
        with ui.row().classes("w-full items-end justify-between gap-2 mb-1"):
            with ui.column().classes("gap-0"):
                ui.label("Live P&L").classes("text-xl font-bold")
                ui.label(f"Paper account · {sizing_label(funds=None)} · compounding · after brokerage "
                         "and taxes · nothing here is a real order").classes("bt-sub")
            with ui.row().classes("gap-1"):
                if is_admin:
                    ui.button("Reset account", icon="restart_alt", on_click=lambda: confirm.open()) \
                        .props("flat dense no-caps")
                refresh_btn = ui.button("Refresh", icon="refresh").props("flat dense no-caps")
        account_box = ui.element("div").classes("w-full mt-3")

        with ui.element("div").classes("bt-bar w-full mt-3"):
            strat_sel = ui.select(["All"], value="All", label="Strategy").props("outlined dense")
            date_sel = ui.select(["All"], value="All", label="Day").props("outlined dense")
            stock_sel = ui.select(["All"], value="All", label="Stock").props("outlined dense")
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
        a = data["account"] or {}
        parts.append(f"<b>{len(data['completed'])}</b> closed trades in the account")
        if a.get("before_start"):
            parts.append(f"{a['before_start']} from before the account started")
        skipped = [f"{v} {what}" for what, v in (("overlapping an open position", n.get("overlap", 0)),
                                                  ("with no exit price", n.get("broken", 0))) if v]
        fr = a.get("report", {})
        if fr.get("no_funds"):
            skipped.append(f'{fr["no_funds"]} with no free funds')
        if skipped:
            parts.append("not counted: " + ", ".join(skipped))
        if fr.get("cut"):
            parts.append(f'{fr["cut"]} sized down to fit the funds')
        if n.get("approx"):
            parts.append(f"{n['approx']} older trades saved without times")
        if data["at"]:
            parts.append(f"updated {data['at'].strftime('%H:%M')}")
        status.set_content(" · ".join(parts))

    def _render():
        _status_line()
        account_box.clear()
        if data["account"]:
            with account_box:
                ui.html(account_card(data["account"]))
        body.clear()
        with body:
            if not get_live_strategy_names():
                ui.html('<div class="bt-card bt-empty">No strategies are switched on for Live. '
                        'Turn some on in <b>Strategies</b>.</div>')
                return

            positions = _filtered(data["active"], date=False)
            if positions:
                html, unreal, unfunded = _positions_table(positions, st["mode"], st["amount"], data["account"]["balance"])
                with ui.element("div").classes("bt-card w-full mb-3"):
                    ui.html(f'<div class="bt-h">Open now · <span class="{tone(unreal)}">{rs(unreal, sign=True)}</span> '
                            f'unrealised</div><div class="bt-hs">{len(positions)} position'
                            f'{"s" if len(positions) != 1 else ""}, before charges. Not in the totals below until closed.'
                            + (f' {unfunded} more signal{"s" if unfunded != 1 else ""} had no free funds.' if unfunded else "")
                            + '</div>')
                    ui.html(html)

            if not data["completed"]:
                ui.html('<div class="bt-card bt-empty mt-3">No closed trades since the account started. '
                        'The balance will move as the live engine\'s trades close.</div>')
                return

            sized_all = data["completed"]  # sized and compounded by the account
            trades = _filtered(sized_all)
            unfiltered = len(trades) == len(sized_all)
            s = summarize(trades)
            ui.html(kpi_tiles(s))
            ui.html(charges_html(s))
            if not trades:
                ui.html('<div class="bt-card bt-empty mt-3">No trades match these filters.</div>')
                return

            with ui.element("div").classes("bt-card w-full mt-3"):
                if unfiltered:
                    ui.html('<div class="bt-h">Account balance</div>'
                            '<div class="bt-hs">After every closed trade, net of brokerage and taxes. Hover a point for the trade.</div>')
                    ui.plotly(equity_figure(trades, base=data["account"]["initial"])).classes("w-full")
                else:
                    ui.html('<div class="bt-h">Equity curve</div>'
                            '<div class="bt-hs">Cumulative net P&amp;L of the filtered trades. Hover a point for the trade.</div>')
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
        acct = account_state(completed, positions)
        start = acct["start"]
        completed = acct["sized"]
        positions = [p for p in positions if p["time"] >= start]
        data.update(completed=completed, active=positions, at=now_ist(), notes=notes, account=acct)

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

    with ui.dialog() as confirm, ui.card().classes("p-4"):
        ui.label("Reset the paper account?").classes("text-base font-bold")
        ui.label(f"It starts again now with {rs(RISK_LIMITS['funds'])}. Trades closed before now stop counting; "
                 "the trade history itself is kept.").classes("text-sm bt-dim")
        with ui.row().classes("justify-end w-full mt-2"):
            ui.button("Cancel", on_click=confirm.close).props("flat no-caps")

            async def _do_reset():
                reset_account()
                confirm.close()
                await refresh()
            ui.button("Reset", on_click=_do_reset).props("unelevated no-caps color=negative")
    return refresh
