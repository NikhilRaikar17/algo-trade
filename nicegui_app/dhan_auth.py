"""
Automatic Dhan access-token refresh via TOTP.

Dhan tokens expire after 24 h. With TOTP enabled on the Dhan account, a fresh
token can be generated without logging in:

    POST https://auth.dhan.co/app/generateAccessToken?dhanClientId=..&pin=..&totp=..

Required in .env:
    DHAN_CLIENT_CODE   — Dhan client ID
    DHAN_PIN           — 6-digit Dhan login PIN
    DHAN_TOTP_SECRET   — base32 secret shown when enabling TOTP on Dhan Web

The new token is written back to DHAN_TOKEN_ID in .env; config.py's file
watcher then re-initialises the dhan client.
"""

import base64
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta

import pyotp
import requests

GENERATE_URL = "https://auth.dhan.co/app/generateAccessToken"
PROFILE_URL = "https://api.dhan.co/v2/profile"

# Refresh pre-market so one token covers the whole session.
PREMARKET_START = (7, 0)
PREMARKET_END = (9, 10)
CHECK_INTERVAL_SECONDS = 15 * 60
MIN_REMAINING = timedelta(minutes=10)

_lock = threading.Lock()
_validity_cache: dict = {}  # {token: datetime} — only the current token is kept
# Why the last fetch_token_validity() returned None: "rejected" (Dhan refused the token, e.g. it was
# replaced by a newer one or expired), "unreachable" (network / unexpected reply), or None after a success.
last_validity_error: str | None = None


def fetch_token_validity() -> datetime | None:
    """Expiry of the current token as reported by Dhan's profile API (`tokenValidity`).

    Cached per token, since a token's expiry never changes. None if Dhan rejects the token or can't
    be reached; last_validity_error says which.
    """
    global last_validity_error
    token = os.getenv("DHAN_TOKEN_ID", "")
    if not token:
        last_validity_error = "rejected"
        return None
    if token in _validity_cache:
        return _validity_cache[token]
    try:
        resp = requests.get(
            PROFILE_URL,
            headers={"access-token": token, "Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code in (401, 403):
            last_validity_error = "rejected"
            print(f"  [dhan_auth] token rejected by Dhan (HTTP {resp.status_code})")
            return None
        raw = resp.json().get("tokenValidity")  # e.g. "27/10/2026 19:55", IST
        validity = _ist().localize(datetime.strptime(raw, "%d/%m/%Y %H:%M"))
    except Exception as e:
        last_validity_error = "unreachable"
        print(f"  [dhan_auth] could not read token validity: {e}")
        return None
    last_validity_error = None
    _validity_cache.clear()
    _validity_cache[token] = validity
    return validity


def token_expiry(token: str) -> datetime | None:
    """Read the `exp` claim from a JWT without verifying it. None if unreadable."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload))["exp"]
        return datetime.fromtimestamp(int(exp), tz=_ist())
    except Exception:
        return None


def _ist():
    from config import IST

    return IST


def needs_refresh(token: str | None, now: datetime) -> bool:
    if not token:
        return True
    exp = token_expiry(token)
    if exp is None or exp - now < MIN_REMAINING:
        return True
    # Pre-market: take a new token unless one was already made in today's window,
    # so refreshes stay pinned to the morning instead of drifting into market hours.
    start = now.replace(hour=PREMARKET_START[0], minute=PREMARKET_START[1], second=0, microsecond=0)
    end = now.replace(hour=PREMARKET_END[0], minute=PREMARKET_END[1], second=0, microsecond=0)
    return start <= now <= end and exp < start + timedelta(hours=24)


def generate_token() -> str:
    """Generate a new access token, retrying once in the next TOTP window."""
    try:
        return _request_token()
    except RuntimeError as e:
        if "Invalid TOTP" not in str(e):
            raise
        time.sleep(30 - time.time() % 30 + 1)
        return _request_token()


def _request_token() -> str:
    """Generate a new access token with PIN + TOTP. Raises on failure."""
    client_id = os.getenv("DHAN_CLIENT_CODE", "").strip()
    pin = os.getenv("DHAN_PIN", "").strip()
    secret = os.getenv("DHAN_TOTP_SECRET", "").replace(" ", "").strip()
    if not (client_id and pin and secret):
        raise RuntimeError("DHAN_CLIENT_CODE, DHAN_PIN and DHAN_TOTP_SECRET must be set in .env")

    totp = pyotp.TOTP(secret)
    # A code about to roll over may be stale by the time Dhan checks it.
    if totp.interval - (int(time.time()) % totp.interval) < 5:
        time.sleep(6)

    resp = requests.post(
        GENERATE_URL,
        params={"dhanClientId": client_id, "pin": pin, "totp": totp.now()},
        timeout=15,
    )
    try:
        body = resp.json()
    except ValueError:
        body = {}
    token = body.get("accessToken")
    if resp.status_code != 200 or not token:
        # Never echo the request (it holds the PIN); the response body is safe.
        raise RuntimeError(f"Dhan token generation failed (HTTP {resp.status_code}): {resp.text[:300]}")
    return token


def write_token_to_env(env_file: str, token: str) -> None:
    """Replace (or append) the DHAN_TOKEN_ID line in .env, keeping everything else."""
    with open(env_file, encoding="utf-8") as f:
        lines = f.read().splitlines()
    pattern = re.compile(r"^\s*DHAN_TOKEN_ID\s*=")
    new_line = f"DHAN_TOKEN_ID={token}"
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)
    tmp = env_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, env_file)
    os.environ["DHAN_TOKEN_ID"] = token


def ensure_fresh_token(env_file: str, on_error=None) -> bool:
    """Refresh the token if needed. Returns True if a new token was written."""
    from config import now_ist

    with _lock:
        if not needs_refresh(os.getenv("DHAN_TOKEN_ID"), now_ist()):
            return False
        try:
            token = generate_token()
        except Exception as e:
            print(f"  [dhan_auth] {e}")
            if on_error:
                on_error(str(e))
            return False
        write_token_to_env(env_file, token)
        print(f"  [dhan_auth] new access token, expires {token_expiry(token)}")
        return True


def start_refresher(env_file: str, on_error=None) -> None:
    """Background thread: check on each quarter hour (07:00, 07:15, ...) and refresh when needed."""

    def _loop():
        while True:
            time.sleep(CHECK_INTERVAL_SECONDS - time.time() % CHECK_INTERVAL_SECONDS + 1)
            ensure_fresh_token(env_file, on_error)

    threading.Thread(target=_loop, daemon=True, name="dhan-token-refresher").start()
