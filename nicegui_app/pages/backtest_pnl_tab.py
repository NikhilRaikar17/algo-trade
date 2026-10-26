"""
Backtest P&L — every backtest-enabled strategy run over the top stocks' recent candles.

Trades come from the strategy backtests in algo_strategies; backtest_metrics keeps the ones an
account could have taken (filled, finished, one position per stock and strategy), sizes them and
nets off Dhan's charges. _fetch_all_stocks_trades() also feeds the emailed Excel report.
"""

import asyncio
import time as _time
import traceback
from datetime import datetime
from html import escape

from nicegui import ui

from algo_strategies import (
    find_swing_points, detect_abcd_patterns, backtest_abcd,
    detect_double_top_custom_signals, backtest_double_top_custom,
    detect_double_top_standard_signals, backtest_double_top_standard,
    detect_double_bottom_signals, backtest_double_bottom,
    detect_sma50_signals, backtest_sma50,
    detect_ema10_signals, backtest_ema10,
)
from backtest_metrics import DEFAULT_FUNDS, inr, DEFAULT_MODE, DEFAULT_SIZING, finalize_trades, group_by, size_trades, summarize
from config import now_ist
from data import _fetch_any_stock_candles
from db import get_active_top_stocks
from pages.pnl_widgets import (
    CSS, charges_html, equity_figure, kpi_tiles, sizing_controls, strategy_table, summary_table, trades_table,
)
from state import is_market_open
from strategy_registry import get_backtest_strategy_keys, get_backtest_strategy_names

_ALL_KEY = "ALL:ALL:ALL"
_CACHE_SECONDS = 300  # while the market is open; after the close results hold until the next day

# ── Backtest runner ───────────────────────────────────────────────────────────

_REQUIRED_COLS = {"timestamp", "open", "high", "low", "close"}


def _run_abcd(candles):
    return backtest_abcd(detect_abcd_patterns(find_swing_points(candles, order=2)), candles)


def _run_double_top_custom(candles):
    return backtest_double_top_custom(detect_double_top_custom_signals(candles), candles)


def _run_double_top_standard(candles):
    return backtest_double_top_standard(detect_double_top_standard_signals(candles), candles)


def _run_double_bottom(candles):
    return backtest_double_bottom(detect_double_bottom_signals(candles), candles)


def _run_sma50(candles):
    signals, _ = detect_sma50_signals(candles)
    return backtest_sma50(signals, candles)


def _run_ema10(candles):
    signals, _ = detect_ema10_signals(candles)
    return backtest_ema10(signals, candles)


_RUNNERS = [
    ("abcd",  "ABCD",                  _run_abcd),
    ("dtc",   "Double Top Customized", _run_double_top_custom),
    ("dts",   "Double Top Standard",   _run_double_top_standard),
    ("db",    "Double Bottom",         _run_double_bottom),
    ("sma50", "SMA 50",                _run_sma50),
    ("ema10", "EMA 10",                _run_ema10),
]


def _run_all_backtests(candles, stock_name: str = "", enabled_keys=None, excluded: dict | None = None):
    """Run every backtest-enabled strategy on one stock's candles. Returns the trades an account
    could have taken (see backtest_metrics.finalize_trades); skipped counts are added to `excluded`."""
    if candles is None or candles.empty or not _REQUIRED_COLS.issubset(candles.columns):
        return []
    if enabled_keys is None:
        enabled_keys = get_backtest_strategy_keys()
    raw = []
    for key, name, fn in _RUNNERS:
        if key not in enabled_keys:
            continue
        try:
            for t in fn(candles):
                t["strategy"] = name
                t["stock"] = stock_name
                when = t.get("time")
                t["trade_date"] = when.strftime("%Y-%m-%d") if hasattr(when, "strftime") else str(when)[:10]
                raw.append(t)
        except Exception as e:
            print(f"  [backtest_pnl] {name} error: {e}")
    kept, skipped = finalize_trades(raw, now_ist())
    if excluded is not None:
        for k, v in skipped.items():
            excluded[k] = excluded.get(k, 0) + v
    return kept


def _fetch_all_stocks_trades(stocks: list[dict], report: dict | None = None) -> list[dict]:
    """Fetch candles for every stock and run the backtests. `report` (optional) receives
    loaded / missing stock names and the excluded-trade counts."""
    report = report if report is not None else {}
    report.update(loaded=[], missing=[], excluded={})
    enabled_keys = get_backtest_strategy_keys()
    all_trades = []
    if not enabled_keys:
        return all_trades
    for i, stock in enumerate(stocks):
        if i:
            _time.sleep(0.35)  # Dhan rate limit: back-to-back calls silently fail
        try:
            candles = _fetch_any_stock_candles(stock["security_id"], retries=3)
            if candles is None or candles.empty:
                report["missing"].append(stock["name"])
                continue
            report["loaded"].append(stock["name"])
            all_trades.extend(_run_all_backtests(candles, stock["name"], enabled_keys, report["excluded"]))
        except Exception as e:
            report["missing"].append(stock["name"])
            print(f"  [backtest_pnl ALL] {stock['name']} error: {e}")
    return all_trades


# ── Page renderer ─────────────────────────────────────────────────────────────

def render_backtest_pnl_tab(container):
    """Build the Backtest P&L tab. Returns an async refresh() closure."""

    st = {"key": None, "label": "", "strategy": "All", "date": "All", "stock": "All",
          "view": "strategy", "mode": DEFAULT_MODE, "amount": DEFAULT_SIZING[DEFAULT_MODE], "funds": DEFAULT_FUNDS, "compound": True, "busy": False}
    data = {"trades": [], "report": {}, "stocks": [], "ran_at": None, "funds_report": {}}
    cache: dict[str, dict] = {}

    with container:
        ui.add_head_html(CSS)
        with ui.row().classes("w-full items-end justify-between gap-2 mb-1"):
            with ui.column().classes("gap-0"):
                ui.label("Backtest P&L").classes("text-xl font-bold")
                ui.label("Strategies switched on for backtest · 15-min candles · last 7 days · "
                         "after Dhan intraday charges").classes("bt-sub")
            rerun_btn = ui.button("Re-run", icon="refresh").props("flat dense no-caps")

        with ui.element("div").classes("bt-bar w-full mt-3"):
            stock_sel = ui.select(options={}, value=None, label="Stocks").props("outlined dense use-input input-debounce=0")
            strat_sel = ui.select(["All"], value="All", label="Strategy").props("outlined dense")
            date_sel = ui.select(["All"], value="All", label="Day").props("outlined dense")
            stock_filter = ui.select(["All"], value="All", label="Stock").props("outlined dense")
            sizing_controls(st, lambda: _render())
            ui.switch("Compound", value=True, on_change=lambda e: (st.update(compound=e.value), _render())) \
                .tooltip("On: the funds are the starting balance and every day's net P&L (after charges) "
                         "carries into the next. Off: every day starts with the same funds.")
        status = ui.html("").classes("bt-status mt-2 mb-3")
        body = ui.element("div").classes("w-full")
        with body:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")

    # ── rendering ─────────────────────────────────────────────────────────────

    def _filtered(trades, *, strategy=True):
        out = trades
        if strategy and st["strategy"] != "All":
            out = [t for t in out if t["strategy"] == st["strategy"]]
        if st["date"] != "All":
            out = [t for t in out if t["trade_date"] == st["date"]]
        if st["stock"] != "All":
            out = [t for t in out if t.get("stock") == st["stock"]]
        return out

    def _status_line():
        r, parts = data["report"], []
        if r.get("loaded") is not None:
            total = len(r["loaded"]) + len(r["missing"])
            parts.append(f"<b>{len(r['loaded'])}/{total}</b> stocks loaded")
            if r["missing"]:
                parts.append(f'<span class="bt-warn">no data: {escape(", ".join(r["missing"]))}</span>')
        ex = r.get("excluded", {})
        skipped = [f"{n} {what}" for what, n in (("still open today", ex.get("open", 0)),
                                                  ("never filled", ex.get("no_fill", 0)),
                                                  ("overlapping an open position", ex.get("overlap", 0))) if n]
        fr = data["funds_report"]
        if fr.get("no_funds"):
            skipped.append(f'{fr["no_funds"]} with no free funds')
        if skipped:
            parts.append("not counted: " + ", ".join(skipped))
        if fr.get("cut"):
            parts.append(f'{fr["cut"]} sized down to fit the funds')
        if st["funds"] and st["compound"] and "end_balance" in fr:
            parts.append(f'<b>₹{inr(st["funds"])} → ₹{inr(fr["end_balance"])}</b> compounding, after charges')
        if data["ran_at"]:
            parts.append(f"ran {data['ran_at'].strftime('%H:%M')}")
        status.set_content(" · ".join(parts))

    def _render():
        _status_line()
        body.clear()
        enabled = get_backtest_strategy_names()
        with body:
            if not enabled:
                ui.html('<div class="bt-card bt-empty">No strategies are switched on for backtest. '
                        'Turn some on in <b>Strategies</b>.</div>')
                return
            if not data["trades"]:
                ui.html('<div class="bt-card bt-empty">No finished trades in the last 7 days for this selection.</div>')
                return

            sized_all = size_trades(data["trades"], st["mode"], st["amount"], st["funds"], data["funds_report"],
                                    compound=st["compound"])
            _status_line()
            trades = _filtered(sized_all)
            s = summarize(trades)
            ui.html(kpi_tiles(s))
            ui.html(charges_html(s))

            if not trades:
                ui.html('<div class="bt-card bt-empty mt-3">No trades match these filters.</div>')
                return

            with ui.element("div").classes("bt-card w-full mt-3"):
                whole = len(trades) == len(sized_all) and st["funds"] and st["compound"]
                if whole:
                    ui.html('<div class="bt-h">Account balance</div>'
                            '<div class="bt-hs">Starting funds plus every trade\'s net P&amp;L after charges, compounding. '
                            'Hover a point for the trade.</div>')
                else:
                    ui.html('<div class="bt-h">Equity curve</div>'
                            '<div class="bt-hs">Cumulative net P&amp;L, one point per trade. Hover a point for the trade.</div>')
                ui.plotly(equity_figure(trades, base=st["funds"] if whole else 0)).classes("w-full")

            with ui.row().classes("w-full items-center justify-between mt-4 mb-2 gap-2"):
                ui.label("Breakdown").classes("bt-h")
                ui.toggle({"strategy": "By strategy", "day": "By day", "stock": "By stock", "trades": "Trades"},
                          value=st["view"], on_change=lambda e: (st.update(view=e.value), _render())) \
                    .props("dense no-caps unelevated toggle-color=primary").classes("bt-seg")

            view = st["view"]
            if view == "strategy":
                _strategy_table(sized_all)
            elif view == "day":
                groups = sorted(group_by(trades, "trade_date"), key=lambda kv: kv[0], reverse=True)
                groups = [(datetime.strptime(d, "%Y-%m-%d").strftime("%a %d %b"), g) for d, g in groups]
                ui.html(summary_table(groups, "Day"))
            elif view == "stock":
                ui.html(summary_table(group_by(trades, "stock"), "Stock"))
            else:
                ui.html(trades_table(trades, show_stock=st["key"] == _ALL_KEY))

    def _strategy_table(sized_all):
        groups = dict(group_by(_filtered(sized_all, strategy=False), "strategy"))
        strategy_table(groups, get_backtest_strategy_names(), st["strategy"], _pick_strategy)

    def _pick_strategy(name):
        strat_sel.set_value("All" if st["strategy"] == name else name)  # fires _on_filter → _render

    # ── filters ───────────────────────────────────────────────────────────────

    def _sync_filter_options():
        trades = data["trades"]
        strategies = ["All"] + sorted({t["strategy"] for t in trades})
        dates = ["All"] + sorted({t["trade_date"] for t in trades}, reverse=True)
        stocks = ["All"] + sorted({t["stock"] for t in trades if t.get("stock")})
        for sel, key, opts in ((strat_sel, "strategy", strategies), (date_sel, "date", dates), (stock_filter, "stock", stocks)):
            if st[key] not in opts:
                st[key] = "All"
            sel.set_options(opts, value=st[key])
        stock_filter.set_visibility(st["key"] == _ALL_KEY)

    def _on_filter(key, value):
        if value is None or st[key] == value:
            return
        st[key] = value
        _render()

    strat_sel.on_value_change(lambda e: _on_filter("strategy", e.value))
    date_sel.on_value_change(lambda e: _on_filter("date", e.value))
    stock_filter.on_value_change(lambda e: _on_filter("stock", e.value))

    # ── data ──────────────────────────────────────────────────────────────────

    def _fresh(entry) -> bool:
        if entry is None or entry["enabled"] != tuple(get_backtest_strategy_keys()):
            return False
        age = (now_ist() - entry["at"]).total_seconds()
        return age < _CACHE_SECONDS if is_market_open() else entry["at"].date() == now_ist().date()

    async def _load(key: str, label: str, force: bool = False):
        st["key"], st["label"] = key, label
        if body.client._deleted or st["busy"]:
            return
        entry = cache.get(key)
        if not force and _fresh(entry):
            data.update(trades=entry["trades"], report=entry["report"], ran_at=entry["at"])
            _sync_filter_options()
            _render()
            return

        st["busy"] = True
        rerun_btn.props("loading")
        body.clear()
        with body:
            with ui.column().classes("w-full items-center py-10 gap-2"):
                ui.spinner("dots", size="lg")
                n = len(data["stocks"]) if key == _ALL_KEY else 1
                ui.label(f"Running backtests for {label}" + (f" · {n} stocks, about {n // 2 + 1}s" if n > 1 else "") + "…") \
                    .classes("text-sm bt-dim")
        try:
            loop = asyncio.get_event_loop()
            report: dict = {}
            if key == _ALL_KEY:
                stocks = data["stocks"]
                trades = await loop.run_in_executor(None, lambda: _fetch_all_stocks_trades(stocks, report))
            else:
                _, sec_id, name = key.split(":", 2)
                trades = await loop.run_in_executor(None, lambda: _fetch_all_stocks_trades(
                    [{"security_id": sec_id, "name": name}], report))
            if body.client._deleted:
                return
            ran_at = now_ist()
            cache[key] = {"trades": trades, "report": report, "at": ran_at,
                          "enabled": tuple(get_backtest_strategy_keys())}
            data.update(trades=trades, report=report, ran_at=ran_at)
            _sync_filter_options()
            _render()
        except Exception as e:
            print(f"  [backtest_pnl:{label}] error:\n{traceback.format_exc()}")
            if not body.client._deleted:
                body.clear()
                with body:
                    ui.html(f'<div class="bt-card bt-empty bt-down">Backtest failed: {escape(str(e))}</div>')
        finally:
            st["busy"] = False
            if not body.client._deleted:
                rerun_btn.props(remove="loading")

    def _on_stock(e):
        if e.value and e.value != st["key"]:
            st["stock"] = "All"
            asyncio.ensure_future(_load(e.value, (stock_sel.options or {}).get(e.value, "")))

    stock_sel.on_value_change(_on_stock)
    rerun_btn.on_click(lambda: asyncio.ensure_future(_load(st["key"], st["label"], force=True)) if st["key"] else None)

    async def refresh():
        stocks = await asyncio.get_event_loop().run_in_executor(None, get_active_top_stocks)
        data["stocks"] = stocks
        options = {_ALL_KEY: f"All top stocks ({len(stocks)})"}
        options.update({f"EQ:{s['security_id']}:{s['name']}": s["name"] for s in stocks})
        if stock_sel.client._deleted:
            return
        key = st["key"] if st["key"] in options else _ALL_KEY
        st["key"] = key  # set first so the select's change event below doesn't start a second load
        stock_sel.set_options(options, value=key)
        await _load(key, options[key])

    return refresh
