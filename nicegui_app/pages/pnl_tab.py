"""
P&L summary tab page.
"""

from nicegui import ui

from pnl import collect_all_trades
from ui_components import build_trade_table


def render_pnl_tab(container):
    """Build the P&L summary tab content inside container."""
    with container:
        ui.label("Profit / Loss Summary — All Strategies").classes(
            "text-xl font-bold mb-2"
        )
        summary_container = ui.element("div").classes("w-full")

    async def refresh():
        all_active, all_completed = collect_all_trades()

        summary_container.clear()
        with summary_container:
            # Completed trades
            ui.label("Completed Trades").classes("text-lg font-bold mt-4")
            if not all_completed:
                ui.label("No completed trades today").classes("text-gray-500 italic")
            else:
                total_pnl = sum(t.get("pnl", 0) for t in all_completed)
                winners = sum(1 for t in all_completed if t.get("pnl", 0) > 0)
                losers = sum(1 for t in all_completed if t.get("pnl", 0) < 0)

                with ui.row().classes("gap-4 sm:gap-8 flex-wrap"):
                    with ui.card().classes("p-3 sm:p-4 min-w-[120px] flex-1"):
                        ui.label("Total P&L").classes("text-sm text-gray-500")
                        color = "text-green-600" if total_pnl >= 0 else "text-red-600"
                        ui.label(f"{total_pnl:+.2f}").classes(
                            f"text-xl sm:text-2xl font-bold {color}"
                        )
                    with ui.card().classes("p-3 sm:p-4 min-w-[120px] flex-1"):
                        ui.label("Total Trades").classes("text-sm text-gray-500")
                        ui.label(str(len(all_completed))).classes("text-xl sm:text-2xl font-bold")
                    with ui.card().classes("p-3 sm:p-4 min-w-[120px] flex-1"):
                        ui.label("Winners").classes("text-sm text-gray-500")
                        ui.label(str(winners)).classes(
                            "text-xl sm:text-2xl font-bold text-green-600"
                        )
                    with ui.card().classes("p-3 sm:p-4 min-w-[120px] flex-1"):
                        ui.label("Losers").classes("text-sm text-gray-500")
                        ui.label(str(losers)).classes("text-xl sm:text-2xl font-bold text-red-600")

                ui.separator()

                strategies = set(t.get("strategy", "Unknown") for t in all_completed)
                for strat in sorted(strategies):
                    strat_trades = [
                        t for t in all_completed if t.get("strategy") == strat
                    ]
                    spnl = sum(t.get("pnl", 0) for t in strat_trades)
                    ui.label(
                        f"{strat}: {len(strat_trades)} trades | PnL: {spnl:+.2f}"
                    ).classes("text-md font-semibold")

                ui.separator()

                rows = [
                    {
                        "Strategy": t.get("strategy", ""),
                        "Signal": t.get("signal", ""),
                        "Entry": t.get("entry", 0),
                        "Exit": round(t.get("exit_price", 0), 2),
                        "PnL": t.get("pnl", 0),
                        "Status": t.get("status", ""),
                    }
                    for t in all_completed
                ]
                trade_container = ui.element("div").classes("w-full")
                build_trade_table(trade_container, rows, "PnL")

            # Active trades
            ui.label("Active Trades").classes("text-lg font-bold mt-6")
            if not all_active:
                ui.label("No active trades").classes("text-gray-500 italic")
            else:
                total_unreal = sum(t.get("unrealized_pnl", 0) for t in all_active)
                color = "text-green-600" if total_unreal >= 0 else "text-red-600"
                ui.label(f"Unrealized P&L: {total_unreal:+.2f}").classes(
                    f"text-lg font-bold {color}"
                )

                rows = [
                    {
                        "Strategy": t.get("strategy", ""),
                        "Signal": t.get("signal", ""),
                        "Entry": t.get("entry", 0),
                        "Target": t.get("target", 0),
                        "Stop Loss": t.get("stop_loss", 0),
                        "Unreal. PnL": t.get("unrealized_pnl", 0),
                    }
                    for t in all_active
                ]
                trade_container = ui.element("div").classes("w-full")
                build_trade_table(trade_container, rows, "Unreal. PnL")

    return refresh
