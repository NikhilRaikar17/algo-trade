"""The paper account's book: one take-or-skip decision per live signal, made once, and only taken
trades alerted and counted."""

from datetime import datetime

import pandas as pd
import pytest

import account
import algo_strategies
from config import RISK_LIMITS
from trade_desk import SKIPPED, TAKEN, Book, DeskRow, check

IST = "Asia/Kolkata"
LIMITS = dict(RISK_LIMITS, funds=100_000, max_loss_per_trade=250, max_capital_pct=33, min_risk_pct=50,
              max_trades_per_day=3, max_daily_loss=750, square_off="15:20")


def _at(hhmm, day="2026-10-27"):
    return pd.Timestamp(f"{day} {hhmm}", tz=IST).to_pydatetime()


def _sig(hhmm, entry, stop, target, signal="SELL"):
    return {"time": pd.Timestamp(f"2026-10-27 {hhmm}", tz=IST), "entry": entry, "stop_loss": stop,
            "target": target, "signal": signal}


@pytest.fixture
def acct(tmp_path, monkeypatch):
    monkeypatch.setattr(account, "_FILE", str(tmp_path / "acct.json"))
    monkeypatch.setattr(account, "_BOOK_FILE", str(tmp_path / "book.json"))
    monkeypatch.setattr(account, "RISK_LIMITS", LIMITS)
    with open(account._FILE, "w") as f:
        f.write('{"start": "2026-10-27T09:00:00+05:30", "initial": 100000}')
    sent = []
    import state
    monkeypatch.setattr(state, "_send_telegram", sent.append)
    return sent


def _row(entry, stop, target, symbol="X"):
    return DeskRow(key=symbol, symbol=symbol, strategy="S", side="BUY" if target > entry else "SELL",
                   signal_time=_at("10:05"), entry=entry, stop=stop, target=target, status="Active")


def test_sizes_to_the_max_loss():
    r = check(_row(2303.70, 2326.74, 2270.00), Book(balance=100_000), LIMITS, _at("10:05"))
    assert r.verdict == TAKEN and r.qty == 10                 # ₹250 / ₹23.04 risk per share
    assert r.max_loss <= 250 and r.capital == pytest.approx(23_037)


def test_per_trade_cap_cuts_a_tight_stop_and_skips_it_if_cut_too_far():
    half_pct = check(_row(500, 497.5, 505), Book(balance=100_000), LIMITS, _at("10:05"))
    assert half_pct.verdict == TAKEN and half_pct.qty == 66   # 100 wanted, ₹33,000 cap buys 66
    assert "size cut" in half_pct.warnings[0]
    tight = check(_row(500, 499, 502), Book(balance=100_000), LIMITS, _at("10:05"))
    assert tight.verdict == SKIPPED and "only buys 66 shares" in tight.reasons[0]   # risks ₹66 < ₹125


def test_no_free_funds_and_daily_limits():
    full = Book(balance=100_000, open_capital=99_900)
    assert "no free funds" in check(_row(500, 495, 510), full, LIMITS, _at("10:05")).reasons[0]
    done = Book(balance=100_000, taken_today=3, risk_today=600)
    assert "daily limit reached" in check(_row(500, 495, 510), done, LIMITS, _at("10:05")).reasons[0]
    held = Book(balance=100_000, open_symbols={"X"})
    assert "already holding X" in check(_row(500, 495, 510), held, LIMITS, _at("10:05")).reasons
    late = check(_row(500, 495, 510), Book(balance=100_000), LIMITS, _at("15:05"))
    assert late.verdict == SKIPPED and "entry window" in late.reasons[0]


def test_decision_is_made_once_and_never_redone(acct):
    a = _sig("10:00", 500, 495, 510, "BUY")
    rec, new = account.open_signal(a, "S", "A", 500, now=_at("10:05"))
    assert new and rec["verdict"] == TAKEN and rec["qty"] == 50
    for sym, hhmm in (("B", "10:10"), ("C", "10:15")):
        account.open_signal(_sig(hhmm, 200, 198, 204, "BUY"), "S", sym, 200, now=_at(hhmm))
    d, _ = account.open_signal(_sig("10:20", 100, 99, 102, "BUY"), "S", "D", 100, now=_at("10:25"))
    assert d["verdict"] == SKIPPED and "daily limit" in d["reasons"][0]

    assert account.close_signal(a, "S", "A", 510, "Target Hit", now=_at("11:00"))["net"] > 0
    again, new = account.open_signal(_sig("10:20", 100, 99, 102, "BUY"), "S", "D", 100, now=_at("11:05"))
    assert not new and again["verdict"] == SKIPPED              # A closing doesn't change D's verdict


def test_close_only_reports_a_taken_open_trade_once(acct):
    a = _sig("10:00", 500, 495, 510, "BUY")
    account.open_signal(a, "S", "A", 500, now=_at("10:05"))
    first = account.close_signal(a, "S", "A", 495, "SL Hit", now=_at("10:30"))
    assert first["gross"] == pytest.approx(-250)               # 50 shares × ₹5
    assert account.close_signal(a, "S", "A", 495, "SL Hit", now=_at("10:32")) is None
    unseen = _sig("10:40", 300, 297, 306, "BUY")
    assert account.close_signal(unseen, "S", "U", 306, "Target Hit", now=_at("11:00")) is None
    assert account.decisions("2026-10-27")[f"S|U|{unseen['time'].isoformat()}"]["verdict"] == SKIPPED


def test_square_off_and_account_state(acct):
    a = _sig("10:00", 500, 495, 510, "BUY")
    account.open_signal(a, "S", "A", 500, now=_at("10:05"))
    account.mark_price(a, "S", "A", 503)
    s = account.account_state(now=_at("14:00"))
    assert s["open"] == 1 and s["in_positions"] == pytest.approx(25_000)
    assert s["unrealized"] == pytest.approx(150) and s["free"] == pytest.approx(75_000)
    assert account.square_off(now=_at("15:20"))[0]["status"] == "Day Close"
    assert acct and acct[0].startswith("SQUARED OFF")
    s = account.account_state(now=_at("15:30"))
    assert s["open"] == 0 and s["trades"] == 1
    assert s["balance"] == pytest.approx(100_000 + s["realized"])


def test_open_trade_from_an_earlier_day_is_squared_off(acct):
    a = _sig("10:00", 500, 495, 510, "BUY")
    account.open_signal(a, "S", "A", 500, now=_at("10:05"))
    assert len(account.square_off(now=_at("09:30", day="2026-10-28"))) == 1


def test_telegram_only_alerts_taken_trades(acct, monkeypatch):
    sent = acct
    monkeypatch.setattr(algo_strategies, "_send_telegram", sent.append)
    monkeypatch.setattr(algo_strategies, "_is_already_sent", lambda k: True)
    monkeypatch.setattr(account, "now_ist", lambda: _at("10:30"))
    sigs = [dict(_sig(f"10:{m:02d}", 100, 99, 102, "BUY"), signal="BUY") for m in (0, 5, 10, 15)]
    for i, s in enumerate(sigs):  # four stocks, one signal each; the fourth is over 3 trades/day
        algo_strategies._classify_generic([s], 100.5, f"STK{i}", "EMA10", "ema10")
    assert [m.split(" [")[0] for m in sent] == ["NEW TRADE"] * 3 + ["SKIPPED"]
    assert "Size: BUY 250 × ₹100.00" in sent[0] and "daily limit" in sent[3]

    sent.clear()
    for i, s in enumerate(sigs):
        algo_strategies._classify_generic([dict(s)], 102, f"STK{i}", "EMA10", "ema10")
    assert len(sent) == 3 and all(m.startswith("TRADE CLOSED") for m in sent)
    assert "on 250 shares" in sent[0]
