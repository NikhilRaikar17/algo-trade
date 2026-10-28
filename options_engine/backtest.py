"""Small fail-closed primitives for historical option-price research."""
from __future__ import annotations

import pandas as pd

from .models import OptionLeg


_REQUIRED = {"timestamp", "contract_id", "close"}


def validate_price_history(prices: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize a historical option-price table without filling gaps."""
    missing = _REQUIRED.difference(prices.columns)
    if missing:
        raise ValueError("missing price-history columns: " + ", ".join(sorted(missing)))
    out = prices.loc[:, ["timestamp", "contract_id", "close"]].copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="raise")
    out["contract_id"] = out["contract_id"].astype(str)
    out["close"] = pd.to_numeric(out["close"], errors="raise")
    if out[["timestamp", "contract_id", "close"]].isna().any().any():
        raise ValueError("price history contains null timestamps, contracts or prices")
    if (out["close"] < 0).any():
        raise ValueError("option prices cannot be negative")
    if out.duplicated(["timestamp", "contract_id"]).any():
        raise ValueError("duplicate timestamp/contract rows are ambiguous")
    return out.sort_values(["timestamp", "contract_id"]).reset_index(drop=True)


def prices_at(prices: pd.DataFrame, timestamp: object, contract_ids: set[str]) -> dict[str, float]:
    """Return exact timestamp prices; missing contracts raise instead of stale filling."""
    history = validate_price_history(prices)
    ts = pd.Timestamp(timestamp)
    rows = history.loc[(history["timestamp"] == ts) & history["contract_id"].isin(contract_ids)]
    found = dict(zip(rows["contract_id"], rows["close"], strict=True))
    missing = contract_ids.difference(found)
    if missing:
        raise KeyError(f"missing exact prices at {ts}: {', '.join(sorted(missing))}")
    return {key: float(value) for key, value in found.items()}


def mark_to_market_pnl(legs: list[OptionLeg], exit_prices: dict[str, float],
                       lot_size: int = 1) -> float:
    """Gross P&L from entry premiums to exit prices, before costs/slippage."""
    if lot_size < 1:
        raise ValueError("lot_size must be >= 1")
    missing = {leg.contract_id for leg in legs}.difference(exit_prices)
    if missing:
        raise KeyError("missing exit prices: " + ", ".join(sorted(missing)))
    return sum(
        leg.quantity * lot_size * (exit_prices[leg.contract_id] - leg.premium)
        for leg in legs
    )
