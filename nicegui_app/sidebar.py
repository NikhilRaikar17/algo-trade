"""
Sidebar navigation: tree-structured with Backtest / Live Trading sections.
"""

from nicegui import ui

from config import now_ist, REFRESH_SECONDS, get_next_holiday, reinit_dhan, ENV_FILE


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

    def _nav_button(page_id, label, icon, indent=False, color="text-gray-800", icon_color="icon-gray"):
        cls = "nav-sub-btn" if indent else "nav-btn"
        ml = "ml-6" if indent else ""
        btn = (
            ui.button(
                label,
                icon=icon,
                on_click=lambda e, pid=page_id: set_active_page(pid),
            )
            .props("flat no-caps align=left color=dark")
            .classes(f"{cls} {icon_color} rounded-lg mx-2 mb-1 {ml}")
        )
        if page_id == active_page["value"]:
            btn.classes(add="nav-btn-active")
        nav_btn_refs[page_id] = btn

    def _section_label(text, dot_color="bg-gray-400"):
        with ui.row().classes("items-center gap-2 px-4 pt-2 pb-1"):
            ui.element("div").classes(f"w-1.5 h-1.5 rounded-full {dot_color}")
            ui.label(text).classes("nav-section-label !p-0")

    with drawer:
        # ---- Top-level ----
        ui.element("div").classes("pt-1")
        _nav_button("dashboard", "Dashboard", "dashboard", icon_color="icon-blue")

        # ---- Markets section ----
        _section_label("Markets", "bg-orange-400")
        _nav_button("markets",      "Overview",     "bar_chart",    icon_color="icon-orange")
        _nav_button("market_news",  "Market News",  "newspaper",    icon_color="icon-orange")
        _nav_button("top_stocks",   "Top Stocks",   "rocket_launch", icon_color="icon-amber")
        _nav_button("swing_trades", "Swing Trades", "trending_up",   icon_color="icon-orange")

        ui.separator().classes("my-2 mx-4")

        # ---- Option Chains ----
        _section_label("Options", "bg-emerald-400")
        _nav_button("nifty",     "NIFTY",     "show_chart",        icon_color="icon-blue")
        _nav_button("banknifty", "BANKNIFTY", "candlestick_chart", icon_color="icon-blue")

        ui.separator().classes("my-2 mx-4")

        # ---- Strategies ----
        _section_label("Strategies", "bg-purple-400")
        with ui.expansion("Backtest Algos", icon="history_edu").classes(
            "mx-2 rounded-lg text-gray-700"
        ).props("dense"):
            _nav_button("abcd_only", "ABCD",              "insights",            icon_color="icon-purple")
            _nav_button("dt_only",   "Double Top",        "moving",              icon_color="icon-purple")
            _nav_button("db_only",   "Double Bottom",     "moving",              icon_color="icon-purple")
            _nav_button("sma50",         "SMA 50 Crossover",  "stacked_line_chart",  icon_color="icon-purple")
            _nav_button("ema10",         "EMA 10 Crossover",  "show_chart",          icon_color="icon-purple")
        _nav_button("backtest_pnl", "Backtest P&L", "analytics", icon_color="icon-amber")

        ui.separator().classes("my-2 mx-4")

        # ---- Live Trading ----
        _section_label("Live Trading", "bg-green-400")
        _nav_button("algo", "Live Algos", "insights", icon_color="icon-green")
        _nav_button("pnl", "Live P&L", "account_balance_wallet", icon_color="icon-rose")

        ui.separator().classes("my-3 mx-4")

        # ---- Market Info ----
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
            holiday_date_label = ui.label("").classes("text-sm text-gray-600")
            holiday_days_label = ui.label("").classes("text-xs text-gray-400")

            def _update_holiday():
                info = get_next_holiday()
                if info:
                    _, next_date, days_left = info
                    holiday_date_label.set_text(next_date.strftime("%a, %d %b %Y"))
                    holiday_days_label.set_text(
                        "Today" if days_left == 0
                        else f"in {days_left} day{'s' if days_left != 1 else ''}"
                    )
                else:
                    holiday_date_label.set_text("No upcoming holidays")
                    holiday_days_label.set_text("")

            _update_holiday()
            # Refresh once per hour so it stays accurate without a page reload
            ui.timer(3600, _update_holiday)

        ui.space()

        with ui.element("div").classes("px-4 pb-4"):
            token_input = ui.input(placeholder="Paste new Dhan token...") \
                .props("dense outlined clearable") \
                .classes("w-full text-xs mb-1")

            def _apply_token():
                token = token_input.value.strip()
                if not token:
                    ui.notify("Token is empty", type="warning")
                    return
                # Write to .env
                import re
                with open(ENV_FILE, "r") as f:
                    content = f.read()
                if re.search(r"^DHAN_TOKEN_ID=.*", content, re.MULTILINE):
                    content = re.sub(r"^DHAN_TOKEN_ID=.*", f"DHAN_TOKEN_ID={token}", content, flags=re.MULTILINE)
                else:
                    content += f"\nDHAN_TOKEN_ID={token}"
                with open(ENV_FILE, "w") as f:
                    f.write(content)
                reinit_dhan()
                token_input.set_value("")
                ui.notify("Dhan token updated", type="positive")

            ui.button("Apply Token", icon="check", on_click=_apply_token) \
                .props("flat no-caps size=sm color=green") \
                .classes("w-full mb-2")

            ui.label(f"Auto-refresh: {REFRESH_SECONDS}s").classes(
                "text-xs text-gray-400"
            )
