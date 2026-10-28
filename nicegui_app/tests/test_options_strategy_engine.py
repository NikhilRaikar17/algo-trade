"""Unit tests for the NiceGUI options expiry-payoff engine."""
import unittest

from nicegui_app.options_strategy_engine import build_strategy


def build(key, **overrides):
    args = dict(
        strike=100, lower_strike=95, upper_strike=105, spot=100,
        premium=8, long_premium=8, short_premium=3,
        call_premium=8, put_premium=7, put_wing=90, put_wing_premium=1,
        short_put_premium=4, short_call_premium=4, call_wing=110,
        call_wing_premium=1,
    )
    args.update(overrides)
    return build_strategy(key, **args)


class OptionsStrategyPayoffTests(unittest.TestCase):
    def test_long_call_max_loss_is_premium(self):
        strategy = build("opt_long_call")
        self.assertEqual(strategy.payoff(80), -8)
        self.assertEqual(strategy.payoff(120), 12)

    def test_bull_call_spread_defined_payoff(self):
        strategy = build("opt_bull_call_spread")
        self.assertEqual(strategy.payoff(90), -5)
        self.assertEqual(strategy.payoff(110), 5)

    def test_bull_put_spread_defined_payoff(self):
        strategy = build("opt_bull_put_spread", long_premium=3, short_premium=8)
        self.assertEqual(strategy.payoff(90), -5)
        self.assertEqual(strategy.payoff(110), 5)

    def test_straddle_cost_is_sum_of_premiums(self):
        strategy = build("opt_long_straddle")
        self.assertEqual(strategy.payoff(100), -15)

    def test_iron_condor_credit_and_defined_wings(self):
        strategy = build("opt_iron_condor", short_put_premium=2.5, short_call_premium=2.5)
        self.assertEqual(strategy.payoff(100), 3)
        self.assertEqual(strategy.payoff(80), -2)
        self.assertEqual(strategy.payoff(120), -2)

    def test_invalid_iron_condor_ordering_rejected(self):
        with self.assertRaises(ValueError):
            build("opt_iron_condor", put_wing=96, lower_strike=95)


if __name__ == "__main__":
    unittest.main()
