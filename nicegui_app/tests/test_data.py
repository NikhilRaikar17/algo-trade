"""Tests for data.py: expiry parsing, API health check, cache behavior."""

import pytest


# ── check_dhan_api ───────────────────────────────────────────────────────────

def test_check_dhan_api_ok(mocker):
    mocker.patch("data.dhan.expiry_list", return_value={
        "status": "success",
        "data": ["2026-03-27", "2026-04-03"],
    })
    from data import check_dhan_api
    result = check_dhan_api()
    assert result["ok"] is True
    assert result["error"] is None
    assert isinstance(result["latency_ms"], int)


def test_check_dhan_api_error(mocker):
    mocker.patch("data.dhan.expiry_list", return_value={
        "status": "failure",
        "remarks": "Token expired",
    })
    from data import check_dhan_api
    result = check_dhan_api()
    assert result["ok"] is False
    assert result["error"] is not None


def test_check_dhan_api_exception(mocker):
    mocker.patch("data.dhan.expiry_list", side_effect=ConnectionError("timeout"))
    from data import check_dhan_api
    result = check_dhan_api()
    assert result["ok"] is False
    assert "timeout" in result["error"]


# ── get_expiries ─────────────────────────────────────────────────────────────

def test_get_expiries_parses_response(mocker):
    mocker.patch("data.dhan.expiry_list", return_value={
        "status": "success",
        "data": ["2026-03-27", "2026-04-03", "2026-04-10"],
    })
    mocker.patch("data._cache_get", return_value=None)
    mocker.patch("data._cache_set")
    import pytz
    from datetime import datetime
    IST = pytz.timezone("Asia/Kolkata")
    mocker.patch("data.now_ist", return_value=IST.localize(datetime(2026, 3, 10, 10, 0)))

    from data import get_expiries
    result = get_expiries("13", "IDX_I", count=2)
    assert len(result) == 2


def test_get_expiries_raises_on_error(mocker):
    mocker.patch("data.dhan.expiry_list", return_value={
        "status": "failure",
        "remarks": "Invalid token",
    })
    mocker.patch("data._cache_get", return_value=None)

    from data import get_expiries
    with pytest.raises(RuntimeError, match="expiry_list failed"):
        get_expiries("13", "IDX_I")


def test_get_expiries_uses_cache(mocker):
    cached = ["2026-03-27", "2026-04-03", "2026-04-10"]
    mocker.patch("data._cache_get", return_value=cached)
    mock_api = mocker.patch("data.dhan.expiry_list")

    from data import get_expiries
    result = get_expiries("13", "IDX_I", count=2)

    mock_api.assert_not_called()
    assert len(result) == 2


# ── nifty50_stocks ───────────────────────────────────────────────────────────

def _index(n=50):
    return [{"Symbol": f"S{i}", "ISIN Code": f"INE{i:05d}"} for i in range(n)]


def _instruments(n=50, **override):
    rows = [{"INSTRUMENT": "EQUITY", "SERIES": "EQ", "ISIN": f"INE{i:05d}",
             "UNDERLYING_SYMBOL": f"S{i}", "SECURITY_ID": str(1000 + i)} for i in range(n)]
    rows[0].update(override)
    return rows


def test_map_nifty50_matches_on_isin():
    from data import map_nifty50
    stocks = map_nifty50(_index(), _instruments() + [
        {"INSTRUMENT": "EQUITY", "SERIES": "BE", "ISIN": "INE00000", "UNDERLYING_SYMBOL": "S0", "SECURITY_ID": "9"},
    ])
    assert stocks[0] == {"name": "S0", "security_id": "1000"}   # the BE-series row is ignored
    assert len(stocks) == 50


@pytest.mark.parametrize("override", [{"UNDERLYING_SYMBOL": "OTHER"}, {"ISIN": "INE99999"}])
def test_map_nifty50_rejects_a_symbol_it_cannot_match_exactly(override):
    from data import map_nifty50
    with pytest.raises(ValueError, match="S0"):
        map_nifty50(_index(), _instruments(**override))


def test_map_nifty50_rejects_a_list_that_is_not_50():
    from data import map_nifty50
    with pytest.raises(ValueError, match="49"):
        map_nifty50(_index(49), _instruments(49))


@pytest.fixture
def nifty50(mocker, tmp_path):
    import data
    mocker.patch.object(data, "_NIFTY50_FILE", str(tmp_path / ".nifty50.json"))
    mocker.patch.dict(data._nifty50, {"day": None, "list": [], "retry_at": 0.0})
    return data


def test_nifty50_downloads_once_a_day_and_saves(nifty50, mocker):
    fresh = [{"name": "JPL", "security_id": "766830"}]
    dl = mocker.patch.object(nifty50, "_download_nifty50", return_value=fresh)
    assert nifty50.nifty50_stocks() == fresh
    assert nifty50.nifty50_stocks() == fresh
    assert dl.call_count == 1
    nifty50._nifty50.update(day=None)          # a restart the same day reads the file
    assert nifty50.nifty50_stocks() == fresh
    assert dl.call_count == 1


def test_nifty50_falls_back_to_saved_then_builtin_list(nifty50, mocker):
    import json
    mocker.patch.object(nifty50, "_download_nifty50", side_effect=OSError("offline"))
    assert nifty50.nifty50_stocks() == nifty50.NIFTY50_STOCKS

    saved = [{"name": "OLD", "security_id": "1"}]
    with open(nifty50._NIFTY50_FILE, "w") as f:
        json.dump({"day": "2000-01-01", "list": saved}, f)
    nifty50._nifty50.update(retry_at=0.0)
    assert nifty50.nifty50_stocks() == saved
