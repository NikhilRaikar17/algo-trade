import pandas as pd

import analysis_email as ae
from backtest_metrics import size_trades

IST = "Asia/Kolkata"


def _trade(time, exit_time, entry, exit_px, stop, target, strategy, key, stock="X", status="Target Hit"):
    return {"time": pd.Timestamp(time, tz=IST), "exit_time": pd.Timestamp(exit_time, tz=IST), "entry": entry,
            "exit_price": exit_px, "stop_loss": stop, "target": target, "status": status, "stock": stock,
            "strategy": strategy, "strategy_key": key, "trade_date": time[:10],
            "pnl": (exit_px - entry) if target > entry else (entry - exit_px)}


def _data():
    now = pd.Timestamp("2026-10-26 15:45", tz=IST)
    live = [_trade("2026-10-26 10:00", "2026-10-26 11:00", 500, 510, 495, 510, "ABCD", "abcd", "INFY")]
    sized = size_trades(live, "risk", 1000, 100_000, compound=True)
    acct = {"initial": 100_000, "start": pd.Timestamp("2026-10-26 09:00", tz=IST), "balance": 100_000 + sized[0]["net"],
            "return_pct": sized[0]["net"] / 1000, "free": 100_000, "in_positions": 0, "open": 0, "unrealized": 0,
            "sized": sized}
    backtest = [_trade("2026-10-26 12:00", "2026-10-26 13:00", 200, 198, 202, 196, "EMA 10", "ema10", "TCS")
                for _ in range(1)]
    backtest[0]["status"] = "Target Hit"
    loser = _trade("2026-10-26 13:15", "2026-10-26 14:00", 300, 297, 297, 306, "EMA 10", "ema10", "WIPRO", "SL Hit")
    rows = [{"key": "abcd", "display_name": "ABCD", "live_enabled": True, "backtest_enabled": True},
            {"key": "ema10", "display_name": "EMA 10", "live_enabled": False, "backtest_enabled": True}]
    opt = [_trade("2026-10-26 11:00", "2026-10-26 11:40", 200, 198.5, 198.5, 210, "SMA50", "sma50",
                  "NIFTY 09NOV 22750 CE", "SL Hit")]
    opt_sized = size_trades(opt, "risk", 1000, 200_000, compound=True)
    for t in opt_sized:
        t["lot_size"], t["qty"] = 65, 130
    opts = dict(acct, initial=200_000, balance=200_000 + opt_sized[0]["net"], free=200_000,
                return_pct=opt_sized[0]["net"] / 2000, sized=opt_sized)
    # long term: entered last week, closed today (counted on its exit day, not its entry day)
    lt = [_trade("2026-10-20 15:15", "2026-10-26 10:30", 1000, 1060, 970, 1060, "LT 20D Breakout", "lt_breakout",
                 "RELIANCE")]
    lt_sized = size_trades(lt, "risk", 2000, 100_000, compound=True)
    lts = dict(acct, balance=100_000 + lt_sized[0]["net"], return_pct=lt_sized[0]["net"] / 1000, sized=lt_sized)
    return {"now": now, "rows": rows, "backtest": backtest + [loser], "backtest_report": {"loaded": ["X"], "missing": []},
            "live": live, "account": acct, "options": opts, "longterm": lts}


def test_live_results_only_stocks_and_options():
    ins = ae.insights(_data())
    assert any(x.startswith("ABCD made ₹") and "on stocks today" in x for x in ins["right"])
    assert any(x.startswith("SMA50 lost ₹") and "on options today" in x for x in ins["wrong"])
    assert any("Worst trade: NIFTY 09NOV 22750 CE BUY" in x for x in ins["wrong"])
    assert any(x.startswith("LT 20D Breakout made ₹") and "on long term today" in x for x in ins["right"])
    lines = " ".join(ins["right"] + ins["wrong"])
    assert "WIPRO" not in lines and "TCS" not in lines and "backtest" not in lines.lower().replace("backtest losing", "")
    assert not any("−₹" in x and "lost" in x for x in ins["right"] + ins["wrong"])   # no "lost −₹…"


def test_email_has_live_report_and_analysis_and_subject():
    ins = ae.insights(_data())
    html = ae.build_html(ins, "Monday, 26 Oct 2026")
    for part in ("LIVE report", "Stocks", "INFY", "Options · NIFTY", "NIFTY 09NOV 22750 CE", "2 lots (130)",
                 "Long term · NIFTY futures", "RELIANCE", "Long-term net",
                 "Strategy analysis", "What went right", "Which strategies work", "BACKTEST email"):
        assert part in html
    assert "Backtest net" not in html and "TCS" not in html          # no backtest ₹ in the live email
    subject = ae.build_subject(ins)
    assert subject.startswith("[AlgoTrading] LIVE report & strategy analysis — 2026-10-26")
    assert "stocks +₹" in subject and "options −₹" in subject and "long term +₹" in subject


def test_sends_only_in_the_window_and_once(monkeypatch):
    sent, marked = [], set()
    monkeypatch.setattr(ae, "_is_already_sent", lambda k: k in marked)
    monkeypatch.setattr(ae, "_mark_sent", marked.add)
    monkeypatch.setattr(ae, "_is_trading_day", lambda now: True)
    monkeypatch.setattr(ae, "gather", lambda now: _data())
    import email_report
    monkeypatch.setattr(email_report, "_send_email", lambda *a: sent.append(a[0]))
    for hhmm in ("15:44", "15:45", "15:46", "15:56"):
        monkeypatch.setattr(ae, "now_ist", lambda h=hhmm: pd.Timestamp(f"2026-10-26 {h}", tz=IST))
        ae.send_strategy_analysis_email()
    assert len(sent) == 1
