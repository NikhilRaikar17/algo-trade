import pytest
import requests

import dhan_auth


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    dhan_auth._validity_cache.clear()
    monkeypatch.setenv("DHAN_TOKEN_ID", "header.payload.sig")


def test_valid_token_reads_dhan_expiry(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, {"tokenValidity": "28/10/2026 08:38"}))
    v = dhan_auth.fetch_token_validity()
    assert (v.day, v.hour, v.minute) == (28, 8, 38) and dhan_auth.last_validity_error is None


def test_rejected_token_is_reported_as_rejected(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(401, {"errorCode": "DH-901"}))
    assert dhan_auth.fetch_token_validity() is None and dhan_auth.last_validity_error == "rejected"


def test_network_failure_is_unreachable_and_not_cached(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "get", boom)
    assert dhan_auth.fetch_token_validity() is None and dhan_auth.last_validity_error == "unreachable"
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, {"tokenValidity": "28/10/2026 08:38"}))
    assert dhan_auth.fetch_token_validity() is not None   # the next check retries
