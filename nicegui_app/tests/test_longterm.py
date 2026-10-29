"""The long-term account: the current NIFTY future traded on the index's daily chart — which contract,
futures charges, lots on margin, long and short, held across days and closed after max_hold_days trading
days, the daily scan running the enabled moving-average strategies, and the backtest."""

import numpy as np
import pandas as pd
import pytest

import account
import algo_strategies
import longterm
from brokerage import calculate_brokerage
from config import LONGTERM_LIMITS
from trade_desk import SKIPPED, TAKEN

IST = "Asia/Kolkata"
FUTURES = [{"symbol": "NIFTY NOV FUT", "security_id": "61471", "expiry": "2026-11-23", "lot_size": 65},
           {"symbol": "NIFTY DEC FUT", "security_id": "58875", "expiry": "2026-12-29", "lot_size": 65},
           {"symbol": "NIFTY OCT FUT", "security_id": "50000", "expiry": "2026-10-27", "lot_size": 65}]
NOV = FUTURES[0]


def _at(day, hhmm="15:15"):
    return pd.Timestamp(f"{day} {hhmm}", tz=IST).to_pydatetime()


def _daily(closes, end="2026-10-28"):
    """Daily bars ending on `end`, a 1% range around each close."""
    days = pd.bdate_range(end=end, periods=len(closes)).tz_localize(IST)
    c = np.array(closes, dtype=float)
    return pd.DataFrame({"timestamp": days, "open": c, "high": c * 1.005, "low": c * 0.995, "close": c})


@pytest.fixture
def lt(tmp_path, monkeypatch):
    acct = account.LONGTERM
    monkeypatch.setattr(acct, "file", str(tmp_path / "acct.json"))
    monkeypatch.setattr(acct, "book_file", str(tmp_path / "book.json"))
    monkeypatch.setattr(acct, "meta", {NOV["symbol"]: longterm._meta(NOV)})
    with open(acct.file, "w") as f:
        f.write('{"start": "2026-10-01T09:00:00+05:30", "initial": 500000}')
    sent = []
    import state
    for mod in (state, algo_strategies, longterm):
        monkeypatch.setattr(mod, "_send_telegram", sent.append)
    return acct, sent


def _sig(day, entry=22_800.0, stop=22_400.0, target=23_600.0):
    return {"time": pd.Timestamp(day, tz=IST), "entry": entry, "stop_loss": stop, "target": target,
            "signal": "BUY — test" if target > entry else "SELL — test"}


def test_always_trades_the_nearest_expiry_closest_to_the_spot():
    assert longterm.pick_future(FUTURES, "2026-10-27")["symbol"] == "NIFTY NOV FUT"   # Oct expires today
    assert longterm.pick_future(FUTURES, "2026-10-28")["symbol"] == "NIFTY NOV FUT"
    assert longterm.pick_future(FUTURES, "2026-11-20")["symbol"] == "NIFTY NOV FUT"   # 1 trading day left
    assert longterm.pick_future(FUTURES, "2026-11-23")["symbol"] == "NIFTY DEC FUT"   # Nov's expiry day


def test_a_trade_still_open_on_its_expiry_day_is_closed_then(lt):
    acct, sent = lt
    rec, _ = acct.open_signal(_sig("2026-11-19"), "SMA50", NOV["symbol"], 22_800, now=_at("2026-11-19"))
    assert rec["expiry"] == "2026-11-23"
    assert not acct.square_off(_at("2026-11-23", "15:00"))           # expiry day, before the square-off time
    closed = acct.square_off(_at("2026-11-23", "15:20"))             # 2 trading days held, but it expires
    assert [r["status"] for r in closed] == ["Expiry"]
    assert sent[-1].startswith("LONGTERM EXPIRY EXIT [SMA50] | NIFTY NOV FUT") and "2026-11-23" in sent[-1]


def test_futures_charges_are_on_the_contract_value():
    b = calculate_brokerage(22_800, 23_000, lot_size=1, quantity=65, segment="fno_futures")
    assert b["gross_pnl"] == 13_000
    assert b["brokerage"] == 40                                  # ₹20 an order
    assert b["stt"] == 748                                       # 0.05% of the ₹14,95,000 sold, to the rupee
    short = calculate_brokerage(22_800, 22_600, lot_size=1, quantity=65, segment="fno_futures", short=True)
    assert short["gross_pnl"] == 13_000


def test_sized_in_lots_on_margin_and_one_position_at_a_time(lt):
    acct, sent = lt
    rec, _ = acct.open_signal(_sig("2026-10-19"), "SMA50", NOV["symbol"], 22_800, now=_at("2026-10-19"))
    assert rec["verdict"] == TAKEN and rec["qty"] == 65              # ₹26,000 risk a lot: one lot in ₹30,000
    assert rec["capital"] == pytest.approx(22_800 * 65 * 0.125)      # the margin, not the contract value
    assert rec["group"] == "NIFTY futures" and rec["security_id"] == "61471"
    other, _ = acct.open_signal(_sig("2026-10-19", 22_800, 23_200, 22_000), "EMA100", NOV["symbol"], 22_800,
                                now=_at("2026-10-19"))
    assert other["verdict"] == SKIPPED and "already holding" in other["reasons"][0]


def test_a_short_is_held_across_days_and_closed_after_five_trading_days(lt):
    acct, sent = lt
    rec, _ = acct.open_signal(_sig("2026-10-19", 22_800, 23_200, 22_000), "SMA50", NOV["symbol"], 22_800,
                              now=_at("2026-10-19"))
    assert rec["side"] == "SELL" and rec["verdict"] == TAKEN
    assert not acct.square_off(_at("2026-10-26", "15:25"))            # 4 trading days in (21 Oct is a holiday)
    assert not acct.square_off(_at("2026-10-27", "10:00"))            # day 5, before the square-off time
    acct.on_tick(rec["key"], 22_700.0, now=_at("2026-10-27", "11:00"))
    closed = acct.square_off(_at("2026-10-27", "15:20"))
    assert [r["status"] for r in closed] == ["Time Exit"] and closed[0]["gross"] == 6_500   # 100 points × 65, short
    assert sent[-1].startswith("LONGTERM TIME EXIT [SMA50] | NIFTY NOV FUT") and "after 5 trading days" in sent[-1]


def test_target_on_a_later_day_closes_it(lt):
    acct, _ = lt
    rec, _ = acct.open_signal(_sig("2026-10-19"), "SMA50", NOV["symbol"], 22_800, now=_at("2026-10-19"))
    closed = acct.on_tick(rec["key"], 23_610.0, now=_at("2026-10-22", "11:00"))
    assert closed["status"] == "Target Hit" and closed["exit_price"] == 23_600.0


def test_daily_signals_get_atr_levels_long_and_short():
    df = _daily(list(np.linspace(24_000, 22_000, 120)) + [22_000] * 5 + [23_000])
    sig = longterm.detect_daily_signals(df, "sma50")[-1]
    assert sig["bar"] == len(df) - 1 and sig["type"] == "Bullish" and sig["entry"] == 23_000
    assert sig["target"] - 23_000 == pytest.approx(2 * (23_000 - sig["stop_loss"]), abs=0.02)   # 3 ATR vs 1.5 ATR
    down = _daily(list(np.linspace(22_000, 24_000, 120)) + [24_000] * 5 + [23_000])
    short = longterm.detect_daily_signals(down, "sma50")[-1]
    assert short["type"] == "Bearish" and short["stop_loss"] > 23_000 > short["target"]
    moved = longterm.on_future(short, 23_080.0)
    assert moved["entry"] == 23_080 and moved["stop_loss"] - 23_080 == pytest.approx(short["stop_loss"] - 23_000)


def test_runs_the_moving_average_strategies_enabled_for_backtest(monkeypatch):
    rows = [{"key": "abcd", "backtest_enabled": True}, {"key": "sma50", "backtest_enabled": True},
            {"key": "ema10", "backtest_enabled": False}, {"key": "sma200", "backtest_enabled": True}]
    monkeypatch.setattr(longterm, "get_strategy_rows", lambda: rows)
    assert longterm.strategy_keys() == ["sma50", "sma200"]               # ABCD can't run on daily bars
    assert longterm.strategy_names() == ["SMA50", "SMA200"]


def test_daily_scan_books_the_future_and_alerts(lt, monkeypatch):
    acct, sent = lt
    hist = _daily(list(np.linspace(24_000, 22_000, 120)) + [22_000] * 5, end="2026-10-27")
    monkeypatch.setattr(longterm, "current_future", lambda: NOV)
    monkeypatch.setattr(longterm, "strategy_keys", lambda: ["sma50"])
    monkeypatch.setattr(longterm, "fetch_daily_history", lambda: hist)
    monkeypatch.setattr(longterm, "fetch_quotes",
                        lambda sid: ({"open": 22_010.0, "high": 23_050.0, "low": 22_000.0, "close": 23_000.0}, 23_080.0))
    for mod in (longterm, algo_strategies, account):
        monkeypatch.setattr(mod, "now_ist", lambda: _at("2026-10-28"))
    res = longterm.scan(book=True)
    assert [s["strategy"] for s in res["signals"]] == ["SMA50"] and res["signals"][0]["verdict"] == TAKEN
    trades = acct.open_trades()
    assert len(trades) == 1 and trades[0]["symbol"] == "NIFTY NOV FUT" and trades[0]["entry"] == 23_080
    assert trades[0]["qty"] % 65 == 0 and trades[0]["side"] == "BUY"
    assert sent[0].startswith("LONGTERM NEW TRADE [SMA50] | NIFTY NOV FUT") and "margin" in sent[0]
    longterm.scan(book=True)                                            # a second scan decides nothing again
    assert len(sent) == 1


def test_backtest_exits_long_and_short():
    df = _daily([100] * 8)
    sig = {"bar": 1, "entry": 100.0, "stop_loss": 97.0, "target": 106.0, "time": df["timestamp"].iloc[1]}
    out = longterm.backtest_signals(df, [sig], hold=5)
    assert out[0]["status"] == "Time Exit" and out[0]["exit_time"] == df["timestamp"].iloc[6]
    df.loc[3, "low"] = 96.0
    assert longterm.backtest_signals(df, [sig], hold=5)[0]["status"] == "SL Hit"
    short = {"bar": 1, "entry": 100.0, "stop_loss": 103.0, "target": 94.0, "time": df["timestamp"].iloc[1]}
    assert longterm.backtest_signals(df, [short], hold=5)[0]["status"] == "Time Exit"
    df.loc[2, "low"] = 93.0
    hit = longterm.backtest_signals(df, [short], hold=5)[0]
    assert hit["status"] == "Target Hit" and hit["exit_price"] == 94.0
    df.loc[2, "low"] = 99.5
    df.loc[2, "high"] = 104.0
    assert longterm.backtest_signals(df, [short], hold=5)[0]["status"] == "SL Hit"
    assert longterm.backtest_signals(df, [dict(sig, bar=4)], hold=5) == []   # still running


def test_backtest_account_holds_one_position_in_lots_and_compounds():
    t0 = pd.Timestamp("2026-10-01", tz=IST)
    base = {"entry": 22_800.0, "stop_loss": 22_400.0, "target": 23_600.0, "status": "Target Hit",
            "exit_price": 23_600.0, "stock": "NIFTY futures", "strategy": "SMA50"}
    trades = [dict(base, time=t0, exit_time=t0 + pd.Timedelta(days=3)),
              dict(base, time=t0 + pd.Timedelta(days=1), exit_time=t0 + pd.Timedelta(days=4)),   # still holding
              dict(base, time=t0 + pd.Timedelta(days=5), exit_time=t0 + pd.Timedelta(days=7),
                   stop_loss=23_200.0, target=22_000.0, exit_price=22_000.0)]                       # a short
    sized, report = longterm.simulate_account(trades, LONGTERM_LIMITS, lot=65)
    assert len(sized) == 2 and report["skipped"] == 1
    assert [t["qty"] for t in sized] == [65, 65] and [t["side"] for t in sized] == ["BUY", "SELL"]
    assert sized[1]["gross"] == 800 * 65
