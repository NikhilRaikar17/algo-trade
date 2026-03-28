"""
Option Chain NiceGUI App
------------------------
NIFTY & BANKNIFTY option chain with ABCD and RSI+SMA algo trading.
Run:  cd nicegui_app && uv run python main.py
"""

import asyncio
from nicegui import ui, context

from config import now_ist, REFRESH_SECONDS, INDICES
from state import is_market_open, get_next_market_open
from sidebar import build_sidebar
from pnl import send_daily_pnl_summary, send_morning_message
from pages import (
    render_dashboard,
    render_index_tab,
    render_algo_tab,
    render_rsi_only_tab,
    render_abcd_only_tab,
    render_pnl_tab,
    render_market_closed,
)


# ================= PAGE IDS =================
# All page IDs used for containers and navigation
ALL_PAGE_IDS = [
    "dashboard",
    "nifty",
    "banknifty",
    "abcd",
    "rsi",
    "rsi_nifty",
    "rsi_banknifty",
    "abcd_nifty",
    "abcd_banknifty",
    "pnl",
]


# ================= MAIN PAGE =================


@ui.page("/")
async def index():
    ui.page_title("Algo Trading")

    # ---- Custom CSS ----
    ui.add_head_html(
        """
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        .q-tab { font-size: 1.1rem !important; padding: 12px 20px !important; }
        .nav-btn { width: 100%; justify-content: flex-start !important; text-transform: none !important;
                   white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important;
                   min-height: 36px !important; padding: 4px 12px !important; font-size: 0.85rem !important; }
        .nav-btn .q-btn__content { justify-content: flex-start !important; gap: 10px; flex-wrap: nowrap !important; overflow: hidden !important; }
        .nav-btn-active { background: rgba(59, 130, 246, 0.12) !important; color: #3b82f6 !important; font-weight: 600 !important; }
        .nav-sub-btn { width: 100%; justify-content: flex-start !important; text-transform: none !important;
                       white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important;
                       min-height: 32px !important; padding: 2px 8px !important; font-size: 0.8rem !important; }
        .nav-sub-btn .q-btn__content { justify-content: flex-start !important; gap: 6px; flex-wrap: nowrap !important; overflow: hidden !important; }
        .header-bar { backdrop-filter: blur(8px); }
        .nav-section-label {
            font-size: 0.6rem; font-weight: 700; color: #9ca3af;
            text-transform: uppercase; letter-spacing: 0.08em;
            padding: 6px 16px 2px 16px;
        }
        .q-expansion-item { font-size: 0.82rem !important; }
        .q-expansion-item .q-item__label { white-space: nowrap !important; }

        /* ---- Dashboard clock cards ---- */
        .clock-card-ist {
            background: linear-gradient(135deg, #1e293b 0%, #334155 100%) !important;
            border: none !important;
        }
        .clock-card-cest {
            background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%) !important;
            border: none !important;
        }

        /* ---- Dashboard price cards ---- */
        .price-card-nifty {
            background: #fafbff !important;
            border-left: 4px solid #3b82f6 !important;
            transition: box-shadow 0.2s, transform 0.2s;
        }
        .price-card-nifty:hover { box-shadow: 0 4px 20px rgba(59,130,246,0.12) !important; transform: translateY(-2px); }
        .price-card-bnf {
            background: #fafafa !important;
            border-left: 4px solid #6366f1 !important;
            transition: box-shadow 0.2s, transform 0.2s;
        }
        .price-card-bnf:hover { box-shadow: 0 4px 20px rgba(99,102,241,0.12) !important; transform: translateY(-2px); }

        /* ---- Responsive grid for price cards ---- */
        .responsive-price-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1.25rem;
        }
        @media (max-width: 1024px) {
            .responsive-price-grid {
                grid-template-columns: repeat(2, 1fr);
                gap: 0.75rem;
            }
        }
        @media (max-width: 480px) {
            .responsive-price-grid {
                grid-template-columns: 1fr;
                gap: 0.5rem;
            }
        }

        /* ---- Responsive tabs & header ---- */
        @media (max-width: 768px) {
            .q-tab { font-size: 0.85rem !important; padding: 8px 10px !important; }
            .q-header { padding-left: 12px !important; padding-right: 12px !important; }
            .q-drawer { width: 190px !important; }
            .nav-btn { font-size: 0.78rem !important; padding: 3px 8px !important; }
            .nav-sub-btn { font-size: 0.73rem !important; padding: 2px 6px !important; }
            .nav-section-label { font-size: 0.55rem; padding: 4px 12px 2px 12px; }
        }
        @media (max-width: 480px) {
            .q-tab { font-size: 0.75rem !important; padding: 6px 6px !important; white-space: nowrap !important; }
        }

        /* ---- Responsive tables ---- */
        .responsive-table-wrap {
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }
        .responsive-table-wrap table {
            min-width: 500px;
        }
        .q-table__container { overflow-x: auto !important; }
        @media (max-width: 768px) {
            .q-table th, .q-table td { padding: 4px 6px !important; font-size: 0.75rem !important; }
        }
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
        .style("width: 240px; padding-top: 8px") as drawer
    ):
        pass  # content built after page_containers exist

    # ---- Main Content Area ----
    with ui.element("div").classes("w-full p-3 sm:p-6"):
        page_containers = {}

        for pid in ALL_PAGE_IDS:
            cont = ui.element("div").classes("w-full")
            cont.set_visibility(pid == active_page["value"])
            page_containers[pid] = cont

    # Now build sidebar (needs page_containers to be defined)
    build_sidebar(drawer, active_page, nav_btn_refs, page_containers)

    # ---- Build Page Content ----
    async def build_ui():
        nonlocal refresh_fns
        refresh_fns = []

        market_open = is_market_open()

        for pid in ALL_PAGE_IDS:
            page_containers[pid].clear()

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

        # Historical backtest — always render
        refresh_fns.append(
            render_rsi_only_tab(page_containers["rsi_nifty"], "NIFTY")
        )
        refresh_fns.append(
            render_rsi_only_tab(page_containers["rsi_banknifty"], "BANKNIFTY")
        )
        refresh_fns.append(
            render_abcd_only_tab(page_containers["abcd_nifty"], "NIFTY")
        )
        refresh_fns.append(
            render_abcd_only_tab(page_containers["abcd_banknifty"], "BANKNIFTY")
        )

        # Live algo tabs need market open
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
                    if page_client._deleted:
                        return
                    print(f"  [refresh fn error] {fn_err}")
                if page_client._deleted:
                    return
                await asyncio.sleep(1)
            if not page_client._deleted:
                status_label.text = f"Last refresh: {now_ist().strftime('%H:%M:%S')} | Next in {REFRESH_SECONDS}s"
        except Exception as e:
            if not page_client._deleted:
                status_label.text = f"Refresh error: {e}"
            print(f"  [refresh error] {e}")

        send_morning_message()
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
    ui.run(title="AlgTrd", host="0.0.0.0", port=8501, reload=True)
