"""Tests for economic_calendar.get_upcoming_events."""
from datetime import date
from unittest.mock import patch

import pytest


def test_returns_n_events():
    from economic_calendar import get_upcoming_events
    with patch("economic_calendar._today", return_value=date(2026, 1, 1)):
        events = get_upcoming_events(n=3)
    assert len(events) == 3


def test_events_are_in_future_only():
    from economic_calendar import get_upcoming_events
    today = date(2026, 6, 15)
    with patch("economic_calendar._today", return_value=today):
        events = get_upcoming_events(n=10)
    for ev in events:
        assert ev["date"] >= today, f"Past event returned: {ev}"


def test_events_sorted_ascending():
    from economic_calendar import get_upcoming_events
    with patch("economic_calendar._today", return_value=date(2026, 1, 1)):
        events = get_upcoming_events(n=10)
    dates = [ev["date"] for ev in events]
    assert dates == sorted(dates)


def test_event_has_required_keys():
    from economic_calendar import get_upcoming_events
    with patch("economic_calendar._today", return_value=date(2026, 1, 1)):
        events = get_upcoming_events(n=1)
    ev = events[0]
    assert "date" in ev
    assert "label" in ev
    assert "type" in ev
    assert ev["type"] in ("expiry", "rbi", "fed")


def test_returns_empty_if_no_future_events():
    from economic_calendar import get_upcoming_events
    # Far future date — no events defined beyond 2026
    with patch("economic_calendar._today", return_value=date(2030, 1, 1)):
        events = get_upcoming_events(n=5)
    assert events == []
