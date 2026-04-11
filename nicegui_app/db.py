"""
db.py — SQLAlchemy engine and session factory for algo.db
"""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_PATH = Path(__file__).parent / "algo.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False}, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

TOP_STOCKS_CAP = 20


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session and closes it when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def sync_top_stocks(gainers: list[dict], losers: list[dict]) -> None:
    """
    Sync the top_stocks table with the latest gainers/losers.

    Rules:
    - Each entry in gainers/losers is {"name": str, "security_id": str}
    - Stocks newly appearing → INSERT with deleted=False, added_at=now
    - Stocks that disappeared → UPDATE deleted=True, deleted_at=now
    - Re-added stocks (were deleted) → INSERT a NEW row, deleted=False
    - Active list is capped at TOP_STOCKS_CAP (20). If adding new ones would
      exceed the cap, the oldest active rows (by added_at) are soft-deleted first.
    """
    # Import here to avoid circular import (models imports Base from db)
    from models import TopStock

    now = datetime.utcnow()
    db = SessionLocal()
    try:
        incoming = {s["security_id"]: s for s in gainers + losers}
        incoming_sides = {
            **{s["security_id"]: "gainer" for s in gainers},
            **{s["security_id"]: "loser"  for s in losers},
        }

        # Current active rows keyed by security_id
        active_rows: list[TopStock] = (
            db.query(TopStock).filter(TopStock.deleted == False).all()  # noqa: E712
        )
        active_by_sid = {r.security_id: r for r in active_rows}

        active_sids   = set(active_by_sid.keys())
        incoming_sids = set(incoming.keys())

        to_remove = active_sids - incoming_sids   # no longer in top results
        to_add    = incoming_sids - active_sids   # newly appeared

        # Soft-delete removed stocks
        for sid in to_remove:
            row = active_by_sid[sid]
            row.deleted    = True
            row.deleted_at = now

        # Enforce cap: if adding new ones exceeds the cap, soft-delete oldest active first
        remaining_active = active_sids - to_remove
        slots_available  = TOP_STOCKS_CAP - len(remaining_active)
        if slots_available < len(to_add):
            # Sort remaining active by added_at ascending (oldest first) and evict
            remaining_rows = sorted(
                [active_by_sid[sid] for sid in remaining_active],
                key=lambda r: r.added_at,
            )
            evict_count = len(to_add) - slots_available
            for row in remaining_rows[:evict_count]:
                row.deleted    = True
                row.deleted_at = now

        # Insert new stocks
        for sid in to_add:
            stock = incoming[sid]
            db.add(TopStock(
                name        = stock["name"],
                security_id = sid,
                side        = incoming_sides[sid],
                added_at    = now,
                deleted     = False,
                deleted_at  = None,
            ))

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_active_top_stocks() -> list[dict]:
    """Return all currently active (deleted=False) top stocks as a list of dicts."""
    from models import TopStock

    db = SessionLocal()
    try:
        rows = (
            db.query(TopStock)
            .filter(TopStock.deleted == False)  # noqa: E712
            .order_by(TopStock.added_at.desc())
            .all()
        )
        return [
            {"name": r.name, "security_id": r.security_id, "side": r.side}
            for r in rows
        ]
    finally:
        db.close()
