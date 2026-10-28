# Options Strategy Research Engine

Research-only primitives for Indian listed options, with a NiceGUI payoff-comparison screen under `nicegui_app/pages/options_strategy_lab.py`. Nothing in this package places broker orders.

## Current scope
- Multi-leg option positions and expiry payoff
- Five payoff templates: long call, bull call spread, bull put spread, long straddle, and iron condor
- Optional TA-Lib indicators (clear error if TA-Lib is not installed)
- Basic risk guards and exact timestamp/contract price lookup primitives
- Unit tests for payoff, risk, and historical-price validation
- NiceGUI integration through the existing database-backed Strategies page and Backtest toggles

**Important:** the current NiceGUI Options Strategy Lab is an expiry-payoff comparison tool, not yet a historical options backtester. Historical option-chain data, strategy-specific entry/exit rules, option repricing before expiry, realistic fills, brokerage/slippage and margin simulation still need to be implemented and validated. Options live switches remain disabled.

This is a foundation, not a complete transcription of every strategy in Guy Cohen's book and not a claim of profitability. Expand the registry incrementally after validating data and execution assumptions.

## Data contract

The historical-price primitive accepts a pandas DataFrame with `timestamp`, `contract_id`, and `close` columns. Prices must be exact timestamp/contract matches; missing prices are rejected rather than silently forward-filled. For serious research, use bid/ask execution and instrument-specific charges/slippage.

## Quick start

From the repository root:

    uv sync
    uv run pytest options_engine/tests nicegui_app/tests -q

Example payoff:

    from options_engine.models import OptionLeg, OptionType
    from options_engine.payoff import expiry_payoff
    legs = [OptionLeg("NIFTY-EXPIRY-25000-CE", OptionType.CALL, 25000, 1, 120)]
    print(expiry_payoff(legs, spot_at_expiry=25200, lot_size=65))

The example lot size is illustrative only. Load applicable contract lot size and expiry from validated historical metadata; contract specifications can change.

## Safety boundaries
- Research/backtesting only; no live order-routing code for these strategies.
- Naked short calls/puts are not included in the initial templates.
- Risk limits are guards, not guarantees against gaps, illiquidity or broker margin changes.
- Historical performance is not evidence of future returns.
