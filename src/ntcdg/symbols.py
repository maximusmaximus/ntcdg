"""Symbol configuration loading, canonical traditional tarot symbolism, and cohesive image generation."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from typing import Any

from .config import HAS_TQDM, Config, logger, requests

if HAS_TQDM:
    from tqdm import tqdm


# ==================== CANONICAL TRADITIONAL TAROT SYMBOLS ====================
# Comprehensive registry of traditional tarot archetypal symbols across the 22 Major Arcana,
# the 4 Elemental Suits, and Court archetypes (Rider-Waite-Smith & classical esoteric tradition).

def _load_traditional_symbols() -> list[dict[str, Any]]:
    """Load the canonical Rider-Waite-Smith / esoteric symbol table from JSON."""
    data_path = os.path.join(os.path.dirname(__file__), "data", "traditional_symbols.json")
    with open(data_path, encoding="utf-8") as f:
        return json.load(f)


TRADITIONAL_TAROT_SYMBOLS: list[dict[str, Any]] = _load_traditional_symbols()


# ==================== TRADITIONAL DECK REGISTRY ====================

class TraditionalDeckRegistry:
    """Registry and tools for canonical traditional tarot symbols and artist matching."""

    @classmethod
    def get_all_symbols(cls) -> list[dict[str, Any]]:
        """Return all canonical traditional tarot symbols."""
        return [s.copy() for s in TRADITIONAL_TAROT_SYMBOLS]

    @classmethod
    def get_symbol_by_id(cls, symbol_id: str) -> dict[str, Any] | None:
        """Find a canonical symbol by its ID."""
        for sym in TRADITIONAL_TAROT_SYMBOLS:
            if sym["id"] == symbol_id:
                return sym.copy()
        return None

    @classmethod
    def get_symbols_for_card(cls, card_def_or_title: str | dict[str, Any]) -> list[dict[str, Any]]:
        """
        Return the canonical traditional symbols associated with a specific card.
        Accepts either a string card title (e.g. 'The Fool', 'Three of Cups', 'Queen of Swords')
        or a card definition dictionary.
        """
        if isinstance(card_def_or_title, str):
            title = card_def_or_title.strip()
            suit = None
            rank = None
            for s in Config.SUITS:
                if f"of {s}" in title or title.startswith(s):
                    suit = s
                    break
        else:
            title = card_def_or_title.get("title", "")
            suit = card_def_or_title.get("suit")
            rank = card_def_or_title.get("rank")

        matched: list[dict[str, Any]] = []

        # 1. Exact card title match in symbol's cards list
        for sym in TRADITIONAL_TAROT_SYMBOLS:
            if title in sym.get("cards", []):
                matched.append(sym.copy())

        # 2. Suit-based match for Minor Arcana
        if suit:
            suit_cat = f"suit_{suit.lower()}"
            for sym in TRADITIONAL_TAROT_SYMBOLS:
                if sym.get("category") == suit_cat and sym not in matched:
                    matched.append(sym.copy())

            # Court card motifs
            rank_str = str(rank) if rank is not None else ""
            courts = ["Page", "Knight", "Queen", "King"]
            if any(court in title or court == rank_str for court in courts):
                for court in courts:
                    if court in title or court == rank_str:
                        for sym in TRADITIONAL_TAROT_SYMBOLS:
                            if (
                                sym.get("category") == "court"
                                and court.lower() in sym["id"]
                                and sym not in matched
                            ):
                                matched.append(sym.copy())

        return matched

    @classmethod
    def match_artist_symbols(cls, artist_symbols: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Analyze artist-provided symbols and match them against canonical traditional tarot archetypes.

        Returns a detailed report including:
        - matched: list of artist symbols correlated to traditional archetypes with card associations
        - unmatched_artist: custom symbols provided by artist that don't match standard archetypes
        - missing_traditional: traditional tarot symbols still unfulfilled
        - coverage: summary statistics (percentages, suits covered, major arcana covered)
        """
        canonical_pool = cls.get_all_symbols()
        matched: list[dict[str, Any]] = []
        covered_canonical_ids: set[str] = set()
        unmatched_artist: list[dict[str, Any]] = []

        for artist_sym in artist_symbols:
            name = (artist_sym.get("name") or "").strip().lower()
            desc = (artist_sym.get("description") or "").strip().lower()
            best_match: dict[str, Any] | None = None
            best_score = 0.0

            for canon in canonical_pool:
                canon_name = canon["name"].lower()
                canon_id = canon["id"].lower()
                score = 0.0

                # Exact name or ID match
                if name in (canon_name, canon_id):
                    score = 1.0
                elif canon_name in name or name in canon_name:
                    score = 0.85
                else:
                    # Keyword matching
                    kw_hits = sum(
                        1 for kw in canon.get("keywords", [])
                        if re.search(rf"\b{re.escape(kw)}\b", f"{name} {desc}")
                    )
                    if kw_hits > 0:
                        score = min(0.9, 0.55 + (kw_hits * 0.15))

                if score > best_score:
                    best_score = score
                    best_match = canon

            if best_match and best_score >= 0.50:
                covered_canonical_ids.add(best_match["id"])
                matched.append({
                    "traditional_id": best_match["id"],
                    "traditional_name": best_match["name"],
                    "traditional_category": best_match["category"],
                    "associated_cards": best_match["cards"],
                    "match_score": round(best_score, 2),
                    "artist_symbol": artist_sym,
                })
            else:
                unmatched_artist.append(artist_sym)

        # Missing traditional symbols
        missing_traditional = [
            c for c in canonical_pool if c["id"] not in covered_canonical_ids
        ]

        # Calculate coverage metrics
        total_canon = len(canonical_pool)
        matched_count = len(covered_canonical_ids)
        pct = round((matched_count / total_canon) * 100.0, 1) if total_canon else 0.0

        # Suit coverage
        suits_covered = []
        for suit in Config.SUITS:
            suit_cat = f"suit_{suit.lower()}"
            if any(m["traditional_category"] == suit_cat for m in matched):
                suits_covered.append(suit)

        # Major Arcana coverage
        majors_covered = []
        for _, major_title in Config.MAJOR_ARCANA:
            if any(major_title in m["associated_cards"] for m in matched):
                majors_covered.append(major_title)

        return {
            "matched": matched,
            "matched_count": matched_count,
            "unmatched_artist": unmatched_artist,
            "unmatched_count": len(unmatched_artist),
            "missing_traditional": missing_traditional,
            "missing_count": len(missing_traditional),
            "coverage": {
                "total_traditional_symbols": total_canon,
                "provided_symbols_count": len(artist_symbols),
                "matched_traditional_count": matched_count,
                "coverage_percentage": pct,
                "suits_covered": suits_covered,
                "suits_missing": [s for s in Config.SUITS if s not in suits_covered],
                "major_arcana_covered": majors_covered,
                "major_arcana_covered_count": len(majors_covered),
            },
        }

    @classmethod
    def get_missing_symbols(
        cls,
        provided_symbols: list[dict[str, Any]],
        target_scope: str = "full",
    ) -> list[dict[str, Any]]:
        """
        Extract missing canonical traditional symbols given a list of provided symbols.
        target_scope can be 'full' (all cards), 'major' (Major only), or 'suits'.
        """
        analysis = cls.match_artist_symbols(provided_symbols)
        missing = analysis["missing_traditional"]

        if target_scope == "major":
            return [s for s in missing if s.get("category") == "major_arcana"]
        elif target_scope == "suits":
            return [s for s in missing if s.get("category", "").startswith("suit_")]
        return missing

    @classmethod
    def assign_symbols_for_card(
        cls,
        card_def: dict[str, Any],
        available_symbols: list[dict[str, Any]] | None = None,
        traditional_mode: bool = True,
        max_symbols: int = 4,
        analysis: dict[str, Any] | None = None,
    ) -> list[str]:
        """
        Assign authentic symbols for a specific card.

        If traditional_mode is True:
        1. Identifies the canonical traditional symbols for this card.
        2. If available_symbols match those canonical archetypes, uses the artist's symbol.
        3. If traditional slots remain, fills with the traditional archetype descriptions.
        4. If extra space remains, blends in unmatched artist symbols (accent/flair symbols).

        ``analysis`` may be a precomputed ``match_artist_symbols(available_symbols)``
        result; when omitted it is computed here.

        If traditional_mode is False:
        Falls back to legacy random sampling.
        """
        if not traditional_mode:
            import random
            available = available_symbols or Config.DEFAULT_SYMBOLS
            names = [s["name"] if isinstance(s, dict) else s for s in available]
            num_pick = min(max_symbols, len(names))
            return random.sample(names, k=num_pick)

        card_symbols: list[str] = []
        canonical_symbols = cls.get_symbols_for_card(card_def)

        # Map available symbols to canonical archetypes if present
        matched_map: dict[str, dict[str, Any]] = {}
        unmatched_artist: list[dict[str, Any]] = []
        if analysis is None and available_symbols:
            analysis = cls.match_artist_symbols(available_symbols)
        if analysis:
            for m in analysis.get("matched", []):
                matched_map[m["traditional_id"]] = m["artist_symbol"]
            unmatched_artist = analysis.get("unmatched_artist", [])

        # Prioritize artist-provided symbols that match this card's canonical archetypes
        for canon in canonical_symbols:
            cid = canon["id"]
            if cid in matched_map:
                art_sym = matched_map[cid]
                # Use artist's symbol name + description
                desc = art_sym.get("description", art_sym.get("name", ""))
                card_symbols.append(f"{art_sym['name']} ({desc})")
            elif len(card_symbols) < max_symbols:
                # Use canonical traditional symbol description
                card_symbols.append(canon["name"])

        # If card has fewer symbols than max, sprinkle in unmatched artist symbols as creative accent
        if len(card_symbols) < max_symbols and unmatched_artist:
            for art in unmatched_artist:
                art_str = art.get("name", "")
                if art_str and art_str not in card_symbols:
                    card_symbols.append(art_str)
                    if len(card_symbols) >= max_symbols:
                        break

        # Fallback if somehow still empty
        if not card_symbols:
            card_symbols = [s["name"] for s in canonical_symbols[:max_symbols]]

        return card_symbols[:max_symbols]

    @classmethod
    def complete_deck_symbols(
        cls,
        symbols_config: dict[str, Any],
        deck_name: str,
        deck_prompt: str,
        api_key: str,
        image_model: str,
        target_scope: str = "full",
        max_missing: int | None = None,
        rate_limit: float = 1.5,
    ) -> dict[str, Any]:
        """
        Take an artist's partial symbol set, identify missing traditional symbols,
        and generate cohesive reference artwork for them using Venice AI in the artist's visual style.
        Returns the unified symbols_config containing both artist and generated symbols.
        """
        symbols_dir = symbols_dir_for(deck_name)
        os.makedirs(symbols_dir, exist_ok=True)

        provided = symbols_config.get("symbols", [])
        # Tag provided symbols as source: artist
        for s in provided:
            if "source" not in s:
                s["source"] = "artist"
        artist_count = sum(1 for s in provided if s.get("source") == "artist")

        missing = cls.get_missing_symbols(provided, target_scope=target_scope)
        if max_missing and max_missing > 0:
            missing = missing[:max_missing]

        if not missing:
            logger.info("No missing traditional symbols need generation")
            updated_config = {
                **symbols_config,
                "symbols": list(provided),
                "artist_symbol_count": artist_count,
                "generated_symbol_count": 0,
                "failed_symbol_count": 0,
                "failed_symbols": [],
            }
            manifest_path = os.path.join(symbols_dir, "symbols.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(updated_config, f, indent=2)
            return updated_config

        style = symbols_config.get("style_prompt", "")
        if not style:
            style = (
                "intricate symbolic linework, vivid atmospheric lighting, "
                "sacred geometry, dramatic composition, masterwork tarot illustration"
            )
        if deck_prompt:
            style = f"{deck_prompt}. {style}"

        logger.info(f"Generating {len(missing)} missing traditional tarot symbols in artist style...")

        generated_symbols: list[dict[str, Any]] = []
        failed_symbols: list[dict[str, Any]] = []
        iterator: Any = range(len(missing))
        if HAS_TQDM:
            iterator = tqdm(iterator, desc="Generating Traditional Symbols", unit="symbol", ncols=110)

        for i in iterator:
            from .runtime import check_cancelled
            check_cancelled()
            sym = missing[i]
            if HAS_TQDM:
                iterator.set_description(f"Symbol: {sym['name'][:25]}")

            prompt = (
                f"A single isolated symbolic tarot icon: {sym['description']}. "
                f"Visual style: {style}. "
                "Centered iconic composition on dark neutral background, "
                "suitable as a recurring traditional tarot card symbol. No card borders, no letters, no text."
            )

            img_path = _safe_generate_symbol(
                prompt=prompt,
                name=sym["name"],
                output_dir=symbols_dir,
                api_key=api_key,
                model=image_model,
                rate_limit=rate_limit,
            )

            if not img_path:
                logger.warning(f"  Failed to generate traditional symbol: {sym['name']}")
                failed_symbols.append({
                    "name": sym["name"],
                    "traditional_id": sym["id"],
                    "category": sym["category"],
                })
                continue

            entry = {
                "name": sym["name"],
                "description": sym["description"],
                "image": img_path,
                "source": "generated",
                "traditional_id": sym["id"],
                "category": sym["category"],
            }
            generated_symbols.append(entry)

        # Merge provided and generated symbols
        merged_symbols = list(provided) + generated_symbols
        updated_config = {
            "style_prompt": symbols_config.get("style_prompt", ""),
            "symbols": merged_symbols,
            "artist_symbol_count": artist_count,
            "generated_symbol_count": len(generated_symbols),
            "failed_symbol_count": len(failed_symbols),
            "failed_symbols": failed_symbols,
        }

        # Save manifest
        manifest_path = os.path.join(symbols_dir, "symbols.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(updated_config, f, indent=2)
        logger.info(f"Completed symbols saved to: {manifest_path}")

        return updated_config


# ==================== SYMBOL CONFIGURATION ====================

def symbols_dir_for(deck_name: str) -> str:
    """Directory holding a deck's symbol images and manifests.

    ``OUTPUT_DIR/symbols/<deck>`` is used everywhere (artist uploads, generated
    traditional symbols, cohesive symbol generation) so a deck's symbols are
    always in one place and a deck called ``images`` can't collide with the
    top-level images folder.
    """
    return os.path.join(Config.OUTPUT_DIR, "symbols", deck_name)


def _safe_generate_symbol(**kwargs: Any) -> str | None:
    """Call ``_generate_single_symbol`` but turn exhausted retries into ``None``.

    The retry decorator re-raises the last exception; one bad symbol must not
    abort generation of the remaining symbols (or the whole deck).
    """
    from .runtime import JobCancelledError, check_cancelled

    check_cancelled()
    try:
        return _generate_single_symbol(**kwargs)
    except JobCancelledError:
        raise
    except Exception as e:
        logger.warning(f"Symbol generation failed for {kwargs.get('name')!r}: {e}")
        return None


def load_symbols_config(symbols_file: str | None = None) -> dict[str, Any]:
    """
    Load symbol definitions from a JSON file.

    Expected format:
    {
      "style_prompt": "shared visual style description (optional)",
      "symbols": [
        {"name": "...", "description": "...", "image": "path/to/img.png (optional)"},
        ...
      ]
    }

    Falls back to Config.DEFAULT_SYMBOLS if no file provided or found.
    Also supports legacy custom_elements/elements_config.json for backward compatibility.
    """
    # Try explicit symbols file
    if symbols_file and os.path.exists(symbols_file):
        try:
            with open(symbols_file, encoding="utf-8") as f:
                config = json.load(f)
            if "symbols" in config and isinstance(config["symbols"], list):
                logger.info(f"Loaded {len(config['symbols'])} symbols from {symbols_file}")
                return config
            else:
                logger.warning(f"Invalid symbols file (missing 'symbols' list): {symbols_file}")
        except Exception as e:
            logger.warning(f"Could not parse symbols file {symbols_file}: {e}")

    # Try legacy elements_config.json
    legacy_path = os.path.join("custom_elements", "elements_config.json")
    if os.path.exists(legacy_path):
        try:
            with open(legacy_path, encoding="utf-8") as f:
                legacy = json.load(f)
            symbols = []
            for name, filename in legacy.items():
                img_path = os.path.join("custom_elements", filename)
                symbols.append({
                    "name": name,
                    "description": name,
                    "image": img_path if os.path.exists(img_path) else None,
                    "source": "artist",
                })
            logger.info(f"Loaded {len(symbols)} symbols from legacy elements_config.json")
            return {"symbols": symbols, "style_prompt": ""}
        except Exception as e:
            logger.warning(f"Could not parse legacy config: {e}")

    # Default
    logger.info("Using default symbol definitions")
    return {"symbols": [s.copy() for s in Config.DEFAULT_SYMBOLS], "style_prompt": ""}


def generate_symbol_images(
    symbols_config: dict[str, Any],
    deck_name: str,
    deck_prompt: str,
    api_key: str,
    image_model: str,
    rate_limit: float = 1.5,
) -> dict[str, Any]:
    """
    Generate cohesive symbol reference images for every symbol that lacks an image.
    Uses a shared style prompt so all generated symbols match visually.
    Returns the updated symbols_config with image paths filled in.
    """
    if not api_key or not requests:
        logger.warning("Cannot generate symbol images: missing API key or requests library")
        return symbols_config

    symbols_dir = symbols_dir_for(deck_name)
    os.makedirs(symbols_dir, exist_ok=True)

    style = symbols_config.get("style_prompt", "")
    if not style:
        style = (
            "psychedelic neon glitch vortex style, intricate symbolic linework, "
            "electric vivid colors, dramatic cinematic lighting, high detail"
        )
    if deck_prompt:
        style = f"{deck_prompt}. {style}"

    symbols = symbols_config["symbols"]
    need_gen = [s for s in symbols if not (s.get("image") and os.path.exists(str(s["image"])))]

    if not need_gen:
        logger.info("All symbols already have images — skipping generation")
        return symbols_config

    logger.info(f"Generating {len(need_gen)} symbol images with cohesive style...")

    iterator: Any = range(len(need_gen))
    if HAS_TQDM:
        iterator = tqdm(iterator, desc="Generating Symbols", unit="symbol", ncols=110)

    for i in iterator:
        symbol = need_gen[i]
        if HAS_TQDM:
            iterator.set_description(f"Symbol: {symbol['name'][:25]}")

        prompt = (
            f"A single isolated symbolic element: {symbol['description']}. "
            f"Visual style: {style}. "
            "Centered composition on a dark background, "
            "suitable as a recurring tarot card symbol. No text, no borders, no frames."
        )

        img_path = _safe_generate_symbol(
            prompt=prompt,
            name=symbol["name"],
            output_dir=symbols_dir,
            api_key=api_key,
            model=image_model,
            rate_limit=rate_limit,
        )

        if img_path:
            symbol["image"] = img_path
            logger.info(f"  Generated symbol: {symbol['name']}")
        else:
            logger.warning(f"  Failed to generate symbol: {symbol['name']}")

    # Save manifest so symbols can be reused later
    manifest_path = os.path.join(symbols_dir, "symbols_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(symbols_config, f, indent=2, ensure_ascii=False)
    logger.info(f"Symbol manifest saved: {manifest_path}")

    return symbols_config


def _generate_single_symbol(
    prompt: str,
    name: str,
    output_dir: str,
    api_key: str,
    model: str,
    rate_limit: float,
) -> str | None:
    """Generate a single symbol image via Venice."""
    if not api_key or not requests:
        return None

    time.sleep(rate_limit)

    from .runtime import current_usage_tracker
    from .venice import _build_image_request, _extract_image_b64, venice_post

    tracker = current_usage_tracker()
    try:
        resp = venice_post(
            Config.VENICE_IMAGE_URL,
            api_key,
            _build_image_request(model, prompt, "1024x1024", Config.DEFAULT_NEGATIVE_PROMPT),
            timeout=180,
            initial_delay=2.0,
        )
        data = resp.json()
    except Exception:
        if tracker:
            tracker.record_image_call(model, "1024x1024", success=False, purpose="symbol")
        raise

    b64 = _extract_image_b64(data)
    if b64:
        filepath = os.path.join(output_dir, symbol_filename(name))
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(b64))
        if tracker:
            tracker.record_image_call(model, "1024x1024", success=True, purpose="symbol")
        return filepath
    if tracker:
        tracker.record_image_call(model, "1024x1024", success=False, purpose="symbol")
    return None


def symbol_filename(name: str) -> str:
    """Filesystem-safe, collision-resistant PNG filename for a symbol name.

    Slugs alone collide when long names share a prefix (or differ only in
    punctuation), so a short content hash of the full name is appended.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")[:30] or "symbol"
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"symbol_{slug}_{digest}.png"

