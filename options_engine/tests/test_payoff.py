import pytest
from options_engine.models import OptionLeg, OptionType
from options_engine.payoff import expiry_payoff
from options_engine.strategies import bull_call_spread, iron_condor, long_call


def test_long_call_expiry_profit_after_premium():
    leg = OptionLeg("NIFTY-CE", OptionType.CALL, 100, 1, 10)
    assert expiry_payoff([leg], 120, lot_size=2) == 20


def test_long_call_max_loss_is_premium():
    strategy = long_call("NIFTY-CE", 100, 10)
    assert expiry_payoff(strategy.legs, 90) == -10
    assert strategy.max_loss_per_unit == 10


def test_bull_call_spread_bounded_loss():
    strategy = bull_call_spread("long", "short", 100, 110, 12, 5)
    assert strategy.max_loss_per_unit == 7
    assert expiry_payoff(strategy.legs, 90) == -7
    assert expiry_payoff(strategy.legs, 120) == 3


def test_iron_condor_rejects_invalid_strike_order():
    with pytest.raises(ValueError):
        iron_condor("lp", "sp", "sc", "lc", 90, 100, 95, 110, 1, 5, 5, 1)


def test_negative_spot_rejected():
    with pytest.raises(ValueError):
        expiry_payoff([OptionLeg("x", OptionType.PUT, 100, 1, 5)], -1)
