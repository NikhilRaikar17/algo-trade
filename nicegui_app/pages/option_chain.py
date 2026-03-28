"""
NIFTY / BANKNIFTY option chain tab page.
"""

import asyncio
from nicegui import ui

from config import now_ist
from data import get_expiries, fetch_option_chain, build_name_column, filter_and_split, add_trend
from ui_components import build_option_chain_table


def render_index_tab(container, index_name, cfg):
    """Build the NIFTY or BANKNIFTY option chain tab content inside container."""
    scrip = cfg["scrip"]
    segment = cfg["segment"]
    strike_step = cfg["strike_step"]
    strike_range = cfg["strike_range"]
    prefix = cfg["name_prefix"]

    with container:
        with ui.row().classes("w-full items-center gap-4 mb-2"):
            spot_label = ui.label("Loading...").classes("text-2xl font-bold")
            atm_label = ui.label("").classes("text-lg text-gray-500")
            time_label = ui.label("").classes("text-sm text-gray-400 ml-auto")

        expiry_tabs_container = ui.element("div").classes("w-full")

    async def refresh():
        try:
            expiries = get_expiries(scrip, segment, 3)
            print(f"  [{index_name}] got expiries: {expiries}")
        except Exception as e:
            print(f"  [{index_name}] expiry error: {e}")
            spot_label.text = f"Error: {e}"
            return

        chain_data = {}
        for expiry in expiries:
            try:
                spot, df = fetch_option_chain(scrip, segment, expiry)
                chain_data[expiry] = (spot, df)
                print(f"  [{index_name}] {expiry}: spot={spot}, rows={len(df)}")
            except Exception as e:
                print(f"  [{index_name}] {expiry} error: {e}")
                chain_data[expiry] = e
            await asyncio.sleep(1)

        spot_val = None
        for result in chain_data.values():
            if not isinstance(result, Exception):
                spot_val = result[0]
                break

        spot_label.text = (
            f"{index_name}: {spot_val:,.2f}" if spot_val else f"{index_name}: N/A"
        )
        atm_val = round(spot_val / strike_step) * strike_step if spot_val else "N/A"
        atm_label.text = f"ATM: {atm_val:,}" if spot_val else "ATM: N/A"
        time_label.text = f"Updated: {now_ist().strftime('%H:%M:%S')}"

        expiry_tabs_container.clear()
        with expiry_tabs_container:
            if not expiries:
                ui.label("No expiries found").classes("text-grey")
            else:
                with ui.tabs().classes("w-full") as tabs:
                    tab_items = []
                    for exp in expiries:
                        tab_items.append(ui.tab(f"Expiry: {exp}"))

                with ui.tab_panels(tabs, value=tab_items[0]).classes("w-full"):
                    for tab_item, exp in zip(tab_items, expiries):
                        with ui.tab_panel(tab_item):
                            result = chain_data.get(exp)
                            if isinstance(result, Exception):
                                ui.label(f"Error: {result}").classes("text-red-500")
                                continue
                            if result is None:
                                ui.label("No data").classes("text-grey")
                                continue

                            spot, df = result
                            atm = round(spot / strike_step) * strike_step
                            df = build_name_column(df, exp, prefix)
                            ce, pe = filter_and_split(df, atm, strike_range)
                            ce = add_trend(ce, index_name, exp, "CE")
                            pe = add_trend(pe, index_name, exp, "PE")

                            print(
                                f"  [{index_name}] {exp}: CE rows={len(ce)}, PE rows={len(pe)}, ATM={atm}"
                            )

                            with ui.row().classes(
                                "w-full gap-4 flex-wrap items-start"
                            ):
                                with ui.column().classes("flex-1 min-w-[300px]"):
                                    ui.label("CALL (CE)").classes(
                                        "text-lg font-bold text-green-600"
                                    )
                                    ce_container = ui.element("div").classes("w-full overflow-x-auto")
                                    build_option_chain_table(ce_container, ce, atm)

                                with ui.column().classes("flex-1 min-w-[300px]"):
                                    ui.label("PUT (PE)").classes(
                                        "text-lg font-bold text-red-600"
                                    )
                                    pe_container = ui.element("div").classes("w-full overflow-x-auto")
                                    build_option_chain_table(pe_container, pe, atm)

    return refresh
