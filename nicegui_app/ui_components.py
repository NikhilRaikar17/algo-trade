"""
Reusable NiceGUI UI components: option chain table, trade table.
"""

import pandas as pd
from nicegui import ui


def _f2(v):
    """Format a value to 2 decimal places if numeric."""
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def build_option_chain_table(container, df, atm):
    """Build a NiceGUI table for option chain data inside a container."""
    container.clear()
    with container:
        if df.empty:
            ui.label("No data available").classes("text-grey")
            return

        num_cols = list(df.select_dtypes("number").columns)
        display_df = df.copy()
        for c in num_cols:
            if c == "Gamma":
                display_df[c] = display_df[c].apply(
                    lambda x: round(x, 6) if pd.notna(x) else x
                )
            else:
                display_df[c] = display_df[c].apply(
                    lambda x: round(x, 4) if pd.notna(x) else x
                )

        columns = [
            {"name": col, "label": col, "field": col, "sortable": True, "align": "left"}
            for col in display_df.columns
        ]
        rows = display_df.to_dict("records")

        table = ui.table(columns=columns, rows=rows, row_key="Strike").classes("w-full")
        table.props("dense flat bordered")

        table.add_slot(
            "body-cell",
            """
            <q-td :props="props"
                   :style="props.row.Strike == """
            + str(atm)
            + """ ? 'background: #ffffb3; font-weight: bold' : ''">
                {{ props.value }}
            </q-td>
        """,
        )


def build_trade_table(container, rows, pnl_col="PnL"):
    """Build a trade table with PnL highlighting."""
    container.clear()
    with container:
        if not rows:
            ui.label("No trades").classes("text-grey italic")
            return

        columns = list(rows[0].keys())
        with ui.element("div").classes("w-full responsive-table-wrap"):
            with ui.element("table").classes("w-full border-collapse text-sm"):
                with ui.element("thead"):
                    with ui.element("tr").classes("bg-gray-100"):
                        for col in columns:
                            with ui.element("th").classes(
                                "px-3 py-2 text-left font-semibold border-b"
                            ):
                                ui.label(col).classes("text-xs font-semibold")
                with ui.element("tbody"):
                    for row in rows:
                        pnl_val = row.get(pnl_col, 0)
                        with ui.element("tr").classes("border-b hover:bg-gray-50"):
                            for col in columns:
                                val = row[col]
                                cell = ui.element("td").classes("px-3 py-2")
                                if col == pnl_col:
                                    if isinstance(pnl_val, (int, float)):
                                        if pnl_val > 0:
                                            cell.classes(
                                                "text-green-700 font-bold bg-green-50"
                                            )
                                        elif pnl_val < 0:
                                            cell.classes(
                                                "text-red-700 font-bold bg-red-50"
                                            )
                                if col == "Status" and isinstance(
                                    pnl_val, (int, float)
                                ):
                                    if pnl_val > 0:
                                        cell.classes("text-green-700 bg-green-50")
                                    elif pnl_val < 0:
                                        cell.classes("text-red-700 bg-red-50")
                                with cell:
                                    ui.label(
                                        _f2(val) if isinstance(val, float) else str(val)
                                    ).classes("text-xs")
