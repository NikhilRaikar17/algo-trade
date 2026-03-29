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

    with ui.element("div").classes("mb-6"):
        ui.label(title).classes(
            "text-xs font-bold text-gray-400 uppercase tracking-widest mb-3"
        )
        with ui.element("div").classes("markets-grid"):
            for entry in sorted_indices:
                _index_card(entry["name"], entry.get("data"))


def _index_card(name, d):
    if d is None:
        with ui.card().classes(
            "border border-gray-100 rounded-xl shadow-sm p-3 bg-white"
        ).props("flat"):
            ui.label(name).classes("text-xs font-bold text-gray-500 uppercase tracking-wide")
            ui.label("No data").classes("text-sm text-gray-300 mt-1")
        return

    is_green   = d["is_green"]
    sign       = "+" if d["change"] >= 0 else ""
    border_cls = "border-l-[3px] border-green-500" if is_green else "border-l-[3px] border-red-500"
    price_cls  = "text-green-700 font-bold" if is_green else "text-red-700 font-bold"
    change_cls = "text-green-600" if is_green else "text-red-600"
    dot_cls    = "bg-green-500" if is_green else "bg-red-500"
    bar_cls    = "bg-green-400" if is_green else "bg-red-400"

    hl_range = d["high"] - d["low"]
    bar_pct  = int(((d["current"] - d["low"]) / hl_range * 100)) if hl_range > 0 else 50
    bar_pct  = max(2, min(98, bar_pct))

    with ui.card().classes(
        f"rounded-xl shadow-sm bg-white p-3 {border_cls}"
    ).props("flat"):
        # Name row
        with ui.row().classes("items-center gap-1.5 w-full mb-1"):
            ui.element("div").classes(f"w-2 h-2 rounded-full {dot_cls}")
            ui.label(name).classes(
                "text-[10px] font-bold text-gray-500 uppercase tracking-widest"
            )

        # Price
        ui.label(f"{d['current']:,.2f}").classes(f"text-xl {price_cls} leading-tight")

        # Change
        with ui.row().classes("items-center gap-1 mt-0.5"):
            ui.label(f"{sign}{d['change']:,.2f}").classes(
                f"text-xs font-semibold {change_cls}"
            )
            ui.label(f"({sign}{d['change_pct']:.2f}%)").classes(
                f"text-xs {change_cls}"
            )

        # High / Low bar
        with ui.element("div").classes("mt-2"):
            with ui.row().classes("justify-between mb-0.5"):
                ui.label(f"L {d['low']:,.0f}").classes("text-[9px] text-gray-400")
                ui.label(f"H {d['high']:,.0f}").classes("text-[9px] text-gray-400")
            with ui.element("div").classes(
                "w-full h-1 bg-gray-100 rounded-full overflow-hidden"
            ):
                ui.element("div").classes(
                    f"h-full {bar_cls} rounded-full"
                ).style(f"width: {bar_pct}%")

        # Prev close
        ui.label(f"Prev {d['prev_close']:,.2f}").classes(
            "text-[9px] text-gray-400 mt-1"
        )
