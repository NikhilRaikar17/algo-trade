"""The live options account: which contracts it trades, lot sizing, its own book and alerts, and the
engine taking only BUY signals from the option charts."""

from datetime import date

import pandas as pd
import pytest

import account
import algo_strategies
import live_candles
import options_engine
from config import OPTIONS_LIMITS, OPTIONS_SELECTION
from option_contracts import needs_reselect, pick_expiry, pick_strike
from trade_desk import SKIPPED, TAKEN, Book, DeskRow, check
from ws_feed import feed_key

IST = "Asia/Kolkata"
LIMITS = dict(OPTIONS_LIMITS, funds=100_000, max_loss_per_trade=250, max_capital_pct=33, min_risk_pct=50,
              max_daily_loss=750, max_losing_streak=3, square_off="15:20")
NIFTY_EXPIRIES = ["2026-10-27", "2026-11-03", "2026-11-09", "2026-11-17", "2026-11-23", "2026-12-01"]
BANKNIFTY_EXPIRIES = ["2026-10-27", "2026-11-23", "2026-12-29", "2027-03-30"]


def _at(hhmm, day="2026-10-27"):
    return pd.Timestamp(f"{day} {hhmm}", tz=IST).to_pydatetime()


def test_expiry_is_next_to_next_and_never_todays():
    assert pick_expiry(NIFTY_EXPIRIES, date(2026, 10, 27)) == "2026-11-09"   # not today's, not 03 Nov
    assert pick_expiry(NIFTY_EXPIRIES, date(2026, 10, 28)) == "2026-11-09"
    assert pick_expiry(NIFTY_EXPIRIES, date(2026, 11, 3)) == "2026-11-17"
    # monthly-only BANKNIFTY: December is 63 days out, over the 45-day limit, so November
    assert pick_expiry(BANKNIFTY_EXPIRIES, date(2026, 10, 27)) == "2026-11-23"
    assert pick_expiry(BANKNIFTY_EXPIRIES, date(2026, 11, 20)) == "2026-12-29"   # 39 days: next-to-next


def _q(sid, ltp, delta, oi=200_000, vol=300_000, spread=1.0):
    return {"security_id": sid, "last_price": ltp, "greeks": {"delta": delta}, "oi": oi, "volume": vol,
            "top_bid_price": ltp - spread / 2, "top_ask_price": ltp + spread / 2, "implied_volatility": 15}


def _chain():
    return {"last_price": 22_690.0, "oc": {
        "22600.000000": {"ce": _q(1, 330, 0.60), "pe": _q(2, 225, -0.40)},
        "22650.000000": {"ce": _q(3, 300, 0.55, spread=8), "pe": _q(4, 250, -0.45)},   # CE spread 2.7%
        "22700.000000": {"ce": _q(5, 272, 0.52, oi=1_000), "pe": _q(6, 280, -0.48)},   # CE: thin OI
        "22750.000000": {"ce": _q(7, 245, 0.47), "pe": _q(8, 310, -0.53)},
        "23500.000000": {"ce": _q(9, 20, 0.08), "pe": _q(10, 820, -0.95)},              # far from the ATM
    }}


def test_strike_is_the_liquid_near_the_money_one_closest_to_half_delta():
    ce, _ = pick_strike(_chain(), "NIFTY", "2026-11-09", "CE", 65, 33_000)
    assert ce["symbol"] == "NIFTY 09NOV 22750 CE" and ce["security_id"] == "7" and ce["lot_size"] == 65
    pe, _ = pick_strike(_chain(), "NIFTY", "2026-11-09", "PE", 65, 33_000)
    assert pe["symbol"] == "NIFTY 09NOV 22700 PE" and pe["delta"] == pytest.approx(0.48)


def test_no_strike_when_none_is_affordable_says_why():
    c, why = pick_strike(_chain(), "NIFTY", "2026-11-09", "CE", 65, 10_000)
    assert c is None and "a lot costs over ₹10,000" in why


def test_reselect_on_a_new_day_or_after_the_index_moves_three_strikes():
    c = {"underlying": "NIFTY", "atm": 22_700, "chosen_on": "2026-10-27"}
    assert not needs_reselect(c, 22_790, "2026-10-27")
    assert needs_reselect(c, 22_850, "2026-10-27")                 # 3 × 50 points away
    assert needs_reselect(c, 22_700, "2026-10-28")
    assert needs_reselect(None, None, "2026-10-27")


def _opt_row(entry, stop, target, lot=65, symbol="NIFTY 09NOV 22750 CE"):
    return DeskRow(key=symbol, symbol=symbol, strategy="S", side="BUY", signal_time=_at("10:05"), entry=entry,
                   stop=stop, target=target, status="Active", lot_size=lot, group="NIFTY options")


def test_options_are_sized_in_whole_lots():
    r = check(_opt_row(200, 198.5, 210), Book(balance=100_000), LIMITS, _at("10:05"))
    assert r.verdict == TAKEN and r.qty == 130                 # ₹250 / (₹1.50 × 65) = 2 lots
    assert r.max_loss == pytest.approx(195) and r.capital == pytest.approx(26_000)
    wide = check(_opt_row(200, 196, 220), Book(balance=100_000), LIMITS, _at("10:05"))
    assert wide.verdict == SKIPPED and "one lot risks ₹260.00" in wide.reasons[0]


def test_reward_risk_counts_the_charges_for_options():
    # 1.5 before charges, but ~₹80 of charges leave ~₹115 to win against ~₹210 to lose
    r = check(_opt_row(200, 198, 203), Book(balance=100_000), LIMITS, _at("10:05"))
    assert r.verdict == SKIPPED and "reward:risk after charges" in r.reasons[0]


def test_one_position_per_index():
    held = Book(balance=100_000, open_symbols={"NIFTY 09NOV 22700 PE", "NIFTY options"})
    r = check(_opt_row(200, 198.5, 210), held, LIMITS, _at("10:05"))
    assert r.reasons == ["already holding NIFTY options"]


# ── the options account and engine ─────────────────────────────────────────────

CE = {"symbol": "NIFTY 09NOV 22750 CE", "security_id": "39887", "underlying": "NIFTY", "opt_type": "CE",
      "expiry": "2026-11-09", "strike": 22_750.0, "lot_size": 65, "premium": 265.0, "spot": 22_740.0,
      "atm": 22_750.0, "delta": 0.5, "oi": 1, "volume": 1, "spread_pct": 0.4, "chosen_on": "2026-10-27",
      "chosen_at": "09:20"}


@pytest.fixture
def opts(tmp_path, monkeypatch):
    acct = account.OPTIONS
    monkeypatch.setattr(acct, "file", str(tmp_path / "acct.json"))
    monkeypatch.setattr(acct, "book_file", str(tmp_path / "book.json"))
    monkeypatch.setattr(acct, "limits", LIMITS)
    monkeypatch.setattr(acct, "meta", {})
    with open(acct.file, "w") as f:
        f.write('{"start": "2026-10-27T09:00:00+05:30", "initial": 100000}')
    sent, marked = [], set()
    import state
    for mod in (state, algo_strategies, options_engine):
        monkeypatch.setattr(mod, "_send_telegram", sent.append)
    monkeypatch.setattr(state, "_is_already_sent", lambda k: k in marked)
    monkeypatch.setattr(state, "_mark_sent", marked.add)
    monkeypatch.setattr(algo_strategies, "_is_already_sent", lambda k: k in marked)
    monkeypatch.setattr(algo_strategies, "_mark_sent", marked.add)
    saved = []
    monkeypatch.setattr(algo_strategies, "save_completed_trade", lambda k, t: saved.append(k))
    monkeypatch.setattr(options_engine.ws_feed, "watch", lambda *a: None)
    monkeypatch.setattr(live_candles, "_bars", {})
    monkeypatch.setattr(live_candles, "_seeded", {})
    monkeypatch.setattr(live_candles, "_last", {})
    monkeypatch.setattr(live_candles, "_history", {})
    return acct, sent, saved


def _sig(hhmm, entry, stop, target):
    return {"time": pd.Timestamp(f"2026-10-27 {hhmm}", tz=IST), "entry": entry, "stop_loss": stop,
            "target": target, "signal": "BUY" if target > entry else "SELL"}


def test_engine_books_only_buy_signals_in_lots_and_alerts_as_options(opts, monkeypatch):
    acct, sent, saved = opts
    bars = pd.DataFrame({"timestamp": [pd.Timestamp("2026-10-27 10:00", tz=IST)],
                         "open": [199.0], "high": [201.0], "low": [198.8], "close": [200.0]})
    monkeypatch.setattr(options_engine, "option_candles", lambda c: bars)
    buy, sell = _sig("10:00", 200, 198.5, 210), _sig("10:00", 200, 201.5, 190)
    monkeypatch.setitem(options_engine._STRATEGY_RUNNERS, "ema10",
                        (lambda c: [dict(buy), dict(sell)], algo_strategies.classify_ema10_trades))
    acct.meta[CE["symbol"]] = options_engine._meta(CE)
    monkeypatch.setattr(algo_strategies, "now_ist", lambda: _at("10:05"))
    monkeypatch.setattr(account, "now_ist", lambda: _at("10:05"))
    options_engine._run_contract(CE, ["ema10"])

    trades = acct.open_trades()
    assert len(trades) == 1 and trades[0]["side"] == "BUY" and trades[0]["qty"] == 130
    assert trades[0]["security_id"] == "39887" and trades[0]["group"] == "NIFTY options"
    assert len(sent) == 1 and sent[0].startswith("OPTIONS NEW TRADE") and "BUY 2 lots (130) × ₹200.00" in sent[0]
    assert not saved                                                    # option signals stay out of the stock history


def test_monitor_closes_an_option_at_its_target_on_a_tick(opts, monkeypatch):
    acct, sent, _ = opts
    acct.meta[CE["symbol"]] = options_engine._meta(CE)
    rec, _ = acct.open_signal(_sig("10:00", 200, 198.5, 210), "S", CE["symbol"], 200, now=_at("10:05"))
    assert rec["verdict"] == TAKEN
    live_candles.on_tick(feed_key(2, "39887"), 210.4)
    options_engine._options_monitor_tick()
    assert not acct.open_trades()
    closed = acct._load_book()[rec["key"]]
    assert closed["status"] == "Target Hit" and closed["exit_price"] == 210 and closed["gross"] == pytest.approx(1300)
    assert closed["charge_parts"]["brokerage"] == 40                    # F&O: flat ₹20 an order
    assert sent[0].startswith("OPTIONS TRADE CLOSED [S] | NIFTY 09NOV 22750 CE\nBUY 2 lots (130) @ 200.00")


def test_option_ticks_are_kept_apart_from_stock_ticks():
    assert feed_key(1, "2885") == "2885" and feed_key(2, "2885") == "2:2885"


def test_the_options_account_has_its_own_day_stop_alert(opts):
    acct, sent, _ = opts
    acct.meta[CE["symbol"]] = options_engine._meta(CE)
    for i, m in enumerate((0, 20, 40)):
        sig = _sig(f"10:{m:02d}", 200, 198.5, 210)
        acct.open_signal(sig, f"S{i}", CE["symbol"], 200, now=_at(f"10:{m + 5:02d}"))
        acct.close_signal(sig, f"S{i}", CE["symbol"], 198.5, "SL Hit", now=_at(f"10:{m + 10:02d}"))
    acct.alert_day_stop(now=_at("11:00"))
    assert sent[-1].startswith("OPTIONS TRADING STOPPED FOR TODAY\n3 losing trades in a row")
    assert OPTIONS_SELECTION["expiry_skip"] == 1
