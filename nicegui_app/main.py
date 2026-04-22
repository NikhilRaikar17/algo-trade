"""
Option Chain NiceGUI App
------------------------
NIFTY & BANKNIFTY option chain with ABCD and RSI+SMA algo trading.
Run:  cd nicegui_app && uv run python main.py
"""

import asyncio
from nicegui import ui, context, app

app.storage.SECRET = "algotrade-secret-key"

# Serve static files (CSS, assets)
app.add_static_files("/static", "static")

# Mount FastAPI auth routes before NiceGUI takes over routing
from routes.auth_routes import router as _auth_router
app.include_router(_auth_router)

from config import now_ist, INDICES
from state import is_market_open, get_next_market_open
from sidebar import build_sidebar
from pnl import send_daily_pnl_summary, send_morning_message, send_premarket_alert
from trading_engine import run_trading_engine
from email_report import send_backtest_email_report
from ws_feed import start_ws_feed
from global_feed import start_global_feed
from pages.homepage import render_homepage
from pages.login import render_login_page
from pages import (
    render_dashboard,
    render_markets_tab,
    render_index_tab,
    render_algo_tab,
    render_abcd_only_tab,
    render_double_top_tab,
    render_double_bottom_tab,
    render_sma50_tab,
    render_ema10_tab,
    render_pnl_tab,
    render_backtest_pnl_tab,
    render_market_closed,
    render_market_news_tab,
    render_top_stocks_tab,
    render_swing_trades_tab,
    render_global_markets_tab,
    render_admin_tab,
)


# ================= PAGE IDS =================
# All page IDs used for containers and navigation
ALL_PAGE_IDS = [
    "dashboard",
    "markets",
    "market_news",
    "top_stocks",
    "swing_trades",
    "global_markets",
    "nifty",
    "banknifty",
    "algo",
    "abcd_only",
    "dt_only",
    "db_only",
    "sma50",
    "ema10",
    "backtest_pnl",
    "pnl",
    "admin",
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
                send_backtest_email_report()
            except Exception as e:
                print(f"  [scheduler error] {e}")

    async def _top_stocks_loop():
        """Fetch & cache top stocks every 5 minutes during market hours.
        Once market closes and data is cached, the loop exits — prices don't
        change after 3:30 PM IST so there's nothing to refresh."""
        from pages.top_stocks import _fetch_top_stocks
        from state import _cache_set, _cache_get_stable, is_market_open
        while True:
            try:
                if is_market_open():
                    gainers, losers = await asyncio.get_event_loop().run_in_executor(
                        None, _fetch_top_stocks
                    )
                    _cache_set("top_stocks_data", {"gainers": gainers, "losers": losers})
                    print(f"  [top_stocks_bg] cached {len(gainers)} gainers, {len(losers)} losers")
                else:
                    if _cache_get_stable("top_stocks_data") is None:
                        # App started outside market hours — do one fetch so the page has data
                        gainers, losers = await asyncio.get_event_loop().run_in_executor(
                            None, _fetch_top_stocks
                        )
                        _cache_set("top_stocks_data", {"gainers": gainers, "losers": losers})
                        print(f"  [top_stocks_bg] one-time fetch (market closed): {len(gainers)} gainers, {len(losers)} losers")
                    else:
                        print("  [top_stocks_bg] market closed & data cached — loop exiting")
                        return  # prices won't change, no point looping further
            except Exception as e:
                print(f"  [top_stocks_bg error] {e}")
            await asyncio.sleep(300)  # check every 5 minutes

    asyncio.create_task(_loop())
    asyncio.create_task(run_trading_engine())
    asyncio.create_task(_top_stocks_loop())
    asyncio.create_task(start_ws_feed())
    asyncio.create_task(start_global_feed())


# ================= MAIN PAGE =================


@ui.page("/")
async def homepage():
    render_homepage()


@ui.page("/login")
async def login_page():
    from auth import validate_session
    session_key = app.storage.user.get("session_key", "")
    if app.storage.user.get("authenticated") and validate_session(session_key):
        ui.navigate.to("/app")
        return
    render_login_page()


@ui.page("/app")
async def index():
    from auth import validate_session, invalidate_session as _invalidate

    session_key = app.storage.user.get("session_key", "")
    username_from_session = validate_session(session_key)

    if not username_from_session:
        # Session missing, expired, or tampered — clear cookie and redirect
        app.storage.user["authenticated"] = False
        app.storage.user["session_key"] = ""
        app.storage.user["username"] = ""
        ui.navigate.to("/")
        return
    ui.page_title("Algo Trading")

    # ---- Fonts + Terminal Theme ----
    ui.add_head_html(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?'
        'family=Outfit:wght@400;500;600;700;800'
        '&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400'
        '&family=JetBrains+Mono:wght@300;400;500;600;700'
        '&display=swap" rel="stylesheet">'
    )
    ui.add_head_html('<link rel="stylesheet" href="/static/terminal_theme.css">')

    # ---- Custom CSS + TradingView ----
    ui.add_head_html(
        '<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>'
    )
    ui.add_head_html(
        """
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
      html, body { overflow-x: hidden !important; overflow-y: auto !important; max-width: 100vw !important; }
      .q-layout, .q-page-container, .q-page { overflow-x: hidden !important; max-width: 100vw !important; }
    </style>
    <style>
        /* ---- NAV BUTTON STRUCTURE (layout, not color — colors in terminal_theme.css) ---- */
        .nav-btn {
            width: 100%;
            justify-content: flex-start !important;
            text-transform: none !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            min-height: 32px !important;
            padding: 4px 14px !important;
            font-size: 0.8rem !important;
            border-radius: 0 !important;
        }
        .nav-btn .q-btn__content {
            justify-content: flex-start !important;
            gap: 10px;
            flex-wrap: nowrap !important;
            overflow: hidden !important;
        }
        .nav-sub-btn {
            width: 100%;
            justify-content: flex-start !important;
            text-transform: none !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            min-height: 28px !important;
            padding: 2px 14px !important;
            font-size: 0.75rem !important;
            border-radius: 0 !important;
        }
        .nav-sub-btn .q-btn__content {
            justify-content: flex-start !important;
            gap: 6px;
            flex-wrap: nowrap !important;
            overflow: hidden !important;
        }
        .q-expansion-item .q-item__label { white-space: nowrap !important; }

        /* ---- Ticker blink animation ---- */
        @keyframes ticker-blink {
            0%   { opacity: 1; }
            40%  { opacity: 0.25; }
            100% { opacity: 1; }
        }
        .ticker-blink { animation: ticker-blink 0.6s ease-in-out; }

        /* ---- Header ticker sizing ---- */
        .ticker-badge {
            display: flex; align-items: center; gap: 6px;
            cursor: default; user-select: none;
        }
        @media (max-width: 599px) { .header-tickers { display: none !important; } }
        .profile-avatar-btn { flex-shrink: 0 !important; margin-left: auto; }

        /* padding-bottom no longer needed — status bar uses ui.footer() layout element */
    </style>
    """
    )

    # ---- State ----
    active_page = {"value": "dashboard"}
    refresh_fns = {}
    _prev_market_open = [None]
    _dashboard_refresh = [None]   # persists across build_ui() calls — avoids re-creating clock timer
    _backtest_loaded: set = set()  # tracks which backtest pages have loaded at least once
    nav_btn_refs = {}
    page_client = context.client

    # ---- Header ----
    with (
        ui.header()
        .classes("header-bar items-center px-4 py-0")
        .style("height: 56px;")
    ):
        with ui.row().classes("items-center w-full").style("gap: 0; flex-wrap: nowrap; height: 100%; min-width: 0;"):
            # Menu button
            menu_btn = (
                ui.button(icon="menu", on_click=lambda: drawer.toggle())
                .props("flat dense round")
                .style("color: #5a6672; margin-right: 8px; flex-shrink: 0;")
            )

            # Brand logo block — text collapses progressively on small screens
            with ui.element("div").classes("at-header-brand").style("gap: 8px; min-width: 0; overflow: hidden;"):
                with ui.element("div").classes("at-header-logo"):
                    ui.label("A")
                with ui.element("div").style("line-height: 1.1; min-width: 0; overflow: hidden;"):
                    ui.label("ALGO TRADE").classes("at-header-title header-title-hide")
                    ui.label("TERMINAL · PRO").classes("at-header-ver header-subtitle-hide")

            _header_tickers = {}  # kept for timer compatibility, no UI rendered

            # Right cluster — flex-shrink: 0 keeps it always fully visible
            with ui.element("div").style(
                "margin-left: auto; display: flex; align-items: center; gap: 6px; flex-shrink: 0; min-width: 0;"
            ):
                # Live clock — hidden on very small screens
                _clock_lbl = ui.label("").style(
                    "font-family: 'JetBrains Mono', monospace; font-size: 11px;"
                    "color: var(--at-fg) !important; letter-spacing: 0.02em; white-space: nowrap;"
                ).classes("header-clock-hide")
                ui.timer(1, lambda: _clock_lbl.set_text(
                    now_ist().strftime("%H:%M:%S") + " IST"
                ))

                # Divider — hidden with clock
                ui.element("div").classes("header-clock-hide").style(
                    "width: 1px; height: 16px; background: var(--at-line); flex-shrink: 0;"
                )

                # Refresh status — hidden on small screens
                status_label = ui.label("").style(
                    "font-family: 'JetBrains Mono', monospace; font-size: 10px;"
                    "color: #5a6672; letter-spacing: 0.04em; white-space: nowrap;"
                ).classes("header-status-hide")

                # Divider — hidden with status
                ui.element("div").classes("header-status-hide").style(
                    "width: 1px; height: 16px; background: var(--at-line); flex-shrink: 0;"
                )

                # Market status badge — text label hidden on small screens
                market_open = is_market_open()
                _mkt_dot_color = "#00d084" if market_open else "#ff4d5e"
                _mkt_bg = "rgba(0,208,132,0.10)" if market_open else "rgba(255,77,94,0.10)"
                _mkt_border = "rgba(0,208,132,0.35)" if market_open else "rgba(255,77,94,0.35)"
                _mkt_txt = "Market Open" if market_open else "Market Closed"
                _mkt_txt_color = "#00d084" if market_open else "#ff4d5e"
                with ui.element("div").style(
                    f"display:flex; align-items:center; gap:6px; background:{_mkt_bg};"
                    f"border:1px solid {_mkt_border}; padding:3px 8px; border-radius:20px; flex-shrink:0;"
                ):
                    ui.element("div").style(
                        f"width:6px; height:6px; border-radius:3px; background:{_mkt_dot_color}; flex-shrink:0;"
                        f"box-shadow: 0 0 6px {_mkt_dot_color};"
                        + (" animation: at-pulse 1.6s ease-in-out infinite;" if market_open else "")
                    )
                    market_badge_label = ui.label(_mkt_txt).style(
                        f"font-family:'JetBrains Mono',monospace; font-size:10px;"
                        f"font-weight:600; letter-spacing:0.08em; color:{_mkt_txt_color}; white-space:nowrap;"
                    ).classes("header-status-label header-mkt-text-hide")

                # Divider
                ui.element("div").style(
                    "width: 1px; height: 16px; background: var(--at-line); flex-shrink: 0;"
                )

                # Theme toggle button
                with ui.element("div").style(
                    "display:flex; align-items:center; justify-content:center;"
                    "width:28px; height:28px; border-radius:8px; cursor:pointer; flex-shrink:0;"
                    "background:rgba(255,255,255,0.06); border:1px solid var(--at-line2);"
                    "transition: background 0.2s, border-color 0.2s;"
                ).tooltip("Toggle light/dark theme") as _toggle_wrap:
                    _theme_icon = ui.icon("light_mode").style(
                        "font-size: 16px; color: #8a97a3; pointer-events:none;"
                    )

                def _toggle_theme():
                    icon_id = _theme_icon.id
                    wrap_id = _toggle_wrap.id
                    ui.run_javascript(
                        "(function(){"
                        "var body=document.body;"
                        "var isLight=body.classList.toggle('at-light-theme');"
                        f"var ic=document.getElementById('c{icon_id}');"
                        f"var wr=document.getElementById('c{wrap_id}');"
                        "if(ic){ic.textContent=isLight?'dark_mode':'light_mode';"
                        "ic.style.color=isLight?'#ffb020':'#8a97a3';}"
                        "if(wr){wr.style.background=isLight?'rgba(255,176,32,0.12)':'rgba(255,255,255,0.06)';"
                        "wr.style.borderColor=isLight?'rgba(255,176,32,0.4)':'var(--at-line2)';}"
                        "})()"
                    )

                _toggle_wrap.on("click", _toggle_theme)

                # Divider
                ui.element("div").style(
                    "width: 1px; height: 16px; background: var(--at-line); flex-shrink: 0;"
                )

                # Profile avatar with logout dropdown
                _username = app.storage.user.get("username", "")
                _initials = (
                    "".join(w[0].upper() for w in _username.split()[:2])
                    if _username else "?"
                )
                with ui.button(_initials).props("round flat").classes("profile-avatar-btn").style(
                    "background: var(--at-accent) !important;"
                    "color: #001a10 !important; font-weight: 700 !important;"
                    "font-family: 'JetBrains Mono',monospace !important;"
                    "font-size: 0.75rem !important;"
                    "width: 30px !important; height: 30px !important;"
                    "min-width: 30px !important; border-radius: 50% !important;"
                    "flex-shrink: 0 !important;"
                ):
                    with ui.menu().props("anchor='bottom end' self='top end'").style(
                        "border-radius: 0; box-shadow: 0 8px 32px rgba(0,0,0,0.6);"
                        "border: 1px solid var(--at-line2); background: var(--at-bg2); overflow: hidden;"
                    ):
                        with ui.element("div").style(
                            "min-width: 180px; padding: 10px 16px 8px; border-bottom: 1px solid #1f2830;"
                        ):
                            ui.label(_username.upper() if _username else "USER").style(
                                "font-family: 'Outfit',sans-serif;"
                                "font-weight: 700; font-size: 0.85rem; color: #e6edf3;"
                                "letter-spacing: 0.06em;"
                            )
                            ui.label("AUTHENTICATED SESSION").style(
                                "font-family: 'JetBrains Mono',monospace;"
                                "font-size: 0.65rem; color: #5a6672; letter-spacing: 0.08em;"
                            )

                        def _do_logout():
                            from auth import invalidate_session
                            invalidate_session(app.storage.user.get("session_key", ""))
                            app.storage.user["authenticated"] = False
                            app.storage.user["session_key"] = ""
                            app.storage.user["username"] = ""
                            ui.navigate.to("/")

                        ui.separator()
                        ui.menu_item(
                            "Logout",
                            on_click=_do_logout,
                        ).style(
                            "color: #ff4d5e; font-family: 'JetBrains Mono',monospace;"
                            "font-size: 0.8rem; letter-spacing: 0.06em;"
                        )

    # ---- Sidebar ----
    with (
        ui.left_drawer(value=True, bordered=False)
        .props("breakpoint=1023")
        .style(
            "width: 240px; padding: 0;"
        ) as drawer
    ):
        pass  # content built after page_containers exist

    # ---- Market Ticker Marquee Strip ----
    # Static fallback data shown until real data loads
    _ticker_fallback = [
        ("NIFTY 50",   None, None, None),
        ("BANK NIFTY", None, None, None),
        ("NIFTY IT",   None, None, None),
        ("NIFTY AUTO", None, None, None),
        ("INDIA VIX",  None, None, None),
    ]

    def _build_ticker_items(items):
        parts = []
        for sym, last, chg, pct in items:
            if last is None:
                parts.append(
                    f'<span class="at-ticker-item">'
                    f'<span class="at-ticker-sym">{sym}</span>'
                    f'<span class="at-ticker-val">—</span>'
                    f'</span>'
                )
                continue
            dp = 4 if ("VIX" in sym or "INR" in sym) else 2
            val = f"{last:,.{dp}f}"
            _pct = pct if pct is not None else 0.0
            _chg = chg if chg is not None else 0.0
            sign = "▲" if _pct >= 0 else "▼"
            cls = "up" if _pct >= 0 else "down"
            if chg is not None:
                chg_str = f"{sign} {abs(_chg):.2f} ({abs(_pct):.2f}%)"
            else:
                chg_str = f"{sign} {abs(_pct):.2f}%"
            parts.append(
                f'<span class="at-ticker-item">'
                f'<span class="at-ticker-sym">{sym}</span>'
                f'<span class="at-ticker-val">{val}</span>'
                f'<span class="at-ticker-chg {cls}">{chg_str}</span>'
                f'</span>'
            )
        return parts

    def _ticker_html(items=None):
        src = items if items is not None else _ticker_fallback
        parts = _build_ticker_items(src)
        inner = "".join(parts * 2)  # duplicate for seamless loop
        return (
            f'<div class="at-ticker-strip">'
            f'<div class="at-ticker-inner">{inner}</div>'
            f'</div>'
        )

    _ticker_el = ui.html(_ticker_html())

    def _refresh_ticker():
        """Update ticker with real data from caches (no extra API calls)."""
        if page_client._deleted:
            return
        from state import _cache_get as _scache, get_live_price, get_all_global_prices
        items = []

        # NIFTY / BANKNIFTY — prefer live WS price, fall back to dashboard_prices cache
        rest_prices = _scache("dashboard_prices") or {}
        for idx_name, sym_label in [("NIFTY", "NIFTY 50"), ("BANKNIFTY", "BANK NIFTY")]:
            ws = get_live_price(idx_name)
            if ws:
                items.append((sym_label, ws["ltp"], ws["change"], ws["change_pct"]))
            else:
                d = rest_prices.get(idx_name, {})
                spot = d.get("spot")
                if spot is not None:
                    items.append((sym_label, spot, d.get("spot_change"), d.get("spot_change_pct")))
                else:
                    items.append((sym_label, None, None, None))

        # Sector indices — from market_overview cache
        mo_key = f"market_overview:{now_ist().strftime('%Y-%m-%d %H')}"
        market_data = _scache(mo_key) or []
        # Build a flat lookup name→data
        idx_lookup: dict = {}
        for grp in market_data:
            for entry in grp.get("indices", []):
                if entry.get("data"):
                    idx_lookup[entry["name"]] = entry["data"]

        for name in ["NIFTY IT", "NIFTY AUTO", "NIFTY BANK"]:
            d = idx_lookup.get(name)
            if d:
                items.append((name, d["current"], d["change"], d["change_pct"]))
            else:
                items.append((name, None, None, None))

        # India VIX from live WS
        vix = get_live_price("VIX")
        if vix:
            items.append(("INDIA VIX", vix["ltp"], vix["change"], vix["change_pct"]))
        else:
            items.append(("INDIA VIX", None, None, None))

        # Global: USD/INR and Gold from global prices cache
        global_prices = get_all_global_prices()
        for sym, label in [("GC=F_INR", "GOLD INR"), ("GC=F", "GOLD USD")]:
            entry = global_prices.get(sym)
            if entry:
                items.append((label, entry["price"], None, entry["change_pct"]))
                break

        if not page_client._deleted:
            _ticker_el.set_content(_ticker_html(items))

    ui.timer(30, _refresh_ticker)

    # ---- Main Content Area ----
    with ui.element("div").style(
        "width: 100%; max-width: 100%; box-sizing: border-box; overflow-x: hidden;"
    ):
        page_containers = {}

        for pid in ALL_PAGE_IDS:
            cont = ui.element("div").style(
                "width: 100%; max-width: 100%; box-sizing: border-box; padding: 10px 12px; overflow-x: hidden;"
            )
            cont.set_visibility(pid == active_page["value"])
            page_containers[pid] = cont

    # Now build sidebar (needs page_containers to be defined)
    # _refresh_trigger is set after full_refresh is defined below; late-binding via list
    _refresh_trigger = [None]
    async def _on_navigate(pid):
        # Auto-close drawer on mobile when a nav item is tapped
        result = await ui.run_javascript("window.innerWidth")
        if result is not None and result <= 1023:
            drawer.hide()
        if _refresh_trigger[0]:
            await _refresh_trigger[0]()

    build_sidebar(
        drawer, active_page, nav_btn_refs, page_containers,
        on_navigate=_on_navigate,
        username=username_from_session,
    )

    # ---- Build Page Content ----
    _pages_built: set = set()  # tracks which pages have been rendered at least once

    async def build_ui():
        nonlocal refresh_fns
        _backtest_loaded.clear()  # force reload when market state changes

        market_open = is_market_open()

        # Dashboard rendered ONCE — its clock timer lives inside the container and
        # must not be destroyed by container.clear() on subsequent build_ui() calls.
        if _dashboard_refresh[0] is None:
            page_containers["dashboard"].clear()
            _dashboard_refresh[0] = render_dashboard(page_containers["dashboard"])
            _pages_built.add("dashboard")
        refresh_fns["dashboard"] = _dashboard_refresh[0]

        # Static pages: render once, then only re-register their refresh_fns.
        # Clearing them on every market-state change wipes content while the user
        # is viewing the page — causing a jarring blank flash.
        _STATIC_ONCE = {
            "markets", "market_news", "top_stocks", "swing_trades", "global_markets",
            "nifty", "banknifty", "pnl", "abcd_only", "dt_only", "db_only",
            "sma50", "ema10", "backtest_pnl", "admin",
        }
        renders = {
            "markets":       lambda: render_markets_tab(page_containers["markets"]),
            "market_news":   lambda: render_market_news_tab(page_containers["market_news"]),
            "top_stocks":    lambda: render_top_stocks_tab(page_containers["top_stocks"]),
            "swing_trades":  lambda: render_swing_trades_tab(page_containers["swing_trades"]),
            "global_markets":lambda: render_global_markets_tab(page_containers["global_markets"]),
            "nifty":         lambda: render_index_tab(page_containers["nifty"], "NIFTY", INDICES["NIFTY"]),
            "banknifty":     lambda: render_index_tab(page_containers["banknifty"], "BANKNIFTY", INDICES["BANKNIFTY"]),
            "pnl":           lambda: render_pnl_tab(page_containers["pnl"]),
            "abcd_only":     lambda: render_abcd_only_tab(page_containers["abcd_only"]),
            "dt_only":       lambda: render_double_top_tab(page_containers["dt_only"]),
            "db_only":       lambda: render_double_bottom_tab(page_containers["db_only"]),
            "sma50":         lambda: render_sma50_tab(page_containers["sma50"]),
            "ema10":         lambda: render_ema10_tab(page_containers["ema10"]),
            "backtest_pnl":  lambda: render_backtest_pnl_tab(page_containers["backtest_pnl"]),
        }
        if username_from_session == "nikhil":
            renders["admin"] = lambda: render_admin_tab(page_containers["admin"])

        for pid, render_fn in renders.items():
            if pid not in _pages_built:
                page_containers[pid].clear()
                try:
                    refresh_fns[pid] = render_fn()
                    _pages_built.add(pid)
                except Exception as e:
                    print(f"  [build_ui] render error for '{pid}': {e}")
            # closure already registered from first render — still valid

        # Live algo tab — only this page needs to swap between live UI and market-closed
        # placeholder, so clear and rebuild it whenever market state changes.
        page_containers["algo"].clear()
        if market_open:
            refresh_fns["algo"] = render_algo_tab(page_containers["algo"])
        else:
            render_market_closed(page_containers["algo"])
            refresh_fns.pop("algo", None)

    async def full_refresh():
        """Fetch fresh data for the currently active page. Called on navigation and initial load."""
        if page_client._deleted:
            return

        active = active_page["value"]
        fn = refresh_fns.get(active)
        if fn is None:
            return

        # Backtest pages: load once; skip re-fetch when market is closed (data doesn't change).
        _BACKTEST_PAGES = {"abcd_only", "dt_only", "db_only", "sma50", "ema10"}
        if active in _BACKTEST_PAGES and not is_market_open() and active in _backtest_loaded:
            return
        if active in _BACKTEST_PAGES:
            _backtest_loaded.add(active)

        # Option chain: load once after market close (LTP snapshot); live during market hours.
        _OPTION_CHAIN_PAGES = {"nifty", "banknifty"}
        if active in _OPTION_CHAIN_PAGES and not is_market_open() and active in _backtest_loaded:
            return
        if active in _OPTION_CHAIN_PAGES:
            _backtest_loaded.add(active)

        status_label.text = f"Loading... {now_ist().strftime('%H:%M:%S')}"
        try:
            scroll_y = await ui.run_javascript("window.scrollY")
            await fn()
            if scroll_y:
                await ui.run_javascript(f"window.scrollTo(0, {scroll_y})")
            if not page_client._deleted:
                if active in _OPTION_CHAIN_PAGES and not is_market_open():
                    status_label.text = f"LTP snapshot: {now_ist().strftime('%H:%M:%S')} | Market closed"
                else:
                    status_label.text = f"Loaded: {now_ist().strftime('%H:%M:%S')}"
        except Exception as e:
            if not page_client._deleted:
                status_label.text = f"Error: {e}"
            print(f"  [refresh error] {e}")

    # Wire up the navigation trigger (must be set after full_refresh is defined)
    _refresh_trigger[0] = full_refresh

    # Initial build and first data load
    await build_ui()
    _prev_market_open[0] = is_market_open()
    ui.timer(2, lambda: asyncio.ensure_future(full_refresh()), once=True)

    # Background market-state watcher: only rebuilds UI when market opens/closes.
    # Does NOT refresh page data — pages fetch data on navigation or manage their own timers.
    async def _market_state_check():
        if page_client._deleted:
            return
        current_open = is_market_open()
        if current_open != _prev_market_open[0]:
            _prev_market_open[0] = current_open
            try:
                await build_ui()
            except Exception as e:
                print(f"  [market_state_check error] {e}")

    ui.timer(30, lambda: asyncio.ensure_future(_market_state_check()))

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

    # ---- Terminal Status Bar ---- (Quasar footer — layout-aware, respects sidebar)
    with ui.footer().style("min-height:0; padding:0; height:22px;"):
        ui.html("""
        <div class="at-status-bar" style="width:100%; height:22px;">
          <div class="at-status-item">
            <span class="at-status-dot live"></span>
            <span class="at-status-key">NSE</span>
            <span class="at-status-val">LIVE</span>
          </div>
          <div class="at-status-item">
            <span class="at-status-dot live"></span>
            <span class="at-status-key">BSE</span>
            <span class="at-status-val">LIVE</span>
          </div>
          <div class="at-status-item">
            <span class="at-status-dot live"></span>
            <span class="at-status-key">MCX</span>
            <span class="at-status-val">LIVE</span>
          </div>
          <div class="at-status-item">
            <span class="at-status-dot live"></span>
            <span class="at-status-key">ENGINE</span>
            <span class="at-status-val">ACTIVE</span>
          </div>
          <span class="at-sebi-text">
            SEBI REG INB231408731 &middot; MEMBER NSE &middot; BSE &middot; MCX
            &middot; INVESTMENT IN SECURITIES MARKET ARE SUBJECT TO MARKET RISKS
          </span>
          <div class="at-shortcuts">
            <span class="at-shortcut-key">⌘K</span>
            <span class="at-shortcut-lbl">SEARCH</span>
          </div>
        </div>
        """)


# ================= RUN =================

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="AlgTrd", host="0.0.0.0", port=8501, reload=True, storage_secret="algotrade-secret-key")
