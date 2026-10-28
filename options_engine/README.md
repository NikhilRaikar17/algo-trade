# Options Strategy Research Engine

A research-only, offline backtesting module for Indian listed options. It is deliberately separate from the existing NiceGUI/live-trading path: this package does not place orders or import broker credentials.

## Initial scope
- Multi-leg option positions and expiry payoff
- Five strategy templates: long call, bull call spread, bull put spread, long straddle, iron condor
- Optional TA-Lib indicators (graceful error if TA-Lib is not installed)
- Per-trade loss limits, daily loss limits, position-size guard and explicit missing-price rejection primitives
- Unit tests

This is a foundation, not a complete transcription of every strategy in Guy Cohen's book and not a claim of profitability. Expand the registry incrementally after validating source data and execution assumptions.

## Data contract
For historical backtests, use a pandas DataFrame with timestamp, contract_id and close columns. Prices must be exact timestamp/contract matches; do not silently forward-fill stale quotes. For serious research, use bid/ask execution and instrument-specific charges/slippage.

## Quick start
From the repository root:

    uv sync
    uv run python -m pytest options_engine/tests -q

Example payoff:

    from options_engine.models import OptionLeg, OptionType
    from options_engine.payoff import expiry_payoff
    legs = [OptionLeg("NIFTY-2026-11-05-25000-CE", OptionType.CALL, 25000, 1, 120)]
    print(expiry_payoff(legs, spot_at_expiry=25200, lot_size=65))

The example lot size is illustrative only. Load applicable contract lot size and expiry from validated historical metadata; contract specifications can change.

## Safety boundaries
- Backtesting only; no live order-routing code.
- Naked short calls/puts are not included in the initial templates.
- Risk limits are guards, not guarantees against gaps, illiquidity or broker margin changes.
- Historical performance is not evidence of future returns.
