"""
Live P&L — what the live engine's trades made, after charges, for the strategies switched on for Live.

Completed trades come from .trade_history.json (state.save_completed_trade) plus any of today's
that are still only in the engine's memory; open positions come from the engine. The maths is the
same as Backtest P&L (backtest_metrics): one position per stock and strategy, sized by ₹ per trade
or shares, net of Dhan's intraday charges.
"""

from datetime import datetime
from html import escape

import pandas as pd
from nicegui import ui

from backtest_metrics import DEFAULT_SIZING, finalize_trades, group_by, size_trades, summarize
from brokerage import is_short
from config import IST, now_ist
from pages.pnl_widgets import (
    CSS, charges_html, equity_figure, kpi_tiles, rs, sizing_controls, strategy_table, summary_table, td, tone,
    trades_table,
)
from pnl import collect_all_trades
from state import load_trade_history
from strategy_registry import get_live_strategy_names


def _to_ts(v):
    if v is None or v == "":
        return None
    try:
        ts = pd.Timestamp(v)
    except (TypeError, ValueError):
        return None
    return ts.tz_localize(IST) if ts.tzinfo is None else ts


def _normalize(t: dict) -> dict:
    """Copy of a live trade with stock / time / exit_time / trade_date filled in. Records saved before
    times were stored get the session open/close and approx_time=True (no overlap check, no clock time)."""
    r = dict(t)
    r["stock"] = r.get("symbol") or r.get("stock") or ""
    entry_t = _to_ts(r.get("time") or (r.get("D") or {}).get("time"))
    exit_t = _to_ts(r.get("exit_time"))
    if entry_t is None or exit_t is None:
        day = pd.Timestamp(r.get("trade_date") or now_ist().strftime("%Y-%m-%d")).tz_localize(IST)
        entry_t = entry_t or day + pd.Timedelta(hours=9, minutes=15)
        exit_t = exit_t or day + pd.Timedelta(hours=15, minutes=30)
        r["approx_time"] = True
    r["time"], r["exit_time"] = entry_t, exit_t
    r["trade_date"] = r.get("trade_date") or entry_t.strftime("%Y-%m-%d")
    return r


def _merge_completed(mem_completed, hist_completed):
    """History is the record; add today's in-memory trades that aren't saved yet (whole trade kept)."""
    result = list(hist_completed)
    today = now_ist().strftime("%Y-%m-%d")
    for t in mem_completed:
        saved = any(
            r.get("strategy") == t.get("strategy") and r.get("symbol") == t.get("symbol")
            and str(r.get("signal")) == str(t.get("signal"))
            and abs(float(r.get("entry", 0)) - float(t.get("entry", 0))) < 0.01
            for r in hist_completed
        )
        if not saved:
            result.append({**t, "trade_date": t.get("trade_date") or today})
    return result


def _open_positions(active: list[dict], completed: list[dict]) -> tuple[list[dict], int]:
    """Active signals an account would actually hold: the first per stock and strategy, and only if
    no counted trade on that stock/strategy was still open at that moment. → (kept, overlapping)."""
    busy: dict[tuple, list] = {}
    for t in completed:
        if not t.get("approx_time"):
            busy.setdefault((t["stock"], t["strategy"]), []).append((t["time"], t["exit_time"]))
    kept, overlap, holding = [], 0, set()
    for t in sorted(active, key=lambda t: t["time"]):
        lane = (t["stock"], t["strategy"])
        if lane in holding or any(s <= t["time"] < e for s, e in busy.get(lane, [])):
            overlap += 1
            continue
        holding.add(lane)
        kept.append(t)
    return kept, overlap


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
        all_active, mem_completed = collect_all_trades()
        hist = [t for t in load_trade_history() if t.get("strategy") in live_names]
        merged = [_normalize(t) for t in _merge_completed(mem_completed, hist)]
        usable = [t for t in merged if float(t.get("entry") or 0) > 0 and float(t.get("exit_price") or 0) > 0]
        completed, ex = finalize_trades(usable, now_ist())
        active = [_normalize(t) for t in all_active if t.get("strategy") in live_names and float(t.get("entry") or 0) > 0]
        positions, open_overlap = _open_positions(active, completed)

        data.update(completed=completed, active=positions, at=now_ist(), notes={
            "overlap": ex["overlap"] + open_overlap,
            "broken": len(merged) - len(usable),
            "approx": sum(1 for t in completed if t.get("approx_time")),
        })

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
