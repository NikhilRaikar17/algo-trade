"""
Sidebar navigation — Bloomberg Terminal dark style.
"""

from nicegui import ui

from config import now_ist, REFRESH_SECONDS, get_next_holiday

# ---- Inline styles for terminal sidebar ---- #
_S = {
    "section": (
        "font-family:'Outfit',sans-serif;"
        "font-size:9px; font-weight:700; letter-spacing:0.14em;"
        "text-transform:uppercase; color:var(--at-fg-faint); padding:6px 16px 4px;"
    ),
    "sep": "margin:4px 12px; background:var(--at-line);",
    "info_key": (
        "font-family:'Outfit',sans-serif;"
        "font-size:9px; font-weight:700; letter-spacing:0.12em;"
        "text-transform:uppercase; color:var(--at-fg-faint); margin-bottom:2px;"
    ),
    "info_val": (
        "font-family:'JetBrains Mono',monospace;"
        "font-size:10px; color:var(--at-fg-dim);"
    ),
    "info_faint": (
        "font-family:'JetBrains Mono',monospace;"
        "font-size:9px; color:var(--at-fg-faint);"
    ),
}


def build_sidebar(drawer, active_page, nav_btn_refs, page_containers, on_navigate=None):
    """Build the sidebar navigation inside the given drawer."""

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
                "font-family:'DM Sans',sans-serif !important;"
                "font-size:12px !important; font-weight:500 !important;"
                "color:var(--at-fg-dim) !important; height:32px !important;"
                "border-left: 2px solid transparent;"
                + ("padding-left:20px !important;" if indent else "")
            )
        )
        if page_id == active_page["value"]:
            btn.classes(add="nav-btn-active")
        nav_btn_refs[page_id] = btn
        return btn

    def _section_label(text):
        ui.html(f'<div style="{_S["section"]}">{text}</div>')

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
            _nav_button("swing_trades",   "Swing Trades",   "trending_up",     icon_color="icon-orange")
            _nav_button("global_markets", "Global Markets", "public",          icon_color="icon-orange")

            ui.separator().style(_S["sep"])

            # OPTIONS
            _section_label("OPTIONS")
            _nav_button("nifty",     "NIFTY 50",   "show_chart",        icon_color="icon-blue")
            _nav_button("banknifty", "BANK NIFTY", "candlestick_chart", icon_color="icon-blue")

            ui.separator().style(_S["sep"])

            # STRATEGIES
            _section_label("STRATEGIES")
            with ui.expansion("Backtest Algos", icon="history_edu") \
                    .classes("mx-2 icon-purple") \
                    .props("dense") \
                    .style(
                        "background:transparent !important; border-radius:0 !important;"
                        "font-family:'DM Sans',sans-serif !important;"
                        "font-size:12px !important; color:var(--at-fg-dim) !important;"
                    ):
                _nav_button("abcd_only", "ABCD Pattern",      "insights",           indent=True, icon_color="icon-purple")
                _nav_button("dt_only",   "Double Top",        "moving",             indent=True, icon_color="icon-purple")
                _nav_button("db_only",   "Double Bottom",     "moving",             indent=True, icon_color="icon-purple")
                _nav_button("sma50",     "SMA 50 Crossover",  "stacked_line_chart", indent=True, icon_color="icon-purple")
                _nav_button("ema10",     "EMA 10 Crossover",  "show_chart",         indent=True, icon_color="icon-purple")
            _nav_button("backtest_pnl", "Backtest P&L", "analytics", icon_color="icon-amber")

            ui.separator().style(_S["sep"])

            # LIVE TRADING
            _section_label("LIVE TRADING")
            _nav_button("algo", "Live Algos", "insights",               icon_color="icon-green")
            _nav_button("pnl",  "Live P&L",   "account_balance_wallet", icon_color="icon-rose")

            ui.separator().style(_S["sep"])

        # ---- Market Info footer ----
        with ui.element("div").style(
            "padding:10px 14px; border-top:1px solid var(--at-line); flex-shrink:0;"
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
                f'AUTO-REFRESH: {REFRESH_SECONDS}s</div>'
            )
