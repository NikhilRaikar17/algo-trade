"""Fail-closed risk guardrails for research/backtest workflows."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    max_loss_per_trade: float
    max_daily_loss: float
    max_open_positions: int = 1
    allow_naked_short_options: bool = False

    def __post_init__(self) -> None:
        if self.max_loss_per_trade <= 0 or self.max_daily_loss <= 0:
            raise ValueError("loss limits must be positive")
        if self.max_open_positions < 1:
            raise ValueError("max_open_positions must be >= 1")


def validate_trade_risk(estimated_max_loss: float | None, limits: RiskLimits,
                        has_naked_short: bool = False) -> None:
    if has_naked_short and not limits.allow_naked_short_options:
        raise ValueError("naked short options are disabled by default")
    if estimated_max_loss is None:
        raise ValueError("trade risk must be bounded before entry")
    if estimated_max_loss < 0:
        raise ValueError("estimated_max_loss cannot be negative")
    if estimated_max_loss > limits.max_loss_per_trade:
        raise ValueError("trade exceeds max_loss_per_trade")
