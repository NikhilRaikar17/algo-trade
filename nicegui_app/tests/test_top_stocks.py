"""Top Stocks: today's change from Dhan's bulk quote payload."""

from pages.top_stocks import quote_changes

UNIVERSE = [{"name": "RELIANCE", "security_id": "2885"}, {"name": "JPL", "security_id": "766830"},
            {"name": "NOPRICE", "security_id": "1"}]


def test_quote_changes_is_vs_the_official_previous_close():
    quotes = {
        "2885":   {"last_price": 1171.6, "ohlc": {"open": 1159, "close": 1158, "high": 1182.1, "low": 1155.6}},
        "766830": {"last_price": 1400.0, "ohlc": {"open": 1410, "close": 1417.5, "high": 1395, "low": 1405}},
        "1":      {"last_price": 0, "ohlc": {"close": 100}},
    }
    rows = {r["name"]: r["data"] for r in quote_changes(quotes, UNIVERSE)}
    assert set(rows) == {"RELIANCE", "JPL"}                       # no last price yet → left out
    assert rows["RELIANCE"]["change"] == 13.6
    assert rows["RELIANCE"]["change_pct"] == 1.17
    assert rows["RELIANCE"]["is_green"] is True
    assert rows["JPL"]["change_pct"] == -1.23 and rows["JPL"]["is_green"] is False
    assert rows["JPL"]["high"] == 1400 and rows["JPL"]["low"] == 1400   # a stale range is widened to the last price
