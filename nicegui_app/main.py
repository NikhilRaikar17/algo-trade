"""
Option Chain NiceGUI App
------------------------
NIFTY & BANKNIFTY option chain with ABCD and RSI+SMA algo trading.
Run:  cd nicegui_app && uv run python main.py
"""

import asyncio
from nicegui import ui, context

from config import now_ist, REFRESH_SECONDS, INDICES, get_next_holiday
from state import is_market_open, get_next_market_open
from pnl import send_daily_pnl_summary, send_market_open_msg
from pages import (
    render_dashboard,
    render_index_tab,
    render_algo_tab,
    render_pnl_tab,
    render_market_closed,
)


# ================= SIDEBAR NAV ITEMS =================

NAV_ITEMS = [
    {"id": "dashboard", "label": "Dashboard", "icon": "dashboard"},
    {"id": "nifty", "label": "NIFTY", "icon": "show_chart"},
    {"id": "banknifty", "label": "BANKNIFTY", "icon": "candlestick_chart"},
    {"id": "abcd", "label": "ABCD Algo", "icon": "insights"},
    {"id": "rsi", "label": "RSI + SMA", "icon": "analytics"},
    {"id": "pnl", "label": "P&L Summary", "icon": "account_balance_wallet"},
]


# ================= MAIN PAGE =================


@ui.page("/")
async def index():
    ui.page_title("Algo Trading")

    # ---- Custom CSS ----
    ui.add_head_html(
        """
    <style>
        .q-tab { font-size: 1.1rem !important; padding: 12px 20px !important; }
        .nav-btn { width: 100%; justify-content: flex-start !important; text-transform: none !important; }
        .nav-btn .q-btn__content { justify-content: flex-start !important; gap: 12px; }
        .nav-btn-active { background: rgba(59, 130, 246, 0.12) !important; color: #3b82f6 !important; font-weight: 600 !important; }
        .header-bar { backdrop-filter: blur(8px); }
    </style>
    """
    )

    # ---- State ----
    active_page = {"value": "dashboard"}
    refresh_fns = []
    _prev_market_open = [None]
    nav_btn_refs = {}
    page_client = context.client

    # ---- Header ----
    with (
        ui.header()
        .classes("header-bar bg-white shadow-sm border-b items-center px-6 py-0")
        .style("height: 56px")
    ):
        with ui.row().classes("items-center gap-3 w-full"):
            menu_btn = (
                ui.button(icon="menu", on_click=lambda: drawer.toggle())
                .props("flat dense round")
                .classes("text-gray-600")
            )

            ui.icon("trending_up", size="28px").classes("text-blue-600")
            ui.label("Algo Trade").classes(
                "text-xl font-bold text-gray-800 tracking-tight"
            )

            ui.space()

            # Market status badge
            market_open = is_market_open()
            if market_open:
                with ui.element("div").classes(
                    "flex items-center gap-2 bg-green-50 border border-green-200 rounded-full px-3 py-1"
                ):
                    ui.element("div").classes("w-2 h-2 rounded-full bg-green-500")
                    market_badge_label = ui.label("Market Open").classes(
                        "text-sm font-semibold text-green-700"
                    )
            else:
                with ui.element("div").classes(
                    "flex items-center gap-2 bg-red-50 border border-red-200 rounded-full px-3 py-1"
                ):
                    ui.element("div").classes("w-2 h-2 rounded-full bg-red-500")
                    market_badge_label = ui.label("Market Closed").classes(
                        "text-sm font-semibold text-red-700"
                    )

            # Refresh status
            status_label = ui.label("").classes("text-xs text-gray-400 hidden sm:block")

    # ---- Sidebar ----
    with (
        ui.left_drawer(value=True, bordered=True)
        .classes("bg-gray-50 border-r")
        .style("width: 220px; padding-top: 8px") as drawer
    ):
        with ui.element("div").classes("px-4 py-3 mb-2"):
            ui.label("Navigation").classes(
                "text-xs font-bold text-gray-400 uppercase tracking-wider"
            )

        def set_active_page(page_id):
            active_page["value"] = page_id
            for nid, btn in nav_btn_refs.items():
                if nid == page_id:
                    btn.classes(add="nav-btn-active")
                else:
                    btn.classes(remove="nav-btn-active")
            for nid, cont in page_containers.items():
                cont.set_visibility(nid == page_id)

        for item in NAV_ITEMS:
            btn = (
                ui.button(
                    item["label"],
                    icon=item["icon"],
                    on_click=lambda e, pid=item["id"]: set_active_page(pid),
                )
                .props("flat no-caps align=left")
                .classes("nav-btn rounded-lg mx-2 mb-1 text-gray-600")
            )
            if item["id"] == active_page["value"]:
                btn.classes(add="nav-btn-active")
            nav_btn_refs[item["id"]] = btn

        ui.separator().classes("my-3 mx-4")

        with ui.element("div").classes("px-4"):
            ui.label("Market Hours").classes(
                "text-xs font-bold text-gray-400 uppercase tracking-wider mb-1"
            )
            ui.label("9:15 AM — 3:30 PM IST").classes("text-sm text-gray-600")
            ui.label("Mon — Fri (excl. holidays)").classes("text-xs text-gray-400")
            current_time_label = ui.label(
                f"Current Time: {now_ist().strftime('%H:%M:%S')} IST"
            ).classes("text-sm text-gray-600 mt-2")
            ui.timer(
                1,
                lambda: current_time_label.set_text(
                    f"Current Time: {now_ist().strftime('%H:%M:%S')} IST"
                ),
            )

            ui.separator().classes("my-2")
            ui.label("Next Holiday").classes(
                "text-xs font-bold text-gray-400 uppercase tracking-wider mb-1"
            )
            holiday_info = get_next_holiday()
            if holiday_info:
                _, next_date, days_left = holiday_info
                day_label = "Today" if days_left == 0 else f"in {days_left} day{'s' if days_left != 1 else ''}"
                ui.label(next_date.strftime("%a, %d %b %Y")).classes(
                    "text-sm text-gray-600"
                )
                ui.label(day_label).classes("text-xs text-gray-400")
            else:
                ui.label("No upcoming holidays").classes("text-xs text-gray-400")

        ui.space()

        with ui.element("div").classes("px-4 pb-4"):
            ui.label(f"Auto-refresh: {REFRESH_SECONDS}s").classes(
                "text-xs text-gray-400"
            )

    # ---- Main Content Area ----
    with ui.element("div").classes("w-full p-6"):
        page_containers = {}

        for item in NAV_ITEMS:
            cont = ui.element("div").classes("w-full")
            cont.set_visibility(item["id"] == active_page["value"])
            page_containers[item["id"]] = cont

        closed_container = ui.element("div").classes("w-full")
        closed_container.set_visibility(False)

    # ---- Build Page Content ----
    async def build_ui():
        nonlocal refresh_fns
        refresh_fns = []

        market_open = is_market_open()

        for item in NAV_ITEMS:
            page_containers[item["id"]].clear()

        # Dashboard always renders
        refresh_fns.append(render_dashboard(page_containers["dashboard"]))

        # Option chains + P&L always render
        refresh_fns.append(
            render_index_tab(page_containers["nifty"], "NIFTY", INDICES["NIFTY"])
        )
        refresh_fns.append(
            render_index_tab(
                page_containers["banknifty"], "BANKNIFTY", INDICES["BANKNIFTY"]
            )
        )
        refresh_fns.append(render_pnl_tab(page_containers["pnl"]))

        # Algo tabs need live candle data
        if market_open:
            refresh_fns.append(render_algo_tab(page_containers["abcd"], "abcd"))
            refresh_fns.append(render_algo_tab(page_containers["rsi"], "rsi"))
        else:
            render_market_closed(page_containers["abcd"])
            render_market_closed(page_containers["rsi"])

    async def full_refresh():
        """Rebuild UI if market state changed, then refresh data."""
        if page_client._deleted:
            return

        current_open = is_market_open()

        if current_open != _prev_market_open[0]:
            _prev_market_open[0] = current_open
            await build_ui()

        status_label.text = f"Refreshing... {now_ist().strftime('%H:%M:%S')}"
        try:
            for fn in refresh_fns:
                if page_client._deleted:
                    return
                try:
                    await fn()
                except Exception as fn_err:
                    print(f"  [refresh fn error] {fn_err}")
                await asyncio.sleep(1)
            if not page_client._deleted:
                status_label.text = f"Last refresh: {now_ist().strftime('%H:%M:%S')} | Next in {REFRESH_SECONDS}s"
        except Exception as e:
            if not page_client._deleted:
                status_label.text = f"Refresh error: {e}"
            print(f"  [refresh error] {e}")

        if is_market_open():
            send_market_open_msg()
        send_daily_pnl_summary()

    # Initial build and refresh
    await build_ui()
    _prev_market_open[0] = is_market_open()
    ui.timer(2, lambda: asyncio.ensure_future(full_refresh()), once=True)

    # Periodic data refresh
    ui.timer(REFRESH_SECONDS, lambda: asyncio.ensure_future(full_refresh()))

    # Live countdown updater (every 1s)
    def update_countdown():
        if page_client._deleted:
            return
        if not is_market_open():
            next_open = get_next_market_open()
            remaining = next_open - now_ist()
            total_sec = max(0, int(remaining.total_seconds()))
            h, rem = divmod(total_sec, 3600)
            m, s = divmod(rem, 60)
            status_label.text = f"Next open: {h:02d}h {m:02d}m {s:02d}s"

    ui.timer(1, update_countdown)


# ================= RUN =================

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="AlgTrd", host="0.0.0.0", port=8501, reload=False)
