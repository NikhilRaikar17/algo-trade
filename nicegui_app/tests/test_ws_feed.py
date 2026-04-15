"""Tests for ws_feed: state writes on tick, reconnect logic, WS health flag."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import state


@pytest.fixture(autouse=True)
def reset_state():
    """Reset live price state before each test."""
    state._live_prices.clear()
    state._ws_connected = False
    yield
    state._live_prices.clear()
    state._ws_connected = False


def test_on_tick_writes_nifty_to_state():
    """A NIFTY tick should update state._live_prices["NIFTY"]."""
    from ws_feed import _on_tick
    tick = {
        "security_id": "13",
        "LTP": 22500.5,
        "prev_close": 22300.0,
    }
    _on_tick(tick)
    entry = state.get_live_price("NIFTY")
    assert entry is not None
    assert entry["ltp"] == 22500.5
    assert entry["change"] == pytest.approx(200.5, abs=0.1)
    assert entry["change_pct"] == pytest.approx(0.9, abs=0.1)


def test_on_tick_writes_banknifty_to_state():
    """A BANKNIFTY tick should update state._live_prices["BANKNIFTY"]."""
    from ws_feed import _on_tick
    tick = {
        "security_id": "25",
        "LTP": 48000.0,
        "prev_close": 47500.0,
    }
    _on_tick(tick)
    entry = state.get_live_price("BANKNIFTY")
    assert entry is not None
    assert entry["ltp"] == 48000.0


def test_on_tick_writes_vix_to_state():
    """A VIX tick should update state._live_prices["VIX"]."""
    from ws_feed import _on_tick
    tick = {
        "security_id": "234613",
        "LTP": 14.5,
        "prev_close": 14.0,
    }
    _on_tick(tick)
    entry = state.get_live_price("VIX")
    assert entry is not None
    assert entry["ltp"] == 14.5


def test_on_tick_sets_ws_connected_true():
    """Any valid tick should set _ws_connected = True."""
    from ws_feed import _on_tick
    tick = {"security_id": "13", "LTP": 22000.0, "prev_close": 21900.0}
    _on_tick(tick)
    assert state._ws_connected is True


def test_on_tick_unknown_security_ignored():
    """Ticks for unknown security IDs should not raise and not pollute state."""
    from ws_feed import _on_tick
    _on_tick({"security_id": "9999", "LTP": 100.0, "prev_close": 99.0})
    assert state._live_prices == {}


def test_on_tick_missing_ltp_ignored():
    """A tick missing 'LTP' key should not raise."""
    from ws_feed import _on_tick
    _on_tick({"security_id": "13"})  # no LTP
    assert state.get_live_price("NIFTY") is None


@pytest.mark.asyncio
async def test_start_ws_feed_sets_disconnected_on_exception(mocker):
    """When DhanFeed raises, _ws_connected should be set to False."""
    mock_feed_cls = mocker.patch("ws_feed.DhanFeed")
    mock_feed = MagicMock()
    mock_feed.run_forever.side_effect = Exception("connection refused")
    mock_feed_cls.return_value = mock_feed

    # Patch sleep so the reconnect loop exits quickly
    sleep_calls = []
    async def fake_sleep(n):
        sleep_calls.append(n)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError()
    mocker.patch("ws_feed.asyncio.sleep", side_effect=fake_sleep)

    from ws_feed import start_ws_feed
    with pytest.raises(asyncio.CancelledError):
        await start_ws_feed()

    assert state._ws_connected is False
