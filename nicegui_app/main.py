"""
Option Chain NiceGUI App
------------------------
NIFTY & BANKNIFTY option chain with ABCD and RSI+SMA algo trading.
Run:  cd nicegui_app && uv run python main.py
"""

import asyncio
from nicegui import ui, context, app

from config import now_ist, REFRESH_SECONDS, INDICES
from state import is_market_open, get_next_market_open
from sidebar import build_sidebar
from pnl import send_daily_pnl_summary, send_morning_message, send_premarket_alert
from pages import (
    render_dashboard,
    render_markets_tab,
    render_index_tab,
    render_algo_tab,
    render_rsi_only_tab,
    render_abcd_only_tab,
    render_double_top_tab,
    render_double_bottom_tab,
    render_channel_breakout_tab,
    render_channel_down_tab,
    render_sma50_tab,
    render_ema10_tab,
    render_pnl_tab,
    render_backtest_pnl_tab,
    render_market_closed,
    render_market_news_tab,
)


# ================= PAGE IDS =================
# All page IDs used for containers and navigation
ALL_PAGE_IDS = [
    "dashboard",
    "markets",
    "market_news",
    "nifty",
    "banknifty",
    "abcd",
    "rsi",
    "rsi_only",
    "abcd_only",
    "dt_only",
    "db_only",
    "cb_only",
    "cd_only",
    "sma50",
    "ema10",
    "backtest_pnl",
    "pnl",
]


# ================= BACKGROUND SCHEDULER =================


@app.on_startup
async def _start_scheduler():
    """Server-side loop — runs independently of any browser connection."""
    async def _loop():
        while True:
            await asyncio.sleep(60)
            try:
                send_premarket_alert()
                send_morning_message()
                send_daily_pnl_summary()
            except Exception as e:
                print(f"  [scheduler error] {e}")

    asyncio.create_task(_loop())


# ================= MAIN PAGE =================


@ui.page("/")
async def index():
    ui.page_title("Algo Trading")

    # ---- Custom CSS + TradingView ----
    ui.add_head_html(
        '<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>'
    )
    ui.add_head_html(
        """
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        .q-tab { font-size: 1.1rem !important; padding: 12px 20px !important; }
        .nav-btn { width: 100%; justify-content: flex-start !important; text-transform: none !important;
                   white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important;
                   min-height: 36px !important; padding: 4px 12px !important; font-size: 0.85rem !important; }
        .nav-btn .q-btn__content { justify-content: flex-start !important; gap: 10px; flex-wrap: nowrap !important; overflow: hidden !important; }
        .nav-btn .q-icon { color: #3b82f6 !important; }
        .nav-btn-active { background: rgba(59, 130, 246, 0.12) !important; color: #3b82f6 !important; font-weight: 600 !important; }
        .nav-sub-btn { width: 100%; justify-content: flex-start !important; text-transform: none !important;
                       white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important;
                       min-height: 32px !important; padding: 2px 8px !important; font-size: 0.8rem !important; }
        .nav-sub-btn .q-btn__content { justify-content: flex-start !important; gap: 6px; flex-wrap: nowrap !important; overflow: hidden !important; }
        .nav-sub-btn .q-icon { color: #3b82f6 !important; }
        .header-bar { backdrop-filter: blur(8px); }
        .nav-section-label {
            font-size: 0.6rem; font-weight: 700; color: #9ca3af;
            text-transform: uppercase; letter-spacing: 0.08em;
            padding: 6px 16px 2px 16px;
        }
        .q-expansion-item { font-size: 0.82rem !important; color: #111827 !important; }
        .q-expansion-item .q-icon { color: #3b82f6 !important; }
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

        /* ---- Header ticker (spot prices) ---- */
        .ticker-badge {
            display: flex; align-items: center; gap: 6px;
            border-radius: 8px; padding: 4px 10px;
            font-size: 0.78rem; font-weight: 700;
            transition: background 0.3s;
            cursor: default; user-select: none;
        }
        .ticker-badge.up   { background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; }
        .ticker-badge.down { background: #fee2e2; color: #b91c1c; border: 1px solid #fecaca; }
        .ticker-badge.flat { background: #f1f5f9; color: #475569; border: 1px solid #e2e8f0; }
        @keyframes ticker-blink {
            0%   { opacity: 1; }
            40%  { opacity: 0.25; }
            100% { opacity: 1; }
        }
        .ticker-blink { animation: ticker-blink 0.6s ease-in-out; }

        /* ---- Responsive tabs & header ---- */
        .q-drawer { background: #fff !important; overflow-y: auto !important; }
        .q-drawer .q-scrollarea { overflow: visible !important; }
        @media (max-width: 1023px) {
            .q-tab { font-size: 0.85rem !important; padding: 8px 10px !important; }
            .q-header { padding-left: 12px !important; padding-right: 12px !important; }
            .q-drawer { width: 200px !important; }
            .nav-btn { font-size: 0.78rem !important; padding: 3px 8px !important; }
            .nav-sub-btn { font-size: 0.73rem !important; padding: 2px 6px !important; }
            .nav-section-label { font-size: 0.55rem; padding: 4px 12px 2px 12px; }
        }
        @media (max-width: 599px) {
            .q-tab { font-size: 0.75rem !important; padding: 6px 6px !important; white-space: nowrap !important; }
            .q-drawer { width: 220px !important; }
        }

        /* ---- Markets grid ---- */
        .markets-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 0.75rem;
        }
        @media (max-width: 1024px) {
            .markets-grid { grid-template-columns: repeat(3, 1fr); }
        }
        @media (max-width: 768px) {
            .markets-grid { grid-template-columns: repeat(2, 1fr); }
        }
        @media (max-width: 480px) {
            .markets-grid { grid-template-columns: 1fr; }
        }

        /* ---- News grid ---- */
        .news-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1rem;
        }
        @media (max-width: 1024px) {
            .news-grid { grid-template-columns: repeat(2, 1fr); }
        }
        @media (max-width: 600px) {
            .news-grid { grid-template-columns: 1fr; }
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
    refresh_fns = {}
    _prev_market_open = [None]
    _dashboard_refresh = [None]   # persists across build_ui() calls — avoids re-creating clock timer
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

            # ---- Live spot price tickers ----
            _header_tickers = {}
            for _idx in ["NIFTY", "BANKNIFTY"]:
                _badge = ui.element("div").classes("ticker-badge flat")
                with _badge:
                    _lbl = ui.label(f"{_idx}  --").classes("font-bold text-sm")
                _header_tickers[_idx] = {"badge": _badge, "label": _lbl, "prev": None}

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
        ui.left_drawer(value=True, bordered=False)
        .props("breakpoint=1023")
        .classes("bg-white")
        .style("width: 240px; padding-top: 8px; box-shadow: 2px 0 12px rgba(0,0,0,0.06); overflow-y: auto; max-height: 100vh;") as drawer
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
    # _refresh_trigger is set after full_refresh is defined below; late-binding via list
    _refresh_trigger = [None]
    async def _on_navigate(pid):
        if _refresh_trigger[0]:
            asyncio.ensure_future(_refresh_trigger[0]())
        # Auto-close drawer on mobile when a nav item is tapped
        result = await ui.run_javascript("window.innerWidth")
        if result is not None and result <= 1023:
            drawer.hide()

    build_sidebar(
        drawer, active_page, nav_btn_refs, page_containers,
        on_navigate=_on_navigate,
    )

    # ---- Build Page Content ----
    async def build_ui():
        nonlocal refresh_fns
        refresh_fns = {}  # page_id → refresh_fn

        market_open = is_market_open()

        # Dashboard rendered ONCE — its clock timer lives inside the container and
        # must not be destroyed by container.clear() on subsequent build_ui() calls.
        if _dashboard_refresh[0] is None:
            page_containers["dashboard"].clear()
            _dashboard_refresh[0] = render_dashboard(page_containers["dashboard"])
        refresh_fns["dashboard"] = _dashboard_refresh[0]

        # Clear all other pages
        for pid in ALL_PAGE_IDS:
            if pid != "dashboard":
                page_containers[pid].clear()

        refresh_fns["markets"]      = render_markets_tab(page_containers["markets"])
        refresh_fns["market_news"]  = render_market_news_tab(page_containers["market_news"])
        refresh_fns["nifty"]     = render_index_tab(page_containers["nifty"], "NIFTY", INDICES["NIFTY"])
        refresh_fns["banknifty"] = render_index_tab(page_containers["banknifty"], "BANKNIFTY", INDICES["BANKNIFTY"])
        refresh_fns["pnl"]       = render_pnl_tab(page_containers["pnl"])
        refresh_fns["rsi_only"]  = render_rsi_only_tab(page_containers["rsi_only"])
        refresh_fns["abcd_only"] = render_abcd_only_tab(page_containers["abcd_only"])
        refresh_fns["dt_only"]   = render_double_top_tab(page_containers["dt_only"])
        refresh_fns["db_only"]   = render_double_bottom_tab(page_containers["db_only"])
        refresh_fns["cb_only"]   = render_channel_breakout_tab(page_containers["cb_only"])
        refresh_fns["cd_only"]   = render_channel_down_tab(page_containers["cd_only"])
        refresh_fns["sma50"]         = render_sma50_tab(page_containers["sma50"])
        refresh_fns["ema10"]         = render_ema10_tab(page_containers["ema10"])
        refresh_fns["backtest_pnl"]  = render_backtest_pnl_tab(page_containers["backtest_pnl"])

        # Live algo tabs — countdown when closed, live data when open
        if market_open:
            refresh_fns["abcd"] = render_algo_tab(page_containers["abcd"], "abcd")
            refresh_fns["rsi"]  = render_algo_tab(page_containers["rsi"], "rsi")
        else:
            render_market_closed(page_containers["abcd"])
            render_market_closed(page_containers["rsi"])

    async def full_refresh():
        """Rebuild UI if market state changed, then refresh active page only."""
        if page_client._deleted:
            return

        current_open = is_market_open()

        if current_open != _prev_market_open[0]:
            _prev_market_open[0] = current_open
            try:
                await build_ui()
            except Exception as build_err:
                print(f"  [build_ui error] {build_err}")

        # Only refresh whichever page the user is currently viewing
        active = active_page["value"]
        fn = refresh_fns.get(active)
        if fn is None:
            return  # static page (e.g. market-closed placeholder)

        status_label.text = f"Refreshing... {now_ist().strftime('%H:%M:%S')}"
        try:
            await fn()
            if not page_client._deleted:
                status_label.text = f"Last refresh: {now_ist().strftime('%H:%M:%S')} | Next in {REFRESH_SECONDS}s"
        except Exception as e:
            if not page_client._deleted:
                status_label.text = f"Refresh error: {e}"
            print(f"  [refresh error] {e}")

        pass  # scheduled messages sent by background task

    # Wire up the navigation trigger (must be set after full_refresh is defined)
    _refresh_trigger[0] = full_refresh

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

    # ---- Header ticker updater ----
    def _update_header_tickers():
        if page_client._deleted:
            return
        if not is_market_open():
            return
        from state import _cache_get
        prices = _cache_get("dashboard_prices")
        if not prices:
            return
        for idx_name, ticker in _header_tickers.items():
            data = prices.get(idx_name, {})
            spot = data.get("spot")
            if spot is None:
                continue
            prev = ticker["prev"]
            if prev is None:
                direction = "flat"
            elif spot > prev:
                direction = "up"
            elif spot < prev:
                direction = "down"
            else:
                direction = "flat"
            ticker["prev"] = spot
            badge = ticker["badge"]
            lbl   = ticker["label"]
            # Update label text
            lbl.set_text(f"{idx_name}  {spot:,.2f}")
            # Swap CSS class for color and trigger blink via JS
            bid = badge.id
            ui.run_javascript(
                f"(function(){{"
                f"var el=document.getElementById('c{bid}');"
                f"if(!el)return;"
                f"el.classList.remove('up','down','flat','ticker-blink');"
                f"void el.offsetWidth;"
                f"el.classList.add('{direction}','ticker-blink');"
                f"}})()"
            )

    ui.timer(5, _update_header_tickers)


# ================= RUN =================

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="AlgTrd", host="0.0.0.0", port=8501, reload=True)
