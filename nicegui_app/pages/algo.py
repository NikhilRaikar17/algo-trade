"""
Live algo trading tab — all strategies, index dropdown, 0.5s WS ticker.
"""

import asyncio
from datetime import datetime
from nicegui import ui
from dhanhq import marketfeed as mf

from config import now_ist, INDICES
from state import _trade_store
from data import get_expiries, fetch_option_chain_raw, fetch_5min_candles
from algo_strategies import (
    # ABCD
    find_swing_points,
    detect_abcd_patterns,
    classify_trades,
    # Double Top / Bottom
    detect_double_top_signals,
    classify_double_top_trades,
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
    render_tv_double_top_chart,
    render_tv_double_bottom_chart,
    render_tv_ema10_chart,
    render_tv_sma50_chart,
    flush_pending_js,
)
from ui_components import build_trade_table
import ws_feed

_STRATEGIES = [
    ("ABCD Harmonic",    "abcd"),
    ("Double Top",       "dt"),
    ("Double Bottom",    "db"),
    ("EMA 10",           "ema10"),
    ("SMA 50",           "sma50"),
]

_INDEX_OPTIONS = {"NIFTY": "NIFTY 50", "BANKNIFTY": "BANKNIFTY"}


def _fmt_time(t):
    if t is None:
        return "—"
    return t.strftime("%d %b %H:%M") if hasattr(t, "strftime") else str(t)


# ── live bid/ask ticker ───────────────────────────────────────────────────────

def _build_live_ticker(container, atm, iv_map, candles_by_type, active_timers):
    """Build the live bid/ask table and start the 0.5s update timer."""
    live_labels = {}

    with container:
        with ui.element("div").classes("w-full overflow-x-auto mb-3"):
            with ui.element("table").classes("text-sm border-collapse w-full"):
                with ui.element("thead"):
                    with ui.element("tr").classes("bg-gray-100"):
                        for col in ["Contract", "LTP", "Bid (Qty)", "Ask (Qty)", "Spread", "OI", "Volume", "IV %"]:
                            with ui.element("th").classes("px-3 py-1 text-left font-semibold border-b text-xs"):
                                ui.label(col)
                with ui.element("tbody"):
                    for opt_type in ["CE", "PE"]:
                        row_bg  = "bg-green-50" if opt_type == "CE" else "bg-red-50"
                        lbl_cls = "text-green-700 font-bold" if opt_type == "CE" else "text-red-700 font-bold"
                        with ui.element("tr").classes(f"border-b {row_bg}"):
                            with ui.element("td").classes("px-3 py-1"):
                                ui.label(f"{int(atm)} {opt_type}").classes(f"text-xs {lbl_cls}")
                            for field, cls in [
                                ("ltp",    "font-semibold"),
                                ("bid",    "text-blue-600"),
                                ("ask",    "text-orange-600"),
                                ("spread", "text-gray-600"),
                                ("oi",     ""),
                                ("vol",    ""),
                            ]:
                                with ui.element("td").classes("px-3 py-1"):
                                    lbl = ui.label("–").classes(f"text-xs {cls}")
                                    live_labels[(opt_type, field)] = lbl
                            with ui.element("td").classes("px-3 py-1"):
                                ui.label(f"{iv_map.get(opt_type, 0):.2f}").classes("text-xs")

    def _update():
        if container.client._deleted:
            return
        for opt_type in ["CE", "PE"]:
            entry = candles_by_type.get(opt_type)
            if not entry:
                continue
            sec_id, _ = entry
            q = ws_feed.get_quote(sec_id)
            if not q:
                continue
            ltp    = q.get("ltp", 0)
            bid    = q.get("bid", 0)
            ask    = q.get("ask", 0)
            bq     = q.get("bid_qty", 0)
            aq     = q.get("ask_qty", 0)
            spread = round(ask - bid, 2)
            live_labels[(opt_type, "ltp")].set_text(f"{ltp:,.2f}")
            live_labels[(opt_type, "bid")].set_text(f"{bid:,.2f} ({bq:,})")
            live_labels[(opt_type, "ask")].set_text(f"{ask:,.2f} ({aq:,})")
            live_labels[(opt_type, "spread")].set_text(f"{spread:,.2f}")
            live_labels[(opt_type, "oi")].set_text(f"{q.get('oi', 0):,}")
            live_labels[(opt_type, "vol")].set_text(f"{q.get('volume', 0):,}")

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


# ── per-option-type strategy dispatch ─────────────────────────────────────────

def _run_strategy(algo_type, candles, current_price, contract_name, candles_by_type, opt_type):
    header = f"{contract_name} — Last: {current_price:.2f} | {len(candles)} candles (5-min, today)"

    if algo_type == "abcd":
        swings   = find_swing_points(candles, order=2)
        patterns = detect_abcd_patterns(swings)
        ui.label(header).classes("text-md font-semibold")
        render_tv_abcd_chart(candles, swings, patterns, contract_name, current_price)
        if not patterns:
            ui.label("No ABCD patterns detected today.").classes("text-gray-500 italic")
        active, completed = classify_trades(patterns, current_price, contract_name)
        _trade_store[f"abcd_trades_{contract_name}"] = {"active": active, "completed": completed}
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

    elif algo_type == "dt":
        signals = detect_double_top_signals(candles)
        ui.label(header).classes("text-md font-semibold")
        render_tv_double_top_chart(candles, signals)
        if not signals:
            ui.label("No Double Top signals detected today.").classes("text-gray-500 italic")
        active, completed = classify_double_top_trades(signals, current_price, contract_name)
        _trade_store[f"dt_trades_{contract_name}"] = {"active": active, "completed": completed}
        _render_trade_tabs(active, completed, current_price, "dt")

    elif algo_type == "db":
        signals = detect_double_bottom_signals(candles)
        ui.label(header).classes("text-md font-semibold")
        render_tv_double_bottom_chart(candles, signals)
        if not signals:
            ui.label("No Double Bottom signals detected today.").classes("text-gray-500 italic")
        active, completed = classify_double_bottom_trades(signals, current_price, contract_name)
        _trade_store[f"db_trades_{contract_name}"] = {"active": active, "completed": completed}
        _render_trade_tabs(active, completed, current_price, "db")

    elif algo_type == "ema10":
        signals, df_ind = detect_ema10_signals(candles)
        ui.label(header).classes("text-md font-semibold")
        render_tv_ema10_chart(candles, df_ind, signals)
        if not signals:
            ui.label("No EMA10 signals detected today.").classes("text-gray-500 italic")
        active, completed = classify_ema10_trades(signals, current_price, contract_name)
        _trade_store[f"ema10_trades_{contract_name}"] = {"active": active, "completed": completed}
        _render_trade_tabs(active, completed, current_price, "ema10")

    elif algo_type == "sma50":
        signals, df_ind = detect_sma50_signals(candles)
        ui.label(header).classes("text-md font-semibold")
        render_tv_sma50_chart(candles, df_ind, signals)
        if not signals:
            ui.label("No SMA50 signals detected today.").classes("text-gray-500 italic")
        active, completed = classify_sma50_trades(signals, current_price, contract_name)
        _trade_store[f"sma50_trades_{contract_name}"] = {"active": active, "completed": completed}
        _render_trade_tabs(active, completed, current_price, "sma50")


# ── per-expiry UI builder ─────────────────────────────────────────────────────

def _render_algo_option(container, cfg, expiry, raw, candles_by_type, algo_type, active_timers):
    spot = round(float(raw["last_price"]), 2)
    atm  = round(spot / cfg["strike_step"]) * cfg["strike_step"]
    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
    exp_tag  = exp_date.strftime("%d%b").upper()

    oc = raw.get("oc", {})
    strikes_sorted = sorted(oc.keys(), key=lambda s: abs(float(s) - atm))
    atm_sides = oc.get(strikes_sorted[0], {}) if strikes_sorted else {}
    ce_iv = round(float(atm_sides.get("ce", {}).get("implied_volatility", 0)), 2)
    pe_iv = round(float(atm_sides.get("pe", {}).get("implied_volatility", 0)), 2)
    iv_map = {"CE": ce_iv, "PE": pe_iv}

    container.clear()
    with container:
        with ui.row().classes("gap-4 sm:gap-8 flex-wrap items-center mb-2"):
            ui.label(f"Spot: {spot:,.2f}").classes("text-sm sm:text-lg font-bold")
            ui.label(f"ATM: {atm:,}").classes("text-sm sm:text-lg")
            ui.label(f"Expiry: {expiry}").classes("text-sm sm:text-lg text-gray-600")
            ui.label("● LIVE").classes("text-xs font-bold text-green-600 animate-pulse")

        ticker_container = ui.element("div").classes("w-full")
        _build_live_ticker(ticker_container, atm, iv_map, candles_by_type, active_timers)

        ui.separator()

        for opt_type in ["CE", "PE"]:
            ui.separator().classes("my-2")
            entry = candles_by_type.get(opt_type)
            if entry is None:
                ui.label(f"No security ID for ATM {opt_type}").classes("text-orange-500")
                continue
            sec_id, candles = entry
            if candles is None or candles.empty:
                ui.label(f"No candle data for ATM {opt_type} (ID: {sec_id})").classes("text-orange-500")
                continue
            contract_name = f"{cfg['name_prefix']} {exp_tag} {int(atm)} {opt_type}"
            current_price = round(float(candles["close"].iloc[-1]), 2)
            _run_strategy(algo_type, candles, current_price, contract_name, candles_by_type, opt_type)


# ── tab entry point ───────────────────────────────────────────────────────────

def render_algo_tab(container, algo_type="abcd"):
    """Build the live algo trading tab. Returns async refresh()."""
    _sel = {"index": "NIFTY", "algo": "abcd"}
    active_timers = []  # 0.5s ticker timers — cancelled before each reload

    def _cancel_timers():
        for t in active_timers:
            t.cancel()
        active_timers.clear()

    with container:
        ui.label("Live Algo Trading").classes("text-xl font-bold mb-2")

        with ui.row().classes("items-center gap-4 flex-wrap mb-4"):
            ui.label("Index:").classes("text-sm font-medium text-gray-700")
            index_select = ui.select(
                options=_INDEX_OPTIONS,
                value=_sel["index"],
                label="",
            ).props("outlined dense").classes("w-40")

            ui.label("Strategy:").classes("text-sm font-medium text-gray-700")
            strategy_select = ui.select(
                options={k: v for v, k in _STRATEGIES},
                value=_sel["algo"],
                label="",
            ).props("outlined dense").classes("w-52")

        content_container = ui.element("div").classes("w-full")
        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            ui.label("Loading data…").classes("text-gray-500 text-center w-full")

    async def _load():
        idx_key = index_select.value or "NIFTY"
        strat   = strategy_select.value or "abcd"
        _sel["index"] = idx_key
        _sel["algo"]  = strat
        cfg  = INDICES[idx_key]
        loop = asyncio.get_event_loop()

        if content_container.client._deleted:
            return

        _cancel_timers()
        content_container.clear()
        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            strat_label = dict(_STRATEGIES).get(strat, strat)
            ui.label(f"Loading {idx_key} — {strat_label}…").classes("text-gray-500 text-center w-full")

        # 1. Expiries
        try:
            expiries = await loop.run_in_executor(
                None, lambda: get_expiries(cfg["scrip"], cfg["segment"], 2, for_algo=True)
            )
        except Exception as e:
            if not content_container.client._deleted:
                content_container.clear()
                with content_container:
                    ui.label(f"Could not fetch expiries: {e}").classes("text-red-500")
            return

        if content_container.client._deleted:
            return

        # 2. Option chains
        expiry_data = {}
        for exp in expiries:
            try:
                raw = await loop.run_in_executor(
                    None, lambda e=exp: fetch_option_chain_raw(cfg["scrip"], cfg["segment"], e)
                )
                expiry_data[exp] = raw
            except Exception as e:
                expiry_data[exp] = e
            if content_container.client._deleted:
                return
            await asyncio.sleep(0.2)

        # 3. 5-min candles for ATM CE + PE
        candles_cache = {}
        ws_securities = []
        today_date = now_ist().date()

        for exp, raw in expiry_data.items():
            if isinstance(raw, Exception):
                continue
            spot = round(float(raw["last_price"]), 2)
            atm  = round(spot / cfg["strike_step"]) * cfg["strike_step"]
            strikes = sorted(raw["oc"].keys(), key=lambda s: abs(float(s) - atm))
            if not strikes:
                continue
            sides = raw["oc"][strikes[0]]
            ce_id = sides.get("ce", {}).get("security_id")
            pe_id = sides.get("pe", {}).get("security_id")

            candles_cache[exp] = {}
            for opt_type, sec_id in [("CE", ce_id), ("PE", pe_id)]:
                if not sec_id:
                    continue
                ws_securities.append((mf.NSE_FNO, sec_id))
                try:
                    candles = await loop.run_in_executor(
                        None, lambda sid=sec_id: fetch_5min_candles(sid)
                    )
                    if not candles.empty:
                        candles = candles[candles["timestamp"].dt.date == today_date].reset_index(drop=True)
                    candles_cache[exp][opt_type] = (sec_id, candles)
                except Exception:
                    candles_cache[exp][opt_type] = (sec_id, None)
                if content_container.client._deleted:
                    return
                await asyncio.sleep(0.2)

        if content_container.client._deleted:
            return

        # 4. Subscribe WS
        if ws_securities:
            ws_feed.subscribe(ws_securities)

        # 5. Build UI
        _cancel_timers()
        content_container.clear()
        with content_container:
            if not expiries:
                ui.label("No expiries found").classes("text-gray-500")
                return

            for exp in expiries:
                result = expiry_data.get(exp)
                with ui.expansion(f"Expiry: {exp}", value=True).classes("w-full border rounded mb-2"):
                    if isinstance(result, Exception):
                        ui.label(f"Error: {result}").classes("text-red-500")
                    elif result is None:
                        ui.label("No data").classes("text-gray-500")
                    else:
                        inner = ui.element("div").classes("w-full")
                        _render_algo_option(
                            inner, cfg, exp, result,
                            candles_cache.get(exp, {}),
                            strat, active_timers,
                        )

        # Flush all chart JS after UI is fully built and DOM is synced
        await flush_pending_js()

    index_select.on_value_change(lambda e: asyncio.ensure_future(_load()))
    strategy_select.on_value_change(lambda e: asyncio.ensure_future(_load()))

    async def refresh():
        await _load()

    return refresh
