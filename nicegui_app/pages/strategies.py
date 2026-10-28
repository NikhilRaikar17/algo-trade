"""
Strategies page — one card per strategy with Backtest / Live toggles.

Flags live in the strategies table (strategy_registry.py). Backtest pages, Backtest P&L
and the email report run only backtest-enabled strategies; the trading engine, Live Algos
dropdown and Live P&L use only live-enabled ones. Only the admin can change toggles.
"""

from nicegui import ui

from strategy_registry import get_strategy_rows, set_strategy_enabled


# key → (direction, one-line description)
_STRATEGY_INFO = {
    "abcd": (
        "Reversal · Both",
        "Harmonic A→B→C→D swing pattern. BC retraces 61.8–78.6% of AB and CD "
        "extends 100–161.8% of AB. Trades at D with a 1:1.4 risk-reward target.",
    ),
    "dtc": (
        "Reversal · Short",
        "Two intraday swing highs within 0.15% of each other. Enters on a close "
        "below the neckline; target neckline − height, stop neckline + 70% of height.",
    ),
    "dts": (
        "Reversal · Short",
        "Textbook double top: peaks within 1%, entry just below the neckline. "
        "Same target and stop rules as the customized variant, without the resistance check.",
    ),
    "db": (
        "Reversal · Long",
        "Two intraday swing lows within 0.15% of each other. Enters on a close "
        "above the neckline; target neckline + height, stop neckline − 70% of height.",
    ),
    "ema10": (
        "Trend · Both",
        "Signals when price closes across the 10-period EMA. No new entries after 15:00 IST.",
    ),
    "sma50": (
        "Trend · Both",
        "Signals when price closes across the 50-period SMA. No new entries after 15:00 IST.",
    ),
    "ema100": (
        "Trend · Both",
        "Signals when price closes across the 100-period EMA (over today and earlier days). "
        "2% target, 1% stop. No new entries after 15:00 IST.",
    ),
    "sma100": (
        "Trend · Both",
        "Signals when price closes across the 100-period SMA (over today and earlier days). "
        "2% target, 1% stop. No new entries after 15:00 IST.",
    ),
    "sma200": (
        "Trend · Both",
        "Signals when price closes across the 200-period SMA (over today and earlier days). "
        "2% target, 1% stop. No new entries after 15:00 IST.",
    ),
    "ema50x100": (
        "Trend · Both",
        "BUY when the 50-period EMA crosses above the 100-period EMA, SELL when it crosses below. "
        "2% target, 1% stop. No new entries after 15:00 IST.",
    ),
    "opt_long_call": (
        "Options · Bullish · Defined loss",
        "Buy a call. Maximum expiry loss is the premium paid; upside is theoretically unlimited. "
        "Available in the Options Strategy Lab for payoff comparison only.",
    ),
    "opt_bull_call_spread": (
        "Options · Bullish · Defined risk",
        "Buy a lower-strike call and sell a higher-strike call for a net debit. "
        "Expiry risk and reward are capped; live execution is not enabled.",
    ),
    "opt_bull_put_spread": (
        "Options · Bullish · Defined risk",
        "Sell a higher-strike put and buy a lower-strike put for a net credit. "
        "Expiry risk and reward are capped; live execution is not enabled.",
    ),
    "opt_long_straddle": (
        "Options · Long volatility",
        "Buy a call and put at the same strike. Benefits from a sufficiently large move either way; "
        "the combined premium is at risk.",
    ),
    "opt_iron_condor": (
        "Options · Range-bound · Defined risk",
        "Combine a put credit spread and call credit spread. Designed for a range-bound expiry; "
        "live execution is not enabled.",
    ),
}

_CSS = """
<style>
  .st-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 12px;
    width: 100%;
  }
  .st-card {
    background: var(--at-bg1);
    border: 1px solid var(--at-line);
    border-radius: var(--at-radius);
    padding: 16px 16px 8px;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .st-card.st-off { opacity: 0.6; }
  .st-name {
    font-family: var(--at-cond);
    font-size: 15px; font-weight: 600;
    color: var(--at-fg);
  }
  .st-meta {
    font-family: var(--at-mono);
    font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase;
    color: var(--at-fg-faint);
    margin-top: 2px;
  }
  .st-desc {
    font-size: 12.5px; line-height: 1.55;
    color: var(--at-fg-dim);
    margin: 10px 0 12px;
    flex: 1;
  }
  .st-row {
    display: flex; align-items: center; justify-content: space-between;
    border-top: 1px solid var(--at-line);
    padding: 4px 0;
    min-height: 40px;
  }
  .st-row-label { font-size: 12.5px; color: var(--at-fg); }
  .st-row-hint  { font-size: 11px; color: var(--at-fg-faint); }
  .st-summary {
    font-family: var(--at-mono);
    font-size: 11px; color: var(--at-fg-dim);
  }
</style>
"""


def render_strategies_tab(container, can_edit: bool = False, on_change=None):
    """Build the Strategies page. Returns an async refresh() closure.

    on_change(key, backtest_enabled, live_enabled) is called after a toggle is saved,
    so the caller can update navigation (e.g. hide disabled backtest pages).
    """

    with container:
        ui.add_head_html(_CSS)
        ui.label("Strategies").classes("text-xl font-bold mb-1")
        ui.label(
            "Choose which strategies run in backtests and in live trading. "
            "Live changes apply on the next engine scan (within 2 minutes)."
        ).classes("text-sm text-gray-500 mb-1")
        summary = ui.label("").classes("st-summary mb-3")
        if not can_edit:
            ui.label("View only — ask the admin to change strategy settings.").classes(
                "text-xs text-gray-500 italic mb-3"
            )
        grid = ui.element("div").classes("st-grid")

    def _update_summary(rows):
        n_bt = sum(r["backtest_enabled"] for r in rows)
        n_live = sum(r["live_enabled"] for r in rows)
        summary.set_text(f"{len(rows)} STRATEGIES · {n_bt} IN BACKTEST · {n_live} LIVE")

    def _build():
        rows = get_strategy_rows()
        _update_summary(rows)
        grid.clear()
        with grid:
            for row in rows:
                _build_card(row)

    def _build_card(row):
        key = row["key"]
        direction, desc = _STRATEGY_INFO.get(key, ("", ""))
        state = {"backtest": row["backtest_enabled"], "live": row["live_enabled"]}

        card = ui.element("div").classes("st-card")
        if not (state["backtest"] or state["live"]):
            card.classes(add="st-off")

        def _toggle(field, value):
            state[field] = value
            set_strategy_enabled(key, **{field: value})
            if state["backtest"] or state["live"]:
                card.classes(remove="st-off")
            else:
                card.classes(add="st-off")
            _update_summary(get_strategy_rows())
            label = "Backtest" if field == "backtest" else "Live algo"
            ui.notify(
                f"{row['display_name']}: {label} {'enabled' if value else 'disabled'}",
                type="positive" if value else "warning",
                position="bottom-right",
            )
            if on_change:
                on_change(key, state["backtest"], state["live"])

        with card:
            ui.label(row["display_name"]).classes("st-name")
            if direction:
                ui.label(direction).classes("st-meta")
            ui.label(desc).classes("st-desc")

            for field, label, hint in (
                ("backtest", "Backtest", "Backtest page, Backtest P&L, email report"),
                ("live", "Live algo", "Trading engine, Live Algos, Live P&L"),
            ):
                with ui.element("div").classes("st-row"):
                    with ui.column().classes("gap-0"):
                        ui.label(label).classes("st-row-label")
                        ui.label(hint).classes("st-row-hint")
                    sw = ui.switch(
                        value=state[field],
                        on_change=lambda e, f=field: _toggle(f, e.value),
                    ).props("color=positive dense")
                    # Options strategies currently have a research/payoff implementation only.
                    # Never expose a Live toggle until signals, order handling and risk checks exist.
                    if not can_edit or (field == "live" and key.startswith("opt_")):
                        sw.disable()
                        if field == "live" and key.startswith("opt_"):
                            sw.tooltip("Options live trading is not implemented")

    _build()

    async def refresh():
        _build()  # re-read flags so changes made in another session show up

    return refresh
