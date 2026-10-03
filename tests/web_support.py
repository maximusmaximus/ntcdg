"""Shared helpers for the web app tests (imported only after ``importorskip("fastapi")``)."""

from __future__ import annotations

import contextlib
import io
import os
import re
from collections.abc import Iterator
from typing import Any

from PIL import Image

PASSWORD = "correct horse battery"
BASE_URL = "https://tarot.example.com"
_PUBLIC_ENV = (
    "NTCDG_PUBLIC_BASE_URL", "NTCDG_PUBLIC_ROOT_DOMAIN",
    "NTCDG_PUBLIC_SUBDOMAIN", "NTCDG_PUBLIC_SCHEME",
)


def setup_out(tmp_path, monkeypatch):
    """Same isolation as the ``out`` fixture used across the suite."""
    out_dir = tmp_path / "generated_decks"
    out_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr("ntcdg.config.Config.IMAGES_DIR", str(out_dir / "images"))
    monkeypatch.delenv("VENICE_API_KEY", raising=False)
    for var in _PUBLIC_ENV:
        monkeypatch.delenv(var, raising=False)
    return out_dir


def make_settings(tmp_path, **overrides: Any):
    from ntcdg.web.settings import Settings

    params: dict[str, Any] = dict(
        secret="s" * 32, dev=False, cookie_secure=False, db_path=str(tmp_path / "web.sqlite3"),
        public_base_url=BASE_URL, job_workers=2,
    )
    params.update(overrides)
    return Settings(**params)


@contextlib.contextmanager
def app_and_client(tmp_path, **overrides: Any) -> Iterator[tuple[Any, Any]]:
    from fastapi.testclient import TestClient

    from ntcdg.web.app import create_app

    app = create_app(make_settings(tmp_path, **overrides))
    with TestClient(app) as client:
        yield app, client


def new_client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


_META_RE = re.compile(r'<meta name="csrf-token" content="([^"]*)"')


def csrf(client, path: str = "/") -> str:
    resp = client.get(path)
    m = _META_RE.search(resp.text)
    assert m, f"no csrf meta on {path}: {resp.status_code}"
    return m.group(1)


def signup(client, username: str, password: str = PASSWORD) -> str:
    token = csrf(client, "/signup")
    resp = client.post("/signup", data={
        "username": username, "password": password, "password2": password, "csrf_token": token,
    }, follow_redirects=False)
    assert resp.status_code == 303, resp.text[:500]
    return csrf(client, "/dashboard")


def login(client, username: str, password: str = PASSWORD, follow: bool = False):
    token = csrf(client, "/login")
    return client.post("/login", data={"username": username, "password": password, "csrf_token": token},
                       follow_redirects=follow)


def run_tool(client, tool: str, inputs: dict[str, Any], token: str):
    return client.post(f"/api/tools/{tool}", json={"inputs": inputs},
                       headers={"X-CSRF-Token": token, "Accept": "application/json"})


def set_key(app, username: str, key: str = "venice-user-key-1234") -> None:
    st = app.state.ntcdg
    user = st.db.get_user_by_username(username)
    st.db.set_venice_key(user["id"], st.keybox.encrypt(key), key[-4:])


def png_bytes(color=(40, 30, 90), size=(60, 100), fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


def make_deck(internal: str, n: int = 3, images: bool = True, titles: list[str] | None = None) -> list[str]:
    """Save a deck (under its *internal* name) with real PNGs in its own image folder."""
    from ntcdg.models import Card
    from ntcdg.storage import deck_images_dir, save_deck

    folder = deck_images_dir(internal)
    os.makedirs(folder, exist_ok=True)
    cards = []
    paths = []
    for pos in range(1, n + 1):
        path = os.path.join(folder, f"{pos:03d}.png")
        if images:
            Image.new("RGB", (60, 100), (pos * 20 % 255, 40, 90)).save(path)
        paths.append(path)
        cards.append(Card(
            position=pos, title=(titles[pos - 1] if titles else f"Card {pos}"), card_type="Major Arcana",
            image_path=path if images else "", symbols=["Star", "Key"],
            description=f"Description {pos}", upright_interpretation=f"Upright {pos}",
            reversed_interpretation=f"Reversed {pos}",
        ))
    save_deck(cards, internal)
    return paths


def publish(internal: str, base_url: str = BASE_URL) -> str:
    """Publish like the web finalize does: slug from the *short* deck name (no username)."""
    from ntcdg import public
    from ntcdg.storage import update_deck_meta
    from ntcdg.web.tools import _seed_public_slug

    _seed_public_slug(internal, internal.split("__", 1)[-1])
    slug = public.ensure_public_identity(internal, base_url)["slug"]
    update_deck_meta(internal, published=True)
    return slug
