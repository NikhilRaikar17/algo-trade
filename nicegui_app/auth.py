"""
auth.py — Password hashing, session creation/validation/invalidation.

On first import:
  • Creates algo.db tables (users + sessions) via db.py / models.py
  • Seeds nikhil, bharath, indresh with username == password (hashed)
  • Seeds strategies table (ABCD, Double Top, Double Bottom, EMA 10, SMA 50)

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
from models import User, UserSession, Strategy, TopStock, UserActivityLog  # noqa: F401 — imported for side-effect: ensures all tables are created by Base.metadata.create_all

# ── Password context ──────────────────────────────────────────────────────────
# sha256_crypt avoids bcrypt/passlib version incompatibilities on Windows
pwd_ctx = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

# Session lifetime
SESSION_TTL_HOURS = 12

# ── Schema migration: recreate tables if they lack an id column ───────────────
# Needed when upgrading from the original schema (username/key/session_key as PK)
# to the new schema (integer id as PK). All data is reseedable so we drop+recreate.
def _needs_id_column(conn, table: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return not any(r[1] == "id" for r in rows)

with engine.connect() as _conn:
    for _tbl in ("users", "strategies", "sessions"):
        try:
            if _needs_id_column(_conn, _tbl):
                _conn.execute(text(f"DROP TABLE IF EXISTS {_tbl}"))
        except Exception:
            pass
    _conn.commit()

# ── Schema creation ───────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

# ── Seed users (idempotent) ───────────────────────────────────────────────────
_SEED: list[tuple[str, str]] = [
    ("nikhil",  "nikhil"),
    ("bharath", "bharath"),
    ("indresh", "indresh"),
]

with SessionLocal() as _s:
    for _uname, _pw in _SEED:
        exists = _s.query(User).filter(User.username == _uname).first()
        if exists is None:
            _s.add(User(username=_uname, hashed_password=pwd_ctx.hash(_pw)))
            _s.flush()
    _s.commit()

# ── Seed strategies (idempotent) ──────────────────────────────────────────────
# key: short code used in trade records and dispatch
# display_name: shown in dropdowns
# short_name: used in trade["strategy"] field and P&L grouping
_SEED_STRATEGIES: list[tuple[str, str, str, int]] = [
    ("abcd",  "ABCD",                    "ABCD",                    1),
    ("dtc",   "Double Top Customized",   "Double Top Customized",   2),
    ("dts",   "Double Top Standard",     "Double Top Standard",     3),
    ("db",    "Double Bottom",           "Double Bottom",           4),
    ("ema10", "EMA 10",                  "EMA 10",                  5),
    ("sma50", "SMA 50",                  "SMA 50",                  6),
]

with SessionLocal() as _s:
    for _key, _display, _short, _order in _SEED_STRATEGIES:
        exists = _s.query(Strategy).filter(Strategy.key == _key).first()
        if exists is None:
            _s.add(Strategy(
                key=_key,
                display_name=_display,
                short_name=_short,
                sort_order=_order,
            ))
        else:
            exists.display_name = _display
            exists.short_name = _short
            exists.sort_order = _order
    _s.commit()


# ── Credential verification ───────────────────────────────────────────────────

def verify_user(username: str, password: str) -> bool:
    """Return True if credentials are valid."""
    with SessionLocal() as s:
        user = s.query(User).filter(User.username == username.strip().lower()).first()
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
            log_row = s.query(UserActivityLog).filter(
                UserActivityLog.session_key == row.session_key
            ).first()
            if log_row and log_row.logout_at is None:
                log_row.logout_at = now
            s.delete(row)
        s.flush()

        s.add(UserSession(
            session_key=key,
            username=username,
            created_at=now,
            expires_at=expires,
        ))

        # Record last login timestamp
        user = s.query(User).filter(User.username == username).first()
        if user:
            user.last_login = now

        s.add(UserActivityLog(
            username=username,
            session_key=key,
            login_at=now,
            logout_at=None,
        ))

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
        row: UserSession | None = s.query(UserSession).filter(UserSession.session_key == session_key).first()
        if row is None:
            return None
        if datetime.utcnow() > row.expires_at:
            log_row = s.query(UserActivityLog).filter(
                UserActivityLog.session_key == session_key
            ).first()
            if log_row and log_row.logout_at is None:
                log_row.logout_at = row.expires_at
            s.delete(row)
            s.commit()
            return None
        return row.username


def invalidate_session(session_key: str) -> None:
    """Delete the session row so the key can never be reused."""
    if not session_key:
        return
    with SessionLocal() as s:
        row = s.query(UserSession).filter(UserSession.session_key == session_key).first()
        if row:
            s.delete(row)
            log_row = s.query(UserActivityLog).filter(
                UserActivityLog.session_key == session_key
            ).first()
            if log_row and log_row.logout_at is None:
                log_row.logout_at = datetime.utcnow()
            s.commit()
