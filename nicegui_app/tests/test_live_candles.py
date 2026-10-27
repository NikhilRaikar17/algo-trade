"""5-minute bars built from websocket ticks, seeded from REST, and the engine reading them."""

import pandas as pd
import pytest

import live_candles as lc

IST = "Asia/Kolkata"


def _at(hhmmss, day="2026-10-28"):
    return pd.Timestamp(f"{day} {hhmmss}", tz=IST).to_pydatetime()


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(lc, "_bars", {})
    monkeypatch.setattr(lc, "_seeded", {})
    monkeypatch.setattr(lc, "_last", {})
    monkeypatch.setattr(lc, "_history", {})


def test_ticks_build_bars_and_only_finished_bars_are_returned():
    for t, p in (("10:00:01", 100), ("10:02:00", 103), ("10:04:59", 99), ("10:05:10", 101), ("10:06:00", 102)):
        lc.on_tick("1", p, _at(t))
    done = lc.candles("1", now=_at("10:07:00"))
    assert len(done) == 1
    assert done.iloc[0][["open", "high", "low", "close"]].tolist() == [100, 103, 99, 99]
    assert done.iloc[0]["timestamp"] == pd.Timestamp("2026-10-28 10:00", tz=IST)
    forming = lc.candles("1", now=_at("10:07:00"), forming=True)
    assert forming.iloc[-1][["open", "high", "close"]].tolist() == [101, 102, 102]
    assert len(lc.candles("1", now=_at("10:10:00"))) == 2                  # 10:05 bar closed at 10:10
    assert lc.last_price("1", now=_at("10:06:30")) == 102
    assert lc.last_price("1", now=_at("10:09:00")) is None                  # older than 90 s


def test_ticks_outside_market_hours_make_no_bars():
    lc.on_tick("1", 100, _at("09:10:00"))
    lc.on_tick("1", 101, _at("15:31:00"))
    assert lc.candles("1", now=_at("15:40:00"), forming=True).empty


def test_seed_fills_earlier_bars_and_keeps_the_live_forming_bar():
    lc.on_tick("1", 105, _at("10:01:00"))
    lc.on_tick("1", 107, _at("10:02:00"))
    rest = pd.DataFrame({"timestamp": [pd.Timestamp(f"2026-10-28 {t}", tz=IST) for t in ("09:50", "09:55", "10:00")],
                         "open": [100, 101, 104], "high": [102, 103, 108], "low": [99, 100, 103],
                         "close": [101, 104, 106]})
    rest.loc[3] = [pd.Timestamp("2026-10-27 15:25", tz=IST), 1, 1, 1, 1]  # yesterday: ignored
    lc.seed("1", rest, now=_at("10:02:30"))
    bars = lc.candles("1", now=_at("10:02:30"), forming=True)
    assert bars["timestamp"].dt.strftime("%H:%M").tolist() == ["09:50", "09:55", "10:00"]
    assert bars.iloc[-1][["open", "high", "low", "close"]].tolist() == [104, 108, 103, 107]


def test_needs_seed_until_seeded_today_and_again_when_ticks_stop():
    assert lc.needs_seed("1", now=_at("10:00:00"))
    lc.seed("1", pd.DataFrame(), now=_at("10:00:00"))
    lc.on_tick("1", 100, _at("10:00:05"))
    assert not lc.needs_seed("1", now=_at("10:01:00"))
    assert not lc.needs_seed("1", now=_at("10:03:00"))                     # quiet, but seeded 3 min ago
    assert lc.needs_seed("1", now=_at("10:05:00"))                         # quiet and seeded 5 min ago
    assert lc.needs_seed("1", now=_at("10:00:00", day="2026-10-29"))       # a new day


def test_engine_seeds_once_then_reads_the_feed(monkeypatch):
    import trading_engine
    calls = []
    rest = pd.DataFrame({"timestamp": [pd.Timestamp("2026-10-28 09:15", tz=IST)],
                         "open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5]})
    monkeypatch.setattr(trading_engine, "_fetch_any_stock_candles", lambda sid, **k: calls.append(sid) or rest)
    monkeypatch.setattr(trading_engine.time, "sleep", lambda s: None)
    now = _at("09:22:00")
    monkeypatch.setattr(lc, "now_ist", lambda: now)
    assert len(trading_engine.feed_candles("9")) == 1 and calls == ["9"]
    lc.on_tick("9", 1.7, _at("09:21:00"))
    now = _at("09:25:01")
    assert len(trading_engine.feed_candles("9")) == 2 and calls == ["9"]     # 09:20 bar from ticks, no REST


def test_engine_wakes_just_after_each_bar_closes():
    import trading_engine
    assert trading_engine._seconds_to_next_bar(_at("10:03:30")) == pytest.approx(92)
    assert trading_engine._seconds_to_next_bar(_at("10:05:00")) == pytest.approx(302)
