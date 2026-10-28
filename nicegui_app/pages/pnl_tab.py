"""
Live P&L — what the live engine's trades made, after charges, for the strategies switched on for Live.
The same page serves the options account (Live P&L Options: render_pnl_tab(..., acct=OPTIONS)), with
the contracts the options engine is trading on top.

Trades come from the paper account's book (account.py): each live signal was taken or skipped once,
when the engine first saw it, sized to risk the max loss at the stop within the free balance. The
account starts with RISK_LIMITS["funds"] and compounds every closed trade's net P&L after brokerage
and taxes.
"""

import asyncio
from datetime import datetime
from html import escape

from nicegui import app, ui

from account import EQUITY, OPTIONS, PaperAccount, qty_text
from backtest_metrics import group_by, sizing_label, summarize
from config import OPTIONS_SELECTION, now_ist
from pages.pnl_widgets import (
    CSS, account_card, charges_html, equity_figure, kpi_tiles, rs, strategy_table, summary_table, td, tone,
    trades_table,
)
from strategy_registry import get_live_strategy_names, get_options_pnl_strategy_keys, get_strategy_rows

LIVE_SECONDS = 5  # how often the open trades and account card pick up live prices


def _positions_table(positions: list[dict], what: str = "Stock") -> tuple[str, float]:
    """(table html, total unrealised ₹ before charges) for the account's open trades."""
    rows, total = [], 0.0
    for t in positions:
        short = t["side"] == "SELL"
        u = t["unrealized"]
        total += u
        rows.append(
            "<tr>"
            + td(what, f'{escape(t["stock"])} <span class="bt-dim">· {escape(t["strategy"])}</span>', "wide")
            + td("Side", f'<b class="{"bt-down" if short else "bt-up"}">{t["side"]}</b>')
            + td("Since", t["time"].strftime("%H:%M"), "n")
            + td("Qty", qty_text(t), "n")
            + td("Entry ₹", f'{t["entry"]:,.2f}', "n")
            + td("Now ₹", f'{float(t["last_price"] or t["entry"]):,.2f}', "n")
            + td("Target", f'{t["target"]:,.2f}', "n bt-dim")
            + td("Stop", f'{t["stop_loss"]:,.2f}', "n bt-dim")
            + td("Unrealised", f"<b>{rs(u, sign=True)}</b>", f"n {tone(u)}")
            + "</tr>"
        )
    head = (f'<tr><th>{what}</th><th>Side</th><th class="n">Since</th><th class="n">Qty</th><th class="n">Entry ₹</th>'
            '<th class="n">Now ₹</th><th class="n">Target</th><th class="n">Stop</th><th class="n">Unrealised</th></tr>')
    html = f'<div class="bt-wrap"><table class="bt-table"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'
    return html, total


def _skipped_table(skipped: list[dict], what: str = "Stock") -> str:
    rows = [
        "<tr>"
        + td("Seen", r["decided_at"][11:16], "n")
        + td(what, f'{escape(r["symbol"])} <span class="bt-dim">· {escape(r["strategy"])}</span>', "wide")
        + td("Side", r["side"])
        + td("Entry ₹", f'{r["entry"]:,.2f}', "n")
        + td("Why not taken", escape("; ".join(r["reasons"])), "bt-dim")
        + "</tr>"
        for r in sorted(skipped, key=lambda r: r["decided_at"], reverse=True)
    ]
    head = f'<tr><th class="n">Seen</th><th>{what}</th><th>Side</th><th class="n">Entry ₹</th><th>Why not taken</th></tr>'
    return f'<div class="bt-wrap"><table class="bt-table"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def _contracts_card(snap: dict) -> str:
    """Live P&L Options: the CE / PE each index is being traded on, and what the selection saw."""
    cfg = OPTIONS_SELECTION
    rows = "".join(
        "<tr>"
        + td("Contract", f'<b>{escape(c["symbol"])}</b>', "wide")
        + td("Premium ₹", f'{c["premium"]:,.2f}', "n")
        + td("Lot", f'{c["lot_size"]:,} · {rs(c["premium"] * c["lot_size"])}', "n")
        + td("Delta", f'{c["delta"]:.2f}', "n")
        + td("OI", f'{c["oi"]:,}', "n bt-dim")
        + td("Volume", f'{c["volume"]:,}', "n bt-dim")
        + td("Spread", f'{c["spread_pct"]:.2f}%', "n bt-dim")
        + td("Chosen", f'{c["chosen_at"]} · {escape(c["underlying"])} {c["spot"]:,.0f}', "n bt-dim")
        + td("Open signals", str(snap["signals"].get(c["symbol"], 0)), "n")
        + "</tr>"
        for c in snap["contracts"]
    )
    head = ('<tr><th>Contract</th><th class="n">Premium ₹</th><th class="n">Lot</th><th class="n">Delta</th>'
            '<th class="n">OI</th><th class="n">Volume</th><th class="n">Spread</th><th class="n">Chosen</th>'
            '<th class="n">Open signals</th></tr>')
    notes = "".join(f'<div class="bt-hs bt-down">{escape(u)}: {escape(why)}</div>' for u, why in snap["status"].items())
    table = (f'<div class="bt-wrap"><table class="bt-table"><thead>{head}</thead><tbody>{rows}</tbody></table></div>'
             if rows else '<div class="bt-hs">None chosen yet: the engine picks them at the first bar close of the '
                          'market day.</div>')
    return (f'<div class="bt-card w-full"><div class="bt-h">Contracts being traded</div>'
            f'<div class="bt-hs">Next-to-next expiry (the next one if that is over {cfg["max_days_to_expiry"]} days '
            f'out) · |delta| {cfg["min_delta"]}–{cfg["max_delta"]}, nearest 0.5 · OI ≥ {cfg["min_oi"]:,} · '
            f'volume ≥ {cfg["min_volume"]:,} · spread ≤ {cfg["max_spread_pct"]}% · a lot within the per-trade cap. '
            f'Chosen again when the index moves {cfg["reselect_strikes"]} strikes. Only BUY signals on each chart '
            f'are traded, one position per index.</div>{notes}{table}</div>')


def render_pnl_tab(container, acct: PaperAccount = EQUITY):
    """Build the Live P&L tab (Live P&L Options with acct=OPTIONS). Returns an async refresh() closure."""
    options = acct is OPTIONS
    what = "Contract" if options else "Stock"

    st = {"strategy": "All", "date": "All", "stock": "All", "view": "strategy"}
    data = {"completed": [], "active": [], "at": None, "account": None}
    live = {"box": None}  # the open-trades card, redrawn on its own between full refreshes
    is_admin = app.storage.user.get("username") == "nikhil"

    with container:
        ui.add_head_html(CSS)
        with ui.row().classes("w-full items-end justify-between gap-2 mb-1"):
            with ui.column().classes("gap-0"):
                ui.label("Live P&L Options" if options else "Live P&L").classes("text-xl font-bold")
                ui.label(("NIFTY & BANKNIFTY options, bought in whole lots · " if options else "")
                         + f"Paper account · {sizing_label(funds=None)} · compounding · after brokerage "
                         "and taxes · nothing here is a real order").classes("bt-sub")
            with ui.row().classes("gap-1"):
                if is_admin:
                    ui.button("Reset account", icon="restart_alt", on_click=lambda: confirm.open()) \
                        .props("flat dense no-caps")
                refresh_btn = ui.button("Refresh", icon="refresh").props("flat dense no-caps")
        account_box = ui.element("div").classes("w-full mt-3")
        contracts_box = ui.html("").classes("w-full mt-3") if options else None

        with ui.element("div").classes("bt-bar w-full mt-3"):
            strat_sel = ui.select(["All"], value="All", label="Strategy").props("outlined dense")
            date_sel = ui.select(["All"], value="All", label="Day").props("outlined dense")
            stock_sel = ui.select(["All"], value="All", label=what).props("outlined dense")
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
        parts = []
        a = data["account"] or {}
        parts.append(f"<b>{len(data['completed'])}</b> closed trades in the account")
        if a.get("skipped_today"):
            parts.append(f"{len(a['skipped_today'])} signals skipped today")
        cut = sum(1 for t in data["completed"] if t.get("funds_cut"))
        if cut:
            parts.append(f"{cut} sized down to fit the funds")
        if data["at"]:
            parts.append(f"updated {data['at'].strftime('%H:%M')}")
        status.set_content(" · ".join(parts))

    def _render_live():
        """The open trades card: redrawn every LIVE_SECONDS with the monitor's latest prices."""
        live["box"].clear()
        positions = _filtered(data["active"], date=False)
        if not positions:
            return
        html, unreal = _positions_table(positions, what)
        with live["box"], ui.element("div").classes("bt-card w-full mb-3"):
            ui.html(f'<div class="bt-h">Open now · <span class="{tone(unreal)}">{rs(unreal, sign=True)}</span> '
                    f'unrealised</div><div class="bt-hs">{len(positions)} position'
                    f'{"s" if len(positions) != 1 else ""}, before charges, at live prices (updated '
                    f'{data["at"]:%H:%M:%S}). Not in the totals below until closed.</div>')
            ui.html(html)

    def _render():
        _status_line()
        account_box.clear()
        if data["account"]:
            with account_box:
                ui.html(account_card(data["account"]))
        body.clear()
        live["box"] = None
        with body:
            if options:
                options_rows = [
                    r for r in get_strategy_rows()
                    if r["key"] in get_options_pnl_strategy_keys()
                ]
                if options_rows:
                    enabled_names = ", ".join(escape(r["display_name"]) for r in options_rows)
                    ui.html(
                        '<div class="bt-card w-full mb-3"><div class="bt-h">Enabled options strategy templates</div>'
                        '<div class="bt-hs">' + enabled_names + '</div>'
                        '<div class="bt-hs mt-2">These templates are enabled for the Options Strategy Lab and '
                        'expiry-payoff research. They do not yet generate paper-account trades, so they are not '
                        'included in realized/unrealized P&amp;L totals below.</div></div>'
                    )
                else:
                    ui.html(
                        '<div class="bt-card bt-empty mb-3">No options strategy templates are enabled for Options P&amp;L. '
                        'Enable them on the Strategies page to make them available in the Strategy Lab.</div>'
                    )

            if not get_live_strategy_names():
                ui.html('<div class="bt-card bt-empty">No strategies are switched on for Live. '
                        'Turn some on in <b>Strategies</b>.</div>')
                return

            live["box"] = ui.element("div").classes("w-full")
            _render_live()

            skipped = _filtered(data["account"]["skipped_today"], date=False)
            if skipped:
                with ui.element("div").classes("bt-card w-full mb-3"):
                    ui.html(f'<div class="bt-h">Skipped today · {len(skipped)}</div><div class="bt-hs">Signals the '
                            'account did not take, with the reason. They are not in any total.</div>')
                    ui.html(_skipped_table(skipped, what))

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
                ui.html(summary_table(group_by(trades, "stock"), what))
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
        state = await asyncio.get_event_loop().run_in_executor(None, acct.account_state)
        if body.client._deleted:
            return
        completed, positions = state["sized"], state["positions"]
        data.update(completed=completed, active=positions, at=now_ist(), account=state)
        _render_contracts()

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

    def _render_contracts():
        if contracts_box is not None:
            from options_engine import snapshot  # noqa: PLC0415 — the engine pulls in the Dhan client
            contracts_box.set_content(_contracts_card(snapshot()))

    async def _live_tick():
        """Live prices without redrawing the whole page; a full refresh when a trade opened or closed."""
        old = data["account"]
        if old is None or not container.visible or body.client._deleted:
            return
        state = await asyncio.get_event_loop().run_in_executor(None, acct.account_state)
        if body.client._deleted:
            return
        if ([p["key"] for p in state["positions"]] != [p["key"] for p in old["positions"]]
                or state["trades"] != old["trades"] or len(state["skipped_today"]) != len(old["skipped_today"])):
            await refresh()
            return
        data.update(active=state["positions"], account=state, at=now_ist())
        _render_contracts()
        account_box.clear()
        with account_box:
            ui.html(account_card(state))
        if live["box"] is not None:
            _render_live()

    with container:
        ui.timer(LIVE_SECONDS, _live_tick)

    with ui.dialog() as confirm, ui.card().classes("p-4"):
        ui.label("Reset the paper account?").classes("text-base font-bold")
        ui.label(f"It starts again now with {rs(acct.limits['funds'])}. Trades closed before now stop counting; "
                 "the trade history itself is kept.").classes("text-sm bt-dim")
        with ui.row().classes("justify-end w-full mt-2"):
            ui.button("Cancel", on_click=confirm.close).props("flat no-caps")

            async def _do_reset():
                acct.reset_account()
                confirm.close()
                await refresh()
            ui.button("Reset", on_click=_do_reset).props("unelevated no-caps color=negative")
    return refresh
