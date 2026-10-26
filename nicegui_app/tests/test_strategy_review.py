from strategy_review import GOOD, NOT_GOOD, TOO_EARLY, WATCH, SourceResult, judge_source, verdict

RULES = {"max_loss_rate": 50, "min_trades": 10}


def _src(trades, losses):
    status = "none" if not trades else "few" if trades < 10 else ("fail" if losses / trades * 100 > 50 else "pass")
    return SourceResult(trades=trades, losses=losses, loss_rate=losses / trades * 100 if trades else 0, status=status)


def test_losing_more_than_half_in_both_is_not_good():
    assert verdict(_src(20, 12), _src(10, 6), RULES)[0] == NOT_GOOD


def test_exactly_half_is_not_over_the_limit():
    assert verdict(_src(20, 10), _src(10, 5), RULES)[0] == GOOD


def test_one_pass_one_fail_is_watch():
    assert verdict(_src(20, 12), _src(10, 3), RULES)[0] == WATCH


def test_only_backtest_judged_follows_backtest():
    v, reasons = verdict(_src(20, 12), _src(3, 3), RULES)
    assert v == NOT_GOOD and "too few to judge" in reasons[1]


def test_too_few_everywhere_is_too_early():
    assert verdict(_src(5, 5), _src(0, 0), RULES)[0] == TOO_EARLY


def test_judge_source_counts_net_losses_after_charges():
    import pandas as pd
    parts = {k: 0 for k in ("brokerage", "stt", "exchange", "gst", "sebi", "stamp")}

    def t(i, net, gross):
        when = pd.Timestamp("2026-10-26 10:00", tz="Asia/Kolkata") + pd.Timedelta(minutes=15 * i)
        return {"net": net, "gross": gross, "charges": gross - net, "capital": 1e5, "ret_pct": 0.1,
                "time": when, "exit_time": when, "charge_parts": parts}
    sized = [t(i, 120.0, 150.0) for i in range(4)]
    sized += [t(4 + i, -10.0, 20.0) for i in range(6)]          # small gross wins eaten by charges
    r = judge_source(sized, RULES, 100_000)
    assert r.losses == 6 and r.loss_rate == 60 and r.status == "fail"
    assert r.end_balance == 100_000 + 4 * 120 - 6 * 10
