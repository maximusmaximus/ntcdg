"""Public card viewer: what a recipient sees after scanning the QR on a card back.

Path mode:       /c/{deck_slug}/{card_slug}   (+ /c/{deck_slug} deck overview)
Subdomain mode:  https://{deck_slug}.{root}/c/{card_slug}   (+ / deck overview)

Only decks with ``published=True`` (finalized with a public URL) resolve.
JSON/image endpoints live under /p/... so they work identically in both modes.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from .. import mcp_server, public
from ..storage import load_deck
from .deps import render, state
from .files import data_roots, is_within, thumbnail_bytes

router = APIRouter()

PHILOSOPHY_LINE = (
    "This card was made to be given away. Its energy is yours alone — "
    "read what it holds for you, in your own time."
)


def subdomain_slug(request: Request) -> str | None:
    """Deck slug when the request host is ``{deck_slug}.{root}`` in subdomain mode."""
    cfg = state(request).settings.public_config()
    suffix = cfg.get("subdomain_suffix") or ""
    if cfg.get("mode") != "subdomain" or not suffix:
        return None
    host = (request.headers.get("host") or "").split(":")[0].strip().lower().rstrip(".")
    if not host.endswith(suffix) or len(host) <= len(suffix):
        return None
    label = host[: -len(suffix)]
    return label if public.is_valid_deck_slug(label) and "." not in label else None


def _published(deck_slug: str) -> tuple[str, dict[str, Any]] | None:
    found = public.find_deck_by_slug(deck_slug)
    if not found or not found[1].get("published"):
        return None
    return found


def _deck_title(internal: str) -> str:
    """Display name without the owner's username prefix."""
    short = internal.split("__", 1)[1] if "__" in internal else internal
    return short.replace("_", " ").replace("-", " ").strip() or "Tarot deck"


def _card_href(deck_slug: str, card_slug: str, on_subdomain: bool) -> str:
    return f"/c/{card_slug}" if on_subdomain else f"/c/{deck_slug}/{card_slug}"


def _card_payload(deck_slug: str, card_slug: str, on_subdomain: bool) -> dict[str, Any] | None:
    data = mcp_server.get_card_by_slug(deck_slug, card_slug)
    if "error" in data:
        return None
    found = _published(deck_slug)
    if not found:
        return None
    internal, meta = found
    slug = data["card_slug"]
    payload = {
        **data,
        "deck_title": _deck_title(internal),
        "url": _card_href(deck_slug, slug, on_subdomain),
        "canonical_url": public.build_card_url(meta.get("public_base_url", ""), deck_slug, slug)
        if meta.get("public_base_url") else "",
        "prev_url": _card_href(deck_slug, data["prev_card_slug"], on_subdomain)
        if data.get("prev_card_slug") else "",
        "next_url": _card_href(deck_slug, data["next_card_slug"], on_subdomain),
        "image_url": f"/p/{deck_slug}/{slug}/image" if data.get("has_image") else "",
        "thumb_url": f"/p/{deck_slug}/{slug}/thumb" if data.get("has_image") else "",
        "json_url": f"/p/{deck_slug}/{slug}.json",
        "arcana": data.get("card_type") or "",
        "deck_url": "/" if on_subdomain else f"/c/{deck_slug}",
    }
    payload["og_image_url"] = ""
    if payload["canonical_url"] and payload["image_url"]:
        parts = urlsplit(payload["canonical_url"])
        payload["og_image_url"] = f"{parts.scheme}://{parts.netloc}{payload['image_url']}"
    return payload


def _scanner_config(request: Request) -> dict[str, Any]:
    cfg = state(request).settings.public_config()
    return {
        "hosts": ",".join(cfg.get("hosts") or []),
        "suffix": cfg.get("subdomain_suffix") or "",
    }


def card_page(request: Request, deck_slug: str, card_slug: str, on_subdomain: bool):
    payload = _card_payload(deck_slug, card_slug, on_subdomain)
    if payload is None:
        return render(request, "public_404.html", status_code=404)
    if card_slug != payload["card_slug"]:
        # Same position, stale/edited title part: send to the canonical address.
        # 302 (not 301) because titles can be edited again later.
        return RedirectResponse(payload["url"], status_code=302)
    return render(
        request, "public_card.html", card=payload, deck_slug=deck_slug,
        on_subdomain=on_subdomain, philosophy=PHILOSOPHY_LINE, scanner=_scanner_config(request),
    )


def deck_page(request: Request, deck_slug: str, on_subdomain: bool):
    found = _published(deck_slug)
    if not found:
        return render(request, "public_404.html", status_code=404)
    internal, _meta = found
    cards = sorted(load_deck(internal), key=lambda c: c.position or 0)
    items = []
    for c in cards:
        slug = public.card_slug(c)
        has_img = bool(c.image_path and os.path.exists(str(c.image_path)))
        items.append({
            "title": c.display_title(), "position": c.position, "card_type": c.card_type or "",
            "href": _card_href(deck_slug, slug, on_subdomain),
            "thumb_url": f"/p/{deck_slug}/{slug}/thumb" if has_img else "",
        })
    return render(
        request, "public_deck.html", deck_title=_deck_title(internal), deck_slug=deck_slug,
        cards=items, philosophy=PHILOSOPHY_LINE, scanner=_scanner_config(request),
    )


@router.get("/c/{first}")
def public_first(request: Request, first: str):
    sub = subdomain_slug(request)
    if sub:
        return card_page(request, sub, first, on_subdomain=True)
    return deck_page(request, first, on_subdomain=False)


@router.get("/c/{deck_slug}/{card_slug}")
def public_card(request: Request, deck_slug: str, card_slug: str):
    return card_page(request, deck_slug, card_slug, on_subdomain=False)


@router.get("/p/{deck_slug}/{card_slug}.json")
def public_card_json(request: Request, deck_slug: str, card_slug: str):
    on_sub = subdomain_slug(request) == deck_slug
    payload = _card_payload(deck_slug, card_slug, on_sub)
    if payload is None:
        return JSONResponse({"error": "Card not found"}, status_code=404)
    return JSONResponse(payload, headers={"Cache-Control": "public, max-age=60"})


def _card_image_path(deck_slug: str, card_slug: str) -> str:
    found = _published(deck_slug)
    position = public.parse_card_position(card_slug)
    if not found or position is None:
        raise HTTPException(status_code=404, detail="Not found")
    card = next((c for c in load_deck(found[0]) if c.position == position), None)
    path = str(card.image_path) if card and card.image_path else ""
    if not path or not os.path.isfile(path) or not is_within(path, data_roots()):
        raise HTTPException(status_code=404, detail="Not found")
    return path


@router.get("/p/{deck_slug}/{card_slug}/image")
def public_card_image(deck_slug: str, card_slug: str):
    path = _card_image_path(deck_slug, card_slug)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=300"})


@router.get("/p/{deck_slug}/{card_slug}/thumb")
def public_card_thumb(deck_slug: str, card_slug: str):
    path = _card_image_path(deck_slug, card_slug)
    return Response(thumbnail_bytes(path), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=300"})
