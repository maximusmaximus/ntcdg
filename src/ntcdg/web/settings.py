"""Web app settings, read from environment variables."""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..config import Config, logger

_TRUE = {"1", "true", "yes", "on"}


def _flag(env: Mapping[str, str], name: str) -> bool:
    return (env.get(name) or "").strip().lower() in _TRUE


@dataclass
class Settings:
    """Runtime configuration for the web app.

    ``public_base_url`` -- ``None`` means "read ``NTCDG_PUBLIC_*`` from the
    environment on each use" (the normal case); tests pass an explicit value.
    """

    secret: str
    dev: bool = False
    db_path: str = ""
    allow_local_url: bool = False
    max_upload_mb: int = 15
    public_base_url: str | None = None
    cookie_secure: bool | None = None
    job_workers: int = 4
    max_active_jobs_per_user: int = 3
    login_max_failures: int = 5
    login_window_seconds: int = 300
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.secret or len(self.secret) < 16:
            raise ValueError("The web secret must be at least 16 characters (NTCDG_WEB_SECRET).")
        if self.cookie_secure is None:
            self.cookie_secure = not self.dev
        if not self.dev:
            # Local QR URLs are a development convenience only.
            self.allow_local_url = False

    # ---------- derived values ----------

    def resolved_db_path(self) -> str:
        return self.db_path or os.path.join(Config.OUTPUT_DIR, "web.sqlite3")

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb) * 1024 * 1024

    def public_config(self) -> dict[str, Any]:
        """Configured public base URL for printed QR codes (never the request host).

        Returns ``{"base_url", "mode", "error", "subdomain_suffix", "hosts"}``;
        ``base_url`` is "" when not configured or invalid.
        """
        from urllib.parse import urlsplit

        from .. import public

        raw = self.public_base_url if self.public_base_url is not None else public.base_url_from_env()
        info: dict[str, Any] = {
            "base_url": "", "mode": "", "error": "", "subdomain_suffix": "", "hosts": [],
        }
        if not raw:
            info["error"] = (
                "No public base URL configured. Set NTCDG_PUBLIC_BASE_URL "
                "(e.g. https://tarot.example.com) so printed QR codes can link to card pages."
            )
            return info
        try:
            base = public.validate_base_url(raw, allow_local=self.allow_local_url)
        except ValueError as e:
            info["error"] = str(e)
            return info
        info["base_url"] = base
        info["mode"] = public.url_mode(base)
        if info["mode"] == "subdomain":
            probe = urlsplit(base.replace(public.DECK_PLACEHOLDER, "x"))
            host = (probe.hostname or "").lower()
            info["subdomain_suffix"] = host[1:]  # ".example.com"
        else:
            host = (urlsplit(base).hostname or "").lower()
            if host:
                info["hosts"] = [host]
        return info

    # ---------- construction ----------

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        dev = _flag(env, "NTCDG_WEB_DEV")
        secret = (env.get("NTCDG_WEB_SECRET") or "").strip()
        if not secret:
            if not dev:
                raise RuntimeError(
                    "NTCDG_WEB_SECRET is required (a long random string). "
                    "For local development only, set NTCDG_WEB_DEV=1 to use a throwaway secret."
                )
            secret = secrets.token_urlsafe(32)
            logger.warning(
                "NTCDG_WEB_DEV=1 and no NTCDG_WEB_SECRET: using a random secret; sessions and "
                "stored Venice keys will not survive a restart. Never do this in production."
            )
        try:
            max_mb = int(env.get("NTCDG_WEB_MAX_UPLOAD_MB") or 15)
        except ValueError:
            max_mb = 15
        try:
            workers = int(env.get("NTCDG_WEB_WORKERS") or 4)
        except ValueError:
            workers = 4
        return cls(
            secret=secret,
            dev=dev,
            db_path=(env.get("NTCDG_WEB_DB") or "").strip(),
            allow_local_url=dev and _flag(env, "NTCDG_WEB_ALLOW_LOCAL_URL"),
            max_upload_mb=max(1, min(max_mb, 200)),
            job_workers=max(1, min(workers, 32)),
        )
