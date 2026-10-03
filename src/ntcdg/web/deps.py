"""Request helpers shared by the web routes: state, current user, rendering."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from . import auth


class LoginRequired(Exception):
    """Raised by HTML routes when no user is logged in (redirects to /login)."""

    def __init__(self, next_path: str = "/"):
        self.next_path = next_path


def state(request: Request) -> Any:
    return request.app.state.ntcdg


def current_user(request: Request) -> dict[str, Any] | None:
    if hasattr(request.state, "user"):
        return request.state.user
    user = None
    uid = request.session.get("uid") if "session" in request.scope else None
    if uid:
        row = state(request).db.get_user(uid)
        if row and int(row["session_version"]) == int(request.session.get("sv") or -1):
            user = row
        else:
            request.session.clear()
    request.state.user = user
    return user


def require_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if user is None:
        raise LoginRequired(request.url.path)
    return user


def require_api_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in.")
    return user


def user_venice_key(request: Request, user: dict[str, Any]) -> str | None:
    return state(request).keybox.decrypt(user.get("venice_key_enc") or "")


def safe_next(target: str | None) -> str:
    """Only allow local redirect targets (no open redirects)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/dashboard"
    return target


def login_url(next_path: str) -> str:
    return "/login?next=" + quote(next_path, safe="/")


def render(request: Request, template: str, status_code: int = 200, **context: Any) -> HTMLResponse:
    st = state(request)
    user = current_user(request)
    base_ctx = {
        "request": request,
        "user": user,
        "csrf_token": auth.csrf_token(request) if "session" in request.scope else "",
        "flashes": auth.pop_flashes(request) if "session" in request.scope else [],
        "public_cfg": st.settings.public_config(),
        "dev": st.settings.dev,
        "has_key": bool(user and user.get("venice_key_enc")),
    }
    base_ctx.update(context)
    return st.templates.TemplateResponse(request, template, base_ctx, status_code=status_code)
