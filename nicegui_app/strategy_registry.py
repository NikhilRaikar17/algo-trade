"""
strategy_registry.py — Helpers to load strategy definitions and enable flags from the DB.

Flags are read on every call (no caching) so toggles on the Strategies page take
effect on the next engine tick / page load without a restart.

Usage:
    get_strategies()               → [("ABCD", "abcd"), ...]           all, for labels
    get_strategy_rows()            → [{"key", "display_name", ...}]    Strategies page
    set_strategy_enabled("abcd", live=False)

    get_live_strategy_keys()       → ["abcd", "sma50"]   live engine / algo dropdown
    get_live_strategy_names()      → ["ABCD", "SMA50"]   live P&L (trade["strategy"] names)
    get_backtest_strategy_keys()   → ["abcd", ...]       backtest pages / sidebar
    get_backtest_strategy_names()  → ["ABCD", ...]       backtest P&L / email report
"""

from config import STRATEGY_NAMES
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


def get_strategy_rows() -> list[dict]:
    """Return every strategy with its enable flags, ordered by sort_order."""
    with SessionLocal() as s:
        rows = s.query(Strategy).order_by(Strategy.sort_order).all()
        return [
            {
                "key": r.key,
                "display_name": r.display_name,
                "short_name": r.short_name,
                "backtest_enabled": bool(r.backtest_enabled),
                "live_enabled": bool(r.live_enabled),
            }
            for r in rows
        ]


def set_strategy_enabled(key: str, *, backtest: bool | None = None, live: bool | None = None) -> None:
    """Update one strategy's backtest and/or live flag."""
    with SessionLocal() as s:
        row = s.query(Strategy).filter(Strategy.key == key).first()
        if row is None:
            return
        if backtest is not None:
            row.backtest_enabled = backtest
        if live is not None:
            row.live_enabled = live
        s.commit()


def get_live_strategy_keys() -> list[str]:
    return [r["key"] for r in get_strategy_rows() if r["live_enabled"]]


def get_live_strategy_names() -> list[str]:
    """Names used in live trade records (config.STRATEGY_NAMES), for enabled live strategies."""
    return [STRATEGY_NAMES[k] for k in get_live_strategy_keys() if k in STRATEGY_NAMES]


def get_backtest_strategy_keys() -> list[str]:
    return [r["key"] for r in get_strategy_rows() if r["backtest_enabled"]]


def get_backtest_strategy_names() -> list[str]:
    """Short names used in backtest trade records, for enabled backtest strategies."""
    return [r["short_name"] for r in get_strategy_rows() if r["backtest_enabled"]]
