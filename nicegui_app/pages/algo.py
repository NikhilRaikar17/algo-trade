"""
ABCD and RSI + SMA algo trading tab pages.
"""

import time
import asyncio
import pandas as pd
from datetime import datetime
from nicegui import ui

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
from charts import build_candlestick_with_abcd, build_candlestick_with_rsi_sma
from ui_components import build_trade_table


def _render_algo_option(container, cfg, expiry, raw, algo_type="abcd"):
    """Render one CE/PE option's algo analysis inside a container."""
    spot = round(float(raw["last_price"]), 2)
    oc = raw["oc"]
    atm = round(spot / cfg["strike_step"]) * cfg["strike_step"]

    strikes = sorted(oc.keys(), key=lambda s: abs(float(s) - atm))
    if not strikes:
        with container:
            ui.label("No strikes found").classes("text-red-500")
        return

    best_strike = strikes[0]
    sides = oc[best_strike]
    ce_id = sides.get("ce", {}).get("security_id")
    pe_id = sides.get("pe", {}).get("security_id")

    if not ce_id or not pe_id:
        with container:
            ui.label(f"No security IDs for ATM strike {best_strike}").classes(
                "text-red-500"
            )
        return

    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
    exp_tag = exp_date.strftime("%d%b").upper()

    container.clear()
    with container:
        with ui.row().classes("gap-8"):
            ui.label(f"Spot: {spot:,.2f}").classes("text-lg font-bold")
            ui.label(f"ATM: {atm:,}").classes("text-lg")
            ui.label(f"Expiry: {expiry}").classes("text-lg text-gray-600")

        ui.separator()

        with ui.tabs().classes("w-full") as opt_tabs:
            ce_tab_item = ui.tab(f"ATM CE — NIFTY {exp_tag} {int(atm)} CE")
            pe_tab_item = ui.tab(f"ATM PE — NIFTY {exp_tag} {int(atm)} PE")

        with ui.tab_panels(opt_tabs).classes("w-full"):
            for tab_item, sec_id, opt_type in [
                (ce_tab_item, ce_id, "CE"),
                (pe_tab_item, pe_id, "PE"),
            ]:
                with ui.tab_panel(tab_item):
                    time.sleep(1)
                    candles = fetch_5min_candles(sec_id)

                    if candles.empty:
                        ui.label(
                            f"No candle data for ATM {opt_type} (ID: {sec_id})"
                        ).classes("text-orange-500")
                        continue

                    contract_name = f"NIFTY {exp_tag} {int(atm)} {opt_type}"
                    current_price = round(candles["close"].iloc[-1], 2)

                    if algo_type == "abcd":
                        swings = find_swing_points(candles, order=2)
                        patterns = detect_abcd_patterns(swings)

                        ui.label(
                            f"{contract_name} — Last: {current_price:.2f} | Candles: {len(candles)}"
                        ).classes("text-md font-semibold")

                        fig = build_candlestick_with_abcd(
                            candles, swings, patterns, contract_name, current_price
                        )
                        ui.plotly(fig).classes("w-full")

                        today_date = pd.Timestamp(now_ist().date())
                        patterns = [
                            p
                            for p in patterns
                            if pd.Timestamp(p["D"]["time"]).normalize() == today_date
                        ]

                        if not patterns:
                            ui.label("No ABCD patterns detected today.").classes(
                                "text-gray-500 italic"
                            )

                        active, completed = classify_trades(
                            patterns, current_price, contract_name
                        )
                        _trade_store[f"abcd_trades_{contract_name}"] = {
                            "active": active,
                            "completed": completed,
                        }

                        with ui.tabs().classes("w-full") as trade_tabs:
                            active_tab_item = ui.tab("Active Trades")
                            completed_tab_item = ui.tab("Completed Trades")

                        with ui.tab_panels(trade_tabs).classes("w-full"):
                            with ui.tab_panel(active_tab_item):
                                if not active:
                                    ui.label("No active trades").classes(
                                        "text-gray-500 italic"
                                    )
                                else:
                                    rows = [
                                        {
                                            "Pattern": t["type"],
                                            "Signal": t["signal"],
                                            "Entry (D)": round(t["entry"], 2),
                                            "Target": round(t["target"], 2),
                                            "Stop Loss": round(t["stop_loss"], 2),
                                            "Current": round(current_price, 2),
                                            "Unreal. PnL": t["unrealized_pnl"],
                                            "A Time": (
                                                t["A"]["time"].strftime("%d %b %H:%M")
                                                if hasattr(t["A"]["time"], "strftime")
                                                else str(t["A"]["time"])
                                            ),
                                            "D Time": (
                                                t["D"]["time"].strftime("%d %b %H:%M")
                                                if hasattr(t["D"]["time"], "strftime")
                                                else str(t["D"]["time"])
                                            ),
                                            "BC Retrace": t["BC_retrace"],
                                            "CD/AB": t["CD_AB_ratio"],
                                        }
                                        for t in active
                                    ]
                                    trade_container = ui.element("div").classes(
                                        "w-full"
                                    )
                                    build_trade_table(
                                        trade_container, rows, "Unreal. PnL"
                                    )

                            with ui.tab_panel(completed_tab_item):
                                if not completed:
                                    ui.label("No completed trades").classes(
                                        "text-gray-500 italic"
                                    )
                                else:
                                    rows = [
                                        {
                                            "Pattern": t["type"],
                                            "Signal": t["signal"],
                                            "Entry (D)": round(t["entry"], 2),
                                            "Target": round(t["target"], 2),
                                            "Stop Loss": round(t["stop_loss"], 2),
                                            "Exit": round(t["exit_price"], 2),
                                            "PnL": t["pnl"],
                                            "Status": t["status"],
                                            "A Time": (
                                                t["A"]["time"].strftime("%d %b %H:%M")
                                                if hasattr(t["A"]["time"], "strftime")
                                                else str(t["A"]["time"])
                                            ),
                                            "D Time": (
                                                t["D"]["time"].strftime("%d %b %H:%M")
                                                if hasattr(t["D"]["time"], "strftime")
                                                else str(t["D"]["time"])
                                            ),
                                        }
                                        for t in completed
                                    ]
                                    trade_container = ui.element("div").classes(
                                        "w-full"
                                    )
                                    build_trade_table(trade_container, rows, "PnL")

                        # Swing points expander
                        with ui.expansion("Swing Points & Pattern Details").classes(
                            "w-full"
                        ):
                            if swings:
                                swing_rows = [
                                    {
                                        "Time": (
                                            s["time"].strftime("%d %b %H:%M")
                                            if hasattr(s["time"], "strftime")
                                            else str(s["time"])
                                        ),
                                        "Type": s["type"],
                                        "Price": round(s["price"], 2),
                                    }
                                    for s in swings
                                ]
                                for sr in swing_rows:
                                    ui.label(
                                        f"{sr['Time']} | {sr['Type']} | {sr['Price']:.2f}"
                                    ).classes("text-sm")
                            if patterns:
                                for i, p in enumerate(patterns):
                                    ui.label(
                                        f"Pattern {i+1} ({p['type']}): A={p['A']['price']:.2f} → B={p['B']['price']:.2f} → "
                                        f"C={p['C']['price']:.2f} → D={p['D']['price']:.2f} | "
                                        f"BC: {p['BC_retrace']} | CD/AB: {p['CD_AB_ratio']}"
                                    ).classes("text-sm")

                    else:  # RSI+SMA
                        signals, df_ind = detect_rsi_sma_signals(candles)
                        today_date = pd.Timestamp(now_ist().date())
                        signals = [
                            s
                            for s in signals
                            if pd.Timestamp(s["time"]).normalize() == today_date
                        ]

                        ui.label(
                            f"{contract_name} — Last: {current_price:.2f} | Candles: {len(candles)}"
                        ).classes("text-md font-semibold")

                        fig, fig_rsi = build_candlestick_with_rsi_sma(
                            candles, df_ind, signals
                        )
                        ui.plotly(fig).classes("w-full")
                        if not df_ind.empty:
                            ui.plotly(fig_rsi).classes("w-full")

                        if not signals:
                            ui.label("No RSI+SMA signals detected today.").classes(
                                "text-gray-500 italic"
                            )

                        active, completed = classify_rsi_trades(
                            signals, current_price, contract_name
                        )
                        _trade_store[f"rsi_trades_{contract_name}"] = {
                            "active": active,
                            "completed": completed,
                        }

                        with ui.tabs().classes("w-full") as trade_tabs:
                            active_tab_item = ui.tab("Active Trades")
                            completed_tab_item = ui.tab("Completed Trades")

                        with ui.tab_panels(trade_tabs).classes("w-full"):
                            with ui.tab_panel(active_tab_item):
                                if not active:
                                    ui.label("No active trades").classes(
                                        "text-gray-500 italic"
                                    )
                                else:
                                    rows = [
                                        {
                                            "Signal": t["signal"],
                                            "Entry": t["entry"],
                                            "Target": t["target"],
                                            "Stop Loss": t["stop_loss"],
                                            "Current": round(current_price, 2),
                                            "Unreal. PnL": t["unrealized_pnl"],
                                            "RSI": t["rsi"],
                                            "Time": (
                                                t["time"].strftime("%d %b %H:%M")
                                                if hasattr(t["time"], "strftime")
                                                else str(t["time"])
                                            ),
                                        }
                                        for t in active
                                    ]
                                    trade_container = ui.element("div").classes(
                                        "w-full"
                                    )
                                    build_trade_table(
                                        trade_container, rows, "Unreal. PnL"
                                    )

                            with ui.tab_panel(completed_tab_item):
                                if not completed:
                                    ui.label("No completed trades").classes(
                                        "text-gray-500 italic"
                                    )
                                else:
                                    rows = [
                                        {
                                            "Signal": t["signal"],
                                            "Entry": t["entry"],
                                            "Target": t["target"],
                                            "Stop Loss": t["stop_loss"],
                                            "Exit": round(t["exit_price"], 2),
                                            "PnL": t["pnl"],
                                            "Status": t["status"],
                                            "Time": (
                                                t["time"].strftime("%d %b %H:%M")
                                                if hasattr(t["time"], "strftime")
                                                else str(t["time"])
                                            ),
                                        }
                                        for t in completed
                                    ]
                                    trade_container = ui.element("div").classes(
                                        "w-full"
                                    )
                                    build_trade_table(trade_container, rows, "PnL")


def render_algo_tab(container, algo_type="abcd"):
    """Build the ABCD or RSI+SMA algo trading tab content inside container."""
    title = (
        "ABCD Harmonic Scanner"
        if algo_type == "abcd"
        else "RSI + SMA Crossover Scanner"
    )

    with container:
        ui.label(f"{title} — NIFTY ATM (5-min candles)").classes(
            "text-xl font-bold mb-2"
        )
        content_container = ui.element("div").classes("w-full")

    async def refresh():
        cfg = INDICES["NIFTY"]
        try:
            expiries = get_expiries(cfg["scrip"], cfg["segment"], 2, for_algo=True)
        except Exception as e:
            content_container.clear()
            with content_container:
                ui.label(f"Could not fetch expiries: {e}").classes("text-red-500")
            return

        expiry_data = {}
        for exp in expiries:
            try:
                raw = fetch_option_chain_raw(cfg["scrip"], cfg["segment"], exp)
                expiry_data[exp] = raw
            except Exception as e:
                expiry_data[exp] = e
            await asyncio.sleep(3)

        content_container.clear()
        with content_container:
            with ui.tabs().classes("w-full") as tabs:
                tab_items = []
                for exp in expiries:
                    tab_items.append(ui.tab(f"Expiry: {exp}"))

            with ui.tab_panels(tabs).classes("w-full"):
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
                                inner_container, cfg, exp, result, algo_type
                            )

    return refresh
