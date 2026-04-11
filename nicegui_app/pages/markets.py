"""
Markets overview page: all NSE indices grouped by category, dashboard-style cards.
"""

import asyncio
import json
import traceback
import uuid

from nicegui import ui, context

from config import now_ist
from data import fetch_market_overview, fetch_daily_candles_for_index
from tv_charts import _BASE_OPTS, _CANDLE_OPTS, _schedule_js, _candles_to_tv, _resize_listener, _ohlc_tooltip_js


def _show_chart_modal(name, security_id):
    """Fetch daily candles in background and show a modal with a Lightweight Chart."""
    with ui.dialog().props("persistent").classes("!max-w-5xl w-full") as dlg:
        dlg.open()
        with ui.card().classes("w-full !rounded-xl").style("min-width:min(900px,95vw);padding:0;"):
            # Header
            with ui.row().classes("items-center gap-2 px-5 py-3 border-b border-gray-200"):
                ui.icon("candlestick_chart", size="20px").classes("text-emerald-500")
                ui.label(f"{name} — Daily Chart").classes("text-sm font-bold text-gray-800 flex-1")
                ui.button(icon="close", on_click=dlg.close).props("flat round dense")

            chart_area = ui.element("div").classes("w-full px-4 py-4")
            with chart_area:
                ui.spinner("dots", size="lg").classes("mx-auto my-8 block")

    async def _load():
        candles = await asyncio.get_event_loop().run_in_executor(
            None, lambda: fetch_daily_candles_for_index(security_id)
        )
        chart_area.clear()
        with chart_area:
            if candles is None or candles.empty:
                ui.label("No data available.").classes("text-gray-400 italic text-sm p-4")
                return

            chart_id = f"tv_{uuid.uuid4().hex[:10]}"
            ui.html(
                f'<div id="{chart_id}" style="width:100%;height:420px;"></div>',
                sanitize=False,
            )

            ohlc = _candles_to_tv(candles)
            opts = dict(_BASE_OPTS)
            opts["height"] = 420

            js = f"""
            (function initModal_{chart_id}() {{
                var el = document.getElementById('{chart_id}');
                if (!el) {{ setTimeout(initModal_{chart_id}, 100); return; }}
                var opts = {json.dumps(opts)};
                opts.width = _tvElWidth(el);
                var chart = LightweightCharts.createChart(el, opts);
                var cs = chart.addCandlestickSeries({json.dumps(_CANDLE_OPTS)});
                cs.setData({json.dumps(ohlc)});
                {_ohlc_tooltip_js("chart", "cs", "el")}
                chart.timeScale().fitContent();
                {_resize_listener("chart", "el")}
            }})();
            """
            _schedule_js(js)

    asyncio.ensure_future(_load())


def render_markets_tab(container):
    with container:
        with ui.row().classes("items-center gap-2 mb-1"):
            ui.icon("bar_chart", size="24px").classes("text-emerald-500")
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
        with ui.element("div").classes(
            "grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2 mb-6"
        ):
            for entry in sorted_indices:
                _index_card(entry["name"], entry.get("security_id"), entry.get("data"))


def _index_card(name, security_id, d):
    def on_click(n=name, sid=security_id):
        _show_chart_modal(n, sid)

    if d is None:
        with ui.card().classes(
            "rounded-lg shadow-sm px-3 py-2 bg-white cursor-pointer"
        ).style("border: 2px solid #d1d5db !important;").on("click", on_click):
            ui.label(name).classes("text-[10px] font-bold text-gray-400 uppercase tracking-wide")
            ui.label("—").classes("text-sm text-gray-300")
        return

    is_green     = d["is_green"]
    sign         = "+" if d["change"] >= 0 else ""
    price_cls    = "text-green-700 font-bold" if is_green else "text-red-700 font-bold"
    change_cls   = "text-green-600" if is_green else "text-red-600"
    dot_cls      = "bg-green-500" if is_green else "bg-red-500"
    border_color = "#4ade80" if is_green else "#f87171"

    with ui.card().classes(
        "rounded-lg shadow-sm px-3 py-2 bg-white cursor-pointer"
    ).style(f"border: 2px solid {border_color} !important;").on("click", on_click):
        with ui.row().classes("items-center gap-1.5 w-full mb-0.5"):
            ui.element("div").classes(f"w-1.5 h-1.5 rounded-full {dot_cls}")
            ui.label(name).classes(
                "text-[10px] font-bold text-gray-500 uppercase tracking-widest truncate"
            )
        ui.label(f"{d['current']:,.2f}").classes(f"text-sm {price_cls} leading-tight")
        ui.label(f"{sign}{d['change_pct']:.2f}%").classes(f"text-[10px] font-semibold {change_cls}")
