"""Shared domain services for deck inspection and traditional tarot coverage audits.

Centralises read-side business logic shared across CLI, MCP tools, and web views
so every interface returns consistent counts and coverage metrics.
"""

from __future__ import annotations

import os
from typing import Any

from .storage import load_deck, load_decks_index
from .symbols import TraditionalDeckRegistry


def get_deck_summary(deck_name: str) -> dict[str, Any]:
    """Build a standard status summary for ``deck_name``."""
    deck = load_deck(deck_name)
    if not deck:
        return {"error": f"Deck '{deck_name}' not found"}

    index = load_decks_index()
    meta = index.get(deck_name, {})
    total = len(deck)

    has_images = sum(
        1 for c in deck
        if c.image_path and os.path.exists(str(c.image_path))
    )
    has_analysis = sum(
        1 for c in deck if c.description and not c.venice_error
    )
    has_meanings = sum(
        1 for c in deck
        if c.upright_interpretation and c.reversed_interpretation
    )
    has_errors = sum(
        1 for c in deck if c.venice_error or c.image_error
    )

    return {
        "name": deck_name,
        "total_cards": total,
        "images": has_images,
        "analysis": has_analysis,
        "meanings": has_meanings,
        "errors": has_errors,
        "has_back": bool(meta.get("back_image", "")),
        "ready_to_finalize": has_images == total and has_analysis == total,
        "vibe": meta.get("vibe", ""),
        "theme": meta.get("theme", ""),
        "created": meta.get("created", ""),
    }


def audit_traditional_coverage(deck_name: str) -> dict[str, Any]:
    """Audit canonical traditional tarot archetype coverage for an existing deck."""
    deck = load_deck(deck_name)
    if not deck:
        return {"error": f"Deck '{deck_name}' not found"}

    all_canonical = TraditionalDeckRegistry.get_all_symbols()
    card_reports: list[dict[str, Any]] = []
    canonical_hits: set[str] = set()

    for card in sorted(deck, key=lambda c: c.position or 0):
        c_symbols = card.symbols or []
        canon_lookup = card.canonical_title or card.title
        card_canons = TraditionalDeckRegistry.get_symbols_for_card(canon_lookup)
        matched_canons_for_card: list[str] = []

        for canon in card_canons:
            cid = canon["id"]
            cname = canon["name"].lower()
            ckws = [kw.lower() for kw in canon.get("keywords", [])]

            found = False
            for cs in c_symbols:
                cs_lower = cs.lower()
                if cname in cs_lower or any(kw in cs_lower for kw in ckws):
                    found = True
                    break

            if found:
                canonical_hits.add(cid)
                matched_canons_for_card.append(canon["name"])

        card_reports.append({
            "position": card.position,
            "title": card.title,
            "card_type": card.card_type,
            "symbols_count": len(c_symbols),
            "traditional_symbols_found": matched_canons_for_card,
        })

    coverage_pct = (
        round((len(canonical_hits) / len(all_canonical)) * 100.0, 1)
        if all_canonical
        else 0.0
    )

    return {
        "deck_name": deck_name,
        "total_cards": len(deck),
        "total_canonical_symbols": len(all_canonical),
        "canonical_symbols_covered": len(canonical_hits),
        "traditional_coverage_percentage": coverage_pct,
        "cards": card_reports,
    }
