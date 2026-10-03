"""Passwords, encrypted Venice keys, sessions, CSRF and login rate limiting."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request

# ==================== PASSWORDS (scrypt) ====================

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LEN = 64
MIN_PASSWORD = 8
MAX_PASSWORD = 256


def validate_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise ValueError(f"Passwords must be at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise ValueError(f"Passwords must be at most {MAX_PASSWORD} characters.")
    return password


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        dklen=_SCRYPT_LEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        expected = bytes.fromhex(hash_hex)
        digest = hashlib.scrypt(
            (password or "").encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


# A real hash to compare against when the username does not exist, so a
# login attempt takes the same time either way (no username enumeration).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def verify_password_or_dummy(password: str, stored: str | None) -> bool:
    if stored is None:
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, stored)


# ==================== VENICE KEY ENCRYPTION ====================

class KeyBox:
    """Fernet-encrypts users' Venice API keys with a key derived from the app secret."""

    def __init__(self, secret: str):
        from cryptography.fernet import Fernet

        raw = hashlib.sha256(b"ntcdg-web/venice-key/v1|" + secret.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(raw))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str | None:
        """Plaintext, or None if the token is empty or was made with another secret."""
        from cryptography.fernet import InvalidToken

        if not token:
            return None
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None


def validate_venice_key(key: str) -> str:
    key = (key or "").strip()
    if len(key) < 8 or len(key) > 512 or any(c.isspace() for c in key):
        raise ValueError("That does not look like a Venice API key.")
    if not key.isprintable():
        raise ValueError("That does not look like a Venice API key.")
    return key


def session_secret(secret: str) -> str:
    """Separate derived key for signing session cookies."""
    return hmac.new(secret.encode("utf-8"), b"ntcdg-web/session/v1", hashlib.sha256).hexdigest()


# ==================== CSRF ====================

CSRF_SESSION_KEY = "csrf"
CSRF_HEADER = "x-csrf-token"
CSRF_FIELD = "csrf_token"


def csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def check_csrf(request: Request, submitted: str | None = None) -> None:
    """Raise 403 unless the submitted (form field or header) token matches the session."""
    expected = request.session.get(CSRF_SESSION_KEY) or ""
    token = submitted or request.headers.get(CSRF_HEADER) or ""
    if not expected or not token or not hmac.compare_digest(str(token), str(expected)):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid. Reload the page.")


async def check_csrf_form(request: Request) -> dict[str, Any]:
    """Parse a form body and verify its CSRF token. Returns the form as a dict."""
    form = await request.form()
    check_csrf(request, form.get(CSRF_FIELD) if form is not None else None)
    return {k: v for k, v in form.items()}


# ==================== LOGIN RATE LIMIT ====================

class LoginRateLimiter:
    """In-memory sliding window of failed logins per (username, client IP)."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 300):
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: tuple[str, str], now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def retry_after(self, username: str, ip: str) -> int:
        """Seconds until another attempt is allowed (0 = allowed now)."""
        key = (username.lower(), ip)
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if len(q) < self.max_failures:
                return 0
            return max(1, int(self.window - (now - q[0])) + 1)

    def record_failure(self, username: str, ip: str) -> None:
        key = (username.lower(), ip)
        with self._lock:
            self._prune(key, time.monotonic()).append(time.monotonic())

    def reset(self, username: str, ip: str) -> None:
        with self._lock:
            self._failures.pop((username.lower(), ip), None)


# ==================== SESSION HELPERS ====================

def login_session(request: Request, user: dict[str, Any]) -> None:
    """Start a fresh session (prevents fixation) bound to the user's session version."""
    request.session.clear()
    request.session["uid"] = int(user["id"])
    request.session["sv"] = int(user["session_version"])
    request.session[CSRF_SESSION_KEY] = secrets.token_urlsafe(32)


def logout_session(request: Request) -> None:
    request.session.clear()


def flash(request: Request, message: str, category: str = "info") -> None:
    msgs = list(request.session.get("flash", []))
    msgs.append([category, message])
    request.session["flash"] = msgs[-5:]


def pop_flashes(request: Request) -> list[list[str]]:
    msgs = request.session.pop("flash", []) if "flash" in request.session else []
    return msgs
