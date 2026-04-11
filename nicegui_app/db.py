"""
db.py — SQLAlchemy engine and session factory for algo.db
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_PATH = Path(__file__).parent / "algo.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False}, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session and closes it when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
