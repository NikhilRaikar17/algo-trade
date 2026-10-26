"""
Strategy Analysis — is each strategy worth keeping? Every strategy (switched on or not) is run through
the last 7 days of backtest on the top stocks and through the paper account's live trades, each on
its own ₹ funds (risk the max loss at the stop, compounding, after brokerage and taxes). The verdict
rule lives in strategy_review.py and config.STRATEGY_REVIEW.
"""

import asyncio
import traceback
from collections import defaultdict
from html import escape

from nicegui import ui

from account import get_settings, in_account
from backtest_metrics import DEFAULT_FUNDS, DEFAULT_MODE, DEFAULT_SIZING, size_trades, sizing_label
from config import STRATEGY_NAMES, STRATEGY_REVIEW, now_ist
from db import get_active_top_stocks
from live_trades import load_live_trades
from pages.backtest_pnl_tab import _fetch_all_stocks_trades
from pages.pnl_widgets import CSS, rs, td, tone
from state import is_market_open
from strategy_registry import get_strategy_rows
from strategy_review import GOOD, NOT_GOOD, TOO_EARLY, WATCH, judge_source, verdict, StrategyReview

_CACHE_SECONDS = 300
_VERDICT_CLS = {NOT_GOOD: "bt-down", WATCH: "bt-warn", GOOD: "bt-up", TOO_EARLY: "bt-dim"}

_PAGE_CSS = """
<style>
  .sa-rule { font-size:12.5px; color:var(--at-fg-dim); line-height:1.6; }
  .sa-rule b { color:var(--at-fg); }
  .sa-counts { display:flex; flex-wrap:wrap; gap:8px; }
  .sa-count { font-family:var(--at-mono); font-size:11px; padding:4px 10px; border-radius:999px;
              border:1px solid currentColor; }
  .sa-rate { display:flex; align-items:center; justify-content:flex-end; gap:8px; }
  .sa-track { width:64px; height:6px; border-radius:3px; background:var(--at-bg3); position:relative; flex-shrink:0; }
  .sa-track > span { position:absolute; left:0; top:0; bottom:0; border-radius:3px; }
  .sa-track::after { content:''; position:absolute; top:-3px; bottom:-3px; width:1px; background:var(--at-fg-dim);
                     left:var(--limit); }
  .sa-why { font-size:11.5px; color:var(--at-fg-dim); white-space:normal; line-height:1.5; margin-top:3px; }
  .sa-on { font-family:var(--at-mono); font-size:9.5px; letter-spacing:.04em; color:var(--at-fg-faint); margin-top:2px; }
  .bt-table td.sa-verdict { width:34%; min-width:220px; white-space:normal; }
  @media (max-width: 899px) { .bt-table td.sa-verdict { grid-column:1 / -1; min-width:0; } .sa-rate { justify-content:flex-start; } }
</style>
"""


def _name_to_key() -> dict[str, str]:
    """Live trades are tagged with config.STRATEGY_NAMES values; map them back to keys."""
    return {v: k for k, v in STRATEGY_NAMES.items()}


def _rate_cell(src, limit) -> str:
    if not src.trades:
        return '<span class="bt-dim">no trades</span>'
    colour = "var(--at-down)" if src.loss_rate > limit else "var(--at-up)"
    return (f'<div class="sa-rate"><span>{src.loss_rate:.0f}% <span class="bt-dim">· {src.losses}/{src.trades}</span></span>'
            f'<span class="sa-track" style="--limit:{limit}%"><span style="width:{min(src.loss_rate, 100):.0f}%;'
            f'background:{colour}"></span></span></div>')


def _net_cell(src) -> str:
    if not src.trades:
        return '<span class="bt-dim">—</span>'
    end = f'<div class="bt-dim" style="font-size:11px">→ {rs(src.end_balance)}</div>' if src.end_balance else ""
    return f'<b class="{tone(src.net)}">{rs(src.net, sign=True)}</b>{end}'


def _table(reviews: list[StrategyReview], flags: dict) -> str:
    limit = STRATEGY_REVIEW["max_loss_rate"]
    head = ('<tr><th>Strategy</th><th class="n">Backtest losing</th><th class="n">Backtest net</th>'
            '<th class="n">Live losing</th><th class="n">Live net</th><th>Verdict</th></tr>')
    rows = []
    for r in reviews:
        f = flags.get(r.key, {})
        on = " · ".join(w for w, k in (("BACKTEST ON", "backtest_enabled"), ("LIVE ON", "live_enabled")) if f.get(k)) or "SWITCHED OFF"
        why = "<br>".join(escape(x) for x in r.reasons)
        if r.verdict == NOT_GOOD and f.get("live_enabled"):
            why += "<br><b>Still switched on for Live</b> — you can turn it off on the Strategies page."
        rows.append(
            "<tr>"
            + td("Strategy", f'<b>{escape(r.name)}</b><div class="sa-on">{on}</div>', "wide")
            + td("Backtest losing", _rate_cell(r.backtest, limit), "n")
            + td("Backtest net", _net_cell(r.backtest), "n")
            + td("Live losing", _rate_cell(r.live, limit), "n")
            + td("Live net", _net_cell(r.live), "n")
            + td("Verdict", f'<span class="bt-badge {_VERDICT_CLS[r.verdict]}">{r.verdict}</span>'
                            f'<div class="sa-why">{why}</div>', "sa-verdict")
            + "</tr>"
        )
    return f'<div class="bt-wrap"><table class="bt-table"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def build_reviews(backtest_trades: list[dict], live_trades: list[dict], strategy_rows: list[dict],
                  live_funds: float) -> list[StrategyReview]:
    """One review per strategy. Each source is sized as its own account: risk the max loss at the
    stop, cut to the funds, compounding, after charges."""
    mode, amount, rules = DEFAULT_MODE, DEFAULT_SIZING[DEFAULT_MODE], STRATEGY_REVIEW
    by_key_bt, by_key_live = defaultdict(list), defaultdict(list)
    for t in backtest_trades:
        by_key_bt[t.get("strategy_key")].append(t)
    names = _name_to_key()
    for t in live_trades:
        by_key_live[names.get(t.get("strategy"), t.get("strategy"))].append(t)
    out = []
    for row in strategy_rows:
        k = row["key"]
        bt = judge_source(size_trades(by_key_bt[k], mode, amount, DEFAULT_FUNDS, compound=True), rules, DEFAULT_FUNDS)
        lv = judge_source(size_trades(by_key_live[k], mode, amount, live_funds, compound=True), rules, live_funds)
        v, reasons = verdict(bt, lv, rules)
        out.append(StrategyReview(key=k, name=row["display_name"], backtest=bt, live=lv, verdict=v, reasons=reasons))
    order = {NOT_GOOD: 0, WATCH: 1, GOOD: 2, TOO_EARLY: 3}
    return sorted(out, key=lambda r: (order[r.verdict], -r.backtest.trades))


def render_strategy_analysis_tab(container):
    """Build the Strategy Analysis page. Returns an async refresh() closure."""
    st = {"busy": False, "cache": None}
    rules = STRATEGY_REVIEW

    with container:
        ui.add_head_html(CSS)
        ui.add_head_html(_PAGE_CSS)
        with ui.row().classes("w-full items-end justify-between gap-2 mb-1"):
            with ui.column().classes("gap-0"):
                ui.label("Strategy Analysis").classes("text-xl font-bold")
                ui.label(f"Every strategy · backtest: last 7 days on the top stocks · live: the paper account's trades · "
                         f"{sizing_label(funds=None)}, compounding · after brokerage and taxes").classes("bt-sub")
            rerun_btn = ui.button("Re-run", icon="refresh").props("flat dense no-caps")
        ui.html(f"""
        <div class="bt-card sa-rule mt-3">
          A strategy is <b class="bt-down">Not good</b> when more than <b>{rules['max_loss_rate']}%</b> of its trades
          lose money after charges, in the backtest <i>and</i> in live trading.
          <b class="bt-warn">Watch</b>: one passes, the other fails. <b class="bt-up">Good</b>: both pass.
          A source needs at least <b>{rules['min_trades']}</b> trades to count; with only one source judged,
          the verdict follows it. Each strategy is sized as its own account, so it doesn't compete
          with the others for funds. The limits are in <code>config.STRATEGY_REVIEW</code>.
        </div>""")
        counts = ui.html("").classes("mt-3")
        status = ui.html("").classes("bt-status mt-2 mb-2")
        body = ui.element("div").classes("w-full")
        with body:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")

    def _render(reviews, flags, note):
        n = defaultdict(int)
        for r in reviews:
            n[r.verdict] += 1
        counts.set_content('<div class="sa-counts">' + "".join(
            f'<span class="sa-count {_VERDICT_CLS[v]}">{n[v]} {v.lower()}</span>'
            for v in (NOT_GOOD, WATCH, GOOD, TOO_EARLY) if n[v]) + "</div>")
        status.set_content(note)
        body.clear()
        with body:
            ui.html(_table(reviews, flags))

    def _gather():
        """Runs in a worker thread: backtests for every strategy, plus the live account's trades."""
        rows = get_strategy_rows()
        report: dict = {}
        bt = _fetch_all_stocks_trades(get_active_top_stocks(), report, keys=[r["key"] for r in rows])
        completed, _, _ = load_live_trades()
        live = in_account(completed)
        return rows, bt, live, report

    async def _load(force=False):
        if st["busy"] or body.client._deleted:
            return
        c = st["cache"]
        fresh = c and (now_ist() - c["at"]).total_seconds() < _CACHE_SECONDS if is_market_open() \
            else c and c["at"].date() == now_ist().date()
        st["busy"] = True
        rerun_btn.props("loading")
        try:
            if force or not fresh:
                body.clear()
                with body:
                    with ui.column().classes("w-full items-center py-10 gap-2"):
                        ui.spinner("dots", size="lg")
                        ui.label("Backtesting every strategy on the top stocks…").classes("text-sm bt-dim")
                rows, bt, live, report = await asyncio.get_event_loop().run_in_executor(None, _gather)
                st["cache"] = c = {"rows": rows, "bt": bt, "live": live, "report": report, "at": now_ist()}
            if body.client._deleted:
                return
            acct = get_settings()
            reviews = build_reviews(c["bt"], c["live"], c["rows"], float(acct["initial"]))
            r = c["report"]
            note = (f"<b>{len(r.get('loaded', []))}/{len(r.get('loaded', [])) + len(r.get('missing', []))}</b> stocks backtested"
                    f" · <b>{len(c['live'])}</b> live trades since the account started "
                    f"{escape(str(acct['start'])[:16].replace('T', ' '))}"
                    f" · ran {c['at']:%H:%M}")
            _render(reviews, {x["key"]: x for x in c["rows"]}, note)
        except Exception as e:
            print(f"  [strategy_analysis] error:\n{traceback.format_exc()}")
            if not body.client._deleted:
                body.clear()
                with body:
                    ui.html(f'<div class="bt-card bt-empty bt-down">Analysis failed: {escape(str(e))}</div>')
        finally:
            st["busy"] = False
            if not body.client._deleted:
                rerun_btn.props(remove="loading")

    rerun_btn.on_click(lambda: asyncio.ensure_future(_load(force=True)))

    async def refresh():
        await _load()

    return refresh
