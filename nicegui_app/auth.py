"""
auth.py — Password hashing, session creation/validation/invalidation.

On first import:
  • Creates algo.db tables (users + sessions) via db.py / models.py
  • Seeds nikhil, bharath, indresh with username == password (hashed)

Session flow:
  login  → create_session()   → returns a session_key (stored in cookie)
  page   → validate_session() → looks up session_key in DB, checks expiry
  logout → invalidate_session() → deletes the DB row, clears cookie
"""

import secrets
from datetime import datetime, timedelta

from passlib.context import CryptContext
from sqlalchemy import text

from db import Base, SessionLocal, engine
from models import User, UserSession

# ── Password context ──────────────────────────────────────────────────────────
# sha256_crypt avoids bcrypt/passlib version incompatibilities on Windows
pwd_ctx = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

# Session lifetime
SESSION_TTL_HOURS = 12

# ── Schema creation ───────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

# Add last_login column to existing databases that pre-date this column
with engine.connect() as _conn:
    try:
        _conn.execute(text("ALTER TABLE users ADD COLUMN last_login DATETIME"))
        _conn.commit()
    except Exception:
        pass  # Column already exists

# ── Seed users (idempotent) ───────────────────────────────────────────────────
_SEED: list[tuple[str, str]] = [
    ("nikhil",  "nikhil"),
    ("bharath", "bharath"),
    ("indresh", "indresh"),
]

with SessionLocal() as _s:
    for _uname, _pw in _SEED:
        if _s.get(User, _uname) is None:
            _s.add(User(username=_uname, hashed_password=pwd_ctx.hash(_pw)))
            _s.flush()
    _s.commit()


# ── Credential verification ───────────────────────────────────────────────────

def verify_user(username: str, password: str) -> bool:
    """Return True if credentials are valid."""
    with SessionLocal() as s:
        user = s.get(User, username.strip().lower())
        if user is None:
            return False
        return pwd_ctx.verify(password, user.hashed_password)


# ── Session management ────────────────────────────────────────────────────────

def create_session(username: str) -> str:
    """
    Create a new server-side session for *username*.
    Returns the session_key that should be stored in the browser cookie.
    Any pre-existing sessions for this user are invalidated first (single active session).
    """
    key = secrets.token_hex(32)          # 256 bits of randomness
    now = datetime.utcnow()
    expires = now + timedelta(hours=SESSION_TTL_HOURS)

    with SessionLocal() as s:
        # Remove any stale sessions for this user
        stale = s.query(UserSession).filter(UserSession.username == username).all()
        for row in stale:
            s.delete(row)
        s.flush()

        s.add(UserSession(
            session_key=key,
            username=username,
            created_at=now,
            expires_at=expires,
        ))

        # Record last login timestamp
        user = s.get(User, username)
        if user:
            user.last_login = now

        s.commit()

    return key


def validate_session(session_key: str) -> str | None:
    """
    Look up *session_key* in the DB.
    Returns the username if the session exists and has not expired, else None.
    Expired sessions are deleted on the spot.
    """
    if not session_key:
        return None

    with SessionLocal() as s:
        row: UserSession | None = s.get(UserSession, session_key)
        if row is None:
            return None
        if datetime.utcnow() > row.expires_at:
            s.delete(row)
            s.commit()
            return None
        return row.username


def invalidate_session(session_key: str) -> None:
    """Delete the session row so the key can never be reused."""
    if not session_key:
        return
    with SessionLocal() as s:
        row = s.get(UserSession, session_key)
        if row:
            s.delete(row)
            s.commit()
