"""Small, validated domain models for option strategy research."""
from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class OptionType(str, Enum):
    CALL = "CE"
    PUT = "PE"


@dataclass(frozen=True)
class OptionLeg:
    contract_id: str
    option_type: OptionType
    strike: float
    quantity: int  # positive = long, negative = short; in lots
    premium: float  # premium per unit at entry

    def __post_init__(self) -> None:
        if not self.contract_id.strip():
            raise ValueError("contract_id cannot be empty")
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        if self.quantity == 0:
            raise ValueError("quantity cannot be zero")
        if self.premium < 0:
            raise ValueError("premium cannot be negative")


@dataclass(frozen=True)
class StrategyDefinition:
    name: str
    description: str
    legs: Sequence[OptionLeg]
    max_loss_per_unit: float | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("strategy name cannot be empty")
        if not self.legs:
            raise ValueError("a strategy must contain at least one leg")
