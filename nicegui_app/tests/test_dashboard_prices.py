"""Tests for dashboard price helper functions."""
import pandas as pd
import pytest

from pages.dashboard import _compute_synthetic_futures


def _make_chain(strike: int, ce_ltp: float, pe_ltp: float) -> pd.DataFrame:
    return pd.DataFrame([
        {"Strike": strike, "Type": "CE", "LTP": ce_ltp},
        {"Strike": strike, "Type": "PE", "LTP": pe_ltp},
    ])


def test_synthetic_futures_basic():
    """Futures = ATM + CE_LTP - PE_LTP (put-call parity)."""
    df = _make_chain(22500, ce_ltp=200.0, pe_ltp=150.0)
    result = _compute_synthetic_futures(spot=22480.0, df=df, strike_step=50)
    # ATM = round(22480/50)*50 = 22500
    assert result == pytest.approx(22500 + 200.0 - 150.0, abs=0.01)


def test_synthetic_futures_none_spot():
    """Returns None when spot is None."""
    df = _make_chain(22500, 200.0, 150.0)
    assert _compute_synthetic_futures(spot=None, df=df, strike_step=50) is None


def test_synthetic_futures_empty_df():
    """Returns None for empty DataFrame."""
    assert _compute_synthetic_futures(spot=22480.0, df=pd.DataFrame(), strike_step=50) is None


def test_synthetic_futures_none_df():
    """Returns None when df is None."""
    assert _compute_synthetic_futures(spot=22480.0, df=None, strike_step=50) is None


def test_synthetic_futures_missing_ce():
    """Returns None when CE row is missing for ATM."""
    df = pd.DataFrame([{"Strike": 22500, "Type": "PE", "LTP": 150.0}])
    assert _compute_synthetic_futures(spot=22480.0, df=df, strike_step=50) is None


def test_synthetic_futures_missing_pe():
    """Returns None when PE row is missing for ATM."""
    df = pd.DataFrame([{"Strike": 22500, "Type": "CE", "LTP": 200.0}])
    assert _compute_synthetic_futures(spot=22480.0, df=df, strike_step=50) is None
