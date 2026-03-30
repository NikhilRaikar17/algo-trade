"""
ABCD and RSI + SMA algo trading tab pages.
"""

import asyncio
import pandas as pd
from datetime import datetime
from nicegui import ui
from dhanhq import marketfeed as mf

from config import now_ist, INDICES
from state import _trade_store
from data import get_expiries, fetch_option_chain_raw, fetch_5min_candles
from algo_strategies import (
    find_swing_points,
    detect_abcd_patterns,
    classify_trades,
    detect_rsi_sma_signals,
    classify_rsi_trades,
)
from tv_charts import render_tv_abcd_chart, render_tv_rsi_sma_chart
from ui_components import build_trade_table
import ws_feed


def _render_algo_option(container, cfg, expiry, raw, candles_by_type, algo_type="abcd"):
    """Render one CE/PE option's algo analysis.
    candles_by_type: {"CE": (sec_id, df), "PE": (sec_id, df)}
    """
    spot = round(float(raw["last_price"]), 2)
    atm = round(spot / cfg["strike_step"]) * cfg["strike_step"]

    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
    exp_tag = exp_date.strftime("%d%b").upper()

    # Static IV from REST snapshot (WS doesn't carry IV)
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

        # --- Live Bid / Ask table ---
        # Build label refs so the timer can update them without clearing the DOM
        live_labels = {}  # (opt_type, field) → ui.label

        with ui.element("div").classes("w-full overflow-x-auto mb-3"):
            with ui.element("table").classes("text-sm border-collapse w-full"):
                with ui.element("thead"):
                    with ui.element("tr").classes("bg-gray-100"):
                        for col in ["Contract", "LTP", "Bid (Qty)", "Ask (Qty)", "Spread", "OI", "Volume", "IV %"]:
                            with ui.element("th").classes("px-3 py-1 text-left font-semibold border-b text-xs"):
                                ui.label(col)
                with ui.element("tbody"):
                    for opt_type in ["CE", "PE"]:
                        row_bg = "bg-green-50" if opt_type == "CE" else "bg-red-50"
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
                            # IV is static
                            with ui.element("td").classes("px-3 py-1"):
                                ui.label(f"{iv_map[opt_type]:.2f}").classes("text-xs")

        def _update_live():
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

        # Populate immediately with whatever is already in the store, then keep updating
        _update_live()
        ui.timer(2, _update_live)

        ui.separator()

        with ui.tabs().classes("w-full") as opt_tabs:
            ce_tab_item = ui.tab(f"ATM CE — {int(atm)} CE")
            pe_tab_item = ui.tab(f"ATM PE — {int(atm)} PE")

        with ui.tab_panels(opt_tabs, value=ce_tab_item).classes("w-full"):
            for tab_item, opt_type in [(ce_tab_item, "CE"), (pe_tab_item, "PE")]:
                with ui.tab_panel(tab_item):
                    entry = candles_by_type.get(opt_type)
                    if entry is None:
                        ui.label(f"No security ID for ATM {opt_type}").classes("text-orange-500")
                        continue
                    sec_id, candles = entry
                    if candles is None or candles.empty:
                        ui.label(
                            f"No candle data for ATM {opt_type} (ID: {sec_id})"
                        ).classes("text-orange-500")
                        continue

                    contract_name = f"NIFTY {exp_tag} {int(atm)} {opt_type}"
                    current_price = round(float(candles["close"].iloc[-1]), 2)

                    if algo_type == "abcd":
                        swings = find_swing_points(candles, order=2)
                        patterns = detect_abcd_patterns(swings)

                        ui.label(
                            f"{contract_name} — Last: {current_price:.2f} | "
                            f"{len(candles)} candles (5-min, today)"
                        ).classes("text-md font-semibold")

                        render_tv_abcd_chart(candles, swings, patterns, contract_name, current_price)

                        if not patterns:
                            ui.label("No ABCD patterns detected today.").classes(
                                "text-gray-500 italic"
                            )

                        active, completed = classify_trades(patterns, current_price, contract_name)
                        _trade_store[f"abcd_trades_{contract_name}"] = {
                            "active": active, "completed": completed,
                        }

                        _render_trade_tabs(active, completed, current_price, "abcd")

                        with ui.expansion("Swing Points & Pattern Details").classes("w-full mt-2"):
                            if swings:
                                for s in swings:
                                    t = s["time"].strftime("%d %b %H:%M") if hasattr(s["time"], "strftime") else str(s["time"])
                                    ui.label(f"{t} | {s['type']} | {s['price']:.2f}").classes("text-sm")
                            if patterns:
                                for i, p in enumerate(patterns):
                                    ui.label(
                                        f"Pattern {i+1} ({p['type']}): "
                                        f"A={p['A']['price']:.2f} → B={p['B']['price']:.2f} → "
                                        f"C={p['C']['price']:.2f} → D={p['D']['price']:.2f} | "
                                        f"BC: {p['BC_retrace']} | CD/AB: {p['CD_AB_ratio']}"
                                    ).classes("text-sm")

                    else:  # RSI+SMA
                        signals, df_ind = detect_rsi_sma_signals(candles)

                        ui.label(
                            f"{contract_name} — Last: {current_price:.2f} | "
                            f"{len(candles)} candles (5-min, today)"
                        ).classes("text-md font-semibold")

                        render_tv_rsi_sma_chart(candles, df_ind, signals)

                        if not signals:
                            ui.label("No RSI+SMA signals detected today.").classes(
                                "text-gray-500 italic"
                            )

                        active, completed = classify_rsi_trades(signals, current_price, contract_name)
                        _trade_store[f"rsi_trades_{contract_name}"] = {
                            "active": active, "completed": completed,
                        }

                        _render_trade_tabs(active, completed, current_price, "rsi")


def _render_trade_tabs(active, completed, current_price, algo_type):
    """Render Active / Completed trade tabs."""
    with ui.tabs().classes("w-full mt-4") as trade_tabs:
        active_tab_item   = ui.tab(f"Active Trades ({len(active)})")
        completed_tab_item = ui.tab(f"Completed Trades ({len(completed)})")

    with ui.tab_panels(trade_tabs, value=active_tab_item).classes("w-full"):
        with ui.tab_panel(active_tab_item):
            if not active:
                ui.label("No active trades").classes("text-gray-500 italic")
            else:
                if algo_type == "abcd":
                    rows = [
                        {
                            "Pattern":     t["type"],
                            "Signal":      t["signal"],
                            "Entry (D)":   round(t["entry"], 2),
                            "Target":      round(t["target"], 2),
                            "Stop Loss":   round(t["stop_loss"], 2),
                            "Current":     round(current_price, 2),
                            "Unreal. PnL": t["unrealized_pnl"],
                            "A Time": t["A"]["time"].strftime("%d %b %H:%M") if hasattr(t["A"]["time"], "strftime") else str(t["A"]["time"]),
                            "D Time": t["D"]["time"].strftime("%d %b %H:%M") if hasattr(t["D"]["time"], "strftime") else str(t["D"]["time"]),
                            "BC Retrace":  t["BC_retrace"],
                            "CD/AB":       t["CD_AB_ratio"],
                        }
                        for t in active
                    ]
                else:
                    rows = [
                        {
                            "Signal":      t["signal"],
                            "Entry":       t["entry"],
                            "Target":      t["target"],
                            "Stop Loss":   t["stop_loss"],
                            "Current":     round(current_price, 2),
                            "Unreal. PnL": t["unrealized_pnl"],
                            "RSI":         t["rsi"],
                            "Time": t["time"].strftime("%d %b %H:%M") if hasattr(t["time"], "strftime") else str(t["time"]),
                        }
                        for t in active
                    ]
                trade_container = ui.element("div").classes("w-full")
                build_trade_table(trade_container, rows, "Unreal. PnL")

        with ui.tab_panel(completed_tab_item):
            if not completed:
                ui.label("No completed trades").classes("text-gray-500 italic")
            else:
                if algo_type == "abcd":
                    rows = [
                        {
                            "Pattern":   t["type"],
                            "Signal":    t["signal"],
                            "Entry (D)": round(t["entry"], 2),
                            "Target":    round(t["target"], 2),
                            "Stop Loss": round(t["stop_loss"], 2),
                            "Exit":      round(t["exit_price"], 2),
                            "PnL":       t["pnl"],
                            "Status":    t["status"],
                            "A Time": t["A"]["time"].strftime("%d %b %H:%M") if hasattr(t["A"]["time"], "strftime") else str(t["A"]["time"]),
                            "D Time": t["D"]["time"].strftime("%d %b %H:%M") if hasattr(t["D"]["time"], "strftime") else str(t["D"]["time"]),
                        }
                        for t in completed
                    ]
                else:
                    rows = [
                        {
                            "Signal":    t["signal"],
                            "Entry":     t["entry"],
                            "Target":    t["target"],
                            "Stop Loss": t["stop_loss"],
                            "Exit":      round(t["exit_price"], 2),
                            "PnL":       t["pnl"],
                            "Status":    t["status"],
                            "Time": t["time"].strftime("%d %b %H:%M") if hasattr(t["time"], "strftime") else str(t["time"]),
                        }
                        for t in completed
                    ]
                trade_container = ui.element("div").classes("w-full")
                build_trade_table(trade_container, rows, "PnL")


def render_algo_tab(container, algo_type="abcd"):
    """Build the ABCD or RSI+SMA algo trading tab content inside container."""
    title = "ABCD Harmonic Scanner" if algo_type == "abcd" else "RSI + SMA Crossover Scanner"

    with container:
        ui.label(f"{title} — NIFTY ATM (5-min intraday)").classes("text-xl font-bold mb-2")
        content_container = ui.element("div").classes("w-full")
        with content_container:
            ui.spinner("dots", size="lg").classes("mx-auto my-8")
            ui.label("Loading data…").classes("text-gray-500 text-center w-full")

    async def refresh():
        loop = asyncio.get_event_loop()
        cfg = INDICES["NIFTY"]

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

        # 2. Raw option chain per expiry
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

        # 3. Pre-fetch today's 5-min candles for ATM CE + PE
        candles_cache = {}   # exp → {"CE": (sec_id, df), "PE": (sec_id, df)}
        ws_securities = []   # for WebSocket subscription

        today_date = now_ist().date()  # plain date, no timezone

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
                    # Filter to today only — compare plain date objects (avoids tz mismatch)
                    if not candles.empty:
                        candles = candles[
                            candles["timestamp"].dt.date == today_date
                        ].reset_index(drop=True)
                    candles_cache[exp][opt_type] = (sec_id, candles)
                except Exception:
                    candles_cache[exp][opt_type] = (sec_id, None)
                if content_container.client._deleted:
                    return
                await asyncio.sleep(0.2)

        if content_container.client._deleted:
            return

        # 4. Start WebSocket feed for ATM CE + PE (non-blocking)
        if ws_securities:
            ws_feed.subscribe(ws_securities)

        # 5. Build UI
        content_container.clear()
        with content_container:
            if not expiries:
                ui.label("No expiries found").classes("text-grey")
                return

            with ui.tabs().classes("w-full") as tabs:
                tab_items = [ui.tab(f"Expiry: {exp}") for exp in expiries]

            with ui.tab_panels(tabs, value=tab_items[0]).classes("w-full"):
                for tab_item, exp in zip(tab_items, expiries):
                    with ui.tab_panel(tab_item):
                        result = expiry_data.get(exp)
                        if isinstance(result, Exception):
                            ui.label(f"Error: {result}").classes("text-red-500")
                        elif result is None:
                            ui.label("No data").classes("text-grey")
                        else:
                            inner_container = ui.element("div").classes("w-full")
                            _render_algo_option(
                                inner_container, cfg, exp, result,
                                candles_cache.get(exp, {}), algo_type
                            )

    return refresh
