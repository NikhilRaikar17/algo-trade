"""
Sidebar navigation: tree-structured with Backtest / Live Trading sections.
"""

from nicegui import ui

from config import now_ist, REFRESH_SECONDS, get_next_holiday


def build_sidebar(drawer, active_page, nav_btn_refs, page_containers):
    """Build the sidebar navigation inside the given drawer."""

    def set_active_page(page_id):
        active_page["value"] = page_id
        for nid, btn in nav_btn_refs.items():
            if nid == page_id:
                btn.classes(add="nav-btn-active")
            else:
                btn.classes(remove="nav-btn-active")
        for nid, cont in page_containers.items():
            cont.set_visibility(nid == page_id)

    def _nav_button(page_id, label, icon, indent=False):
        cls = "nav-sub-btn" if indent else "nav-btn"
        ml = "ml-6" if indent else ""
        btn = (
            ui.button(
                label,
                icon=icon,
                on_click=lambda e, pid=page_id: set_active_page(pid),
            )
            .props("flat no-caps align=left")
            .classes(f"{cls} rounded-lg mx-2 mb-1 text-gray-600 {ml}")
        )
        if page_id == active_page["value"]:
            btn.classes(add="nav-btn-active")
        nav_btn_refs[page_id] = btn

    with drawer:
        # ---- Dashboard ----
        _nav_button("dashboard", "Dashboard", "dashboard")

        ui.separator().classes("my-2 mx-4")

        # ---- Option Chains ----
        ui.label("Options").classes("nav-section-label")
        _nav_button("nifty", "NIFTY", "show_chart")
        _nav_button("banknifty", "BANKNIFTY", "candlestick_chart")

        ui.separator().classes("my-2 mx-4")

        # ---- Historical Backtest ----
        ui.label("Backtest").classes("nav-section-label")
        with ui.expansion("RSI", icon="speed").classes(
            "mx-2 rounded-lg"
        ).props("dense default-opened"):
            _nav_button("rsi_nifty", "NIFTY", "show_chart", indent=True)
            _nav_button("rsi_banknifty", "BANKNIFTY", "candlestick_chart", indent=True)
        with ui.expansion("ABCD", icon="insights").classes(
            "mx-2 rounded-lg"
        ).props("dense default-opened"):
            _nav_button("abcd_nifty", "NIFTY", "show_chart", indent=True)
            _nav_button("abcd_banknifty", "BANKNIFTY", "candlestick_chart", indent=True)

        ui.separator().classes("my-2 mx-4")

        # ---- Live Trading ----
        ui.label("Live Trading").classes("nav-section-label")
        _nav_button("abcd", "ABCD Algo", "insights")
        _nav_button("rsi", "RSI + SMA", "analytics")

        ui.separator().classes("my-2 mx-4")

        # ---- Summary ----
        _nav_button("pnl", "P&L", "account_balance_wallet")

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
            holiday_info = get_next_holiday()
            if holiday_info:
                _, next_date, days_left = holiday_info
                day_label = (
                    "Today"
                    if days_left == 0
                    else f"in {days_left} day{'s' if days_left != 1 else ''}"
                )
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
