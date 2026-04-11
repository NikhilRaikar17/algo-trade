"""
strategies.py — Helpers to load strategy definitions from the DB.

Usage:
    from strategies import get_strategies, get_strategy_keys, get_strategy_short_names

    # For algo.py dropdowns: list of (display_name, key)
    get_strategies()          → [("ABCD Harmonic", "abcd"), ("Double Top", "dt"), ...]

    # For pnl_tab / email_report: list of short names
    get_strategy_short_names() → ["ABCD", "Double Top", "Double Bottom", ...]
"""

from db import SessionLocal
from models import Strategy


def get_strategies() -> list[tuple[str, str]]:
    """Return (display_name, key) pairs ordered by sort_order. Used for dropdowns."""
    with SessionLocal() as s:
        rows = s.query(Strategy).order_by(Strategy.sort_order).all()
        return [(r.display_name, r.key) for r in rows]


def get_strategy_short_names() -> list[str]:
    """Return short_name values ordered by sort_order. Used for P&L grouping."""
    with SessionLocal() as s:
        rows = s.query(Strategy).order_by(Strategy.sort_order).all()
        return [r.short_name for r in rows]
