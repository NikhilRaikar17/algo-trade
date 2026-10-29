"""The opt_* payoff templates never reach the stock backtests or the live engines."""

import strategy_registry


def test_options_templates_stay_out_of_backtest_and_live_even_if_flagged(mocker):
    mocker.patch.object(strategy_registry, "get_strategy_rows", return_value=[
        {"key": "ema10", "short_name": "EMA10", "backtest_enabled": True, "live_enabled": True,
         "options_pnl_enabled": False},
        {"key": "opt_iron_condor", "short_name": "Options · Iron Condor", "backtest_enabled": True,
         "live_enabled": True, "options_pnl_enabled": True},
    ])
    assert strategy_registry.get_live_strategy_keys() == ["ema10"]
    assert strategy_registry.get_backtest_strategy_keys() == ["ema10"]
    assert strategy_registry.get_backtest_strategy_names() == ["EMA10"]
    assert strategy_registry.get_options_pnl_strategy_keys() == ["opt_iron_condor"]
