"""Tests for global_feed: yfinance fetching, state writes, error resilience."""
import asyncio
import pandas as pd
import pytest
import state


@pytest.fixture(autouse=True)
def reset_global_state():
    state._global_prices.clear()
    yield
    state._global_prices.clear()


def _make_yf_df(symbols: list[str], price: float = 100.0, prev: float = 99.0) -> pd.DataFrame:
    """Build a minimal yfinance-style DataFrame (2-day close prices)."""
    dates = pd.to_datetime(["2026-04-14", "2026-04-15"])
    close_data = {sym: [prev, price] for sym in symbols}
    df = pd.DataFrame(close_data, index=dates)
    df.columns = pd.MultiIndex.from_tuples([("Close", sym) for sym in symbols])
    return df


def test_fetch_global_writes_to_state(mocker):
    """After _fetch_and_store(), state._global_prices should have data."""
    from global_feed import _fetch_and_store, SYMBOLS

    mock_df = _make_yf_df(list(SYMBOLS.keys())[:3], price=100.0, prev=98.0)
    mocker.patch("global_feed.yf.download", return_value=mock_df)

    _fetch_and_store()

    stored = state.get_all_global_prices()
    # At least the symbols present in mock_df should be stored
    assert len(stored) >= 1
    first_key = list(stored.keys())[0]
    entry = stored[first_key]
    assert "name" in entry
    assert "price" in entry
    assert "change_pct" in entry
    assert "flag" in entry


def test_fetch_global_computes_change_pct(mocker):
    """change_pct should be (price - prev) / prev * 100."""
    from global_feed import _fetch_and_store

    mock_df = _make_yf_df(["^GSPC"], price=5200.0, prev=5000.0)
    mocker.patch("global_feed.yf.download", return_value=mock_df)

    _fetch_and_store()

    entry = state.get_all_global_prices().get("^GSPC")
    assert entry is not None
    assert entry["change_pct"] == pytest.approx(4.0, abs=0.01)


def test_fetch_global_skips_failed_symbol(mocker):
    """If yfinance returns NaN for a symbol, it should be silently skipped."""
    from global_feed import _fetch_and_store

    dates = pd.to_datetime(["2026-04-14", "2026-04-15"])
    df = pd.DataFrame(
        {("Close", "^GSPC"): [float("nan"), float("nan")]},
        index=dates,
    )
    mocker.patch("global_feed.yf.download", return_value=df)  # use df, not mock_df

    _fetch_and_store()  # should not raise

    stored = state.get_all_global_prices()
    assert "^GSPC" not in stored


def test_fetch_global_handles_download_exception(mocker):
    """If yfinance.download() raises, _fetch_and_store should not propagate."""
    from global_feed import _fetch_and_store
    mocker.patch("global_feed.yf.download", side_effect=Exception("network error"))

    _fetch_and_store()  # should not raise

    assert state.get_all_global_prices() == {}


@pytest.mark.asyncio
async def test_start_global_feed_loops(mocker):
    """start_global_feed should call _fetch_and_store repeatedly."""
    from global_feed import start_global_feed

    calls = []
    def fake_fetch():
        calls.append(1)

    mocker.patch("global_feed._fetch_and_store", side_effect=fake_fetch)

    sleep_count = [0]
    async def fake_sleep(n):
        sleep_count[0] += 1
        if sleep_count[0] >= 2:
            raise asyncio.CancelledError()

    mocker.patch("global_feed.asyncio.sleep", side_effect=fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await start_global_feed()

    assert len(calls) >= 1
