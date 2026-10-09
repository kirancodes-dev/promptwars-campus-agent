"""
Request-scoped user identity for CampusPilot AI.

CampusPilot does not yet have account authentication. To stop visitors of a
public demo from reading or changing each other's data, every request is bound
to an *anonymous session*: the server issues a random 128-bit session ID inside
an HMAC-signed, HttpOnly cookie. Clients cannot choose their own user ID (an
unsigned or tampered cookie is replaced with a fresh session), so one visitor
cannot address another visitor's data without stealing their cookie.

This is session isolation, not authentication: there are no accounts, data is
tied to one browser, and clearing cookies starts a new empty session.

Modes (IDENTITY_MODE environment variable):
- "session" (default): per-browser anonymous sessions as described above.
- "demo": every request shares DEFAULT_USER_ID. Only for local single-user
  development and tests. Never use it for a public deployment.
"""

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import hmac
import logging
import os
import re
import secrets

try:
    from services.persistence import DEFAULT_USER_ID
except ImportError:
    from backend.services.persistence import DEFAULT_USER_ID

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "cp_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days
_SESSION_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")

_current_user_id: ContextVar[str] = ContextVar("campuspilot_user_id", default=DEFAULT_USER_ID)

# Fallback signing key generated per process when SESSION_SECRET is not set.
# Sessions then survive only as long as the process, which matches the
# in-memory persistence lifetime used by default.
_EPHEMERAL_SECRET = secrets.token_bytes(32)
_warned_ephemeral = False


def current_user_id() -> str:
    """Return the user ID bound to the current request (or the demo user outside requests)."""
    return _current_user_id.get()


@contextmanager
def user_context(user_id: str):
    """Bind user_id for the duration of a block (used by middleware and tests)."""
    token = _current_user_id.set(user_id)
    try:
        yield
    finally:
        _current_user_id.reset(token)


def bind_user(user_id: str):
    """Bind user_id to the current context and return the reset token."""
    return _current_user_id.set(user_id)


def reset_user(token) -> None:
    _current_user_id.reset(token)


def get_identity_mode() -> str:
    mode = os.getenv("IDENTITY_MODE", "session").strip().lower()
    return mode if mode in ("session", "demo") else "session"


def _secret() -> bytes:
    global _warned_ephemeral
    configured = os.getenv("SESSION_SECRET", "")
    if configured.strip():
        return configured.encode("utf-8")
    if not _warned_ephemeral:
        logger.info(
            "SESSION_SECRET is not set; using a per-process session signing key. "
            "Sessions reset when the server restarts."
        )
        _warned_ephemeral = True
    return _EPHEMERAL_SECRET


def _sign(session_id: str) -> str:
    return hmac.new(_secret(), session_id.encode("utf-8"), hashlib.sha256).hexdigest()


def new_session_cookie() -> tuple[str, str]:
    """Create a new anonymous session. Returns (user_id, cookie_value)."""
    session_id = secrets.token_hex(16)
    return f"session-{session_id}", f"{session_id}.{_sign(session_id)}"


def user_from_cookie(cookie_value: str | None) -> str | None:
    """Validate a signed session cookie and return its user ID, or None if invalid."""
    if not cookie_value or "." not in cookie_value or len(cookie_value) > 200:
        return None
    session_id, signature = cookie_value.split(".", 1)
    if not _SESSION_ID_PATTERN.match(session_id):
        return None
    if not hmac.compare_digest(signature, _sign(session_id)):
        return None
    return f"session-{session_id}"
