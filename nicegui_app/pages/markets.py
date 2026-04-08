"""
Markets overview page: all NSE indices grouped by category, dashboard-style cards.
"""

import asyncio
import traceback
from nicegui import ui, context

from config import now_ist
from data import fetch_market_overview


def render_markets_tab(container):
    with container:
        with ui.row().classes("items-center gap-2 mb-1"):
            ui.icon("bar_chart", size="24px").classes("text-blue-500")
            ui.label("Markets Overview").classes("text-xl font-bold text-gray-800")
        ui.label("NSE indices — today vs previous close").classes(
            "text-xs text-gray-400 mb-4"
        )
        content = ui.element("div").classes("w-full")
        with content:
            ui.spinner("dots", size="lg").classes("mx-auto my-8 block")

    page_client = context.client

    async def refresh():
        if page_client._deleted:
            return
        try:
            groups = await asyncio.get_event_loop().run_in_executor(
                None, fetch_market_overview
            )
            if page_client._deleted:
                return
            content.clear()
            with content:
                for group in groups:
                    _render_group(group["group"], group["indices"])
                ui.label(
                    f"Last updated: {now_ist().strftime('%H:%M:%S')} IST"
                ).classes("text-xs text-gray-400 mt-4")
        except Exception:
            if not page_client._deleted:
                content.clear()
                with content:
                    ui.label("Error loading market data.").classes("text-red-500")
            print(f"  [markets] error:\n{traceback.format_exc()}")

    return refresh


def _render_group(title, indices):
    # Sort: indices with data first (green then red by % change desc), no-data last
    def _sort_key(e):
        d = e.get("data")
        if d is None:
            return (1, 0)
        return (0, -d["change_pct"])

    sorted_indices = sorted(indices, key=_sort_key)

    with ui.element("div").classes("mb-2"):
        with ui.row().classes("items-center gap-3 mb-3"):
            ui.label(title).classes(
                "text-xs font-bold text-gray-500 uppercase tracking-widest"
            )
            ui.element("div").classes("flex-1 h-px bg-gray-200")
        with ui.element("div").classes("grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2 mb-6"):
            for entry in sorted_indices:
                _index_card(entry["name"], entry.get("data"))


def _index_card(name, d):
    if d is None:
        with ui.card().classes(
            "border border-gray-100 rounded-lg shadow-sm px-3 py-2 bg-white"
        ).props("flat"):
            ui.label(name).classes("text-[10px] font-bold text-gray-400 uppercase tracking-wide")
            ui.label("—").classes("text-sm text-gray-300")
        return

    is_green   = d["is_green"]
    sign       = "+" if d["change"] >= 0 else ""
    border_cls = "border-l-[3px] border-green-500" if is_green else "border-l-[3px] border-red-500"
    price_cls  = "text-green-700 font-bold" if is_green else "text-red-700 font-bold"
    change_cls = "text-green-600" if is_green else "text-red-600"
    dot_cls    = "bg-green-500" if is_green else "bg-red-500"

    with ui.card().classes(
        f"rounded-lg shadow-sm bg-white px-3 py-2 {border_cls}"
    ).props("flat"):
        with ui.row().classes("items-center gap-1.5 w-full mb-0.5"):
            ui.element("div").classes(f"w-1.5 h-1.5 rounded-full {dot_cls}")
            ui.label(name).classes("text-[10px] font-bold text-gray-500 uppercase tracking-widest truncate")

        ui.label(f"{d['current']:,.2f}").classes(f"text-sm {price_cls} leading-tight")

        ui.label(f"{sign}{d['change_pct']:.2f}%").classes(f"text-[10px] font-semibold {change_cls}")
