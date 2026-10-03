"""Public, stable URLs for printed cards (QR codes on card backs).

Every finalized deck gets a globally unique ``public_slug`` (e.g.
``moon-garden-k7m2qx``) and every card a ``card_slug`` (``01-the-fool``).
The QR code printed on a card's back encodes::

    {public_base_url}/c/{deck_slug}/{card_slug}          # "path" mode (default)
    https://{deck_slug}.{root_domain}/c/{card_slug}      # "subdomain" mode

The base URL comes from configuration (never guessed, never localhost) and
is *baked into the deck's metadata on first finalize* so re-printing the
deck later always produces the same codes -- cards already given away keep
working. Changing it requires an explicit ``rebase=True``.

Configuration (environment variables):

* ``NTCDG_PUBLIC_BASE_URL`` -- full base, e.g. ``https://tarot.example.com``.
  May contain ``{deck}`` to give every deck its own subdomain, e.g.
  ``https://{deck}.example.com``.
* or ``NTCDG_PUBLIC_ROOT_DOMAIN`` (``example.com``) +
  ``NTCDG_PUBLIC_SUBDOMAIN`` (``tarot``, empty, or ``{deck}``) +
  ``NTCDG_PUBLIC_SCHEME`` (default ``https``).
"""

from __future__ import annotations

import ipaddress
import os
import re
import secrets
import unicodedata
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

DECK_PLACEHOLDER = "{deck}"
_SLUG_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o/1/l/i look-alikes
_CARD_SLUG_RE = re.compile(r"^(\d{1,3})(?:-[a-z0-9-]*)?$")
_DECK_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


# ==================== SLUGS ====================

def slugify(text: str, max_len: int = 40, fallback: str = "deck") -> str:
    """ASCII, lowercase, hyphen-separated slug safe for URLs and DNS labels."""
    norm = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")
    slug = slug[:max_len].strip("-")
    return slug or fallback


def new_deck_slug(deck_name: str, taken: set[str] | None = None) -> str:
    """``{slugified-name}-{6 random chars}``, unique against ``taken``."""
    base = slugify(deck_name.replace("_", " "), max_len=40)
    taken = taken or set()
    while True:
        suffix = "".join(secrets.choice(_SLUG_ALPHABET) for _ in range(6))
        slug = f"{base}-{suffix}"
        if slug not in taken:
            return slug


def card_slug(card: Any) -> str:
    """Stable slug for a card: zero-padded position + canonical title.

    The canonical ``title`` (e.g. "The Fool") is used rather than the AI-given
    display title so edits never change a printed URL; lookups resolve by the
    numeric prefix anyway.
    """
    position = int(getattr(card, "position", 0) or 0)
    title = getattr(card, "title", "") or "card"
    return f"{position:02d}-{slugify(title, max_len=48, fallback='card')}"


def parse_card_position(slug: str) -> int | None:
    """Return the card position encoded in a card slug, or None if malformed."""
    m = _CARD_SLUG_RE.match(str(slug or "").lower())
    return int(m.group(1)) if m else None


def is_valid_deck_slug(slug: str) -> bool:
    return bool(_DECK_SLUG_RE.match(str(slug or "")))


# ==================== BASE URL CONFIG ====================

def base_url_from_env(env: Mapping[str, str] | None = None) -> str:
    """Compose the configured public base URL ("" when not configured)."""
    env = os.environ if env is None else env
    explicit = (env.get("NTCDG_PUBLIC_BASE_URL") or "").strip()
    if explicit:
        return explicit
    root = (env.get("NTCDG_PUBLIC_ROOT_DOMAIN") or "").strip().strip(".").lower()
    if not root:
        return ""
    scheme = (env.get("NTCDG_PUBLIC_SCHEME") or "https").strip().lower()
    sub = (env.get("NTCDG_PUBLIC_SUBDOMAIN") or "").strip().strip(".")
    host = f"{sub}.{root}" if sub else root
    return f"{scheme}://{host}"


def _is_local_host(host: str) -> bool:
    if host in ("localhost",) or host.endswith(".localhost") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified


def validate_base_url(url: str, allow_local: bool = False) -> str:
    """Normalise and validate a public base URL; raise ``ValueError`` if unusable.

    Printed QR codes live forever, so we refuse localhost / private addresses
    (unless ``allow_local`` for testing) and anything with a query/fragment.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError(
            "No public base URL configured. Set NTCDG_PUBLIC_BASE_URL "
            "(e.g. https://tarot.example.com) or NTCDG_PUBLIC_ROOT_DOMAIN."
        )
    probe = raw.replace(DECK_PLACEHOLDER, "deckslug")
    parts = urlsplit(probe)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"Public base URL must start with https:// (got {raw!r})")
    if parts.query or parts.fragment:
        raise ValueError("Public base URL must not contain a query string or fragment")
    if parts.username or parts.password:
        raise ValueError("Public base URL must not contain credentials")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError(f"Public base URL has no host: {raw!r}")
    if DECK_PLACEHOLDER in raw:
        netloc = urlsplit(raw.replace(DECK_PLACEHOLDER, "deckslug")).netloc
        if "deckslug" not in netloc or not raw.split("://", 1)[1].startswith(DECK_PLACEHOLDER + "."):
            raise ValueError("'{deck}' may only be used as the first subdomain label")
    if not allow_local and _is_local_host(host):
        raise ValueError(
            f"Refusing to print QR codes pointing at a local address ({host}); "
            "use your public domain."
        )
    for label in host.split("."):
        if not _LABEL_RE.match(label):
            raise ValueError(f"Invalid host name in public base URL: {host!r}")
    return raw.rstrip("/")


def url_mode(base_url: str) -> str:
    return "subdomain" if DECK_PLACEHOLDER in base_url else "path"


def build_deck_url(base_url: str, deck_slug: str) -> str:
    if url_mode(base_url) == "subdomain":
        return base_url.replace(DECK_PLACEHOLDER, deck_slug) + "/"
    return f"{base_url}/c/{deck_slug}"


def build_card_url(base_url: str, deck_slug: str, slug: str) -> str:
    if url_mode(base_url) == "subdomain":
        return f"{base_url.replace(DECK_PLACEHOLDER, deck_slug)}/c/{slug}"
    return f"{base_url}/c/{deck_slug}/{slug}"


# ==================== DECK IDENTITY ====================

def ensure_public_identity(
    deck_name: str,
    base_url: str | None = None,
    *,
    rebase: bool = False,
    allow_local: bool = False,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Assign (once) and return a deck's public slug + base URL.

    Returns ``{"enabled", "base_url", "slug", "mode", "warnings", "reason"}``.
    ``enabled`` is False when no base URL is configured or baked; callers
    must then skip QR codes rather than print unusable ones.
    """
    from .storage import load_decks_index, update_deck_meta

    warnings: list[str] = []
    index = load_decks_index()
    meta = index.get(deck_name, {})
    baked = meta.get("public_base_url") or ""
    slug = meta.get("public_slug") or ""

    configured = ""
    candidate = base_url if base_url else base_url_from_env(env)
    if candidate:
        configured = validate_base_url(candidate, allow_local=allow_local)

    if baked and configured and configured != baked:
        if rebase:
            warnings.append(
                f"Public URL changed from {baked} to {configured}; cards printed "
                "earlier will still point at the old address."
            )
            baked = configured
        else:
            warnings.append(
                f"Keeping this deck's original public URL {baked} (configured: "
                f"{configured}). Pass rebase=True to change it."
            )
    effective = baked or configured
    if not effective:
        return {
            "enabled": False, "base_url": "", "slug": slug, "mode": "",
            "warnings": warnings,
            "reason": (
                "No public base URL configured (set NTCDG_PUBLIC_BASE_URL); "
                "QR codes were not added."
            ),
        }

    if not slug:
        taken = {m.get("public_slug") for m in index.values() if m.get("public_slug")}
        slug = new_deck_slug(deck_name, taken)

    update_deck_meta(
        deck_name, public_slug=slug, public_base_url=effective, published=True,
    )
    return {
        "enabled": True, "base_url": effective, "slug": slug,
        "mode": url_mode(effective), "warnings": warnings, "reason": "",
    }


def card_urls(identity: Mapping[str, Any], cards: list[Any]) -> dict[int, str]:
    """Map card position -> public URL for every card (empty if disabled)."""
    if not identity.get("enabled"):
        return {}
    return {
        int(c.position): build_card_url(identity["base_url"], identity["slug"], card_slug(c))
        for c in cards
    }


def find_deck_by_slug(deck_slug: str) -> tuple[str, dict[str, Any]] | None:
    """Return ``(deck_name, meta)`` for a public slug, or None."""
    from .storage import load_decks_index

    if not is_valid_deck_slug(deck_slug):
        return None
    for name, meta in load_decks_index().items():
        if meta.get("public_slug") == deck_slug:
            return name, meta
    return None


def public_links(deck_name: str) -> dict[str, Any]:
    """Public deck URL and per-card URLs for an already-finalized deck."""
    from .storage import load_deck, load_decks_index

    meta = load_decks_index().get(deck_name, {})
    base, slug = meta.get("public_base_url"), meta.get("public_slug")
    if not (base and slug):
        return {"enabled": False, "reason": "Deck has no public URL yet; finalize it first."}
    cards = sorted(load_deck(deck_name), key=lambda c: c.position or 0)
    return {
        "enabled": True,
        "deck_slug": slug,
        "base_url": base,
        "deck_url": build_deck_url(base, slug),
        "cards": [
            {"position": c.position, "title": c.title, "card_slug": card_slug(c),
             "url": build_card_url(base, slug, card_slug(c))}
            for c in cards
        ],
    }
