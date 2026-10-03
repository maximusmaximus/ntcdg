"""FastAPI application factory and ``ntcdg-web`` entry point."""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import SessionMiddleware

from ..config import logger
from . import auth
from .db import Database
from .deps import LoginRequired, login_url, render
from .jobs import JobManager
from .settings import Settings

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(HERE, "templates")
STATIC_DIR = os.path.join(HERE, "static")

JSQR_URL = "https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js"
JSQR_SRI = "sha384-b5Ya4Bq3qCyz39m2ISh+4DxjAIljdeFwK/BsXLuj9gugaNwAcj/ia15fxNZL9Nlx"

CSP = (
    "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
    "script-src 'self' https://cdn.jsdelivr.net; style-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


@dataclass
class AppState:
    settings: Settings
    db: Database
    keybox: auth.KeyBox
    limiter: auth.LoginRateLimiter
    jobs: JobManager
    templates: Jinja2Templates


class SecurityHeadersMiddleware:
    """Pure-ASGI middleware (keeps SSE streaming intact) adding security headers."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                ctype = headers.get("content-type", "")
                if not ctype.startswith("image/svg"):
                    headers.setdefault("Content-Security-Policy", CSP)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "same-origin")
                headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
                if not (path.startswith("/static/") or path.startswith("/p/")):
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _wants_json(request: Request) -> bool:
    path = request.url.path
    if path.startswith(("/api/", "/p/")):
        return True
    if path.startswith("/jobs/") and not path.endswith("/view"):
        return True
    if path.startswith("/uploads") and request.method != "GET":
        return True
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.resolved_db_path())
    interrupted = db.mark_interrupted()
    if interrupted:
        logger.warning(f"Marked {interrupted} unfinished web job(s) as interrupted")
    jobs = JobManager(db, settings)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        jobs.shutdown(wait=False)

    app = FastAPI(
        title="NTCDG — Novel Tarot Card Deck Generator",
        docs_url="/api/docs" if settings.dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.dev else None,
        lifespan=lifespan,
    )
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    from . import tools as webtools

    templates.env.globals.update(jsqr_url=JSQR_URL, jsqr_sri=JSQR_SRI, TOOLS=webtools.REGISTRY)
    app.state.ntcdg = AppState(
        settings=settings, db=db, keybox=auth.KeyBox(settings.secret),
        limiter=auth.LoginRateLimiter(settings.login_max_failures, settings.login_window_seconds),
        jobs=jobs, templates=templates,
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=auth.session_secret(settings.secret),
        session_cookie="ntcdg_session",
        max_age=14 * 24 * 3600,
        same_site="lax",
        https_only=bool(settings.cookie_secure),
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    from . import api, pages, public_views

    app.include_router(pages.router)
    app.include_router(api.router)
    app.include_router(public_views.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        return RedirectResponse(login_url(exc.next_path), status_code=303)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Error"
        if _wants_json(request):
            return JSONResponse({"error": detail}, status_code=exc.status_code,
                                headers=getattr(exc, "headers", None))
        return render(request, "error.html", status_code=exc.status_code,
                      status=exc.status_code, message=detail)

    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def _starlette_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Error"
        if _wants_json(request):
            return JSONResponse({"error": detail}, status_code=exc.status_code)
        return render(request, "error.html", status_code=exc.status_code,
                      status=exc.status_code, message=detail)

    return app


def main() -> None:
    """Run the web app with uvicorn (``ntcdg-web``)."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="NTCDG web app")
    parser.add_argument("--host", default=os.getenv("NTCDG_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("NTCDG_WEB_PORT", "8000")))
    parser.add_argument("--proxy-headers", action="store_true",
                        help="Trust X-Forwarded-* from the reverse proxy")
    args = parser.parse_args()
    uvicorn.run(
        create_app(), host=args.host, port=args.port,
        proxy_headers=args.proxy_headers, forwarded_allow_ips="*" if args.proxy_headers else None,
    )


if __name__ == "__main__":
    main()
