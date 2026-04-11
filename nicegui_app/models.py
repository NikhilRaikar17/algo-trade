"""
models.py — SQLAlchemy ORM models and Pydantic validation schemas.
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from pydantic import BaseModel, field_validator

from db import Base


# ── ORM ───────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    username        = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    last_login      = Column(DateTime, nullable=True)


class Strategy(Base):
    """Trading strategy registry. One row per strategy."""
    __tablename__ = "strategies"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    key          = Column(String, unique=True, nullable=False)   # e.g. "abcd"
    display_name = Column(String, nullable=False)                # e.g. "ABCD Harmonic"
    short_name   = Column(String, nullable=False)                # e.g. "ABCD" (used in trade records)
    sort_order   = Column(Integer, nullable=False, default=0)


class UserSession(Base):
    """Server-side session record. One row per active login."""
    __tablename__ = "sessions"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    session_key = Column(String, unique=True, nullable=False)   # secrets.token_hex(32)
    username    = Column(String, ForeignKey("users.username"), nullable=False)
    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at  = Column(DateTime, nullable=False)


class TopStock(Base):
    """
    Persistent rolling list of top NIFTY 50 movers (capped at 20 active rows).

    - On add   : insert new row with deleted=False, added_at=now
    - On remove: set deleted=True, deleted_at=now  (row is kept)
    - On re-add: insert a NEW row with deleted=False, added_at=now
    """
    __tablename__ = "top_stocks"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String, nullable=False)        # e.g. "RELIANCE"
    security_id = Column(String, nullable=False)        # e.g. "2885"
    side        = Column(String, nullable=False)        # "gainer" | "loser"
    added_at    = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted     = Column(Boolean, nullable=False, default=False)
    deleted_at  = Column(DateTime, nullable=True)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_not_empty(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("username must not be empty")
        return v

    @field_validator("password")
    @classmethod
    def password_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("password must not be empty")
        return v


class LoginResponse(BaseModel):
    success: bool
    username: str | None = None
    session_key: str | None = None
    message: str = ""


class UserPublic(BaseModel):
    username: str

    model_config = {"from_attributes": True}


class SessionPublic(BaseModel):
    session_key: str
    username: str
    created_at: datetime
    expires_at: datetime

    model_config = {"from_attributes": True}
