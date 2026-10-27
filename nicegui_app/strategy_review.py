"""
Strategy Analysis verdicts — pure logic, no UI and no API calls.

Each strategy is judged on two sources, its backtest and its live trades, each sized like the paper
account (risk the max loss at the stop, ₹ funds, compounding) and net of brokerage and taxes:

    loss rate = trades with a net loss ÷ all trades

A source with fewer than STRATEGY_REVIEW["min_trades"] trades is "too few to judge". The verdict:
    Not good   — every source with enough trades loses on more than max_loss_rate % of them
    Watch      — one source passes and the other fails
    Good       — every source with enough trades passes
    Too early  — neither source has enough trades
"""

from collections import defaultdict
from dataclasses import dataclass, field

from backtest_metrics import DEFAULT_FUNDS, DEFAULT_MODE, DEFAULT_SIZING, size_trades, summarize
from config import STRATEGY_NAMES, STRATEGY_REVIEW

NOT_GOOD, WATCH, GOOD, TOO_EARLY = "Not good", "Watch", "Good", "Too early"


@dataclass
class SourceResult:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    loss_rate: float = 0.0          # %
    net: float = 0.0                # ₹ after charges
    charges: float = 0.0
    end_balance: float | None = None
    status: str = "none"            # pass / fail / few / none


@dataclass
class StrategyReview:
    key: str
    name: str
    backtest: SourceResult
    live: SourceResult
    verdict: str = TOO_EARLY
    reasons: list = field(default_factory=list)


def judge_source(sized: list[dict], rules: dict, start_funds: float | None = None) -> SourceResult:
    s = summarize(sized)
    r = SourceResult(trades=s["trades"], wins=s["wins"], losses=s["losses"], net=s["net"], charges=s["charges"])
    r.loss_rate = s["losses"] / s["trades"] * 100 if s["trades"] else 0.0
    if start_funds:
        r.end_balance = start_funds + s["net"]
    if not s["trades"]:
        r.status = "none"
    elif s["trades"] < rules["min_trades"]:
        r.status = "few"
    else:
        r.status = "fail" if r.loss_rate > rules["max_loss_rate"] else "pass"
    return r


def verdict(backtest: SourceResult, live: SourceResult, rules: dict) -> tuple[str, list[str]]:
    limit = rules["max_loss_rate"]
    reasons = []
    judged = []
    for label, src in (("Backtest", backtest), ("Live", live)):
        if src.status in ("pass", "fail"):
            judged.append(src.status)
            word = "loses on" if src.status == "fail" else "only loses on"
            reasons.append(f"{label} {word} {src.loss_rate:.0f}% of {src.trades} trades "
                           f"({'over' if src.status == 'fail' else 'within'} the {limit}% limit)")
        else:
            reasons.append(f"{label}: {src.trades} trade{'s' if src.trades != 1 else ''}, "
                           f"too few to judge (needs {rules['min_trades']})")
    if not judged:
        return TOO_EARLY, reasons
    if all(j == "fail" for j in judged):
        return NOT_GOOD, reasons
    if all(j == "pass" for j in judged):
        return GOOD, reasons
    return WATCH, reasons


def _name_to_key() -> dict[str, str]:
    """Live trades are tagged with config.STRATEGY_NAMES values; map them back to keys."""
    return {v: k for k, v in STRATEGY_NAMES.items()}


def build_reviews(backtest_trades: list[dict], live_trades: list[dict], strategy_rows: list[dict],
                  live_funds: float) -> list[StrategyReview]:
    """One review per strategy. Each source is sized as its own account: risk the max loss at the
    stop, cut to the funds, compounding, after charges."""
    mode, amount, rules = DEFAULT_MODE, DEFAULT_SIZING[DEFAULT_MODE], STRATEGY_REVIEW
    by_key_bt, by_key_live = defaultdict(list), defaultdict(list)
    for t in backtest_trades:
        by_key_bt[t.get("strategy_key")].append(t)
    names = _name_to_key()
    for t in live_trades:
        by_key_live[names.get(t.get("strategy"), t.get("strategy"))].append(t)
    out = []
    for row in strategy_rows:
        k = row["key"]
        bt = judge_source(size_trades(by_key_bt[k], mode, amount, DEFAULT_FUNDS, compound=True), rules, DEFAULT_FUNDS)
        lv = judge_source(size_trades(by_key_live[k], mode, amount, live_funds, compound=True), rules, live_funds)
        v, reasons = verdict(bt, lv, rules)
        out.append(StrategyReview(key=k, name=row["display_name"], backtest=bt, live=lv, verdict=v, reasons=reasons))
    order = {NOT_GOOD: 0, WATCH: 1, GOOD: 2, TOO_EARLY: 3}
    return sorted(out, key=lambda r: (order[r.verdict], -r.backtest.trades))
