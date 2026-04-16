"""
Global Markets page: US, Europe, Asia indices, Commodities & Crypto.
"""

import asyncio
import traceback

from nicegui import ui, context

from config import now_ist
from pages.dashboard import (
    _render_global_markets_grid,
    _render_global_markets_loading,
)


def render_global_markets_tab(container):
    with container:
        with ui.row().classes("items-center gap-2 mb-1"):
            ui.icon("public", size="24px").classes("text-emerald-500")
            ui.label("Global Markets").classes("text-xl font-bold text-gray-800")
        ui.label("Worldwide indices, commodities & crypto — delayed ~15 min").classes(
            "text-xs text-gray-400 mb-4"
        )
        content = ui.element("div").classes("w-full")
        with content:
            _render_global_markets_loading()

    page_client = context.client

    async def refresh():
        if page_client._deleted:
            return
        try:
            from state import get_all_global_prices
            global_prices = get_all_global_prices()
            if page_client._deleted:
                return
            content.clear()
            with content:
                if global_prices:
                    _render_global_markets_grid(global_prices)
                else:
                    _render_global_markets_loading()
            content.update()
        except Exception:
            if not page_client._deleted:
                content.clear()
                with content:
                    ui.label("Error loading global market data.").classes("text-red-500")
            print(f"  [global_markets] error:\n{traceback.format_exc()}")

    return refresh
