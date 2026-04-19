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
        with ui.row().classes("w-full items-center gap-4 mb-2").style(
            "border-bottom:1px solid var(--at-line2); padding-bottom:10px;"
        ):
            spot_label = ui.label("Loading...").style(
                "font-family:var(--at-mono); font-size:1.35rem; font-weight:700; "
                "color:var(--at-fg); letter-spacing:0.02em;"
            )
            with ui.element("div").style(
                "display:flex; align-items:center; gap:6px; "
                "background:rgba(255,176,32,0.12); border:1px solid rgba(255,176,32,0.3); "
                "border-radius:4px; padding:2px 8px;"
            ):
                ui.label("ATM").style(
                    "font-size:0.6rem; font-weight:700; letter-spacing:0.1em; "
                    "color:var(--at-warn); text-transform:uppercase;"
                )
                atm_label = ui.label("").style(
                    "font-family:var(--at-mono); font-size:0.85rem; font-weight:700; "
                    "color:var(--at-warn);"
                )
            time_label = ui.label("").style(
                "font-size:0.7rem; color:var(--at-fg-faint); "
                "font-family:var(--at-mono); margin-left:auto;"
            )

        expiry_tabs_container = ui.element("div").classes("w-full")

    async def refresh():
        loop = asyncio.get_event_loop()
        try:
            expiries = await loop.run_in_executor(
                None, lambda: get_expiries(scrip, segment, 3)
            )
            print(f"  [{index_name}] got expiries: {expiries}")
        except Exception as e:
            print(f"  [{index_name}] expiry error: {e}")
            if not spot_label.client._deleted:
                spot_label.text = f"Error: {e}"
            return

        if spot_label.client._deleted:
            return

        chain_data = {}
        for expiry in expiries:
            try:
                spot, df = await loop.run_in_executor(
                    None, lambda e=expiry: fetch_option_chain(scrip, segment, e)
                )
                chain_data[expiry] = (spot, df)
                print(f"  [{index_name}] {expiry}: spot={spot}, rows={len(df)}")
            except Exception as e:
                print(f"  [{index_name}] {expiry} error: {e}")
                chain_data[expiry] = e
            if spot_label.client._deleted:
                return
            await asyncio.sleep(0.2)

        if spot_label.client._deleted:
            return

        spot_val = None
        for result in chain_data.values():
            if not isinstance(result, Exception):
                spot_val = result[0]
                break

        spot_label.text = (
            f"{index_name}: {spot_val:,.2f}" if spot_val else f"{index_name}: N/A"
        )
        atm_val = round(spot_val / strike_step) * strike_step if spot_val else "N/A"
        atm_label.text = f"{atm_val:,}" if spot_val else "N/A"
        time_label.text = f"⟳  {now_ist().strftime('%H:%M:%S')} IST"

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
                                    with ui.row().style(
                                        "align-items:center; gap:8px; margin-bottom:8px;"
                                    ):
                                        ui.element("div").style(
                                            "width:3px; height:16px; border-radius:2px; "
                                            "background:var(--at-up);"
                                        )
                                        ui.label("CALL").style(
                                            "font-family:var(--at-mono); font-size:0.7rem; "
                                            "font-weight:700; letter-spacing:0.12em; "
                                            "color:var(--at-up); text-transform:uppercase;"
                                        )
                                        ui.label("CE").style(
                                            "font-size:0.6rem; font-weight:700; "
                                            "letter-spacing:0.1em; color:var(--at-fg-faint); "
                                            "background:var(--at-bg2); padding:1px 5px; "
                                            "border-radius:3px;"
                                        )
                                    ce_container = ui.element("div").classes("w-full overflow-x-auto")
                                    build_option_chain_table(ce_container, ce, atm)

                                with ui.column().classes("flex-1 min-w-[300px]"):
                                    with ui.row().style(
                                        "align-items:center; gap:8px; margin-bottom:8px;"
                                    ):
                                        ui.element("div").style(
                                            "width:3px; height:16px; border-radius:2px; "
                                            "background:var(--at-down);"
                                        )
                                        ui.label("PUT").style(
                                            "font-family:var(--at-mono); font-size:0.7rem; "
                                            "font-weight:700; letter-spacing:0.12em; "
                                            "color:var(--at-down); text-transform:uppercase;"
                                        )
                                        ui.label("PE").style(
                                            "font-size:0.6rem; font-weight:700; "
                                            "letter-spacing:0.1em; color:var(--at-fg-faint); "
                                            "background:var(--at-bg2); padding:1px 5px; "
                                            "border-radius:3px;"
                                        )
                                    pe_container = ui.element("div").classes("w-full overflow-x-auto")
                                    build_option_chain_table(pe_container, pe, atm)

    return refresh
