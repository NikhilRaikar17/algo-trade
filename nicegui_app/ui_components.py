"""
Reusable NiceGUI UI components: option chain table, trade table, backtest P&L section.
"""

from collections import defaultdict

import pandas as pd
from nicegui import ui


async def resolve_option_labels_in_dropdown(select_widget, option_groups: dict, live_options: dict) -> None:
    """Resolve real strike/expiry labels for all OPT: entries and update the dropdown.

    Fetches each option contract's real label (e.g. 'NIFTY 07APR 22350 CE') in the
    background and patches the dropdown once all are resolved.
    """
    import asyncio
    from data import resolve_option_label

    loop = asyncio.get_event_loop()
    updated = False
    for key in list(live_options.keys()):
        if not key.startswith("OPT:"):
            continue
        _, index_name, expiry_idx_str, opt_type = key.split(":")
        try:
            real_label = await loop.run_in_executor(
                None, lambda i=index_name, e=int(expiry_idx_str), o=opt_type: resolve_option_label(i, e, o)
            )
            live_options[key] = real_label
            updated = True
        except Exception:
            pass
    if updated and not select_widget.client._deleted:
        resolved_groups = {
            grp: {k: live_options.get(k, v) for k, v in opts.items()}
            for grp, opts in option_groups.items()
        }
        select_widget.options = build_grouped_options_dict(resolved_groups)
        select_widget.update()


def build_grouped_options_dict(option_groups: dict) -> dict:
    """Convert {group_label: {value: display_name}} into a flat dict for ui.select
    with visual group headers embedded as sentinel entries.

    Returns a {value: label} dict compatible with NiceGUI's ui.select(options=dict).
    Header sentinel keys are prefixed '__hdr_' — guard on_change with:
        if e.value and str(e.value).startswith('__hdr_'): return
    """
    result: dict[str, str] = {}
    for group_label, opts in option_groups.items():
        result[f"__hdr_{group_label}"] = f"── {group_label} ──"
        result.update(opts)
    return result


def _f2(v):
    """Format a value to 2 decimal places if numeric."""
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def build_option_chain_table(container, df, atm):
    """Build a styled option chain table for the dark terminal theme."""
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

        columns = list(display_df.columns)
        rows = [
            {k: (v.item() if hasattr(v, "item") else v) for k, v in row.items()}
            for row in display_df.to_dict("records")
        ]

        _RIGHT_ALIGN = {"LTP", "IV", "Delta", "Gamma", "Theta", "Vega", "OI", "Volume",
                        "Strike", "Bid", "Ask", "BidQty", "AskQty"}

        with ui.element("div").style(
            "width:100%; overflow-x:auto; border-radius:6px; "
            "border:1px solid var(--at-line2);"
        ):
            with ui.element("table").style(
                "width:100%; border-collapse:collapse; "
                "font-family:var(--at-mono); font-size:0.72rem; "
                "background:var(--at-panel); color:var(--at-fg);"
            ):
                # ── Header ────────────────────────────────────────────────────
                with ui.element("thead"):
                    with ui.element("tr").style(
                        "background:var(--at-bg2); border-bottom:2px solid var(--at-line2);"
                    ):
                        for col in columns:
                            align = "right" if col in _RIGHT_ALIGN else "left"
                            with ui.element("th").style(
                                f"padding:7px 10px; text-align:{align}; "
                                "font-size:0.65rem; font-weight:700; letter-spacing:0.08em; "
                                "text-transform:uppercase; color:var(--at-fg-faint); "
                                "white-space:nowrap;"
                            ):
                                ui.label(col)

                # ── Body ──────────────────────────────────────────────────────
                with ui.element("tbody"):
                    for i, row in enumerate(rows):
                        is_atm = row.get("Strike") == atm
                        stripe = "background:rgba(255,255,255,0.02);" if i % 2 == 1 else ""
                        atm_style = (
                            "background:rgba(255,176,32,0.10) !important; "
                            "border-left:3px solid var(--at-warn);"
                            if is_atm else "border-left:3px solid transparent;"
                        )
                        with ui.element("tr").style(
                            f"{stripe}{atm_style} border-bottom:1px solid var(--at-line); "
                            "transition:background 0.12s;"
                        ):
                            for col in columns:
                                val = row[col]
                                align = "right" if col in _RIGHT_ALIGN else "left"

                                # Format value
                                if col == "Trend":
                                    if str(val) == "UP":
                                        cell_style = (
                                            "padding:5px 10px; color:var(--at-up); "
                                            "font-weight:700; letter-spacing:0.04em;"
                                        )
                                        display_val = "▲ UP"
                                    elif str(val) == "DOWN":
                                        cell_style = (
                                            "padding:5px 10px; color:var(--at-down); "
                                            "font-weight:700; letter-spacing:0.04em;"
                                        )
                                        display_val = "▼ DOWN"
                                    else:
                                        cell_style = (
                                            "padding:5px 10px; color:var(--at-fg-faint); "
                                            "letter-spacing:0.04em;"
                                        )
                                        display_val = "— FLAT"
                                elif col == "Strike":
                                    cell_style = (
                                        f"padding:5px 10px; text-align:{align}; "
                                        "font-weight:700; color:var(--at-fg); "
                                        + ("color:var(--at-warn);" if is_atm else "")
                                    )
                                    display_val = str(int(val)) if isinstance(val, float) and val == int(val) else str(val)
                                elif isinstance(val, float):
                                    cell_style = (
                                        f"padding:5px 10px; text-align:{align}; "
                                        "color:var(--at-fg-dim);"
                                    )
                                    display_val = _f2(val)
                                else:
                                    cell_style = (
                                        f"padding:5px 10px; text-align:{align}; "
                                        "color:var(--at-fg);"
                                    )
                                    display_val = str(val)

                                with ui.element("td").style(cell_style):
                                    ui.label(display_val)


def build_trade_table(container, rows, pnl_col="PnL"):
    """Build a trade table with PnL highlighting."""
    container.clear()
    with container:
        if not rows:
            ui.label("No trades").classes("text-grey italic")
            return

        columns = list(rows[0].keys())
        with ui.element("div").classes("w-full responsive-table-wrap"):
            with ui.element("table").style(
                "width:100%; border-collapse:collapse; font-size:0.8rem;"
                "background:var(--at-panel); color:var(--at-fg);"
            ):
                with ui.element("thead"):
                    with ui.element("tr").style("background:var(--at-bg2);"):
                        for col in columns:
                            with ui.element("th").style(
                                "padding:6px 10px; text-align:left; font-size:0.7rem;"
                                "font-weight:600; letter-spacing:0.05em; text-transform:uppercase;"
                                "color:var(--at-fg-dim); border-bottom:1px solid var(--at-line);"
                            ):
                                ui.label(col)
                with ui.element("tbody"):
                    for row in rows:
                        pnl_val = row.get(pnl_col, 0)
                        with ui.element("tr").style(
                            "border-bottom:1px solid var(--at-line);"
                        ):
                            for col in columns:
                                val = row[col]
                                if col == pnl_col and isinstance(pnl_val, (int, float)):
                                    if pnl_val > 0:
                                        cell_style = (
                                            "padding:5px 10px; font-weight:700;"
                                            "color:var(--at-up);"
                                            "background:rgba(0,208,132,0.08);"
                                        )
                                    elif pnl_val < 0:
                                        cell_style = (
                                            "padding:5px 10px; font-weight:700;"
                                            "color:var(--at-down);"
                                            "background:rgba(255,77,94,0.08);"
                                        )
                                    else:
                                        cell_style = "padding:5px 10px; color:var(--at-fg-dim);"
                                elif col == "Status" and isinstance(pnl_val, (int, float)):
                                    if pnl_val > 0:
                                        cell_style = (
                                            "padding:5px 10px; color:var(--at-up);"
                                            "background:rgba(0,208,132,0.08);"
                                        )
                                    elif pnl_val < 0:
                                        cell_style = (
                                            "padding:5px 10px; color:var(--at-down);"
                                            "background:rgba(255,77,94,0.08);"
                                        )
                                    else:
                                        cell_style = "padding:5px 10px; color:var(--at-fg-dim);"
                                else:
                                    cell_style = "padding:5px 10px; color:var(--at-fg);"
                                with ui.element("td").style(cell_style):
                                    ui.label(
                                        _f2(val) if isinstance(val, float) else str(val)
                                    ).style("font-size:0.75rem;")


def render_backtest_pnl_section(completed):
    """Render a P&L summary section for backtest trades.

    Matches the layout of the live P&L tab:
      - Summary cards (Total P&L, Trades, Win Rate, W/L)
      - Signal/type breakdown (Bullish / Bearish) when both exist
      - Day-wise P&L table

    Expects each trade dict to have: pnl (float), time (Timestamp or str),
    and optionally type (str).
    """
    if not completed:
        return

    total_pnl = sum(t["pnl"] for t in completed)
    total_trades = len(completed)
    winners = sum(1 for t in completed if t["pnl"] > 0)
    losers = sum(1 for t in completed if t["pnl"] < 0)
    win_rate = (winners / total_trades * 100) if total_trades else 0

    ui.label("P&L Summary").classes("text-lg font-semibold mb-3")

    # ── Summary cards ─────────────────────────────────────────────────────────
    with ui.row().classes("gap-4 flex-wrap mb-4"):
        with ui.card().classes("p-3 min-w-[120px] flex-1"):
            ui.label("Total P&L").classes("text-sm text-gray-500")
            color = "text-green-600" if total_pnl >= 0 else "text-red-600"
            ui.label(f"{total_pnl:+.2f}").classes(f"text-2xl font-bold {color}")
        with ui.card().classes("p-3 min-w-[120px] flex-1"):
            ui.label("Trades").classes("text-sm text-gray-500")
            ui.label(str(total_trades)).classes("text-2xl font-bold")
        with ui.card().classes("p-3 min-w-[120px] flex-1"):
            ui.label("Win Rate").classes("text-sm text-gray-500")
            ui.label(f"{win_rate:.0f}%").classes("text-2xl font-bold text-emerald-600")
        with ui.card().classes("p-3 min-w-[120px] flex-1"):
            ui.label("W / L").classes("text-sm text-gray-500")
            ui.label(f"{winners} / {losers}").classes("text-2xl font-bold")

    # ── Signal/type breakdown (Bullish / Bearish) ─────────────────────────────
    types = sorted(set(t.get("type", "") for t in completed if t.get("type")))
    if len(types) > 1:
        ui.label("Signal Breakdown").classes("text-base font-semibold mb-1")
        with ui.row().classes("gap-3 flex-wrap mb-4"):
            for typ in types:
                type_trades = [t for t in completed if t.get("type") == typ]
                tpnl = sum(t["pnl"] for t in type_trades)
                tw = sum(1 for t in type_trades if t["pnl"] > 0)
                tl = sum(1 for t in type_trades if t["pnl"] < 0)
                twr = f"{tw / len(type_trades) * 100:.0f}%" if type_trades else "—"
                tcolor = "text-green-600" if tpnl >= 0 else "text-red-600"
                with ui.card().classes("p-3 min-w-[150px] flex-1"):
                    ui.label(typ).classes("text-sm font-bold text-gray-600 mb-1")
                    ui.label(f"{tpnl:+.2f}").classes(f"text-xl font-bold {tcolor}")
                    ui.label(
                        f"{len(type_trades)} trades · {tw}W/{tl}L · WR {twr}"
                    ).classes("text-xs text-gray-500")

    # ── Day-wise P&L table ────────────────────────────────────────────────────
    ui.label("Day-wise P&L").classes("text-base font-semibold mb-2")
    date_groups: dict = defaultdict(list)
    for t in completed:
        entry_time = t.get("time")
        date_str = (
            entry_time.strftime("%Y-%m-%d")
            if hasattr(entry_time, "strftime")
            else str(entry_time)[:10]
        )
        date_groups[date_str].append(t)

    day_rows = []
    for date in sorted(date_groups.keys(), reverse=True):
        dtrades = date_groups[date]
        dpnl = sum(t["pnl"] for t in dtrades)
        dw = sum(1 for t in dtrades if t["pnl"] > 0)
        dl = sum(1 for t in dtrades if t["pnl"] < 0)
        dwr = f"{dw / len(dtrades) * 100:.0f}%" if dtrades else "0%"
        day_rows.append({
            "Date": date,
            "Trades": len(dtrades),
            "Winners": dw,
            "Losers": dl,
            "Win %": dwr,
            "P&L": round(dpnl, 2),
        })

    build_trade_table(ui.element("div").classes("w-full"), day_rows, "P&L")
