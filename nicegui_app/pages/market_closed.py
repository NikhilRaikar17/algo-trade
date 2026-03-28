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
    remaining = next_open - now_ist()
    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    with container:
        with ui.element("div").classes(
            "w-full flex flex-col items-center justify-center py-20"
        ):
            ui.icon("schedule", size="64px").classes("text-blue-300 mb-4")
            ui.label(f"Market is Closed — {close_reason}").classes(
                "text-3xl font-bold text-gray-700"
            )
            ui.label(
                f"Next market open: {next_open.strftime('%A, %d %b %Y at %I:%M %p')}"
            ).classes("text-lg text-gray-500 mt-2")
            countdown_label = ui.label(
                f"{hours:02d}h {minutes:02d}m {seconds:02d}s"
            ).classes("text-6xl font-bold text-blue-500 mt-6")
            ui.label(
                "Market hours: 9:15 AM — 3:30 PM IST (Mon-Fri, excl. NSE holidays)"
            ).classes("text-sm text-gray-400 mt-4")

    return countdown_label
