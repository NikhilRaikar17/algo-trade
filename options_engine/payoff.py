"""Expiry payoff and premium-aware P&L helpers."""
from typing import Iterable
from .models import OptionLeg, OptionType


def expiry_payoff(legs: Iterable[OptionLeg], spot_at_expiry: float, lot_size: int = 1) -> float:
    """Return net expiry P&L in currency, including entry premium, before fees."""
    if spot_at_expiry < 0:
        raise ValueError("spot_at_expiry cannot be negative")
    if lot_size < 1:
        raise ValueError("lot_size must be >= 1")
    pnl = 0.0
    for leg in legs:
        intrinsic = (max(spot_at_expiry - leg.strike, 0.0)
                     if leg.option_type == OptionType.CALL
                     else max(leg.strike - spot_at_expiry, 0.0))
        pnl += leg.quantity * lot_size * (intrinsic - leg.premium)
    return pnl


def premium_cashflow(legs: Iterable[OptionLeg], lot_size: int = 1) -> float:
    """Entry cashflow: negative means debit, positive means credit."""
    if lot_size < 1:
        raise ValueError("lot_size must be >= 1")
    return -sum(leg.quantity * leg.premium * lot_size for leg in legs)
