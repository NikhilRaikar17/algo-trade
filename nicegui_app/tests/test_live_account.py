"""The paper account's book: one take-or-skip decision per live signal, made once, and only taken
trades alerted and counted."""

from datetime import datetime

import pandas as pd
import pytest

import account
import algo_strategies
from config import RISK_LIMITS
from trade_desk import SKIPPED, TAKEN, Book, DeskRow, check, day_stop

IST = "Asia/Kolkata"
LIMITS = dict(RISK_LIMITS, funds=100_000, max_loss_per_trade=250, max_capital_pct=33, min_risk_pct=50,
              max_trades_per_day=None, max_daily_loss=750, max_losing_streak=3, square_off="15:20")


def _at(hhmm, day="2026-10-27"):
    return pd.Timestamp(f"{day} {hhmm}", tz=IST).to_pydatetime()


def _sig(hhmm, entry, stop, target, signal="SELL"):
    return {"time": pd.Timestamp(f"2026-10-27 {hhmm}", tz=IST), "entry": entry, "stop_loss": stop,
            "target": target, "signal": signal}


@pytest.fixture
def acct(tmp_path, monkeypatch):
    monkeypatch.setattr(account.EQUITY, "file", str(tmp_path / "acct.json"))
    monkeypatch.setattr(account.EQUITY, "book_file", str(tmp_path / "book.json"))
    monkeypatch.setattr(account.EQUITY, "limits", LIMITS)
    with open(account.EQUITY.file, "w") as f:
        f.write('{"start": "2026-10-27T09:00:00+05:30", "initial": 100000}')
    sent, marked = [], set()
    import state
    monkeypatch.setattr(state, "_send_telegram", sent.append)
    monkeypatch.setattr(state, "_is_already_sent", lambda k: k in marked)  # never the real dedup file
    monkeypatch.setattr(state, "_mark_sent", marked.add)
    monkeypatch.setattr(algo_strategies, "_is_already_sent", lambda k: k in marked)
    monkeypatch.setattr(algo_strategies, "_mark_sent", marked.add)
    monkeypatch.setattr(algo_strategies, "save_completed_trade", lambda k, t: None)
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
    done = Book(balance=100_000, taken_today=9, day_stopped="3 losing trades in a row")
    assert check(_row(500, 495, 510), done, LIMITS, _at("10:05")).reasons == [
        "trading stopped for today: 3 losing trades in a row"]
    many = Book(balance=100_000, taken_today=12)                  # no limit on the number of trades
    assert check(_row(500, 495, 510), many, LIMITS, _at("10:05")).verdict == TAKEN
    held = Book(balance=100_000, open_symbols={"X"})
    assert "already holding X" in check(_row(500, 495, 510), held, LIMITS, _at("10:05")).reasons
    late = check(_row(500, 495, 510), Book(balance=100_000), LIMITS, _at("15:05"))
    assert late.verdict == SKIPPED and "entry window" in late.reasons[0]


def _closed(*nets):
    return [{"net": n, "exit_time": f"2026-10-27T1{i}:00:00+05:30"} for i, n in enumerate(nets)]


def test_day_stops_on_three_losses_in_a_row_or_750_down():
    assert day_stop(_closed(-10, -10, -10), LIMITS) == "3 losing trades in a row"
    assert day_stop(_closed(-200, -200, 100, -200, -150), LIMITS) == ""          # 2 in a row, −₹650
    assert day_stop(_closed(-300, 50, -300, 10, -250), LIMITS).startswith("down ₹790")
    assert day_stop(_closed(-10, -10, -10, 500), LIMITS) != ""                   # stays stopped


def test_decision_is_made_once_and_never_redone(acct):
    sigs = [("A", "10:00", 500, 495, 510)] + [(s, f"10:{m}", 200, 198, 204) for s, m in (("B", 10), ("C", 15), ("D", 20))]
    for sym, hhmm, entry, stop, target in sigs:               # four trades of ₹25,000: the ₹1L is used up
        rec, new = account.open_signal(_sig(hhmm, entry, stop, target, "BUY"), "S", sym, entry, now=_at(hhmm))
        assert new and rec["verdict"] == TAKEN and rec["capital"] == pytest.approx(25_000)
    e = _sig("10:30", 100, 99, 102, "BUY")
    rec, _ = account.open_signal(e, "S", "E", 100, now=_at("10:35"))
    assert rec["verdict"] == SKIPPED and "no free funds" in rec["reasons"][0]

    a = _sig("10:00", 500, 495, 510, "BUY")
    assert account.close_signal(a, "S", "A", 510, "Target Hit", now=_at("11:00"))["net"] > 0
    again, new = account.open_signal(e, "S", "E", 100, now=_at("11:05"))
    assert not new and again["verdict"] == SKIPPED              # A closing doesn't change E's verdict


def test_three_losses_stop_the_day_in_the_book(acct):
    for sym, m in (("A", 0), ("B", 5), ("C", 10)):
        sig = _sig(f"10:{m:02d}", 200, 198, 204, "BUY")
        account.open_signal(sig, "S", sym, 200, now=_at(f"10:{m + 2:02d}"))
        account.close_signal(sig, "S", sym, 198, "SL Hit", now=_at(f"10:{m + 4:02d}"))
    rec, _ = account.open_signal(_sig("11:00", 100, 99, 102, "BUY"), "S", "D", 100, now=_at("11:05"))
    assert rec["verdict"] == SKIPPED and rec["reasons"] == ["trading stopped for today: 3 losing trades in a row"]
    tomorrow = _sig("11:00", 100, 99, 102, "BUY") | {"time": pd.Timestamp("2026-10-28 10:00", tz=IST)}
    rec, _ = account.open_signal(tomorrow, "S", "D", 100, now=_at("10:05", day="2026-10-28"))
    assert rec["verdict"] == TAKEN


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


def test_telegram_only_alerts_taken_trades_and_the_day_stop(acct, monkeypatch):
    sent = acct
    monkeypatch.setattr(algo_strategies, "_send_telegram", sent.append)
    monkeypatch.setattr(algo_strategies, "now_ist", lambda: _at("11:00"))
    monkeypatch.setattr(account, "now_ist", lambda: _at("10:30"))
    sigs = [dict(_sig(f"10:{m:02d}", 100, 99, 102, "BUY"), signal="BUY") for m in (0, 5, 10, 15, 20)]
    for i, s in enumerate(sigs):  # five stocks at ₹25,000 each: the fifth has no free funds
        algo_strategies._classify_generic([s], 100.5, f"STK{i}", "EMA10", "ema10")
    assert [m.split(" [")[0] for m in sent] == ["NEW TRADE"] * 4   # the fifth is skipped, quietly
    assert "Size: BUY 250 × ₹100.00" in sent[0]

    sent.clear()
    monkeypatch.setattr(account, "now_ist", lambda: _at("11:00"))
    for i, s in enumerate(sigs):  # all four taken trades stop out; the skipped one sends nothing
        algo_strategies._classify_generic([dict(s)], 99, f"STK{i}", "EMA10", "ema10")
    heads = [m.splitlines()[0].split(" [")[0] for m in sent]
    assert heads == ["TRADE CLOSED"] * 3 + ["TRADING STOPPED FOR TODAY"] + ["TRADE CLOSED"]
    assert "on 250 shares" in sent[0] and "3 losing trades in a row" in sent[3]


def test_ticks_close_at_the_target_or_stop_level(acct):
    buy = _sig("10:00", 500, 495, 510, "BUY")
    rec, _ = account.open_signal(buy, "S", "A", 500, now=_at("10:05"))
    assert account.on_tick(rec["key"], 503.4, now=_at("10:06")) is None
    assert account.open_trades()[0]["last_price"] == 503.4
    hit = account.on_tick(rec["key"], 511.2, now=_at("10:07"))            # traded through the target
    assert hit["status"] == "Target Hit" and hit["exit_price"] == 510
    assert account.on_tick(rec["key"], 495, now=_at("10:08")) is None      # already closed

    sell = _sig("10:00", 300, 303, 294, "SELL")
    rec, _ = account.open_signal(sell, "S", "B", 300, now=_at("10:05"))
    stop = account.on_tick(rec["key"], 303.5, now=_at("10:09"))
    assert stop["status"] == "SL Hit" and stop["exit_price"] == 303
    assert stop["gross"] == pytest.approx(-3 * stop["qty"])


def test_candle_fallback_also_fills_at_the_level(acct):
    a = _sig("10:00", 500, 495, 510, "BUY")
    account.open_signal(a, "S", "A", 500, now=_at("10:05"))
    assert account.close_signal(a, "S", "A", 512.7, "Target Hit", now=_at("11:00"))["exit_price"] == 510


def test_monitor_closes_open_trades_on_live_ticks(acct, monkeypatch):
    import trading_engine
    import ws_feed
    rec, _ = account.open_signal(_sig("10:00", 500, 495, 510, "BUY"), "S", "A", 500, now=_at("10:05"))
    watched, sent = [], acct
    monkeypatch.setattr(trading_engine, "_security_ids", lambda: {"A": "111"})
    monkeypatch.setattr(trading_engine, "_send_telegram", sent.append)
    monkeypatch.setattr(trading_engine, "alert_day_stop", lambda: None)
    monkeypatch.setattr(ws_feed, "watch", lambda source, secs: watched.append((source, secs)))
    price = {"ltp": 504.0}
    monkeypatch.setattr(trading_engine.live_candles, "last_price", lambda sid, max_age=60: price["ltp"])
    trading_engine._monitor_tick()
    assert watched[-1][0] == "positions" and watched[-1][1][0][1] == "111"
    assert account.open_trades()[0]["last_price"] == 504.0 and not sent
    price["ltp"] = 494.5
    trading_engine._monitor_tick()
    assert not account.open_trades() and sent[0].startswith("TRADE CLOSED [S] | A")
    trading_engine._monitor_tick()
    assert watched[-1] == ("positions", [])                               # nothing left to watch


def test_feed_carries_the_union_of_every_watcher(monkeypatch):
    import ws_feed
    monkeypatch.setattr(ws_feed, "_eq_watch", {"algo": frozenset({(1, "5")}), "positions": frozenset({(1, "7"), (1, "5")})})
    assert ws_feed._wanted() == {(1, "5"), (1, "7")}
