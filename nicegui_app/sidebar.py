"""
Sidebar navigation — Bloomberg Terminal dark style.
"""

from nicegui import ui

from config import now_ist, get_next_holiday
from pages import BACKTEST_PAGES
from strategy_registry import get_strategy_rows

# Long Term drop-down: page_id → (label, icon)
LONGTERM_PAGES = {
    "longterm_signals":  ("Signals", "radar"),
    "longterm_backtest": ("Backtest", "history_edu"),
    "pnl_longterm":      ("Live P&L Long Term", "account_balance_wallet"),
}

# ---- Inline styles for terminal sidebar ---- #
_S = {
    "section": (
        "font-family:var(--at-cond);"
        "font-size:9px; font-weight:700; letter-spacing:0.14em;"
        "text-transform:uppercase; color:var(--at-nav-meta); padding:6px 16px 4px;"
    ),
    "sep": "margin:4px 12px; background:var(--at-line);",
    "info_key": (
        "font-family:var(--at-cond);"
        "font-size:9px; font-weight:700; letter-spacing:0.12em;"
        "text-transform:uppercase; color:var(--at-nav-meta); margin-bottom:2px;"
    ),
    "info_val": (
        "font-family:var(--at-mono);"
        "font-size:10px; color:var(--at-nav-fg);"
    ),
    "info_faint": (
        "font-family:var(--at-mono);"
        "font-size:9px; color:var(--at-nav-meta);"
    ),
    "live_dot": (
        "width:6px; height:6px; border-radius:50%; flex-shrink:0;"
        "margin-left:auto; background:var(--at-up);"
        "box-shadow:0 0 0 3px color-mix(in srgb, var(--at-up) 18%, transparent);"
    ),
    "menu_empty": (
        "font-family:var(--at-mono);"
        "font-size:10px; color:var(--at-nav-meta); padding:6px 16px 8px 46px; cursor:pointer;"
    ),
}


def build_sidebar(drawer, active_page, nav_btn_refs, page_containers, on_navigate=None, username: str = ""):
    """Build the sidebar navigation inside the given drawer.

    Returns refresh_backtest_menu(), which rebuilds the Backtest Algos list from the
    strategies table — call it after a strategy toggle.
    """

    async def set_active_page(page_id):
        active_page["value"] = page_id
        for nid, btn in nav_btn_refs.items():
            if nid == page_id:
                btn.classes(add="nav-btn-active")
            else:
                btn.classes(remove="nav-btn-active")
        for nid, cont in page_containers.items():
            cont.set_visibility(nid == page_id)
        if on_navigate:
            await on_navigate(page_id)

    def _nav_button(page_id, label, icon, indent=False, icon_color="icon-gray", badge=None):
        cls = "nav-sub-btn" if indent else "nav-btn"
        btn = (
            ui.button(
                label,
                icon=icon,
                on_click=lambda e, pid=page_id: set_active_page(pid),
            )
            .props("flat no-caps align=left")
            .classes(f"{cls} {icon_color} mx-2 mb-0")
            .style(
                "border-radius:0 !important;"
                "font-family:var(--at-sans) !important;"
                "font-size:12px !important; font-weight:500 !important;"
                "color:var(--at-nav-fg) !important; height:32px !important;"
                "border-left: 2px solid transparent;"
                + ("padding-left:30px !important;" if indent else "")
            )
        )
        if page_id == active_page["value"]:
            btn.classes(add="nav-btn-active")
        nav_btn_refs[page_id] = btn
        return btn

    def _section_label(text):
        ui.html(f'<div style="{_S["section"]}">{text}</div>')

    def _fold(label, icon, icon_color, page_ids):
        """A nav-styled header that folds the sub-list below it (not a q-expansion, whose own padding
        and background never matched the other nav buttons); open at start if the page is in it.
        → the sub-list's element, to fill."""
        is_open = {"value": active_page["value"] in page_ids}
        toggle = (
            ui.button(label, icon=icon)
            .props("flat no-caps align=left")
            .classes(f"nav-btn {icon_color} mx-2 mb-0")
            .style(
                "border-radius:0 !important;"
                "font-family:var(--at-sans) !important;"
                "font-size:12px !important; font-weight:500 !important;"
                "color:var(--at-nav-fg) !important; height:32px !important;"
                "border-left: 2px solid transparent;"
            )
        )
        with toggle:
            chevron = ui.icon("expand_more").style(
                "margin-left:auto; font-size:16px; color:var(--at-nav-meta);"
                "transition:transform .15s;"
            )
        menu = ui.element("div")

        def _apply():
            menu.set_visibility(is_open["value"])
            chevron.style(f"transform:rotate({180 if is_open['value'] else 0}deg);")

        def _toggle():
            is_open["value"] = not is_open["value"]
            _apply()

        toggle.on_click(_toggle)
        _apply()
        return menu

    def refresh_backtest_menu():
        """Rebuild Backtest Algos from the strategies table: enabled ones only, live ones dotted."""
        rows = [r for r in get_strategy_rows() if r["backtest_enabled"] and r["key"] in BACKTEST_PAGES]
        for page_id, _, _ in BACKTEST_PAGES.values():
            nav_btn_refs.pop(page_id, None)
        backtest_menu.clear()
        with backtest_menu:
            if not rows:
                ui.label("None enabled — manage").style(_S["menu_empty"]).on(
                    "click", lambda: set_active_page("strategies")
                )
            for r in rows:
                page_id, _, icon = BACKTEST_PAGES[r["key"]]
                btn = _nav_button(page_id, r["display_name"], icon, indent=True, icon_color="icon-purple")
                if r["live_enabled"]:
                    with btn:
                        ui.element("span").style(_S["live_dot"]).tooltip("Also running live")

    with drawer:
        # ---- Nav ----
        with ui.element("div").style("flex:1; padding:8px 0;"):

            # OVERVIEW
            _section_label("OVERVIEW")
            _nav_button("dashboard", "Dashboard", "dashboard", icon_color="icon-blue")

            ui.separator().style(_S["sep"])

            # MARKETS
            _section_label("MARKETS")
            _nav_button("markets",        "Overview",       "bar_chart",       icon_color="icon-orange")
            _nav_button("market_news",    "Market News",    "newspaper",       icon_color="icon-orange")
            _nav_button("top_stocks",     "Top Stocks",     "rocket_launch",   icon_color="icon-amber")
            _nav_button("global_markets", "Global Markets", "public",          icon_color="icon-orange")

            ui.separator().style(_S["sep"])

            # OPTIONS
            _section_label("OPTIONS")
            _nav_button("nifty",     "NIFTY 50",   "show_chart",        icon_color="icon-blue")
            _nav_button("banknifty", "BANK NIFTY", "candlestick_chart", icon_color="icon-blue")
            _nav_button("pnl_options", "Live P&L Options", "account_balance_wallet", icon_color="icon-rose")
            _nav_button("options_strategy_lab", "Strategy Lab", "query_stats", icon_color="icon-blue")

            ui.separator().style(_S["sep"])

            # LONG TERM — one-week swing trades on daily charts, in a drop-down
            _section_label("LONG TERM")
            with _fold("Long Term", "event_note", "icon-green", set(LONGTERM_PAGES)):
                for page_id, (label, icon) in LONGTERM_PAGES.items():
                    _nav_button(page_id, label, icon, indent=True, icon_color="icon-green")

            ui.separator().style(_S["sep"])

            # STRATEGIES
            _section_label("STRATEGIES")
            _nav_button("strategies", "Strategies", "tune", icon_color="icon-purple")
            _nav_button("strategy_analysis", "Strategy Analysis", "grading", icon_color="icon-purple")
            backtest_menu = _fold("Backtest Algos", "history_edu", "icon-purple",
                                  {pid for pid, _, _ in BACKTEST_PAGES.values()})
            _nav_button("backtest_pnl", "Backtest P&L", "analytics", icon_color="icon-amber")

            ui.separator().style(_S["sep"])

            # TRADE TOOLS
            _section_label("TRADE TOOLS")
            _nav_button("trade_desk",   "Trade Desk",   "fact_check", icon_color="icon-green")
            _nav_button("trade_replay", "Trade Replay", "replay",     icon_color="icon-blue")

            ui.separator().style(_S["sep"])

            # LIVE TRADING
            _section_label("LIVE TRADING")
            _nav_button("algo", "Live Algos", "insights",               icon_color="icon-green")
            _nav_button("pnl",  "Live P&L",   "account_balance_wallet", icon_color="icon-rose")

            # ADMIN (nikhil only)
            if username == "nikhil":
                ui.separator().style(_S["sep"])
                _section_label("ADMIN")
                _nav_button("admin", "Admin Settings", "admin_panel_settings", icon_color="icon-rose")

            ui.separator().style(_S["sep"])

        # ---- Market Info footer ----
        with ui.element("div").style(
            "padding:10px 14px 16px; border-top:1px solid var(--at-line); flex-shrink:0; margin-bottom:22px;"
        ):
            ui.html(f'<div style="{_S["info_key"]}">MARKET HOURS</div>')
            ui.html(f'<div style="{_S["info_val"]}">09:15 — 15:30 IST</div>')
            ui.html(f'<div style="{_S["info_faint"]}">Mon — Fri (excl. holidays)</div>')

            _clock_el = ui.html(
                f'<div style="{_S["info_val"]}; margin-top:6px;">'
                f'{now_ist().strftime("%H:%M:%S")} IST</div>'
            )
            ui.timer(1, lambda: _clock_el.set_content(
                f'<div style="{_S["info_val"]}; margin-top:6px;">'
                f'{now_ist().strftime("%H:%M:%S")} IST</div>'
            ))

            ui.separator().style(_S["sep"] + "margin:8px 0 6px;")

            ui.html(f'<div style="{_S["info_key"]}">NEXT HOLIDAY</div>')
            holiday_el = ui.html(f'<div style="{_S["info_val"]}">—</div>')
            holiday_days_el = ui.html(f'<div style="{_S["info_faint"]}">—</div>')

            def _update_holiday():
                info = get_next_holiday()
                if info:
                    _, next_date, days_left = info
                    holiday_el.set_content(
                        f'<div style="{_S["info_val"]}">'
                        f'{next_date.strftime("%a, %d %b %Y")}</div>'
                    )
                    txt = "Today" if days_left == 0 else f"in {days_left} day{'s' if days_left!=1 else ''}"
                    holiday_days_el.set_content(
                        f'<div style="{_S["info_faint"]}">{txt}</div>'
                    )
                else:
                    holiday_el.set_content(
                        f'<div style="{_S["info_val"]}">No upcoming holidays</div>'
                    )
                    holiday_days_el.set_content("")

            _update_holiday()
            ui.timer(3600, _update_holiday)

            ui.html(
                f'<div style="{_S["info_faint"]}; margin-top:4px;">'
                f'DATA: ON-DEMAND + WS FEED</div>'
            )

    refresh_backtest_menu()
    return refresh_backtest_menu
