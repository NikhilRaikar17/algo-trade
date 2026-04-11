"""
routes/auth_routes.py — FastAPI auth endpoints mounted onto the NiceGUI app.

GET  /api/users/{username}   — fetch a user's public profile
POST /api/auth/login         — validate credentials, create server-side session
POST /api/auth/logout        — invalidate session by session_key
GET  /api/sessions/{key}     — inspect a session (admin / debug)
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from models import LoginRequest, LoginResponse, SessionPublic, User, UserPublic
from auth import create_session, invalidate_session, pwd_ctx, validate_session

router = APIRouter(prefix="/api", tags=["auth"])


# ── GET /api/users/{username} ─────────────────────────────────────────────────

@router.get("/users/{username}", response_model=UserPublic)
def get_user(username: str, db: Session = Depends(get_db)):
    """Return public profile for a user. 404 if not found."""
    user: User | None = db.get(User, username.strip().lower())
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ── POST /api/auth/login ──────────────────────────────────────────────────────

@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Validate credentials, create a server-side session, return the session_key.
    The caller should store session_key in a secure HttpOnly cookie.
    """
    user: User | None = db.get(User, payload.username)
    if user is None or not pwd_ctx.verify(payload.password, user.hashed_password):
        return LoginResponse(success=False, message="Invalid username or password")

    key = create_session(user.username)
    return LoginResponse(success=True, username=user.username, session_key=key)


# ── POST /api/auth/logout ─────────────────────────────────────────────────────

@router.post("/auth/logout")
def logout(x_session_key: str = Header(..., alias="X-Session-Key")):
    """
    Invalidate the session identified by the X-Session-Key request header.
    Always returns 200 — even if the key was already gone.
    """
    invalidate_session(x_session_key)
    return {"success": True}


# ── GET /api/sessions/{key} ───────────────────────────────────────────────────

@router.get("/sessions/{key}", response_model=SessionPublic)
def inspect_session(key: str, db: Session = Depends(get_db)):
    """
    Return session metadata for *key*. 401 if missing or expired.
    Useful for debugging and health checks.
    """
    from models import UserSession
    row: UserSession | None = db.get(UserSession, key)
    if row is None:
        raise HTTPException(status_code=401, detail="Session not found or expired")
    username = validate_session(key)
    if username is None:
        raise HTTPException(status_code=401, detail="Session expired")
    return row
