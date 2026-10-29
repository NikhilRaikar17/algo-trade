"""Interactive expiry-payoff comparison for registered options strategies."""
from __future__ import annotations

from nicegui import ui

from options_strategy_engine import STRATEGY_INFO, build_strategy
from strategy_registry import get_strategy_rows

_CSS = """
<style>
.opt-lab-note { border-left:3px solid var(--at-accent,#64748b); padding:10px 12px;
  background:var(--at-bg1); color:var(--at-fg-dim); font-size:12px; line-height:1.55; }
.opt-lab-kpi { border:1px solid var(--at-line); background:var(--at-bg1); border-radius:8px; padding:12px; }
.opt-lab-label { font-size:10px; color:var(--at-fg-faint); text-transform:uppercase; letter-spacing:.08em; }
.opt-lab-value { font-family:var(--at-mono); font-size:18px; font-weight:600; color:var(--at-fg); }
</style>
"""


def render_options_strategy_lab_tab(container):
    with container:
        ui.add_head_html(_CSS)
        ui.label("Options Strategy Lab").classes("text-xl font-bold")
        ui.label("Compare expiry payoff profiles for NIFTY, BANKNIFTY and stock options.").classes("text-sm text-gray-500 mb-3")
        ui.html(
            '<div class="opt-lab-note mb-3"><b>Research mode only.</b> This calculates theoretical expiry payoff from the '
            'strikes and premiums you enter. It is not a historical backtest, does not model early exits, IV/theta before '
            'expiry, slippage, brokerage, margin or fills, and cannot place orders. Live trading is intentionally disabled.</div>'
        )
        enabled = [r for r in get_strategy_rows() if r["key"] in STRATEGY_INFO and r["options_pnl_enabled"]]
        if not enabled:
            ui.label("No options strategies are enabled for Options P&L. Enable one on the Strategies page.").classes("text-amber-700")

            async def refresh_empty():
                container.clear()
                render_options_strategy_lab_tab(container)

            return refresh_empty

        choices = {r["key"]: r["display_name"] for r in enabled}
        with ui.card().classes("w-full"):
            strategy = ui.select(choices, value=next(iter(choices)), label="Strategy").classes("w-full")
            with ui.grid(columns=2).classes("w-full gap-3"):
                spot = ui.number("Current underlying price (₹)", value=25000, min=0.01)
                multiplier = ui.number("Lot size / quantity multiplier", value=1, min=1, step=1)
                strike = ui.number("Single strike (Long Call / Straddle)", value=25000, min=0.01)
                premium = ui.number("Long Call premium (₹)", value=250, min=0)
                lower = ui.number("Lower strike / Iron Condor short put strike", value=24800, min=0.01)
                upper = ui.number("Upper strike / Iron Condor short call strike", value=25200, min=0.01)
                long_p = ui.number("Spread long premium / Straddle call premium (₹)", value=150, min=0)
                short_p = ui.number("Spread short premium / Straddle put premium (₹)", value=100, min=0)
                put_wing = ui.number("Iron Condor long put wing strike", value=24600, min=0.01)
                put_wing_p = ui.number("Iron Condor long put wing premium (₹)", value=40, min=0)
                ic_short_put = ui.number("Iron Condor short put premium (₹)", value=180, min=0)
                ic_short_call = ui.number("Iron Condor short call premium (₹)", value=180, min=0)
                call_wing = ui.number("Iron Condor long call wing strike", value=25400, min=0.01)
                call_wing_p = ui.number("Iron Condor long call wing premium (₹)", value=40, min=0)
            run = ui.button("Calculate expiry payoff", icon="calculate").props("color=primary no-caps")
        status = ui.label("").classes("text-sm mt-2")
        kpis = ui.row().classes("w-full gap-3 flex-wrap mt-2")
        chart = ui.echart({}).classes("w-full").style("height:360px")
        table = ui.table(columns=[
            {"name": "underlying", "label": "Underlying at expiry (₹)", "field": "underlying", "align": "right"},
            {"name": "pnl", "label": "Gross P&L (₹)", "field": "pnl", "align": "right"},
        ], rows=[], row_key="underlying").classes("w-full")

    def calculate():
        try:
            key = strategy.value
            if key not in choices:
                raise ValueError("Select an enabled options strategy.")
            s = float(spot.value)
            qty = int(multiplier.value)
            if s <= 0 or qty < 1:
                raise ValueError("Underlying price must be positive and multiplier must be at least 1.")
            built = build_strategy(
                key, strike=float(strike.value), lower_strike=float(lower.value),
                upper_strike=float(upper.value), spot=s, premium=float(premium.value),
                long_premium=float(short_p.value if key == "opt_bull_put_spread" else long_p.value),
                short_premium=float(long_p.value if key == "opt_bull_put_spread" else short_p.value),
                call_premium=float(long_p.value), put_premium=float(short_p.value),
                put_wing=float(put_wing.value), put_wing_premium=float(put_wing_p.value),
                short_put_premium=float(ic_short_put.value), short_call_premium=float(ic_short_call.value),
                call_wing=float(call_wing.value), call_wing_premium=float(call_wing_p.value),
            )
            scenarios = sorted(
                {round(s * (0.8 + i * 0.025), 2) for i in range(17)}
                | {round(leg.strike, 2) for leg in built.legs}
            )
            values = [{"underlying": price, "pnl": built.payoff(price, qty)} for price in scenarios]
            pnls = [r["pnl"] for r in values]
            kpis.clear()
            with kpis:
                for label, value in (
                    ("Strategy", built.name),
                    ("Worst shown P&L", f"₹{min(pnls):,.2f}"),
                    ("Best shown P&L", f"₹{max(pnls):,.2f}" if key != "opt_long_call" else "Unlimited upside"),
                ):
                    with ui.element("div").classes("opt-lab-kpi").style("min-width:180px; flex:1"):
                        ui.label(label).classes("opt-lab-label")
                        ui.label(value).classes("opt-lab-value")
            chart.options.clear()  # ui.echart's options can't be reassigned (NiceGUI 3), only changed in place
            chart.options.update({
                "tooltip": {"trigger": "axis"},
                "grid": {"left": 55, "right": 20, "top": 25, "bottom": 45},
                "xAxis": {"type": "category", "name": "Underlying at expiry (₹)", "data": [str(r["underlying"]) for r in values]},
                "yAxis": {"type": "value", "name": "Gross P&L (₹)"},
                "series": [{"type": "line", "smooth": False, "symbol": "circle", "data": pnls,
                            "markLine": {"data": [{"yAxis": 0}]}}],
            })
            chart.update()
            table.rows = values
            table.update()
            status.set_text("Gross expiry payoff only; costs and pre-expiry option repricing are excluded.")
        except Exception as exc:
            status.set_text(f"Could not calculate: {exc}")
            ui.notify(str(exc), type="warning")

    run.on_click(calculate)
    calculate()

    async def refresh():
        latest = [r for r in get_strategy_rows()
                  if r["key"] in STRATEGY_INFO and r["backtest_enabled"]]
        new_choices = {r["key"]: r["display_name"] for r in latest}
        choices.clear()
        choices.update(new_choices)
        strategy.options = new_choices
        if strategy.value not in new_choices:
            strategy.value = next(iter(new_choices), None)
        strategy.update()
        if not new_choices:
            run.disable()
            status.set_text("No options strategies enabled. Enable one on the Strategies page.")
            kpis.clear()
            chart.options.clear()
            chart.update()
            table.rows = []
            table.update()
            return
        run.enable()
        calculate()

    return refresh
