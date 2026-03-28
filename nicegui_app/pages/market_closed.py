"""
Market closed countdown display page.
"""

from nicegui import ui

from config import now_ist, is_nse_holiday
from state import get_next_market_open


def render_market_closed(container):
    """Build the market-closed countdown view inside container."""
    ist_now = now_ist()
    if is_nse_holiday(ist_now):
        close_reason = "NSE Holiday"
    elif ist_now.weekday() > 4:
        close_reason = "Weekend"
    else:
        close_reason = "After Hours"

    next_open = get_next_market_open()

    with container:
        with ui.element("div").classes(
            "w-full flex flex-col items-center justify-center py-10 sm:py-20 px-4"
        ):
            ui.icon("schedule", size="64px").classes("text-blue-300 mb-4")
            reason_label = ui.label(f"Market is Closed — {close_reason}").classes(
                "text-xl sm:text-3xl font-bold text-gray-700 text-center"
            )
            next_open_label = ui.label(
                f"Next market open: {next_open.strftime('%A, %d %b %Y at %I:%M %p')}"
            ).classes("text-sm sm:text-lg text-gray-500 mt-2 text-center")
            countdown_label = ui.label("").classes(
                "text-4xl sm:text-6xl font-bold text-blue-500 mt-6"
            )
            ui.label(
                "Market hours: 9:15 AM — 3:30 PM IST (Mon-Fri, excl. NSE holidays)"
            ).classes("text-xs sm:text-sm text-gray-400 mt-4 text-center")

        def _tick():
            ist = now_ist()
            target = get_next_market_open()
            remaining = target - ist
            total_sec = max(0, int(remaining.total_seconds()))
            h, rem = divmod(total_sec, 3600)
            m, s = divmod(rem, 60)
            countdown_label.set_text(f"{h:02d}h {m:02d}m {s:02d}s")

            # Update reason in case day changes (e.g. weekend -> after hours)
            if is_nse_holiday(ist):
                reason = "NSE Holiday"
            elif ist.weekday() > 4:
                reason = "Weekend"
            else:
                reason = "After Hours"
            reason_label.set_text(f"Market is Closed — {reason}")
            next_open_label.set_text(
                f"Next market open: {target.strftime('%A, %d %b %Y at %I:%M %p')}"
            )

        _tick()
        ui.timer(1, _tick)
