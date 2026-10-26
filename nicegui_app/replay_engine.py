"""
replay_engine.py — Monte Carlo trade replay ("time machine") on NSE 5-minute bars.

Given a trade (entry, stop, target, entry time), rebuild the rest of the session many
times from the stock's own recent 5-minute bars and report how often the target is hit
first, the stop first, or neither by the exit time. Also re-run the same trade (same
entry time, same % stop/target distances) on every past session as a real-data check.

Method (adapted from the day-trader-skill Time Machine, re-timed for NSE):
  • Pool: only FULL past sessions. The session length is read from the data (Dhan's 5-minute
    NSE bars stop at the 15:10 bar, not 15:25), and a full session has every bar up to it.
    Each bar becomes four ratios to the previous bar's close in the same session.
  • One replay: start at the entry price; for each remaining bar, draw a past bar from the
    same time of day (± window bars) and scale it to the current price. Stop is checked
    before target, so a bar that touches both counts as the stop.
  • R: +reward/risk at the target, −1 at the stop, otherwise (price at exit − entry)/risk.
Pure Python, no I/O — every number is reproducible from (candles, plan, seed).
"""

import random
import statistics
from dataclasses import dataclass, field
from datetime import date, time

SESSION_OPEN = time(9, 15)
BAR_MINUTES = 5
SESSION_BARS = 75          # 09:15 … 15:25 bar starts; the session closes at 15:30
MIN_SESSIONS = 20
SLOT_COVERAGE = 0.8        # a slot is part of the session if ≥80% of days have it


class ReplayError(ValueError):
    """A plan or data problem, with a message meant for the user."""


def slot_for(t: time) -> int:
    """Bar index of the bar that STARTS at t (09:15 → 0, 09:20 → 1, …)."""
    minutes = (t.hour * 60 + t.minute) - (SESSION_OPEN.hour * 60 + SESSION_OPEN.minute)
    if minutes < 0 or minutes % BAR_MINUTES:
        raise ReplayError(f"{t.strftime('%H:%M')} is not on the 5-minute grid from 09:15.")
    return minutes // BAR_MINUTES


def slot_time(slot: int) -> str:
    m = SESSION_OPEN.hour * 60 + SESSION_OPEN.minute + slot * BAR_MINUTES
    return f"{m // 60:02d}:{m % 60:02d}"


@dataclass
class Plan:
    entry: float
    stop: float
    target: float
    entry_time: time       # close time of the entry bar, e.g. 10:15
    exit_time: time = time(15, 30)

    @property
    def is_buy(self) -> bool:
        return self.target > self.entry

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward_r(self) -> float:
        return abs(self.target - self.entry) / self.risk

    def validate(self):
        if self.entry <= 0 or self.stop <= 0 or self.target <= 0:
            raise ReplayError("Entry, stop and target must all be positive prices.")
        if self.target == self.entry:
            raise ReplayError("Target equals the entry: there is nothing to replay.")
        if self.is_buy and self.stop >= self.entry:
            raise ReplayError("For a BUY (target above entry) the stop must be below the entry.")
        if not self.is_buy and self.stop <= self.entry:
            raise ReplayError("For a SELL (target below entry) the stop must be above the entry.")
        if self.risk < self.entry * 0.0005:
            raise ReplayError("Stop is under 0.05% from the entry: too tight to survive the spread.")
        start, end = self.start_slot, self.end_slot
        if start < 1:
            raise ReplayError("Entry time must be 09:20 or later (after the first bar closes).")
        if start >= end:
            raise ReplayError("Entry time must be before the exit time.")

    @property
    def start_slot(self) -> int:
        """First bar simulated: the bar that starts at the entry time."""
        return slot_for(self.entry_time)

    @property
    def end_slot(self) -> int:
        """One past the last bar simulated: bars starting before the exit time."""
        return min(slot_for(self.exit_time), SESSION_BARS)


@dataclass
class ReplayResult:
    replays: int
    seed: int
    sessions: int
    first_session: str
    last_session: str
    target_pct: float
    stop_pct: float
    neither_pct: float
    green_pct: float
    avg_r: float
    close_p5: float
    close_median: float
    close_p95: float
    exit_time: str = ""                             # when replays actually end (may be before the plan's)
    bands: list = field(default_factory=list)      # [{time, p5, p25, p50, p75, p95}]
    history: dict = field(default_factory=dict)    # {sessions, target, stop, neither, avg_r}
    verdict: str = ""
    notes: list = field(default_factory=list)


def build_sessions(candles, before: date | None = None) -> tuple[list[tuple[date, list[tuple]]], int]:
    """Group a candles DataFrame (timestamp tz Asia/Kolkata, open/high/low/close) into FULL
    sessions before `before`. Returns ([(date, [(o, h, l, c) × n_bars])], n_bars), oldest
    first, where n_bars is the session length the data actually has (see SLOT_COVERAGE)."""
    if candles is None or len(candles) == 0:
        return [], 0
    df = candles.sort_values("timestamp")
    days = []
    for d, day in df.groupby(df["timestamp"].dt.date):
        if before is not None and d >= before:
            continue
        bars = {}
        for ts, o, h, l, c in zip(day["timestamp"], day["open"], day["high"], day["low"], day["close"]):
            try:
                s = slot_for(ts.time())
            except ReplayError:
                continue  # off-grid tick
            if s < SESSION_BARS and None not in (o, h, l, c):
                bars[s] = (float(o), float(h), float(l), float(c))
        days.append((d, bars))
    if not days:
        return [], 0

    # Session length = leading run of slots that most days have
    n_bars = 0
    while n_bars < SESSION_BARS and sum(n_bars in b for _, b in days) >= SLOT_COVERAGE * len(days):
        n_bars += 1
    sessions = [(d, [b[i] for i in range(n_bars)]) for d, b in days
                if n_bars and all(i in b for i in range(n_bars))]
    return sessions, n_bars


def _ratio_pool(sessions, n_bars) -> list[list[tuple]]:
    """pool[slot] = [(o, h, l, c) / previous close] for every session; slot 0 has no in-session prev."""
    pool = [[] for _ in range(n_bars)]
    for _, bars in sessions:
        for i in range(1, n_bars):
            pc = bars[i - 1][3]
            if pc > 0:
                o, h, l, c = bars[i]
                pool[i].append((o / pc, h / pc, l / pc, c / pc))
    return pool


def _pct(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def _walk(plan: Plan, bars) -> tuple[str, float]:
    """Walk (o, h, l, c) bars after the entry. Returns (outcome, price at exit)."""
    price = plan.entry
    for o, h, l, c in bars:
        if plan.is_buy:
            if l <= plan.stop:
                return "stop", plan.stop
            if h >= plan.target:
                return "target", plan.target
        else:
            if h >= plan.stop:
                return "stop", plan.stop
            if l <= plan.target:
                return "target", plan.target
        price = c
    return "neither", price


def _r_multiple(plan: Plan, outcome: str, price: float) -> float:
    if outcome == "target":
        return plan.reward_r
    if outcome == "stop":
        return -1.0
    move = (price - plan.entry) if plan.is_buy else (plan.entry - price)
    return move / plan.risk


def _verdict(plan: Plan, target_n: int, stop_n: int, replays: int, exit_label: str) -> str:
    decided = target_n + stop_n
    if decided == 0:
        return f"No replay reached the stop or the target: the price at {exit_label} decides every one."
    if decided / replays < 0.2:
        # Too few decided replays for a lean to mean much — say what actually decides the trade
        return (f"Mostly undecided: {100 - decided / replays * 100:.1f}% of replays reach neither the stop "
                f"nor the target by {exit_label}, so the price at {exit_label} decides most outcomes.")
    share = target_n / decided * 100
    breakeven = 100 / (1 + plan.reward_r)
    gap = share - breakeven
    label = f"target first in {share:.1f}% of replays that hit a side (break-even {breakeven:.1f}% at {plan.reward_r:.2f}R)"
    if abs(gap) < 5:
        head = "Close to a coin flip" if abs(plan.reward_r - 1) < 0.05 else "Close to break-even"
    elif abs(gap) < 15:
        head = "Leans toward the target" if gap > 0 else "Leans toward the stop"
    else:
        head = "Strongly toward the target" if gap > 0 else "Strongly toward the stop"
    return f"{head}: {label}."


def run_replay(candles, plan: Plan, trade_date: date, replays: int = 10_000, seed: int = 19,
               window: int = 2) -> ReplayResult:
    """Simulate the rest of `trade_date`'s session `replays` times from sessions before it."""
    plan.validate()
    sessions, n_bars = build_sessions(candles, before=trade_date)
    if len(sessions) < MIN_SESSIONS:
        raise ReplayError(
            f"Only {len(sessions)} full past sessions in the data; at least {MIN_SESSIONS} are needed."
        )
    pool = _ratio_pool(sessions, n_bars)
    start, end = plan.start_slot, min(plan.end_slot, n_bars)
    data_end = slot_time(n_bars)  # close time of the last bar the data has
    if start >= end:
        raise ReplayError(f"The data's last 5-minute bar closes at {data_end}: enter before that.")
    clipped = end < plan.end_slot
    exit_label = data_end if clipped else plan.exit_time.strftime("%H:%M")

    # Candidate bars per slot: same time of day ± window (never slot 0, which has no ratio)
    candidates = {}
    for s in range(start, end):
        cands = []
        for k in range(max(1, s - window), min(n_bars - 1, s + window) + 1):
            cands.extend(pool[k])
        candidates[s] = cands

    rng = random.Random(seed)
    counts = {"target": 0, "stop": 0, "neither": 0}
    green = 0
    r_total = 0.0
    finals = []
    closes_by_slot = {s: [] for s in range(start, end)}

    for _ in range(replays):
        price = plan.entry
        outcome = None
        for s in range(start, end):
            ro, rh, rl, rc = rng.choice(candidates[s])
            h, l, c = price * rh, price * rl, price * rc
            if outcome is None:
                if plan.is_buy:
                    if l <= plan.stop:
                        outcome = "stop"
                    elif h >= plan.target:
                        outcome = "target"
                else:
                    if h >= plan.stop:
                        outcome = "stop"
                    elif l <= plan.target:
                        outcome = "target"
            price = c
            closes_by_slot[s].append(price)
        outcome = outcome or "neither"
        counts[outcome] += 1
        r = _r_multiple(plan, outcome, price)
        r_total += r
        if outcome == "target" or (outcome == "neither" and r > 0):
            green += 1
        finals.append(price)

    finals.sort()
    bands = []
    for s in range(start, end):
        vals = sorted(closes_by_slot[s])
        bands.append({
            "time": slot_time(s + 1),  # close time of bar s
            "p5": round(_pct(vals, 0.05), 2), "p25": round(_pct(vals, 0.25), 2),
            "p50": round(_pct(vals, 0.50), 2), "p75": round(_pct(vals, 0.75), 2),
            "p95": round(_pct(vals, 0.95), 2),
        })

    # Real-data check: same entry time and same % distances on every past session
    stop_pct = (plan.stop - plan.entry) / plan.entry
    target_pct = (plan.target - plan.entry) / plan.entry
    hist = {"target": 0, "stop": 0, "neither": 0}
    hist_r = []
    for _, bars in sessions:
        e = bars[start - 1][3]  # close of the bar before the entry time
        past = Plan(e, e * (1 + stop_pct), e * (1 + target_pct), plan.entry_time, plan.exit_time)
        outcome, price = _walk(past, bars[start:end])
        hist[outcome] += 1
        hist_r.append(_r_multiple(past, outcome, price))

    n = replays
    result = ReplayResult(
        replays=n, seed=seed, sessions=len(sessions),
        first_session=sessions[0][0].isoformat(), last_session=sessions[-1][0].isoformat(),
        target_pct=round(counts["target"] / n * 100, 1),
        stop_pct=round(counts["stop"] / n * 100, 1),
        neither_pct=round(counts["neither"] / n * 100, 1),
        green_pct=round(green / n * 100, 1),
        avg_r=round(r_total / n, 3),
        close_p5=round(_pct(finals, 0.05), 2),
        close_median=round(_pct(finals, 0.50), 2),
        close_p95=round(_pct(finals, 0.95), 2),
        bands=bands,
        history={**hist, "sessions": len(sessions), "avg_r": round(statistics.fmean(hist_r), 3)},
        exit_time=exit_label,
        verdict=_verdict(plan, counts["target"], counts["stop"], n, exit_label),
    )
    if clipped:
        result.notes.insert(0, f"The 5-minute data ends with the bar closing at {data_end}, so replays stop "
                               f"there, not at {plan.exit_time.strftime('%H:%M')}.")
    if 40 < result.neither_pct <= 80:
        result.notes.append(
            f"{result.neither_pct}% of replays hit neither side by {exit_label}; the price at {exit_label} decides those."
        )
    leans_target = counts["target"] / max(1, counts["target"] + counts["stop"]) > 1 / (1 + plan.reward_r)
    if (result.avg_r < 0 and leans_target) or (result.avg_r > 0 and not leans_target):
        result.notes.append(
            f"Average R is {result.avg_r:+.3f}, against the lean: the replays that hit neither side pull it the other way."
        )
    return result
