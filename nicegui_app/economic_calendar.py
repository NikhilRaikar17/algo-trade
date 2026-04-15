"""
Economic calendar: NSE expiry dates, RBI MPC dates, US Fed FOMC dates for 2026.
"""
from datetime import date


def _today() -> date:
    """Returns today's date. Separated for easy mocking in tests."""
    return date.today()


# ── NSE Monthly expiry dates (last Thursday of each month, 2026) ──────────────
_NSE_MONTHLY_EXPIRIES = [
    date(2026, 1, 29),
    date(2026, 2, 26),
    date(2026, 3, 26),
    date(2026, 4, 30),
    date(2026, 5, 28),
    date(2026, 6, 25),
    date(2026, 7, 30),
    date(2026, 8, 27),
    date(2026, 9, 24),
    date(2026, 10, 29),
    date(2026, 11, 26),
    date(2026, 12, 31),
]

# ── RBI MPC decision dates 2026 ───────────────────────────────────────────────
_RBI_MPC_DATES = [
    date(2026, 2, 7),
    date(2026, 4, 9),
    date(2026, 6, 6),
    date(2026, 8, 7),
    date(2026, 10, 9),
    date(2026, 12, 4),
]

# ── US Fed FOMC decision dates 2026 ──────────────────────────────────────────
_FED_FOMC_DATES = [
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 5, 6),
    date(2026, 6, 10),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 9),
]


def _all_events() -> list[dict]:
    events = []
    for d in _NSE_MONTHLY_EXPIRIES:
        events.append({"date": d, "label": "NSE Monthly Expiry", "type": "expiry"})
    for d in _RBI_MPC_DATES:
        events.append({"date": d, "label": "RBI MPC Decision", "type": "rbi"})
    for d in _FED_FOMC_DATES:
        events.append({"date": d, "label": "US Fed FOMC Decision", "type": "fed"})
    return sorted(events, key=lambda e: e["date"])


def get_upcoming_events(n: int = 5) -> list[dict]:
    """Return the next n events on or after today, sorted ascending by date."""
    today = _today()
    future = [e for e in _all_events() if e["date"] >= today]
    return future[:n]
