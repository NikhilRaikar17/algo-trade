import pytest
from options_research.risk import RiskLimits, validate_trade_risk


def test_risk_limit_rejects_oversized_trade():
    limits = RiskLimits(max_loss_per_trade=5000, max_daily_loss=10000)
    with pytest.raises(ValueError, match="max_loss_per_trade"):
        validate_trade_risk(6000, limits)


def test_unbounded_trade_rejected():
    limits = RiskLimits(max_loss_per_trade=5000, max_daily_loss=10000)
    with pytest.raises(ValueError, match="bounded"):
        validate_trade_risk(None, limits)


def test_naked_short_rejected_by_default():
    limits = RiskLimits(max_loss_per_trade=5000, max_daily_loss=10000)
    with pytest.raises(ValueError, match="disabled"):
        validate_trade_risk(1000, limits, has_naked_short=True)
