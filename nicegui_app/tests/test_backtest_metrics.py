from datetime import datetime

import pandas as pd
import pytest

from backtest_metrics import finalize_trades, max_drawdown, size_trades, summarize
from brokerage import calculate_brokerage

IST = "Asia/Kolkata"


def _ts(s):
    return pd.Timestamp(s, tz=IST)


def _trade(time, exit_time, entry, exit_px, target, status="Target Hit", stock="X", strategy="S"):
    return {"time": _ts(time), "exit_time": _ts(exit_time), "entry": entry, "exit_price": exit_px,
            "target": target, "status": status, "stock": stock, "strategy": strategy,
            "pnl": (exit_px - entry) if target > entry else (entry - exit_px), "trade_date": time[:10]}


def test_short_gross_pnl_is_positive_when_price_falls():
    b = calculate_brokerage(100, 90, lot_size=1, quantity=10, segment="equity_intraday", short=True)
    assert b["gross_pnl"] == pytest.approx(100)
    long_ = calculate_brokerage(100, 90, lot_size=1, quantity=10, segment="equity_intraday")
    assert long_["gross_pnl"] == pytest.approx(-100)


def test_finalize_drops_no_fill_and_overlap():
    now = datetime(2026, 10, 27, 18, 0, tzinfo=_ts("2026-10-27").tzinfo)
    a = _trade("2026-10-26 10:00", "2026-10-26 11:00", 100, 102, 102)
    overlapping = _trade("2026-10-26 10:30", "2026-10-26 12:00", 101, 99, 103, status="SL Hit")
    after = _trade("2026-10-26 11:15", "2026-10-26 12:00", 101, 99, 103, status="SL Hit")
    other_stock = _trade("2026-10-26 10:30", "2026-10-26 12:00", 50, 51, 52, stock="Y")
    no_fill = dict(a, status="No Fill", exit_price=None)
    kept, ex = finalize_trades([a, overlapping, after, other_stock, no_fill], now)
    assert kept == [a, other_stock, after]
    assert ex == {"no_fill": 1, "open": 0, "overlap": 1}


def test_finalize_holds_back_todays_running_trade():
    now = _ts("2026-10-27 13:00").to_pydatetime()
    running = _trade("2026-10-27 11:00", "2026-10-27 12:45", 100, 101, 105, status="Day Close")
    kept, ex = finalize_trades([running], now)
    assert kept == [] and ex["open"] == 1


def test_size_and_summary():
    trades = [
        _trade("2026-10-26 10:00", "2026-10-26 11:00", 100, 102, 102),                     # long win
        _trade("2026-10-26 12:00", "2026-10-26 13:00", 200, 204, 190, status="SL Hit"),    # short loss
    ]
    sized = size_trades(trades, "capital", 10_000)
    assert [t["qty"] for t in sized] == [100, 50]
    assert sized[1]["side"] == "SELL" and sized[1]["gross"] == pytest.approx(-200)
    s = summarize(sized)
    assert s["wins"] == 1 and s["losses"] == 1
    assert s["net"] == pytest.approx(s["gross"] - s["charges"])
    assert s["max_drawdown"] == pytest.approx(-sized[1]["net"])  # the loss came after the only high
    assert max_drawdown([]) == 0


def test_risk_sizing_loses_the_set_amount_at_the_stop():
    from backtest_metrics import qty_for
    long_ = {"entry": 500.0, "stop_loss": 495.0}               # ₹5 risk per share
    short = {"entry": 200.0, "stop_loss": 202.5}               # ₹2.50 risk per share
    assert qty_for(long_, "risk", 1000) == 200
    assert qty_for(short, "risk", 1000) == 400
    assert qty_for({"entry": 1000.0}, "risk", 1000) == 100     # no stop saved: assume 1%
    stopped = _trade("2026-10-26 10:00", "2026-10-26 11:00", 500, 495, 510, status="SL Hit")
    stopped["stop_loss"] = 495.0
    t = size_trades([stopped], "risk", 1000)[0]
    assert t["gross"] == pytest.approx(-1000)                  # exactly the max loss, before charges


def test_funds_cap_limits_open_positions_and_resets_daily():
    def t(time, exit_time, entry, stock):
        r = _trade(time, exit_time, entry, entry * 1.01, entry * 1.02, stock=stock)
        r["stop_loss"] = entry * 0.99                            # 1% stop → ₹1,000 risk ≈ ₹1L of shares
        return r
    trades = [
        t("2026-10-26 10:00", "2026-10-26 11:00", 500, "A"),     # takes ~₹1L
        t("2026-10-26 10:30", "2026-10-26 12:00", 200, "B"),     # A still open → no funds
        t("2026-10-26 11:00", "2026-10-26 12:00", 250, "C"),     # A closed at 11:00 → funded
        t("2026-10-27 10:30", "2026-10-27 12:00", 200, "B"),     # new day: full funds again
    ]
    report = {}
    sized = size_trades(trades, "risk", 1000, 100_000, report)
    assert [x["stock"] for x in sized] == ["A", "C", "B"]
    assert report["no_funds"] == 1
    assert all(x["capital"] <= 100_000 for x in sized)


def test_trade_desk_blocks_when_funds_are_used():
    from datetime import datetime
    from trade_desk import DeskRow, evaluate
    limits = {"funds": 100_000, "max_loss_per_trade": 1000, "max_trades_per_day": 3, "max_daily_loss": 3000,
              "min_reward_risk": 1.0, "no_entries_before": "09:20", "no_entries_after": "15:00"}
    rows = [DeskRow(key=k, symbol=k, strategy="S", side="BUY", signal_time=datetime(2026, 10, 26, h, 0),
                    entry=500, stop=495, target=510, status="Active") for k, h in (("A", 10), ("B", 11))]
    a, b = evaluate(rows, limits)
    assert a.verdict == "PASS" and a.capital == 100_000
    assert b.verdict == "BLOCK" and "no free funds" in b.reasons[0]


def test_compounding_carries_each_days_net_into_the_next():
    def t(day, entry, exit_px):
        r = _trade(f"2026-10-{day} 10:00", f"2026-10-{day} 11:00", entry, exit_px, entry * 1.02)
        r["stop_loss"] = entry * 0.99
        return r
    trades = [t(26, 500, 505), t(27, 500, 505)]               # +1% day one
    flat, comp = {}, {}
    size_trades(trades, "capital", 1_000_000, 100_000, flat)                  # same ₹1L every day
    sized = size_trades(trades, "capital", 1_000_000, 100_000, comp, compound=True)
    day1 = sized[0]["net"]
    assert comp["day_open"][sized[1]["time"].date()] == pytest.approx(100_000 + day1)
    assert sized[1]["qty"] > sized[0]["qty"]                  # the profit buys more shares on day two
    assert comp["end_balance"] == pytest.approx(100_000 + sum(x["net"] for x in sized))
    assert flat["day_open"][sized[1]["time"].date()] == 100_000


def test_account_state_balance_free_and_start(tmp_path, monkeypatch):
    import account
    monkeypatch.setattr(account, "_FILE", str(tmp_path / "acct.json"))
    with open(account._FILE, "w") as f:
        f.write('{"start": "2026-10-26T09:00:00+05:30", "initial": 100000}')
    before = _trade("2026-10-23 10:00", "2026-10-23 11:00", 500, 495, 510, status="SL Hit")
    win = _trade("2026-10-26 10:00", "2026-10-26 11:00", 500, 505, 510)
    for x in (before, win):
        x["stop_loss"] = 495.0
    pos = dict(_trade("2026-10-26 12:00", "2026-10-26 15:30", 250, 250, 260), unrealized_pnl=1.0, stop_loss=247.5)
    a = account.account_state([before, win], [pos])
    assert a["trades"] == 1 and a["before_start"] == 1          # the 23 Oct trade predates the account
    assert a["balance"] == pytest.approx(100_000 + a["realized"])
    assert a["realized"] == pytest.approx(a["gross"] - a["charges"])
    assert a["in_positions"] == pytest.approx(400 * 250)        # ₹1,000 / ₹2.50 risk = 400 shares
    assert a["free"] == pytest.approx(a["balance"] - a["in_positions"])


def test_net_rupees_for_a_live_trade_without_a_time():
    from backtest_metrics import net_rupees
    # what the engine passes to the TRADE CLOSED alert: no "time" key (ABCD keeps it under "D")
    r = net_rupees({"entry": 1199.6, "exit_price": 1187.6, "target": 1180, "stop_loss": 1211.6})
    assert r is not None and r > 0
