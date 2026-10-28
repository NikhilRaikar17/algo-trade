"""Starter strategy templates; these describe legs, not entry signals."""
from .models import OptionLeg, OptionType, StrategyDefinition


def long_call(contract_id: str, strike: float, premium: float) -> StrategyDefinition:
    return StrategyDefinition("long_call", "Long call; bullish, premium at risk.",
        [OptionLeg(contract_id, OptionType.CALL, strike, 1, premium)],
        max_loss_per_unit=premium)


def bull_call_spread(long_id: str, short_id: str, lower_strike: float,
                     upper_strike: float, long_premium: float,
                     short_premium: float) -> StrategyDefinition:
    if lower_strike >= upper_strike:
        raise ValueError("bull call spread requires lower_strike < upper_strike")
    debit = long_premium - short_premium
    if debit < 0:
        raise ValueError("initial implementation expects a debit bull call spread")
    return StrategyDefinition("bull_call_spread", "Defined-risk bullish call debit spread.",
        [OptionLeg(long_id, OptionType.CALL, lower_strike, 1, long_premium),
         OptionLeg(short_id, OptionType.CALL, upper_strike, -1, short_premium)],
        max_loss_per_unit=debit)


def bull_put_spread(short_id: str, long_id: str, lower_strike: float,
                    upper_strike: float, short_premium: float,
                    long_premium: float) -> StrategyDefinition:
    if lower_strike >= upper_strike:
        raise ValueError("bull put spread requires lower_strike < upper_strike")
    credit = short_premium - long_premium
    if credit < 0:
        raise ValueError("initial implementation expects a credit bull put spread")
    return StrategyDefinition("bull_put_spread", "Defined-risk bullish put credit spread.",
        [OptionLeg(short_id, OptionType.PUT, upper_strike, -1, short_premium),
         OptionLeg(long_id, OptionType.PUT, lower_strike, 1, long_premium)],
        max_loss_per_unit=(upper_strike - lower_strike) - credit)


def long_straddle(call_id: str, put_id: str, strike: float,
                  call_premium: float, put_premium: float) -> StrategyDefinition:
    return StrategyDefinition("long_straddle", "Long call and put at same strike; long volatility.",
        [OptionLeg(call_id, OptionType.CALL, strike, 1, call_premium),
         OptionLeg(put_id, OptionType.PUT, strike, 1, put_premium)],
        max_loss_per_unit=call_premium + put_premium)


def iron_condor(long_put_id: str, short_put_id: str, short_call_id: str,
                long_call_id: str, put_wing: float, short_put: float,
                short_call: float, call_wing: float, lp: float, sp: float,
                sc: float, lc: float) -> StrategyDefinition:
    if not put_wing < short_put < short_call < call_wing:
        raise ValueError("iron condor strikes must satisfy put_wing < short_put < short_call < call_wing")
    credit = sp + sc - lp - lc
    if credit < 0:
        raise ValueError("initial implementation expects a net credit iron condor")
    wing_width = max(short_put - put_wing, call_wing - short_call)
    return StrategyDefinition("iron_condor", "Defined-risk, range-bound four-leg credit spread.",
        [OptionLeg(long_put_id, OptionType.PUT, put_wing, 1, lp),
         OptionLeg(short_put_id, OptionType.PUT, short_put, -1, sp),
         OptionLeg(short_call_id, OptionType.CALL, short_call, -1, sc),
         OptionLeg(long_call_id, OptionType.CALL, call_wing, 1, lc)],
        max_loss_per_unit=wing_width - credit)
