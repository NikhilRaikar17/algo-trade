"""Paper-traded options templates: entry rules on the index's 15-min bars, legs from the option chain,
the net-premium plan, and booking / closing a multi-leg position in the options account."""

import pandas as pd
import pytest

import account
import live_candles
import options_templates as ot
from config import OPTIONS_LIMITS, OPTIONS_TEMPLATES
from trade_desk import SKIPPED, TAKEN

IST = "Asia/Kolkata"
LIMITS = dict(OPTIONS_LIMITS, funds=200_000, max_loss_per_trade=5_000, max_capital_pct=50, min_reward_risk=1.0,
              max_daily_loss=10_000, max_losing_streak=3, square_off="15:20")


def _at(hhmm, day="2026-10-29"):
    return pd.Timestamp(f"{day} {hhmm}", tz=IST).to_pydatetime()


def _bars(*ohlc, day="2026-10-29"):
    """15-min bars from 09:15, one (open, high, low, close) each."""
    start = pd.Timestamp(f"{day} 09:15", tz=IST)
    return pd.DataFrame([{"timestamp": start + pd.Timedelta(minutes=15 * i), "open": o, "high": h, "low": lo,
                          "close": c} for i, (o, h, lo, c) in enumerate(ohlc)])


# ── entry rules ───────────────────────────────────────────────────────────────

def test_only_finished_bars_of_today_count():
    bars = pd.concat([_bars((1, 2, 0, 1), day="2026-10-28"), _bars((1, 2, 0, 1), (1, 2, 0, 1), (1, 2, 0, 1))])
    assert len(ot.finished_bars(bars, _at("09:45"))) == 2   # the 09:45 bar is still forming


def test_breakout_fires_on_a_close_above_the_opening_range_high():
    cfg = OPTIONS_TEMPLATES["opt_long_call"]
    fired, why = ot.entry_trigger(cfg, _bars((100, 110, 95, 105), (105, 112, 104, 109)))
    assert fired is None and "110.00" in why
    fired, _ = ot.entry_trigger(cfg, _bars((100, 110, 95, 105), (105, 112, 104, 109), (109, 115, 108, 111)))
    assert fired == pd.Timestamp("2026-10-29 09:45", tz=IST)


def test_squeeze_needs_a_narrow_opening_range():
    cfg = OPTIONS_TEMPLATES["opt_long_straddle"]   # max 0.35%
    assert ot.entry_trigger(cfg, _bars((25_000, 25_040, 24_990, 25_020)))[0] is not None   # 0.20%
    fired, why = ot.entry_trigger(cfg, _bars((25_000, 25_100, 24_950, 25_020)))            # 0.60%
    assert fired is None and "no squeeze" in why


def test_range_needs_a_quiet_day_back_inside_the_opening_range():
    cfg = OPTIONS_TEMPLATES["opt_iron_condor"]     # max 0.6%
    quiet = _bars((25_000, 25_050, 24_980, 25_010), (25_010, 25_060, 25_000, 25_055), (25_055, 25_070, 25_020, 25_030))
    assert ot.entry_trigger(cfg, quiet)[0] == pd.Timestamp("2026-10-29 09:45", tz=IST)
    outside = _bars((25_000, 25_050, 24_980, 25_010), (25_010, 25_080, 25_000, 25_070))
    assert "back inside" in ot.entry_trigger(cfg, outside)[1]
    wild = _bars((25_000, 25_050, 24_980, 25_010), (25_010, 25_200, 24_990, 25_020))
    assert "over 0.6%" in ot.entry_trigger(cfg, wild)[1]


# ── legs and plan ─────────────────────────────────────────────────────────────

def _chain(spot=25_010, spread=1.0, **ltp):
    """An option chain around 25,000 with every strike quoted; ltp={"25100ce": 80.0, …} overrides prices."""
    oc = {}
    for k in range(24_600, 25_450, 50):
        oc[f"{k}.000000"] = {}
        for t in ("ce", "pe"):
            p = ltp.get(f"{k}{t}", max((spot - k) if t == "ce" else (k - spot), 0) + 60.0)
            oc[f"{k}.000000"][t] = {"last_price": p, "security_id": f"{k}{t}", "top_bid_price": p - spread / 2,
                                     "top_ask_price": p + spread / 2}
    return {"last_price": spot, "oc": oc}


def test_build_legs_counts_strike_steps_from_the_atm():
    legs, why = ot.build_legs(_chain(), "NIFTY", "2026-11-09", OPTIONS_TEMPLATES["opt_iron_condor"]["legs"])
    assert why == ""
    assert [(leg["opt_type"], leg["strike"], leg["qty"]) for leg in legs] == [
        ("PE", 24_800, 1), ("PE", 24_900, -1), ("CE", 25_100, -1), ("CE", 25_200, 1)]
    assert legs[1]["symbol"] == "NIFTY 09NOV 24900 PE" and legs[1]["security_id"] == "24900pe"


def test_build_legs_refuses_a_wide_or_missing_quote():
    cfg = OPTIONS_TEMPLATES["opt_bull_call_spread"]["legs"]
    assert "spread" in ot.build_legs(_chain(spread=20.0), "NIFTY", "2026-11-09", cfg)[1]
    assert "no quote" in ot.build_legs(_chain(**{"25100ce": 0}), "NIFTY", "2026-11-09", cfg)[1]


def _legs(*spec):
    return [{"opt_type": t, "strike": float(k), "qty": q, "premium": p, "symbol": f"{k}{t}", "security_id": f"{k}{t}"}
            for t, k, q, p in spec]


def test_plan_debit_spread_caps_the_target_under_its_width():
    p = ot.plan(_legs(("CE", 25_000, 1, 120.0), ("CE", 25_100, -1, 70.0)), {"target_pct": 150, "stop_pct": 25})
    assert p == {"side": "BUY", "entry": 50.0, "target": 95.0, "stop_loss": 37.5, "cost_per_unit": 50.0}


def test_plan_long_call_target_is_not_capped():
    p = ot.plan(_legs(("CE", 25_000, 1, 100.0)), {"target_pct": 40, "stop_pct": 25})
    assert (p["side"], p["target"], p["stop_loss"]) == ("BUY", 140.0, 75.0)


def test_plan_credit_ties_up_its_max_loss():
    condor = _legs(("PE", 24_800, 1, 20.0), ("PE", 24_900, -1, 45.0), ("CE", 25_100, -1, 50.0), ("CE", 25_200, 1, 25.0))
    p = ot.plan(condor, {"target_pct": 40, "stop_pct": 30})
    assert p == {"side": "SELL", "entry": 50.0, "target": 30.0, "stop_loss": 65.0, "cost_per_unit": 50.0}
    # the position's price is what it costs to close
    assert ot.position_value(condor, [20.0, 45.0, 50.0, 25.0], "SELL") == 50.0


def test_plan_refuses_an_unhedged_short_call():
    with pytest.raises(ValueError, match="no limit"):
        ot.plan(_legs(("CE", 25_000, -1, 100.0)), {"target_pct": 40, "stop_pct": 30})


# ── booking in the options account ────────────────────────────────────────────

@pytest.fixture
def opts(tmp_path, monkeypatch):
    acct = account.OPTIONS
    monkeypatch.setattr(acct, "file", str(tmp_path / "acct.json"))
    monkeypatch.setattr(acct, "book_file", str(tmp_path / "book.json"))
    monkeypatch.setattr(acct, "limits", LIMITS)
    monkeypatch.setattr(acct, "meta", {})
    with open(acct.file, "w") as f:
        f.write('{"start": "2026-10-29T09:00:00+05:30", "initial": 200000}')
    sent = []
    monkeypatch.setattr(ot, "_send_telegram", sent.append)
    monkeypatch.setattr(ot.ws_feed, "watch", lambda *a: None)
    monkeypatch.setattr(ot, "lot_size", lambda u, e: 65)
    monkeypatch.setattr(ot, "get_expiries", lambda *a, **k: ["2026-10-29", "2026-11-03", "2026-11-09"])
    monkeypatch.setattr(ot, "fetch_option_chain_raw", lambda *a: _chain(
        **{"24800pe": 20.0, "24900pe": 45.0, "25100ce": 50.0, "25200ce": 25.0}))
    monkeypatch.setattr(ot.time, "sleep", lambda s: None)
    monkeypatch.setattr(live_candles, "_last", {})
    monkeypatch.setattr(ot, "_status", {})
    return acct, sent


def test_an_iron_condor_is_booked_as_one_credit_position_and_closed_at_its_target(opts):
    acct, sent = opts
    cfg, fired = OPTIONS_TEMPLATES["opt_iron_condor"], pd.Timestamp("2026-10-29 10:30", tz=IST)
    ot._enter("NIFTY", "opt_iron_condor", "Options · Iron Condor", cfg, fired, _at("10:46"))

    [rec] = acct.open_trades()
    assert rec["symbol"] == "NIFTY 09NOV IRON CONDOR 24800P/24900P/25100C/25200C"
    assert (rec["side"], rec["entry"], rec["target"], rec["stop_loss"]) == ("SELL", 50.0, 30.0, 65.0)
    # ₹5,000 max loss / (15 × 65 risk a lot) → 5 lots; capital is the max loss at expiry: 5 × 65 × (100 − 50)
    assert rec["qty"] == 5 * 65 and rec["capital"] == 5 * 65 * 50.0
    assert sent[0].startswith("OPTIONS NEW TRADE [Options · Iron Condor]")

    # a second firing the same day is not entered again
    assert ot._decided_today(_at("11:00"))[("NIFTY", "Options · Iron Condor")]["verdict"] == TAKEN

    now = pd.Timestamp.now(tz=IST).to_pydatetime()
    for leg, p in zip(rec["legs"], [12.0, 28.0, 30.0, 14.0]):   # closing costs 28 − 12 + 30 − 14 = 32 …
        live_candles._last[ot._leg_key(leg)] = (p, now)
    ot.monitor_tick(max_age=60)
    assert acct.open_trades()                                   # … not yet the 30 target
    live_candles._last[ot._leg_key(rec["legs"][2])] = (28.0, now)
    ot.monitor_tick(max_age=60)                                  # 28 − 12 + 28 − 14 = 30 → target
    closed = acct.account_state(_at("12:00"))["sized"]
    assert len(closed) == 1 and closed[0]["status"] == "Target Hit"
    t = closed[0]
    assert t["gross"] == pytest.approx((50.0 - 30.0) * 5 * 65)
    assert t["charge_parts"]["brokerage"] == pytest.approx(4 * 2 * 20)   # every leg is a pair of orders
    assert t["net"] == pytest.approx(t["gross"] - t["charges"])
    assert sent[-1].startswith("OPTIONS TRADE CLOSED")


def test_a_position_the_limits_reject_is_booked_as_skipped(opts, monkeypatch):
    acct, sent = opts
    monkeypatch.setattr(acct, "limits", dict(LIMITS, max_loss_per_trade=500))   # one lot risks ₹975
    ot._enter("NIFTY", "opt_iron_condor", "Options · Iron Condor", OPTIONS_TEMPLATES["opt_iron_condor"],
              pd.Timestamp("2026-10-29 10:30", tz=IST), _at("10:46"))
    assert not acct.open_trades()
    [rec] = acct.decisions("2026-10-29").values()
    assert rec["verdict"] == SKIPPED and "max loss per trade" in rec["reasons"][0]
    assert sent[0].startswith("OPTIONS SKIPPED")
