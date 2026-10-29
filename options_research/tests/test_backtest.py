import pandas as pd
import pytest

from options_research.backtest import mark_to_market_pnl, prices_at, validate_price_history
from options_research.models import OptionLeg, OptionType


def test_prices_at_requires_exact_contract_and_timestamp():
    frame = pd.DataFrame([
        {"timestamp": "2026-01-01 10:00", "contract_id": "CE", "close": 100.0},
        {"timestamp": "2026-01-01 10:01", "contract_id": "CE", "close": 101.0},
    ])
    assert prices_at(frame, "2026-01-01 10:00", {"CE"}) == {"CE": 100.0}
    with pytest.raises(KeyError, match="missing exact prices"):
        prices_at(frame, "2026-01-01 10:00", {"PE"})


def test_duplicate_contract_timestamp_rejected():
    frame = pd.DataFrame([
        {"timestamp": "2026-01-01", "contract_id": "CE", "close": 10},
        {"timestamp": "2026-01-01", "contract_id": "CE", "close": 11},
    ])
    with pytest.raises(ValueError, match="duplicate"):
        validate_price_history(frame)


def test_mark_to_market_handles_short_legs():
    legs = [
        OptionLeg("CE", OptionType.CALL, 100, 1, 10),
        OptionLeg("PE", OptionType.PUT, 100, -1, 8),
    ]
    assert mark_to_market_pnl(legs, {"CE": 14, "PE": 5}, lot_size=2) == 14
