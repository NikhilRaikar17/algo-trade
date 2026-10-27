"""
Trade Desk — today's live signals with odds, size and a risk check, in one table.

For every signal the live engine found today (Live Algos strategies): the replay odds from
replay_engine (open signals only), and the paper account's decision — TAKEN at a size that keeps
the loss at the stop inside the max loss per trade, or SKIPPED with the reason. Each decision was
made once, when the engine first saw the signal (account.open_signal), and never changes. Nothing
is placed.

Signals come from live_signals.get_today_signals(): the engine's memory, or a read-only
rebuild from today's candles when the engine isn't scanning.
"""

import asyncio
from datetime import time

from nicegui import ui

from account import current_state, decisions
from backtest_metrics import inr
from config import RISK_LIMITS, now_ist
from data import fetch_stock_candles_history
from live_signals import get_today_signals
from replay_engine import Plan, ReplayError, run_replay
from trade_desk import TAKEN, build_rows, day_summary
from pages.trade_replay import _stock_options

_ODDS_REPLAYS = 2000
_REFRESH_SECONDS = 60

_CSS = """
<style>
  .td-limits { font-family:var(--at-mono); font-size:11px; color:var(--at-fg-dim); }
  .td-tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:10px; }
  .td-tile { background:var(--at-bg1); border:1px solid var(--at-line); border-radius:var(--at-radius); padding:12px 14px; }
  .td-k { font-family:var(--at-mono); font-size:10px; letter-spacing:.08em; text-transform:uppercase; color:var(--at-fg-faint); }
  .td-v { font-family:var(--at-cond); font-size:22px; font-weight:600; color:var(--at-fg); margin-top:4px; }
  .td-s { font-size:11px; color:var(--at-fg-dim); margin-top:2px; }
  .td-wrap { width:100%; overflow-x:auto; border:1px solid var(--at-line); border-radius:var(--at-radius); }
  .td-table { width:100%; border-collapse:collapse; font-size:12.5px; }
  .td-table th { text-align:left; font-family:var(--at-mono); font-size:10px; font-weight:500; letter-spacing:.06em;
                 text-transform:uppercase; color:var(--at-fg-faint); padding:8px 10px; border-bottom:1px solid var(--at-line);
                 white-space:nowrap; background:var(--at-bg1); }
  .td-table td { padding:8px 10px; border-bottom:1px solid var(--at-line); color:var(--at-fg); vertical-align:top; }
  .td-table tr:last-child td { border-bottom:none; }
  .td-num { text-align:right; font-family:var(--at-mono); white-space:nowrap; }
  .td-dim { color:var(--at-fg-dim); }
  .td-badge { display:inline-flex; align-items:center; gap:4px; font-family:var(--at-mono); font-size:10.5px; font-weight:600;
              padding:2px 7px; border-radius:4px; border:1px solid currentColor; white-space:nowrap; }
  .td-pass { color:var(--at-up); }
  .td-block { color:var(--at-down); }
  .td-why { font-size:11.5px; color:var(--at-fg-dim); margin-top:3px; }
  .td-table td.td-check { min-width:220px; }
  /* Below 900px each signal becomes a 2-column card with labelled values */
  @media (max-width: 899px) {
    .td-wrap { border:none; }
    .td-table thead { display:none; }
    .td-table, .td-table tbody { display:block; width:100%; }
    .td-table tr { display:grid; grid-template-columns:1fr 1fr; gap:8px 14px; padding:12px 14px; margin-bottom:10px;
                   background:var(--at-bg1); border:1px solid var(--at-line); border-radius:var(--at-radius); }
    .td-table td { display:block; padding:0; border:none !important; text-align:left !important; white-space:normal; min-width:0; }
    .td-table td::before { content:attr(data-label); display:block; font-family:var(--at-mono); font-size:9.5px;
                           letter-spacing:.06em; text-transform:uppercase; color:var(--at-fg-faint); margin-bottom:2px; }
    .td-table td.td-check, .td-table td.td-status { grid-column:1 / -1; min-width:0; }
  }
  .td-warn { font-size:11.5px; color:var(--at-warn); margin-top:3px; }
  .td-side-buy { color:var(--at-up); font-weight:600; }
  .td-side-sell { color:var(--at-down); font-weight:600; }
  .td-foot { font-family:var(--at-mono); font-size:10.5px; color:var(--at-fg-faint); line-height:1.6; margin-top:10px; }
</style>
"""


def _short_verdict(verdict: str) -> str:
    """'Leans toward the stop: target first in …' → 'leans stop'."""
    head = verdict.split(":")[0].lower()
    for long, short in (("strongly toward the target", "strong target"), ("strongly toward the stop", "strong stop"),
                        ("leans toward the target", "leans target"), ("leans toward the stop", "leans stop"),
                        ("close to a coin flip", "coin flip"), ("close to break-even", "break-even"),
                        ("mostly undecided", "undecided"), ("no replay reached", "undecided")):
        if head.startswith(long):
            return short
    return head


def render_trade_desk_tab(container):
    """Build the Trade Desk page. Returns an async refresh() closure."""
    odds_cache: dict[str, dict] = {}       # row key → {"target", "stop", "label"} or {"error"}
    history_cache: dict[tuple, object] = {}  # (security_id, date) → candles DataFrame
    state = {"busy": False, "rows": []}

    lim = dict(RISK_LIMITS)  # "funds" is replaced by the paper account's balance on every refresh

    def _limits_text():
        return (f"LIMITS · funds ₹{inr(lim['funds'])} (account balance) · max loss ₹{lim['max_loss_per_trade']:,}/trade · "
                f"≤{lim['max_capital_pct']}% of funds/trade · {lim['max_trades_per_day']} trades/day · "
                f"₹{lim['max_daily_loss']:,}/day · reward:risk ≥ {lim['min_reward_risk']} · "
                f"entries {lim['no_entries_before']}–{lim['no_entries_after']} · edit in config.RISK_LIMITS")

    with container:
        ui.add_head_html(_CSS)
        ui.label("Trade Desk").classes("text-xl font-bold mb-1")
        ui.label(
            "Today's live signals with their odds and what the paper account did with each: taken (at what size) "
            "or skipped (and why), decided once when the engine first saw it. Nothing is placed: you trade in Dhan."
        ).classes("text-sm text-gray-500 mb-1")
        limits_lbl = ui.label(_limits_text()).classes("td-limits mb-3")
        tiles = ui.element("div").classes("w-full mb-3")
        table_box = ui.element("div").classes("w-full")
        status = ui.label("").classes("td-foot")

    def _render():
        rows = state["rows"]
        s = day_summary(rows, lim)
        tiles.clear()
        with tiles:
            ui.html(f"""
            <div class="td-tiles">
              <div class="td-tile"><div class="td-k">Signals today</div><div class="td-v">{s['signals']}</div>
                <div class="td-s">{s['passed']} taken · {s['blocked']} skipped</div></div>
              <div class="td-tile"><div class="td-k">Trades used</div><div class="td-v">{s['trades_used']} / {s['trades_limit']}</div>
                <div class="td-s">taken by the paper account</div></div>
              <div class="td-tile"><div class="td-k">Loss at risk</div><div class="td-v">₹{s['loss_used']:,.0f}</div>
                <div class="td-s">of ₹{s['loss_limit']:,} daily limit</div></div>
              <div class="td-tile"><div class="td-k">Capital in taken</div><div class="td-v">₹{s['capital_passed']:,.0f}</div>
                <div class="td-s">qty × entry · funds ₹{inr(lim['funds'])}</div></div>
            </div>""")

        table_box.clear()
        with table_box:
            if not rows:
                ui.label(
                    "No live signals yet today. The engine scans the top stocks every 2 minutes in market hours, "
                    "using the strategies switched on for Live on the Strategies page."
                ).classes("text-sm text-gray-500 italic")
                return
            body = []
            for r in reversed(rows):  # newest first
                o = odds_cache.get(r.key)
                if r.status != "Active":
                    odds = '<span class="td-dim">closed</span>'
                elif o is None:
                    odds = '<span class="td-dim">computing…</span>'
                elif "error" in o:
                    odds = f'<span class="td-dim" title="{o["error"]}">n/a</span>'
                else:
                    odds = (f'{o["target"]:.0f}% / {o["stop"]:.0f}%'
                            f'<div class="td-why">{o["label"]}</div>')
                if not r.verdict:
                    badge = '<span class="td-badge td-dim">not decided</span>'
                    r.reasons = ["the live engine has not seen this signal (it was not scanning)"]
                elif r.verdict == TAKEN:
                    badge = f'<span class="td-badge td-pass">✓ TAKEN {r.decided_at:%H:%M}</span>'
                else:
                    badge = f'<span class="td-badge td-block">✕ SKIPPED {r.decided_at:%H:%M}</span>'
                why = "".join(f'<div class="td-why">{x}</div>' for x in r.reasons)
                warn = "".join(f'<div class="td-warn">⚠ {x}</div>' for x in r.warnings)
                label = r.status
                if r.status == "Active" and now_ist().time() >= time(15, 30):
                    label = "Open at close"
                status_txt = label if r.current_price is None else f"{label} · ₹{r.current_price:,.2f}"
                body.append(f"""
                <tr>
                  <td class="td-num" data-label="Time">{r.signal_time:%H:%M}</td>
                  <td data-label="Stock"><b>{r.symbol}</b><div class="td-why">{r.strategy}</div></td>
                  <td class="td-side-{r.side.lower()}" data-label="Side">{r.side}</td>
                  <td class="td-num" data-label="Entry / plan">₹{r.entry:,.2f}<div class="td-why">stop ₹{r.stop:,.2f}<br>target ₹{r.target:,.2f}</div></td>
                  <td class="td-num" data-label="R:R">{r.reward_risk:.2f}</td>
                  <td class="td-num" data-label="Odds T/S">{odds}</td>
                  <td class="td-num" data-label="Size">{f"{r.qty:,} sh" if r.qty else "—"}<div class="td-why">₹{r.capital:,.0f}<br>max loss ₹{r.max_loss:,.0f}</div></td>
                  <td class="td-check" data-label="Risk check">{badge}{why}{warn}</td>
                  <td class="td-dim td-status" data-label="Status">{status_txt}</td>
                </tr>""")
            ui.html(f"""
            <div class="td-wrap"><table class="td-table">
              <thead><tr>
                <th>Time</th><th>Stock</th><th>Side</th><th style="text-align:right">Entry / plan</th>
                <th style="text-align:right" title="reward ÷ risk">R:R</th>
                <th style="text-align:right" title="replays: target first / stop first">Odds T/S</th>
                <th style="text-align:right" title="max loss = loss if the stop fills at the stop price">Size</th>
                <th>Risk check</th><th>Status</th>
              </tr></thead>
              <tbody>{''.join(body)}</tbody>
            </table></div>""")

    def _odds_for(row, name_to_sid):
        """Replay odds for one open signal (runs in a worker thread)."""
        sid = name_to_sid.get(row.symbol)
        if not sid:
            return {"error": f"{row.symbol} is not in the stock list"}
        key = (sid, now_ist().date())
        if key not in history_cache:
            history_cache[key] = fetch_stock_candles_history(sid, interval=5, days=60)
        candles = history_cache[key]
        if candles is None or candles.empty:
            return {"error": "no history from Dhan"}
        t = row.signal_time.time()
        try:
            plan = Plan(row.entry, row.stop, row.target, time(t.hour, t.minute - t.minute % 5), time(15, 15))
            res = run_replay(candles, plan, now_ist().date(), replays=_ODDS_REPLAYS, seed=19)
        except ReplayError as e:
            return {"error": str(e)}
        return {"target": res.target_pct, "stop": res.stop_pct, "label": _short_verdict(res.verdict)}

    async def refresh():
        if state["busy"] or container.client._deleted:
            return
        state["busy"] = True
        try:
            loop = asyncio.get_event_loop()
            active, completed, source = await loop.run_in_executor(None, get_today_signals)
            try:
                lim["funds"] = (await loop.run_in_executor(None, current_state))["balance"]
            except Exception as e:  # keep the last known funds rather than block the desk
                print(f"  [trade_desk] account: {e}")
            if container.client._deleted:
                return
            limits_lbl.set_text(_limits_text())
            book = await loop.run_in_executor(None, decisions)
            state["rows"] = build_rows(active, completed, book)
            _render()
            status.set_text(f"Updated {now_ist():%H:%M:%S} · source: {source} · refreshes every {_REFRESH_SECONDS}s "
                            f"while open · odds from {_ODDS_REPLAYS:,} replays of the last 60 days, exit 15:15, seed 19")

            missing = [r for r in state["rows"] if r.status == "Active" and r.key not in odds_cache]
            if missing:
                name_to_sid = {v: k for k, v in _stock_options().items()}
                loop = asyncio.get_event_loop()
                for r in missing:
                    odds_cache[r.key] = await loop.run_in_executor(None, _odds_for, r, name_to_sid)
                    if container.client._deleted:
                        return
                    _render()
        finally:
            state["busy"] = False

    async def _tick():
        if container.visible:
            await refresh()

    with container:
        ui.timer(_REFRESH_SECONDS, _tick)

    return refresh
