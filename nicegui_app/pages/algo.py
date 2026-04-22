"""
Live algo trading tab — all strategies, top-stocks equity selector, 0.5s WS ticker.

Candles are fetched once on initial load (or when stock/strategy changes).
A 30s timer checks if a new 5-min candle has closed via the WS feed and
appends it in-place, then re-runs signals without a full page re-render.
The global 120s refresh is a no-op for this tab.
"""

import asyncio
import pandas as pd
from nicegui import ui
from dhanhq import marketfeed as mf

from config import now_ist
from state import _trade_store
from data import _fetch_any_stock_candles, STOCK_WATCH_GROUPS
from algo_strategies import (
    # ABCD
    find_swing_points,
    detect_abcd_patterns,
    classify_trades,
    # Double Top / Bottom
    detect_double_top_custom_signals,
    classify_double_top_custom_trades,
    detect_double_bottom_signals,
    classify_double_bottom_trades,
    # EMA10 / SMA50
    detect_ema10_signals,
    classify_ema10_trades,
    detect_sma50_signals,
    classify_sma50_trades,
)
from tv_charts import (
    render_tv_abcd_chart,
    render_tv_double_top_custom_chart,
    render_tv_double_bottom_chart,
    render_tv_ema10_chart,
    render_tv_sma50_chart,
    flush_pending_js,
)
from ui_components import build_trade_table
from strategy_registry import get_strategies
import ws_feed

_STRATEGIES = get_strategies()

# Flatten all stocks from all groups for the selector
_ALL_STOCKS: list[dict] = []
for _grp in STOCK_WATCH_GROUPS:
    _ALL_STOCKS.extend(_grp["stocks"])

_STOCK_OPTIONS: dict[str, str] = {s["security_id"]: s["name"] for s in _ALL_STOCKS}
_STOCK_BY_SID:  dict[str, dict] = {s["security_id"]: s for s in _ALL_STOCKS}


def _fmt_time(t):
    if t is None:
        return "—"
    return t.strftime("%d %b %H:%M") if hasattr(t, "strftime") else str(t)


def _candle_minute(ts) -> int:
    """Return a monotonic minute-bucket integer for a pandas Timestamp."""
    return ts.hour * 60 + ts.minute


# ── live price ticker ─────────────────────────────────────────────────────────

def _build_live_ticker(container, security_id, stock_name, active_timers):
    """Build a live bid/ask ticker table for an equity, updated every 0.5s."""
    live_labels = {}

    with container:
        with ui.element("div").classes("w-full overflow-x-auto mb-3"):
            with ui.element("table").classes("text-sm border-collapse w-full"):
                with ui.element("thead"):
                    with ui.element("tr").style("background:#141a1f;"):
                        for col in ["Stock", "LTP", "Bid (Qty)", "Ask (Qty)", "Spread", "OI", "Volume"]:
                            with ui.element("th").classes("px-3 py-1 text-left font-semibold border-b text-xs"):
                                ui.label(col)
                with ui.element("tbody"):
                    with ui.element("tr").classes("border-b").style("background:rgba(79,140,255,0.08);"):
                        with ui.element("td").classes("px-3 py-1"):
                            ui.label(stock_name).classes("text-xs text-blue-700 font-bold")
                        for field, cls in [
                            ("ltp",    "font-semibold"),
                            ("bid",    "text-emerald-600"),
                            ("ask",    "text-orange-600"),
                            ("spread", "text-gray-600"),
                            ("oi",     ""),
                            ("vol",    ""),
                        ]:
                            with ui.element("td").classes("px-3 py-1"):
                                lbl = ui.label("–").classes(f"text-xs {cls}")
                                live_labels[field] = lbl

    def _update():
        if container.client._deleted:
            return
        q = ws_feed.get_quote(security_id)
        if not q:
            return
        ltp    = q.get("ltp", 0)
        bid    = q.get("bid", 0)
        ask    = q.get("ask", 0)
        bq     = q.get("bid_qty", 0)
        aq     = q.get("ask_qty", 0)
        spread = round(ask - bid, 2)
        live_labels["ltp"].set_text(f"₹{ltp:,.2f}")
        live_labels["bid"].set_text(f"₹{bid:,.2f} ({bq:,})")
        live_labels["ask"].set_text(f"₹{ask:,.2f} ({aq:,})")
        live_labels["spread"].set_text(f"₹{spread:,.2f}")
        live_labels["oi"].set_text(f"{q.get('oi', 0):,}")
        live_labels["vol"].set_text(f"{q.get('volume', 0):,}")

    _update()
    t = ui.timer(0.5, _update)
    active_timers.append(t)


# ── trade tables ──────────────────────────────────────────────────────────────

def _active_rows(active, current_price, algo_type):
    rows = []
    for t in active:
        row = {
            "Signal":      t.get("signal", ""),
            "Entry":       t.get("entry", ""),
            "Target":      t.get("target", ""),
            "Stop Loss":   t.get("stop_loss", ""),
            "Current":     round(current_price, 2),
            "Unreal. PnL": t.get("unrealized_pnl", ""),
            "Time":        _fmt_time(t.get("time")),
        }
        if algo_type == "abcd":
            row["Pattern"] = t.get("type", "")
            row["BC Ret."] = t.get("BC_retrace", "")
            row["CD/AB"]   = t.get("CD_AB_ratio", "")
        rows.append(row)
    return rows


def _completed_rows(completed, algo_type):
    rows = []
    for t in completed:
        row = {
            "Signal":    t.get("signal", ""),
            "Entry":     t.get("entry", ""),
            "Target":    t.get("target", ""),
            "Stop Loss": t.get("stop_loss", ""),
            "Exit":      round(t.get("exit_price", 0), 2),
            "PnL":       t.get("pnl", ""),
            "Status":    t.get("status", ""),
            "Time":      _fmt_time(t.get("time")),
        }
        if algo_type == "abcd":
            row["Pattern"] = t.get("type", "")
            row["BC Ret."] = t.get("BC_retrace", "")
            row["CD/AB"]   = t.get("CD_AB_ratio", "")
        rows.append(row)
    return rows


def _render_trade_tabs(active, completed, current_price, algo_type):
    with ui.tabs().classes("w-full mt-4") as trade_tabs:
        active_tab    = ui.tab(f"Active Trades ({len(active)})")
        completed_tab = ui.tab(f"Completed Trades ({len(completed)})")

    with ui.tab_panels(trade_tabs, value=active_tab).classes("w-full"):
        with ui.tab_panel(active_tab):
            if not active:
                ui.label("No active trades").classes("text-gray-500 italic")
            else:
                build_trade_table(ui.element("div").classes("w-full"),
                                  _active_rows(active, current_price, algo_type),
                                  "Unreal. PnL")

        with ui.tab_panel(completed_tab):
            if not completed:
                ui.label("No completed trades").classes("text-gray-500 italic")
            else:
                build_trade_table(ui.element("div").classes("w-full"),
                                  _completed_rows(completed, algo_type),
                                  "PnL")


# ── per-stock strategy dispatch ───────────────────────────────────────────────

def _run_strategy(algo_type, candles, current_price, stock_name):
    header = f"{stock_name} — Last: ₹{current_price:.2f} | {len(candles)} candles (5-min, today)"

    if algo_type == "abcd":
        swings   = find_swing_points(candles, order=2)
        patterns = detect_abcd_patterns(swings)
        ui.label(header).classes("text-md font-semibold")
        render_tv_abcd_chart(candles, swings, patterns, stock_name, current_price)
        if not patterns:
            ui.label("No ABCD patterns detected today.").classes("text-gray-500 italic")
        active, completed = classify_trades(patterns, current_price, stock_name)
        _trade_store[f"abcd_trades_{stock_name}"] = {"active": active, "completed": completed}
        _render_trade_tabs(active, completed, current_price, "abcd")
        with ui.expansion("Swing Points & Pattern Details").classes("w-full mt-2"):
            for s in swings:
                ui.label(f"{_fmt_time(s['time'])} | {s['type']} | {s['price']:.2f}").classes("text-sm")
            for i, p in enumerate(patterns):
                ui.label(
                    f"Pattern {i+1} ({p['type']}): "
                    f"A={p['A']['price']:.2f}→B={p['B']['price']:.2f}"
                    f"→C={p['C']['price']:.2f}→D={p['D']['price']:.2f} "
                    f"| BC:{p['BC_retrace']} CD/AB:{p['CD_AB_ratio']}"
                ).classes("text-sm")

    elif algo_type == "dtc":
        signals = detect_double_top_custom_signals(candles)
        ui.label(header).classes("text-md font-semibold")
        render_tv_double_top_custom_chart(candles, signals)
        if not signals:
            ui.label("No Double Top Customized signals detected today.").classes("text-gray-500 italic")
        active, completed = classify_double_top_custom_trades(signals, current_price, stock_name)
        _trade_store[f"dtc_trades_{stock_name}"] = {"active": active, "completed": completed}
        _render_trade_tabs(active, completed, current_price, "dtc")

    elif algo_type == "db":
        signals = detect_double_bottom_signals(candles)
        ui.label(header).classes("text-md font-semibold")
        render_tv_double_bottom_chart(candles, signals)
        if not signals:
            ui.label("No Double Bottom signals detected today.").classes("text-gray-500 italic")
        active, completed = classify_double_bottom_trades(signals, current_price, stock_name)
        _trade_store[f"db_trades_{stock_name}"] = {"active": active, "completed": completed}
        _render_trade_tabs(active, completed, current_price, "db")

    elif algo_type == "ema10":
        signals, df_ind = detect_ema10_signals(candles)
        ui.label(header).classes("text-md font-semibold")
        render_tv_ema10_chart(candles, df_ind, signals)
        if not signals:
            ui.label("No EMA10 signals detected today.").classes("text-gray-500 italic")
        active, completed = classify_ema10_trades(signals, current_price, stock_name)
        _trade_store[f"ema10_trades_{stock_name}"] = {"active": active, "completed": completed}
        _render_trade_tabs(active, completed, current_price, "ema10")

    elif algo_type == "sma50":
        signals, df_ind = detect_sma50_signals(candles)
        ui.label(header).classes("text-md font-semibold")
        render_tv_sma50_chart(candles, df_ind, signals)
        if not signals:
            ui.label("No SMA50 signals detected today.").classes("text-gray-500 italic")
        active, completed = classify_sma50_trades(signals, current_price, stock_name)
        _trade_store[f"sma50_trades_{stock_name}"] = {"active": active, "completed": completed}
        _render_trade_tabs(active, completed, current_price, "sma50")


# ── tab entry point ───────────────────────────────────────────────────────────

def render_algo_tab(container, algo_type="abcd"):
    """Build the live algo trading tab. Returns async refresh() (no-op after first load)."""
    _default_sid = _ALL_STOCKS[0]["security_id"] if _ALL_STOCKS else None

    # Mutable state shared across closures
    _state = {
        "security_id": _default_sid,
        "algo": "abcd",
        "candles": None,        # DataFrame of today's 5-min candles
        "last_candle_min": -1,  # minute-bucket of last candle (HH*60+MM)
        "loaded": False,        # True after first successful load
        "ltp_label": None,      # ui.label for the live LTP header
        "strategy_container": None,  # ui.element holding chart + trades
    }
    active_timers = []

    def _cancel_timers():
        for t in active_timers:
            t.cancel()
        active_timers.clear()

    with container:
        ui.label("Live Algo Trading").classes("text-xl font-bold mb-2")

        with ui.row().classes("items-center gap-4 flex-wrap mb-4"):
            ui.label("Stock:").classes("text-sm font-medium text-gray-700")
            stock_select = ui.select(
                options=_STOCK_OPTIONS,
                value=_state["security_id"],
                label="",
            ).props("outlined dense").classes("w-48")

            ui.label("Strategy:").classes("text-sm font-medium text-gray-700")
            strategy_select = ui.select(
                options={k: v for v, k in _STRATEGIES},
                value=_state["algo"],
                label="",
            ).props("outlined dense").classes("w-52")

        content_container = ui.element("div").classes("w-full")
        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            ui.label("Loading data…").classes("text-gray-500 text-center w-full")

    # ── full (re)load — called on first render and on dropdown change ──────────

    async def _load():
        sid   = stock_select.value or _default_sid
        strat = strategy_select.value or "abcd"
        _state["security_id"] = sid
        _state["algo"]        = strat
        _state["loaded"]      = False

        stock = _STOCK_BY_SID.get(sid)
        if not stock:
            return
        stock_name = stock["name"]

        loop = asyncio.get_event_loop()

        if content_container.client._deleted:
            return

        _cancel_timers()
        content_container.clear()
        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            strat_label = dict(_STRATEGIES).get(strat, strat)
            ui.label(f"Loading {stock_name} — {strat_label}…").classes("text-gray-500 text-center w-full")

        try:
            candles = await loop.run_in_executor(
                None, lambda: _fetch_any_stock_candles(sid, interval=5)
            )
        except Exception as e:
            if not content_container.client._deleted:
                content_container.clear()
                with content_container:
                    ui.label(f"Could not fetch candles: {e}").classes("text-red-500")
            return

        if content_container.client._deleted:
            return

        # Filter to today
        today_date = now_ist().date()
        if candles is not None and not candles.empty:
            candles = candles[candles["timestamp"].dt.date == today_date].reset_index(drop=True)

        # Subscribe WS for live price
        ws_feed.subscribe([(mf.NSE, sid)])

        _cancel_timers()
        content_container.clear()

        if candles is None or candles.empty:
            with content_container:
                ui.label(f"No candle data for {stock_name} today.").classes("text-orange-500")
            return

        _state["candles"] = candles
        _state["last_candle_min"] = _candle_minute(candles["timestamp"].iloc[-1])

        current_price = round(float(candles["close"].iloc[-1]), 2)

        with content_container:
            with ui.row().classes("gap-4 sm:gap-8 flex-wrap items-center mb-2"):
                ui.label(f"{stock_name}").classes("text-sm sm:text-lg font-bold")
                ltp_lbl = ui.label(f"LTP: ₹{current_price:,.2f}").classes("text-sm sm:text-lg")
                ui.label("● LIVE").classes("text-xs font-bold text-green-600 animate-pulse")
                candle_status = ui.label("").classes("text-xs text-gray-400 ml-2")
            _state["ltp_label"] = ltp_lbl

            ticker_container = ui.element("div").classes("w-full")
            _build_live_ticker(ticker_container, sid, stock_name, active_timers)

            ui.separator()

            strat_container = ui.element("div").classes("w-full")
            _state["strategy_container"] = strat_container

        with strat_container:
            _run_strategy(strat, candles, current_price, stock_name)

        await flush_pending_js()
        _state["loaded"] = True

        # ── candle-close watcher — fires every 30s ─────────────────────────────
        def _check_new_candle():
            if content_container.client._deleted:
                return
            if not _state["loaded"]:
                return

            q = ws_feed.get_quote(_state["security_id"])
            if not q:
                return

            ltp = q.get("ltp", 0)
            tick_dt = ws_feed.get_last_tick_time(_state["security_id"])
            if tick_dt is None:
                return

            # Update LTP header label
            if _state["ltp_label"] is not None:
                _state["ltp_label"].set_text(f"LTP: ₹{ltp:,.2f}")

            # Detect new 5-min candle close: tick is in a different 5-min bucket
            tick_min_bucket = (tick_dt.hour * 60 + tick_dt.minute) // 5
            last_candles = _state["candles"]
            if last_candles is None or last_candles.empty:
                return

            last_ts = last_candles["timestamp"].iloc[-1]
            last_min_bucket = (last_ts.hour * 60 + last_ts.minute) // 5

            if tick_min_bucket <= last_min_bucket:
                return  # same bucket — no new candle yet

            # New 5-min candle has closed — build a synthetic row from WS data
            # The candle open = last close, high/low/close approximate from LTP
            prev_close = float(last_candles["close"].iloc[-1])
            new_ts = pd.Timestamp(tick_dt).tz_localize("Asia/Kolkata") if tick_dt.tzinfo is None else pd.Timestamp(tick_dt).tz_convert("Asia/Kolkata")
            # Align timestamp to 5-min boundary
            aligned_min = tick_min_bucket * 5
            new_ts = new_ts.replace(hour=aligned_min // 60, minute=aligned_min % 60, second=0, microsecond=0)

            new_row = pd.DataFrame([{
                "timestamp": new_ts,
                "open":  prev_close,
                "high":  max(prev_close, ltp),
                "low":   min(prev_close, ltp),
                "close": ltp,
            }])
            updated = pd.concat([last_candles, new_row], ignore_index=True)
            _state["candles"] = updated
            _state["last_candle_min"] = tick_min_bucket * 5

            # Re-render strategy section only
            sc = _state["strategy_container"]
            if sc is None:
                return
            sc.clear()
            with sc:
                _run_strategy(_state["algo"], updated, round(ltp, 2), stock_name)

            candle_status.set_text(f"New candle at {new_ts.strftime('%H:%M')}")

            asyncio.ensure_future(flush_pending_js())

        t = ui.timer(30, _check_new_candle)
        active_timers.append(t)

    # Dropdown changes trigger a full reload
    stock_select.on_value_change(lambda e: asyncio.ensure_future(_load()))
    strategy_select.on_value_change(lambda e: asyncio.ensure_future(_load()))

    async def refresh():
        # Skip global 120s re-render if already loaded; only re-load on first visit
        if not _state["loaded"]:
            await _load()

    return refresh
