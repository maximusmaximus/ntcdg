"""Web app: the public card viewer reached by scanning a card-back QR code."""

from __future__ import annotations

import re

import pytest

pytest.importorskip("fastapi")

from tests.web_support import app_and_client, make_deck, publish, setup_out


@pytest.fixture
def out(tmp_path, monkeypatch):
    return setup_out(tmp_path, monkeypatch)


@pytest.fixture
def web(out, tmp_path):
    with app_and_client(tmp_path) as (app, client):
        yield app, client


@pytest.fixture
def deck(web):
    make_deck("alice__luna", 3, titles=["The Fool", "The Magician", "The High Priestess"])
    return publish("alice__luna")


class TestCardPage:
    def test_card_page_shows_icon_and_all_sections(self, web, deck):
        _app, c = web
        r = c.get(f"/c/{deck}/02-the-magician")
        assert r.status_code == 200
        html = r.text
        assert "The Magician" in html
        for text in ("Upright 2", "Reversed 2", "Description 2", "Star", "Key"):
            assert text in html
        assert f'src="/p/{deck}/02-the-magician/image"' in html
        assert 'name="viewport"' in html
        assert 'property="og:title"' in html
        og_image = f"https://tarot.example.com/p/{deck}/02-the-magician/image"
        assert f'property="og:image" content="{og_image}"' in html
        assert f'rel="canonical" href="https://tarot.example.com/c/{deck}/02-the-magician"' in html
        assert "made to be given away" in html
        # deck title never exposes the owner's username
        assert "alice" not in html.lower()

    def test_readable_without_js(self, web, deck):
        _app, c = web
        html = c.get(f"/c/{deck}/01-the-fool").text
        # sections are open <details> and navigation is plain links
        assert html.count("<details class=\"section\" open") == 4
        assert f'href="/c/{deck}/02-the-magician" rel="next"' in html
        assert f'href="/c/{deck}/03-the-high-priestess" rel="prev"' in html
        # scripts are external (CSP forbids inline)
        assert "<script>" not in html
        assert re.search(r'<script src="/static/viewer\.js"', html)

    def test_prev_next_wrap(self, web, deck):
        _app, c = web
        last = c.get(f"/p/{deck}/03-the-high-priestess.json").json()
        assert last["next_url"] == f"/c/{deck}/01-the-fool"
        assert last["prev_url"] == f"/c/{deck}/02-the-magician"
        first = c.get(f"/p/{deck}/01-the-fool.json").json()
        assert first["prev_url"] == f"/c/{deck}/03-the-high-priestess"
        assert first["position"] == 1 and first["total"] == 3

    def test_json_endpoint(self, web, deck):
        _app, c = web
        r = c.get(f"/p/{deck}/02-the-magician.json")
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "The Magician"
        assert data["upright_interpretation"] == "Upright 2"
        assert data["image_url"] == f"/p/{deck}/02-the-magician/image"
        assert "image_path" not in data
        assert "alice" not in str(data)
        assert c.get(f"/p/{deck}/99-nope.json").status_code == 404

    def test_image_and_thumb_endpoints(self, web, deck):
        _app, c = web
        img = c.get(f"/p/{deck}/01-the-fool/image")
        assert img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n"
        thumb = c.get(f"/p/{deck}/01-the-fool/thumb")
        assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
        assert c.get(f"/p/{deck}/42-x/image").status_code == 404

    def test_canonical_redirect_for_stale_title(self, web, deck):
        _app, c = web
        r = c.get(f"/c/{deck}/02-old-title", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == f"/c/{deck}/02-the-magician"
        r = c.get(f"/c/{deck}/2", follow_redirects=False)
        assert r.status_code == 302

    def test_unpublished_and_unknown_decks_404(self, web, deck):
        from ntcdg.storage import update_deck_meta

        _app, c = web
        make_deck("bob__draft", 2)
        assert c.get("/c/draft-zzzzzz/01-card-1").status_code == 404
        update_deck_meta("alice__luna", published=False)
        r = c.get(f"/c/{deck}/01-the-fool")
        assert r.status_code == 404 and "isn" in r.text
        assert c.get(f"/p/{deck}/01-the-fool.json").status_code == 404
        assert c.get(f"/p/{deck}/01-the-fool/image").status_code == 404
        assert c.get(f"/c/{deck}").status_code == 404

    def test_deck_overview(self, web, deck):
        _app, c = web
        r = c.get(f"/c/{deck}")
        assert r.status_code == 200
        for slug in ("01-the-fool", "02-the-magician", "03-the-high-priestess"):
            assert f'href="/c/{deck}/{slug}"' in r.text
        assert "Luna" in r.text or "luna" in r.text

    def test_scanner_is_configured_for_this_site(self, web, deck):
        _app, c = web
        html = c.get(f"/c/{deck}/01-the-fool").text
        assert 'data-hosts="tarot.example.com"' in html
        assert 'data-jsqr-sri="sha384-' in html and "cdn.jsdelivr.net/npm/jsqr@" in html

    def test_public_pages_are_cacheable_and_viewer_assets_exist(self, web, deck):
        _app, c = web
        assert "max-age" in c.get(f"/p/{deck}/01-the-fool.json").headers["cache-control"]
        for asset in ("/static/viewer.js", "/static/scanner.js", "/static/app.js", "/static/app.css",
                      "/static/logo.svg"):
            assert c.get(asset).status_code == 200, asset


class TestSubdomainMode:
    def test_subdomain_host_resolution(self, out, tmp_path):
        with app_and_client(tmp_path, public_base_url="https://{deck}.example.com") as (_app, c):
            make_deck("alice__sky", 2, titles=["The Star", "The Moon"])
            slug = publish("alice__sky", "https://{deck}.example.com")
            host = {"Host": f"{slug}.example.com"}

            overview = c.get("/", headers=host)
            assert overview.status_code == 200 and 'href="/c/01-the-star"' in overview.text

            card = c.get("/c/02-the-moon", headers=host)
            assert card.status_code == 200 and "Upright 2" in card.text
            assert f'href="https://{slug}.example.com/c/02-the-moon"' in card.text
            assert 'href="/c/01-the-star" rel="next"' in card.text

            data = c.get(f"/p/{slug}/02-the-moon.json", headers=host).json()
            assert data["next_url"] == "/c/01-the-star"
            assert 'data-suffix=".example.com"' in card.text

            # plain host keeps the landing page; unknown subdomain is a 404
            assert "give it away" in c.get("/").text
            assert c.get("/", headers={"Host": "nope-zzzzzz.example.com"}).status_code == 404
