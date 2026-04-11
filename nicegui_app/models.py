"""
models.py — SQLAlchemy ORM models and Pydantic validation schemas.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String
from pydantic import BaseModel, field_validator

from db import Base


# ── ORM ───────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    username        = Column(String, primary_key=True, nullable=False)
    hashed_password = Column(String, nullable=False)


class UserSession(Base):
    """Server-side session record. One row per active login."""
    __tablename__ = "sessions"

    session_key = Column(String, primary_key=True, nullable=False)   # secrets.token_hex(32)
    username    = Column(String, ForeignKey("users.username"), nullable=False)
    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at  = Column(DateTime, nullable=False)


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
