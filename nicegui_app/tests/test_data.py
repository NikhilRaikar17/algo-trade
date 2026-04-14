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
