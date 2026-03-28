"""
Dashboard page: clocks (IST / CEST) and market price cards.
"""

import time
import asyncio
from datetime import datetime
from nicegui import ui

from config import now_ist, now_cest, INDICES
from state import _cache_get, _cache_set
from data import get_expiries, fetch_option_chain


def _compute_synthetic_futures(spot, df, strike_step):
    """Compute synthetic futures price from ATM CE and PE using put-call parity."""
    if df is None or df.empty or spot is None:
        return None
    atm = round(spot / strike_step) * strike_step
    ce_rows = df[(df["Strike"] == atm) & (df["Type"] == "CE")]
    pe_rows = df[(df["Strike"] == atm) & (df["Type"] == "PE")]
    if ce_rows.empty or pe_rows.empty:
        return None
    ce_ltp = ce_rows.iloc[0]["LTP"]
    pe_ltp = pe_rows.iloc[0]["LTP"]
    return round(atm + ce_ltp - pe_ltp, 2)


def fetch_dashboard_prices():
    """Fetch spot and synthetic futures prices for NIFTY and BANKNIFTY."""
    cache_key = "dashboard_prices"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    prices = {}
    for name, cfg in INDICES.items():
        scrip = cfg["scrip"]
        segment = cfg["segment"]
        strike_step = cfg["strike_step"]
        try:
            expiries = get_expiries(scrip, segment, 1)
            expiry = expiries[0]
            spot, df = fetch_option_chain(scrip, segment, expiry)
            fut = _compute_synthetic_futures(spot, df, strike_step)
            prices[name] = {"spot": spot, "fut": fut, "expiry": expiry}
        except Exception as e:
            print(f"  [dashboard] {name} price error: {e}")
            prices[name] = {"spot": None, "fut": None, "expiry": None}
        time.sleep(1)

    _cache_set(cache_key, prices)
    return prices


def render_dashboard(container):
    """Build the dashboard page with clocks and price cards."""
    with container:
        # ---- Time Cards ----
        with ui.row().classes("w-full gap-4 sm:gap-6 mb-6 sm:mb-8 flex-wrap"):
            # IST Clock
            with ui.card().classes(
                "flex-1 min-w-[140px] clock-card-ist shadow-lg !rounded-xl"
            ):
                with ui.column().classes("items-center w-full py-4 sm:py-6"):
                    ui.icon("schedule", size="28px").classes("text-blue-300 mb-2 hidden sm:block")
                    ui.label("INDIA (IST)").classes(
                        "text-[10px] font-bold text-slate-400 uppercase tracking-[0.2em]"
                    )
                    ist_time_label = ui.label(
                        now_ist().strftime("%I:%M:%S %p")
                    ).classes("text-2xl sm:text-4xl font-bold text-white mt-2 tracking-tight")
                    ist_date_label = ui.label(
                        now_ist().strftime("%A, %d %B %Y")
                    ).classes("text-xs sm:text-sm text-slate-400 mt-1")

            # CEST Clock
            with ui.card().classes(
                "flex-1 min-w-[140px] clock-card-cest shadow-lg !rounded-xl"
            ):
                with ui.column().classes("items-center w-full py-4 sm:py-6"):
                    ui.icon("public", size="28px").classes("text-sky-300 mb-2 hidden sm:block")
                    ui.label("EUROPE (CET/CEST)").classes(
                        "text-[10px] font-bold text-slate-400 uppercase tracking-[0.2em]"
                    )
                    cest_time_label = ui.label(
                        now_cest().strftime("%I:%M:%S %p")
                    ).classes("text-2xl sm:text-4xl font-bold text-white mt-2 tracking-tight")
                    cest_date_label = ui.label(
                        now_cest().strftime("%A, %d %B %Y")
                    ).classes("text-xs sm:text-sm text-slate-400 mt-1")

        # Update clocks every second
        def update_clocks():
            ist_now = now_ist()
            cest_now = now_cest()
            ist_time_label.set_text(ist_now.strftime("%I:%M:%S %p"))
            ist_date_label.set_text(ist_now.strftime("%A, %d %B %Y"))
            cest_time_label.set_text(cest_now.strftime("%I:%M:%S %p"))
            cest_date_label.set_text(cest_now.strftime("%A, %d %B %Y"))

        ui.timer(1, update_clocks)

        # ---- Section Header ----
        with ui.row().classes("w-full items-center mb-4"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("monitoring", size="22px").classes("text-blue-500")
                ui.label("Market Overview").classes(
                    "text-lg font-semibold text-gray-800"
                )
            ui.space()
            update_time_label = ui.label("").classes("text-xs text-gray-400")

        # ---- Price Cards ----
        price_container = ui.element("div").classes("w-full")

        # Loading state
        with price_container:
            with ui.element("div").classes("w-full responsive-price-grid"):
                for name in ["NIFTY", "BANKNIFTY"]:
                    card_cls = "price-card-nifty" if name == "NIFTY" else "price-card-bnf"
                    for ptype in ["SPOT", "FUT"]:
                        with ui.card().classes(
                            f"{card_cls} border border-gray-200 shadow-sm !rounded-xl"
                        ).style("min-height: 120px"):
                            with ui.column().classes("items-center justify-center w-full h-full py-4"):
                                ui.label(f"{name} {ptype}").classes(
                                    "text-xs font-semibold text-gray-400 uppercase tracking-wider"
                                )
                                ui.label("--").classes(
                                    "text-2xl font-bold text-gray-300 mt-1"
                                )

    async def refresh():
        prices = await asyncio.get_event_loop().run_in_executor(
            None, fetch_dashboard_prices
        )

        price_container.clear()
        with price_container:
            with ui.element("div").classes("w-full responsive-price-grid"):
                for name in ["NIFTY", "BANKNIFTY"]:
                    data = prices.get(name, {})
                    spot = data.get("spot")
                    fut = data.get("fut")
                    expiry = data.get("expiry")

                    card_cls = "price-card-nifty" if name == "NIFTY" else "price-card-bnf"
                    dot_color = "bg-blue-500" if name == "NIFTY" else "bg-indigo-500"

                    # Spot card
                    with ui.card().classes(
                        f"{card_cls} border border-gray-200 shadow-sm !rounded-xl"
                    ).style("min-height: 120px"):
                        with ui.column().classes("w-full h-full justify-center py-4 sm:py-5 pl-4 sm:pl-5"):
                            with ui.row().classes("items-center gap-2"):
                                ui.element("div").classes(f"w-2 h-2 rounded-full {dot_color}")
                                ui.label(f"{name} SPOT").classes(
                                    "text-[11px] font-bold text-gray-500 uppercase tracking-widest"
                                )
                            spot_text = f"{spot:,.2f}" if spot else "N/A"
                            ui.label(spot_text).classes(
                                "text-xl sm:text-3xl font-bold text-gray-900 mt-2 tracking-tight"
                            )

                    # Futures card
                    with ui.card().classes(
                        f"{card_cls} border border-gray-200 shadow-sm !rounded-xl"
                    ).style("min-height: 120px"):
                        with ui.column().classes("w-full h-full justify-center py-4 sm:py-5 pl-4 sm:pl-5"):
                            with ui.row().classes("items-center gap-2"):
                                ui.element("div").classes(f"w-2 h-2 rounded-full {dot_color}")
                                exp_tag = ""
                                if expiry:
                                    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
                                    exp_tag = f" ({exp_date.strftime('%d%b').upper()})"
                                ui.label(f"{name} FUT{exp_tag}").classes(
                                    "text-[11px] font-bold text-gray-500 uppercase tracking-widest"
                                )
                            fut_text = f"{fut:,.2f}" if fut else "N/A"
                            ui.label(fut_text).classes(
                                "text-xl sm:text-3xl font-bold text-gray-900 mt-2 tracking-tight"
                            )

                            # Basis
                            if spot and fut:
                                basis = round(fut - spot, 2)
                                basis_pct = round((basis / spot) * 100, 3)
                                sign = "+" if basis >= 0 else ""
                                if basis >= 0:
                                    bg = "bg-green-50 text-green-700"
                                    icon = "arrow_drop_up"
                                else:
                                    bg = "bg-red-50 text-red-700"
                                    icon = "arrow_drop_down"
                                with ui.row().classes(
                                    f"items-center gap-0 mt-2 px-2 py-0.5 rounded-md {bg}"
                                ).style("width: fit-content"):
                                    ui.icon(icon, size="18px")
                                    ui.label(
                                        f"{sign}{basis:,.2f} ({sign}{basis_pct}%)"
                                    ).classes("text-xs font-semibold")

        update_time_label.set_text(
            f"Updated {now_ist().strftime('%H:%M:%S')} IST"
        )

    return refresh
