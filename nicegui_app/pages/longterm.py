"""
Long Term pages (sidebar LONG TERM drop-down): one-week swing trades in the current NIFTY future on the
index's daily chart (longterm.py).

- Signals: the contract being traded, the strategies running, and the engine's daily scan (taken /
  skipped by the long-term account), or a display-only scan on demand.
- Backtest: the same strategies over the last year of daily bars, sized through a paper account with
  the live account's rules.

The account itself is on Live P&L Long Term (pages/pnl_tab.py with acct=LONGTERM).
"""

import asyncio
from html import escape

from nicegui import ui

import longterm
from backtest_metrics import group_by, summarize
from config import LONGTERM_ATR, LONGTERM_LIMITS, LONGTERM_UNDERLYING
from pages.pnl_widgets import CSS, charges_html, equity_figure, kpi_tiles, rs, summary_table, td, trades_table


def _rules_card(names: list[str], contract: dict | None, fut_price: float | None) -> str:
    lim = LONGTERM_LIMITS
    if contract:
        price = f" · last {fut_price:,.2f}" if fut_price else ""
        what = (f'<b>{escape(contract["symbol"])}</b> (expires {contract["expiry"]}, lot {contract["lot_size"]}'
                f'{price})')
    else:
        what = f"the current {LONGTERM_UNDERLYING} future"
    strategies = ", ".join(f"<b>{escape(n)}</b>" for n in names) or \
        '<span class="bt-down">none — enable a moving-average strategy for Backtest on the Strategies page</span>'
    return (f'<div class="bt-card w-full"><div class="bt-h">How it trades</div>'
            f'<div class="bt-hs">Trades {what} · signals from the {LONGTERM_UNDERLYING} index\'s daily chart, '
            f'scanned once a day at {lim["scan_at"]} · BUY on a cross up, SELL (short) on a cross down · stop '
            f'{LONGTERM_ATR["stop"]} × ATR(14), target {LONGTERM_ATR["target"]} × ATR(14) · out at the target, '
            f'the stop, or after {lim["max_hold_days"]} trading days at {lim["square_off"]} · whole lots, '
            f'{lim["margin_pct"]}% margin, risks up to {rs(lim["max_loss_per_trade"])} a trade, one position at a '
            f'time · rolls to the next month when the current one expires within {lim["max_hold_days"]} trading '
            f'days.</div><div class="bt-hs">Strategies (the moving-average ones enabled for Backtest on the '
            f'Strategies page): {strategies}</div></div>')


def _signals_table(signals: list[dict]) -> str:
    verdicts = {"TAKEN": ("Taken", "bt-up"), "SKIPPED": ("Skipped", "bt-down")}
    rows = []
    for s in sorted(signals, key=lambda s: s["strategy"]):
        label, cls = verdicts.get(str(s.get("verdict") or "").upper(), ("Not booked", "bt-dim"))
        buy = s["target"] > s["entry"]
        why = "; ".join(s.get("reasons") or [])
        rows.append(
            "<tr>"
            + td("Strategy", f'<b>{escape(s["strategy"])}</b> <span class="bt-dim">· {escape(s["signal"])}</span>', "wide")
            + td("Side", f'<b class="{"bt-up" if buy else "bt-down"}">{"BUY" if buy else "SELL"}</b>')
            + td("Index", f'{s.get("index_entry", s["entry"]):,.2f}', "n")
            + td("Entry ₹", f'{s["entry"]:,.2f}', "n")
            + td("Target", f'{s["target"]:,.2f}', "n bt-dim")
            + td("Stop", f'{s["stop_loss"]:,.2f}', "n bt-dim")
            + td("ATR", f'{s["atr"]:,.1f}', "n bt-dim")
            + td("Account", f'<span class="bt-badge {cls}">{label}</span>'
                 + (f' <span class="bt-dim">{s["qty"]:,} units</span>' if s.get("qty") else "")
                 + (f' <span class="bt-dim">{escape(why)}</span>' if why else ""))
            + "</tr>"
        )
    head = ('<tr><th>Strategy</th><th>Side</th><th class="n">Index</th><th class="n">Entry ₹</th>'
            '<th class="n">Target</th><th class="n">Stop</th><th class="n">ATR</th><th>Account</th></tr>')
    return f'<div class="bt-wrap"><table class="bt-table"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def render_longterm_signals_tab(container):
    """Long Term → Signals. Returns an async refresh() closure."""
    with container:
        ui.add_head_html(CSS)
        with ui.row().classes("w-full items-end justify-between gap-2 mb-1"):
            with ui.column().classes("gap-0"):
                ui.label("Long Term Signals").classes("text-xl font-bold")
                ui.label(f"{LONGTERM_UNDERLYING} futures · one-week swing trades on the daily chart · not intraday "
                         "· paper account").classes("bt-sub")
            scan_btn = ui.button("Scan now", icon="search").props("flat dense no-caps")
        rules = ui.html("").classes("w-full mt-3")
        status = ui.html("").classes("bt-status mt-3 mb-2")
        body = ui.element("div").classes("w-full")

    def _render(res: dict):
        rules.set_content(_rules_card(res.get("strategies") or longterm.strategy_names(), res.get("contract"),
                                      res.get("future_price")))
        body.clear()
        if not res:
            status.set_content(f'No scan yet today. The engine scans at <b>{LONGTERM_LIMITS["scan_at"]}</b> on '
                               'trading days; <b>Scan now</b> shows what it would find (nothing is booked).')
            return
        what = "the engine's scan — the account took or skipped each signal" if res["booked"] else \
            "a display-only scan — nothing booked"
        if not res["trading_day"]:
            what += " · market shut today: the last trading day's signals, at index levels"
        n = len(res["signals"])
        status.set_content(f'<b>{n}</b> signal{"s" if n != 1 else ""} · {res["at"]:%d %b %H:%M} · {what}'
                           + (f' · <span class="bt-down">{escape("; ".join(res["errors"]))}</span>'
                              if res["errors"] else ""))
        with body:
            if not res["signals"]:
                ui.html('<div class="bt-card bt-empty">No strategy fired on the daily chart.</div>')
            else:
                with ui.element("div").classes("bt-card w-full"):
                    ui.html(_signals_table(res["signals"]))

    async def _scan():
        scan_btn.disable()
        status.set_content("Scanning the daily chart…")
        try:
            _render(await asyncio.get_event_loop().run_in_executor(None, longterm.scan, False))
        except Exception as e:
            status.set_content(f'<span class="bt-down">Scan failed: {escape(str(e))}</span>')
        finally:
            scan_btn.enable()

    scan_btn.on_click(_scan)

    async def refresh():
        _render(longterm.last_scan())

    return refresh


def render_longterm_backtest_tab(container):
    """Long Term → Backtest. Returns an async refresh() closure (the backtest runs on demand)."""
    st = {"strategy": "All", "view": "strategy", "res": None}
    with container:
        ui.add_head_html(CSS)
        with ui.row().classes("w-full items-end justify-between gap-2 mb-1"):
            with ui.column().classes("gap-0"):
                ui.label("Long Term Backtest").classes("text-xl font-bold")
                ui.label(f"Last 12 months of {LONGTERM_UNDERLYING} daily bars, traded as futures · starts with "
                         f"{rs(LONGTERM_LIMITS['funds'])}, compounding, live account rules · after futures charges "
                         "· the index price stands in for the future's").classes("bt-sub")
            run_btn = ui.button("Run backtest", icon="play_arrow").props("flat dense no-caps")
        with ui.element("div").classes("bt-bar w-full mt-3"):
            strat_sel = ui.select(["All"], value="All", label="Strategy").props("outlined dense")
        status = ui.html("Press <b>Run backtest</b>.").classes("bt-status mt-2 mb-3")
        body = ui.element("div").classes("w-full")

    def _render():
        res = st["res"]
        body.clear()
        if not res:
            return
        rep = res["report"]
        status.set_content(
            f'<b>{len(res["trades"])}</b> trades taken from {res["signals"]} signals since {res["since"]:%d %b %Y} '
            f'· {rep["skipped"]} skipped (a position was open, or not one lot fits) · ends at '
            f'<b>{rs(res["end_balance"])}</b> · strategies: {escape(", ".join(res["strategies"]) or "none")}')
        trades = [t for t in res["trades"] if st["strategy"] in ("All", t["strategy"])]
        with body:
            if not trades:
                ui.html('<div class="bt-card bt-empty">No trades.</div>')
                return
            s = summarize(trades)
            ui.html(kpi_tiles(s))
            ui.html(charges_html(s))
            with ui.element("div").classes("bt-card w-full mt-3"):
                every = st["strategy"] == "All"
                ui.html(f'<div class="bt-h">{"Account balance" if every else "Equity curve"}</div>'
                        '<div class="bt-hs">After every closed trade, net of futures charges.</div>')
                ui.plotly(equity_figure(trades, base=LONGTERM_LIMITS["funds"] if every else 0.0)).classes("w-full")
            with ui.row().classes("w-full items-center justify-between mt-4 mb-2 gap-2"):
                ui.label("Breakdown").classes("bt-h")
                ui.toggle({"strategy": "By strategy", "side": "By side", "exit": "By exit", "trades": "Trades"},
                          value=st["view"], on_change=lambda e: (st.update(view=e.value), _render())) \
                    .props("dense no-caps unelevated toggle-color=primary").classes("bt-seg")
            if st["view"] == "strategy":
                ui.html(summary_table(group_by(trades, "strategy"), "Strategy"))
            elif st["view"] == "side":
                ui.html(summary_table(group_by(trades, "side"), "Side"))
            elif st["view"] == "exit":
                ui.html(summary_table(group_by(trades, "status"), "Exit"))
            else:
                ui.html(trades_table(trades, show_stock=False))

    async def _run():
        run_btn.disable()
        status.set_content("Backtesting…")
        try:
            st["res"] = await asyncio.get_event_loop().run_in_executor(None, longterm.run_backtest)
            opts = ["All"] + st["res"]["strategies"]
            st["strategy"] = st["strategy"] if st["strategy"] in opts else "All"
            strat_sel.set_options(opts, value=st["strategy"])
            _render()
        except Exception as e:
            status.set_content(f'<span class="bt-down">Backtest failed: {escape(str(e))}</span>')
        finally:
            run_btn.enable()

    def _on_strategy(e):
        if e.value and e.value != st["strategy"]:
            st["strategy"] = e.value
            _render()

    run_btn.on_click(_run)
    strat_sel.on_value_change(_on_strategy)

    async def refresh():
        pass  # on demand

    return refresh
