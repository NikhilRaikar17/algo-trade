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
