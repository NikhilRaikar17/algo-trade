"""Options strategy expiry-payoff engine for the NiceGUI research lab.

This module does not generate entry signals, price options before expiry, simulate fills,
or place broker orders.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Leg:
    kind: str
    strike: float
    quantity: int
    premium: float


@dataclass(frozen=True)
class Strategy:
    key: str
    name: str
    description: str
    legs: tuple[Leg, ...]

    def payoff(self, underlying_at_expiry: float, multiplier: int = 1) -> float:
        if underlying_at_expiry < 0 or multiplier < 1:
            raise ValueError("underlying price must be non-negative and multiplier >= 1")
        total = 0.0
        for leg in self.legs:
            intrinsic = (
                max(underlying_at_expiry - leg.strike, 0.0)
                if leg.kind == "CE"
                else max(leg.strike - underlying_at_expiry, 0.0)
            )
            total += leg.quantity * (intrinsic - leg.premium) * multiplier
        return round(total, 2)


STRATEGY_INFO = {
    "opt_long_call": ("Long Call", "Bullish; loss limited to the call premium."),
    "opt_bull_call_spread": ("Bull Call Spread", "Bullish debit spread; defined risk and capped profit."),
    "opt_bull_put_spread": ("Bull Put Spread", "Bullish credit spread; defined risk and capped profit."),
    "opt_long_straddle": ("Long Straddle", "Long volatility; profits from a sufficiently large move either way."),
    "opt_iron_condor": ("Iron Condor", "Range-bound, four-leg credit strategy with defined risk."),
}


def build_strategy(
    key: str, *, strike: float, lower_strike: float, upper_strike: float, spot: float,
    premium: float, long_premium: float, short_premium: float, call_premium: float,
    put_premium: float, put_wing: float, put_wing_premium: float,
    short_put_premium: float, short_call_premium: float, call_wing: float,
    call_wing_premium: float,
) -> Strategy:
    """Build one of the supported payoff templates; premiums are per underlying unit."""
    del spot  # reserved for future spot-relative strategy validation
    if key == "opt_long_call":
        legs = (Leg("CE", strike, 1, premium),)
    elif key == "opt_bull_call_spread":
        if not lower_strike < upper_strike:
            raise ValueError("Bull Call Spread requires lower strike < upper strike.")
        if long_premium < short_premium:
            raise ValueError("For a debit Bull Call Spread, long premium must be >= short premium.")
        legs = (Leg("CE", lower_strike, 1, long_premium),
                Leg("CE", upper_strike, -1, short_premium))
    elif key == "opt_bull_put_spread":
        if not lower_strike < upper_strike:
            raise ValueError("Bull Put Spread requires lower strike < upper strike.")
        if short_premium < long_premium:
            raise ValueError("For a credit Bull Put Spread, short premium must be >= long premium.")
        legs = (Leg("PE", upper_strike, -1, short_premium),
                Leg("PE", lower_strike, 1, long_premium))
    elif key == "opt_long_straddle":
        legs = (Leg("CE", strike, 1, call_premium), Leg("PE", strike, 1, put_premium))
    elif key == "opt_iron_condor":
        if not put_wing < lower_strike < upper_strike < call_wing:
            raise ValueError("Iron Condor strikes must satisfy put wing < short put < short call < call wing.")
        if short_put_premium + short_call_premium < put_wing_premium + call_wing_premium:
            raise ValueError("Iron Condor inputs must produce a net credit.")
        legs = (Leg("PE", put_wing, 1, put_wing_premium),
                Leg("PE", lower_strike, -1, short_put_premium),
                Leg("CE", upper_strike, -1, short_call_premium),
                Leg("CE", call_wing, 1, call_wing_premium))
    else:
        raise ValueError(f"Unknown options strategy: {key}")
    name, description = STRATEGY_INFO[key]
    return Strategy(key, name, description, legs)
