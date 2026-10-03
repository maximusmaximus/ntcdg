"""MCP (Model Context Protocol) server for NTCDG.

Exposes all deck management functions as MCP tools so AI agents
(like Hermes on Telegram) can control deck generation programmatically.

Run with:
    python -m ntcdg.mcp_server            # stdio transport (default)
    python -m ntcdg.mcp_server --sse      # SSE transport for web clients

Requires: pip install "mcp[cli]"
"""

import os
import sys
from typing import Any

# Defer MCP import — allow module to load without mcp installed
# (tools still work as plain functions for testing/direct use)
_HAS_MCP = False
try:
    from mcp.server.fastmcp import FastMCP
    _HAS_MCP = True
except ImportError:
    FastMCP = None

from .config import Config, setup_logging
from .runtime import capture_output, get_venice_key
from .venice import _extract_text_content

setup_logging()

if _HAS_MCP:
    mcp = FastMCP(
        "ntcdg",
        description="Novel Tarot Card Deck Generator — create AI-powered tarot decks",
    )
else:
    # Stub: when mcp isn't installed, @mcp.tool() is a no-op decorator
    class _Stub:
        @staticmethod
        def tool():
            return lambda fn: fn

        def run(self, **kwargs):
            print(
                "MCP server requires the 'mcp' package. Install with:\n"
                "  pip install 'mcp[cli]'",
                file=sys.stderr,
            )
            sys.exit(1)

    mcp = _Stub()


# ==================== HELPERS ====================

MAX_CARDS = 200


def _capture_print(func, *args, **kwargs) -> str:
    """Call a function that prints to stdout and capture the output.

    Uses per-thread capture so concurrent tool calls don't interleave.
    """
    _result, output = capture_output(func, *args, **kwargs)
    return output


def _get_venice_key() -> str:
    """Get the Venice API key bound to this request, else from the environment."""
    return get_venice_key(required=True)


def _deck_summary(deck_name: str) -> dict[str, Any]:
    """Build a structured summary of a deck."""
    from .storage import load_deck, load_decks_index

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


# ==================== TOOLS ====================

@mcp.tool()
def create_deck(
    name: str,
    cards: int = 78,
    vibe: str = "ethereal dreamscape",
    deck_prompt: str = "",
    symbol_mode: str = "generate",
    symbols_file: str = "",
    image_size: str = "",
    traditional_mode: bool = True,
    auto_complete_symbols: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create a new tarot card deck with AI-generated art and meanings.

    Args:
        name: Deck name (letters, numbers, underscores, hyphens; max 100 chars)
        cards: Number of cards, 1-200 (22 for Major Arcana only, 78 for full)
        vibe: Artistic style/aesthetic (e.g., "cosmic horror meets art nouveau")
        deck_prompt: Additional theme instructions
        symbol_mode: "generate" (AI creates) or "provide" (user artwork)
        symbols_file: Path to symbols.json (when symbol_mode="provide")
        image_size: Image dimensions (default: 768x1280 for 3:5 tarot bleed)
        traditional_mode: If True, cards use authentic canonical tarot symbols
        auto_complete_symbols: If True, AI completes missing traditional symbols in artist style
        overwrite: If True, replace an existing deck with the same name
    """
    from .generator import generate_deck
    from .storage import deck_exists, validate_deck_name

    try:
        validate_deck_name(name)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    if not 1 <= int(cards) <= MAX_CARDS:
        return {"success": False, "error": f"cards must be between 1 and {MAX_CARDS}"}
    if symbol_mode not in ("generate", "provide"):
        return {"success": False, "error": "symbol_mode must be 'generate' or 'provide'"}
    if symbols_file and not os.path.isfile(symbols_file):
        return {"success": False, "error": f"symbols_file not found: {symbols_file}"}
    if deck_exists(name) and not overwrite:
        return {
            "success": False,
            "error": (
                f"Deck '{name}' already exists. Use retry_failed to resume it, "
                "or pass overwrite=True to replace it."
            ),
        }

    venice_key = _get_venice_key()
    size = image_size or Config.DEFAULT_IMAGE_SIZE

    if overwrite and deck_exists(name):
        from .storage import delete_deck as _delete
        _capture_print(_delete, name, confirm=False)

    generate_deck(
        name=name,
        num_cards=int(cards),
        vibe=vibe,
        deck_prompt=deck_prompt,
        venice_key=venice_key,
        analyze=True,
        text_model=Config.DEFAULT_TEXT_MODEL,
        generate_images=True,
        image_model=Config.DEFAULT_IMAGE_MODEL,
        image_size=size,
        negative_prompt="",
        rate_limit=1.5,
        interactive=False,   # No stdin prompts
        symbol_mode=symbol_mode,
        symbols_file=symbols_file or None,
        preview=False,       # No interactive preview
        traditional_mode=traditional_mode,
        auto_complete_symbols=auto_complete_symbols,
    )

    return _deck_summary(name)


@mcp.tool()
def list_decks() -> dict[str, Any]:
    """List all saved tarot decks with card counts and themes."""
    from .storage import load_decks_index

    index = load_decks_index()
    if not index:
        return {"decks": [], "count": 0}

    decks = []
    for deck_name, info in sorted(index.items()):
        decks.append({
            "name": deck_name,
            "cards": info.get("num_cards", 0),
            "vibe": info.get("vibe", ""),
            "theme": info.get("theme", ""),
            "last_modified": info.get("last_modified", ""),
            "has_back": bool(info.get("back_image", "")),
        })

    return {"decks": decks, "count": len(decks)}


@mcp.tool()
def deck_info(deck_name: str) -> dict[str, Any]:
    """Get detailed status and readiness report for a deck.

    Shows completion percentages, error counts, and whether
    the deck is ready for finalization.
    """
    return _deck_summary(deck_name)


@mcp.tool()
def deck_stats(deck_name: str) -> dict[str, Any]:
    """Get API usage, cost estimate, and generation stats for a deck.

    Shows token counts, API call counts, estimated cost in USD,
    generation time, models used, symbol info, and the style prompt.
    """
    from .storage import load_decks_index

    index = load_decks_index()
    meta = index.get(deck_name, {})
    if not meta:
        return {"error": f"Deck '{deck_name}' not found"}

    usage = meta.get("usage", {})
    if not usage:
        return {"error": f"No usage stats recorded for '{deck_name}'"}

    return {
        "deck_name": deck_name,
        **usage,
    }


@mcp.tool()
def list_cards(deck_name: str) -> dict[str, Any]:
    """List all cards in a deck with completion status per card.

    Returns each card's title, type, and whether it has an image,
    analysis text, and upright/reversed meanings.
    """
    from .storage import load_deck

    deck = load_deck(deck_name)
    if not deck:
        return {"error": f"Deck '{deck_name}' not found"}

    sorted_deck = sorted(deck, key=lambda c: c.position or 0)
    cards = []
    for card in sorted_deck:
        has_img = bool(
            card.image_path and os.path.exists(str(card.image_path))
        )
        has_text = bool(card.description and not card.venice_error)
        has_mean = bool(
            card.upright_interpretation and card.reversed_interpretation
        )

        entry = {
            "position": card.position,
            "title": card.display_title(),
            "type": card.card_type or "",
            "has_image": has_img,
            "has_analysis": has_text,
            "has_meanings": has_mean,
            "complete": has_img and has_text and has_mean,
        }
        if card.image_path and has_img:
            entry["image_path"] = card.image_path
        if card.venice_error:
            entry["error"] = card.venice_error
        if card.image_error:
            entry["error"] = card.image_error

        cards.append(entry)

    complete = sum(1 for c in cards if c["complete"])
    return {
        "deck_name": deck_name,
        "total": len(cards),
        "complete": complete,
        "cards": cards,
    }


@mcp.tool()
def retry_failed(deck_name: str) -> dict[str, Any]:
    """Retry generation for failed or incomplete cards in a deck.

    Only re-processes cards that are missing images, analysis, or
    had errors. Already-complete cards are skipped.
    """
    from .generator import generate_deck
    from .storage import deck_exists, load_deck, load_decks_index

    if not deck_exists(deck_name):
        return {
            "success": False,
            "error": f"Deck '{deck_name}' not found. Use create_deck to start a new deck.",
        }

    venice_key = _get_venice_key()

    index = load_decks_index()
    meta = index.get(deck_name, {})
    target = meta.get("target_cards") or meta.get("num_cards") or len(load_deck(deck_name))

    generate_deck(
        name=deck_name,
        num_cards=int(target),
        vibe=meta.get("vibe"),
        deck_prompt=meta.get("theme", ""),
        venice_key=venice_key,
        analyze=True,
        text_model=Config.DEFAULT_TEXT_MODEL,
        generate_images=True,
        image_model=Config.DEFAULT_IMAGE_MODEL,
        image_size=Config.DEFAULT_IMAGE_SIZE,
        negative_prompt="",
        rate_limit=1.5,
        interactive=False,
        resume=True,
        preview=False,
    )

    return _deck_summary(deck_name)


@mcp.tool()
def generate_back(
    deck_name: str,
    prompt: str,
) -> dict[str, Any]:
    """Generate a card back design for a deck.

    Args:
        deck_name: Name of the deck
        prompt: Art prompt for the back design (e.g., "sacred geometry mandala")
    """
    from .storage import deck_exists, update_deck_meta
    from .venice import generate_card_back

    if not deck_exists(deck_name):
        return {"success": False, "error": f"Deck '{deck_name}' not found"}
    if not prompt or not prompt.strip():
        return {"success": False, "error": "prompt must not be empty"}

    venice_key = _get_venice_key()

    back_path = generate_card_back(
        prompt=prompt,
        api_key=venice_key,
        model=Config.DEFAULT_IMAGE_MODEL,
        deck_name=deck_name,
        image_size=Config.DEFAULT_IMAGE_SIZE,
        rate_limit_delay=1.5,
    )

    if back_path:
        update_deck_meta(deck_name, back_image=back_path, back_prompt=prompt)
        return {"success": True, "back_image_path": back_path}

    return {"success": False, "error": "Failed to generate card back"}


@mcp.tool()
def finalize_deck(
    deck_name: str,
    sheet_size: str = "letter",
    color_mode: str = "color",
    duplex_flip: str = "long_edge",
    qr_codes: bool = True,
    public_base_url: str = "",
    rebase_url: bool = False,
    back_offset_x_mm: float = 0.0,
    back_offset_y_mm: float = 0.0,
) -> dict[str, Any]:
    """Generate print-ready, duplex-registered PDFs (fronts, per-card QR backs, booklet).

    Produces an interleaved DUPLEX PDF (print 2-sided) plus separate fronts and
    backs files, all from one slot plan so every back lines up with its front.
    Each back carries a QR code linking to that card's public page.

    Args:
        deck_name: Name of the deck to finalize
        sheet_size: "letter" (8.5x11), "tabloid" (11x17), "a4", or "a3"
        color_mode: "color" or "bw" (both output as CMYK)
        duplex_flip: "long_edge" (flip like a book; default) or "short_edge"
        qr_codes: Put a per-card QR code on each back (needs a public base URL)
        public_base_url: e.g. "https://tarot.example.com" (default: NTCDG_PUBLIC_BASE_URL).
            Baked into the deck on first finalize so reprints keep the same codes.
        rebase_url: Allow changing a deck's already-baked public URL
        back_offset_x_mm: Printer drift correction for backs (+ = right), from the calibration sheet
        back_offset_y_mm: Printer drift correction for backs (+ = up)

    Returns success, the exact output files, QR/public URL info and validation errors/warnings.
    """
    from .finalize import finalize_deck_report

    try:
        report, output = capture_output(
            finalize_deck_report,
            deck_name,
            sheet_size=sheet_size,
            color_mode=color_mode,
            duplex_flip=duplex_flip,
            qr_codes=qr_codes,
            public_base_url=public_base_url or None,
            rebase_url=rebase_url,
            back_offset_mm=(back_offset_x_mm, back_offset_y_mm),
        )
    except ValueError as e:
        return {"success": False, "deck_name": deck_name, "error": str(e)}

    pdfs = [p for p in (report["duplex_pdf"], report["print_pdf"], report["backs_pdf"]) if p]
    return {
        "success": report["success"],
        "deck_name": deck_name,
        "error": report["error"] or None,
        "pdfs": pdfs,
        "duplex_pdf": report["duplex_pdf"] or None,
        "print_pdf": report["print_pdf"] or None,
        "backs_pdf": report["backs_pdf"] or None,
        "booklet": report["booklet_pdf"] or None,
        "pages": report["pages"],
        "qr": report["qr"],
        "warnings": report["warnings"],
        "validation": report["validation"],
        "output": output,
    }


@mcp.tool()
def duplex_calibration(
    sheet_size: str = "letter",
    duplex_flip: str = "long_edge",
    back_offset_x_mm: float = 0.0,
    back_offset_y_mm: float = 0.0,
) -> dict[str, Any]:
    """Create a 2-page duplex calibration sheet to check front/back registration.

    Print it 2-sided with the same printer settings as the deck and hold it to a
    light. If the back crosshairs are shifted, measure the shift in mm and pass
    it to finalize_deck as back_offset_x_mm / back_offset_y_mm.
    """
    from .duplex import create_calibration_pdf

    try:
        path = create_calibration_pdf(
            sheet_size, duplex_flip, (back_offset_x_mm, back_offset_y_mm),
        )
    except ValueError as e:
        return {"success": False, "error": str(e)}
    if not path:
        return {"success": False, "error": "reportlab is required"}
    return {
        "success": True,
        "calibration_pdf": path,
        "instructions": (
            f"Print 2-sided, flip on {duplex_flip.replace('_', ' ')}, at 100% scale. "
            "Hold to a light: crosshairs on both sides should coincide. "
            "Measure any shift in mm (+x = backs need to move right, +y = up, "
            "as seen on the back) and pass it to finalize_deck."
        ),
    }


@mcp.tool()
def get_public_links(deck_name: str) -> dict[str, Any]:
    """Get the public deck URL and every card's QR/page URL for a finalized deck."""
    from .public import public_links
    from .storage import deck_exists

    if not deck_exists(deck_name):
        return {"enabled": False, "error": f"Deck '{deck_name}' not found"}
    return public_links(deck_name)


@mcp.tool()
def get_card_by_slug(deck_slug: str, card_slug: str) -> dict[str, Any]:
    """Resolve a scanned QR code (deck slug + card slug) to the card's full details.

    Only published (finalized with a public URL) decks resolve. Also returns
    the previous/next card slugs so a viewer can swipe through the deck.
    """
    from .public import card_slug as make_card_slug
    from .public import find_deck_by_slug, parse_card_position
    from .storage import load_deck

    found = find_deck_by_slug(deck_slug)
    position = parse_card_position(card_slug)
    if not found or not found[1].get("published") or position is None:
        return {"error": "Card not found"}
    deck_name, _meta = found
    cards = sorted(load_deck(deck_name), key=lambda c: c.position or 0)
    idx = next((i for i, c in enumerate(cards) if c.position == position), None)
    if idx is None:
        return {"error": "Card not found"}
    card = cards[idx]
    prev_card = cards[idx - 1] if cards else None
    next_card = cards[(idx + 1) % len(cards)]
    return {
        "deck_slug": deck_slug,
        "card_slug": make_card_slug(card),
        "position": card.position,
        "total": len(cards),
        "title": card.display_title(),
        "original_title": card.title,
        "card_type": card.card_type or "",
        "suit": card.suit,
        "symbols": card.symbols,
        "description": card.description or "",
        "upright_interpretation": card.upright_interpretation or "",
        "reversed_interpretation": card.reversed_interpretation or "",
        "has_image": bool(card.image_path and os.path.exists(str(card.image_path))),
        "prev_card_slug": make_card_slug(prev_card) if prev_card else None,
        "next_card_slug": make_card_slug(next_card),
    }


@mcp.tool()
def export_bundle(deck_name: str) -> dict[str, Any]:
    """Create a zip bundle with all deck assets for distribution.

    Bundle includes: card images, PDFs, booklet, spreadsheet, deck JSON.
    """
    from .finalize import export_deck_bundle

    zip_path = export_deck_bundle(deck_name)
    if zip_path:
        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        return {
            "success": True,
            "zip_path": zip_path,
            "size_mb": round(size_mb, 2),
        }
    return {"success": False, "error": "Export failed"}


@mcp.tool()
def edit_card(
    deck_name: str,
    card_num: int,
    field: str,
    value: str,
) -> dict[str, Any]:
    """Edit a single field of a card in a saved deck.

    Args:
        deck_name: Deck to edit
        card_num: Card position number (1-based)
        field: Field to edit (title, description, upright_interpretation, reversed_interpretation)
        value: New value for the field
    """
    from .storage import edit_card_field

    success, output = capture_output(edit_card_field, deck_name, card_num, field, value)
    result: dict[str, Any] = {"success": bool(success), "card_num": card_num, "field": field}
    if not success:
        result["error"] = output or "Edit failed"
    return result


@mcp.tool()
def clone_deck(source: str, new_name: str) -> dict[str, Any]:
    """Clone a deck and all its images under a new name.

    Args:
        source: Source deck name
        new_name: Name for the cloned deck
    """
    from .storage import clone_deck as _clone

    success = _clone(source, new_name)
    if success:
        return {"success": True, **_deck_summary(new_name)}
    return {"success": False, "error": "Clone failed"}


@mcp.tool()
def delete_deck(deck_name: str) -> dict[str, Any]:
    """Delete a deck and all its associated files.

    This permanently removes the deck JSON, all card images,
    PDFs, spreadsheets, and the index entry.
    """
    from .storage import delete_deck as _delete

    # Skip confirmation for programmatic use
    success = _delete(deck_name, confirm=False)
    return {"success": success, "deleted": deck_name}


@mcp.tool()
def get_card_image(deck_name: str, card_num: int) -> dict[str, Any]:
    """Get the file path to a specific card's image.

    Args:
        deck_name: Deck name
        card_num: Card position number (1-based)

    Returns the absolute path to the card image if it exists.
    """
    from .storage import load_deck

    deck = load_deck(deck_name)
    if not deck:
        return {"error": f"Deck '{deck_name}' not found"}

    card = next((c for c in deck if c.position == card_num), None)
    if not card:
        return {"error": f"Card {card_num} not found"}

    if card.image_path and os.path.exists(str(card.image_path)):
        return {
            "card_num": card_num,
            "title": card.display_title(),
            "image_path": os.path.abspath(card.image_path),
        }
    return {
        "card_num": card_num,
        "title": card.display_title(),
        "error": "Image not generated yet",
    }


@mcp.tool()
def get_card_details(deck_name: str, card_num: int) -> dict[str, Any]:
    """Get full details for a specific card including title, meanings, and prompt.

    Args:
        deck_name: Deck name
        card_num: Card position number (1-based)
    """
    from .storage import load_deck

    deck = load_deck(deck_name)
    if not deck:
        return {"error": f"Deck '{deck_name}' not found"}

    card = next((c for c in deck if c.position == card_num), None)
    if not card:
        return {"error": f"Card {card_num} not found"}

    return {
        "position": card.position,
        "title": card.display_title(),
        "original_title": card.title,
        "card_type": card.card_type or "",
        "symbols": card.symbols,
        "layout": card.layout or "",
        "description": card.description or "",
        "upright_interpretation": card.upright_interpretation or "",
        "reversed_interpretation": card.reversed_interpretation or "",
        "prompt": card.prompt or "",
        "image_path": card.image_path or "",
        "has_image": bool(
            card.image_path and os.path.exists(str(card.image_path))
        ),
        "serial": card.serial or "",
    }


# ==================== SYMBOL REGISTRATION ====================

@mcp.tool()
def register_symbols(
    deck_name: str,
    symbols: list[dict[str, str]],
    auto_describe: bool = True,
    traditional_match: bool = True,
    replace: bool = False,
) -> dict[str, Any]:
    """Register user-provided symbol artwork for a deck.

    Call this when a user sends symbol images in Telegram. It copies
    the images to a standard location and creates a symbols.json file
    that can be passed to preview_style() and create_deck(). Repeated
    calls merge with earlier registrations (same name = replaced).

    Args:
        deck_name: Name of the deck these symbols are for
        symbols: List of symbol definitions, each with:
            - "name": symbol name (e.g., "Serpent")
            - "image_path": absolute path to the image file
            - "description": (optional) description of the symbol
        auto_describe: If True, use Venice vision model to auto-generate
            descriptions for symbols that don't have one
        traditional_match: If True, correlates symbols with traditional
            tarot archetypes and reports deck coverage
        replace: If True, discard previously registered symbols for this deck

    Example:
        register_symbols("Gothic_Rose", [
            {"name": "Serpent", "image_path": "/tmp/serpent.png"},
            {"name": "Eye", "image_path": "/tmp/eye.png"},
        ])
    """
    import json as json_mod
    import shutil

    from .storage import validate_deck_name
    from .symbols import symbol_filename, symbols_dir_for

    try:
        validate_deck_name(deck_name)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    if not isinstance(symbols, list) or not symbols:
        return {"success": False, "error": "symbols must be a non-empty list"}

    symbols_dir = symbols_dir_for(deck_name)
    os.makedirs(symbols_dir, exist_ok=True)
    symbols_file = os.path.join(symbols_dir, "symbols.json")

    # Merge with symbols registered earlier (artists often send art in batches).
    previous: list[dict[str, Any]] = []
    style_prompt = ""
    if not replace and os.path.exists(symbols_file):
        try:
            with open(symbols_file, encoding="utf-8") as f:
                prev_cfg = json_mod.load(f)
            previous = [s for s in prev_cfg.get("symbols", []) if isinstance(s, dict)]
            style_prompt = prev_cfg.get("style_prompt", "")
        except (OSError, ValueError):
            previous = []

    registered = []
    errors = []
    allowed_ext = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

    for sym in symbols:
        if not isinstance(sym, dict):
            errors.append({"error": "Each symbol must be an object", "input": sym})
            continue
        name = (sym.get("name") or "").strip()
        src_path = sym.get("image_path", "")
        description = sym.get("description", "") or ""

        if not name:
            errors.append({"error": "Missing 'name' field", "input": sym})
            continue
        if not src_path or not os.path.isfile(src_path):
            errors.append({
                "name": name,
                "error": f"Image not found: {src_path}",
            })
            continue
        ext = os.path.splitext(src_path)[1].lower() or ".png"
        if ext not in allowed_ext:
            errors.append({"name": name, "error": f"Unsupported image type '{ext}'"})
            continue
        try:
            from PIL import Image
            with Image.open(src_path) as im:
                im.verify()
        except Exception:
            errors.append({"name": name, "error": "File is not a readable image"})
            continue

        # Copy image to symbols dir under a collision-free name
        dest_filename = symbol_filename(name)[: -len(".png")] + ext
        dest_path = os.path.join(symbols_dir, dest_filename)
        if os.path.abspath(src_path) != os.path.abspath(dest_path):
            shutil.copy2(src_path, dest_path)

        registered.append({
            "name": name,
            "description": description,
            "image": os.path.abspath(dest_path),
            "source": "artist",
        })

    # Auto-describe symbols that lack descriptions
    if auto_describe and registered:
        needs_description = [s for s in registered if not s["description"]]
        if needs_description:
            try:
                venice_key = _get_venice_key()
                descriptions = _describe_artwork(
                    [s["image"] for s in needs_description],
                    [s["name"] for s in needs_description],
                    venice_key,
                )
                for sym_entry, desc in zip(needs_description, descriptions, strict=False):
                    sym_entry["description"] = desc
            except Exception:
                # Non-fatal: symbols work without descriptions
                pass
    for sym_entry in registered:
        if not sym_entry["description"]:
            sym_entry["description"] = sym_entry["name"]

    # Newly registered symbols replace earlier ones with the same name
    new_names = {s["name"].lower() for s in registered}
    all_symbols = [s for s in previous if str(s.get("name", "")).lower() not in new_names]
    all_symbols.extend(registered)

    if not registered:
        return {
            "success": False,
            "error": "No valid symbols were registered",
            "registered": 0,
            "errors": errors,
        }

    # Write symbols.json
    symbols_config = {
        "style_prompt": style_prompt,
        "symbols": all_symbols,
    }
    with open(symbols_file, "w", encoding="utf-8") as f:
        json_mod.dump(symbols_config, f, indent=2)

    # Optional traditional tarot symbol matching analysis
    coverage_info = None
    if traditional_match and all_symbols:
        from .symbols import TraditionalDeckRegistry
        coverage_info = TraditionalDeckRegistry.match_artist_symbols(all_symbols)

    response: dict[str, Any] = {
        "success": True,
        "symbols_file": os.path.abspath(symbols_file),
        "symbols_dir": os.path.abspath(symbols_dir),
        "registered": len(registered),
        "total_symbols": len(all_symbols),
        "errors": errors,
        "symbols": [
            {"name": s["name"], "description": s["description"][:80]}
            for s in registered
        ],
        "usage_hint": (
            f'Use with: preview_style(name="{deck_name}", '
            f'symbol_mode="provide", symbols_file="{os.path.abspath(symbols_file)}")'
        ),
    }

    if coverage_info:
        response["traditional_coverage"] = coverage_info["coverage"]
        response["matched_traditional"] = [
            {
                "traditional_name": m["traditional_name"],
                "traditional_category": m["traditional_category"],
                "associated_cards": m["associated_cards"],
                "artist_symbol": m["artist_symbol"]["name"],
            }
            for m in coverage_info.get("matched", [])
        ]
        response["missing_traditional_count"] = coverage_info.get("missing_count", 0)

    return response


def _describe_artwork(
    image_paths: list[str],
    names: list[str],
    api_key: str,
) -> list[str]:
    """Use Venice vision model to describe symbol artwork images.

    Returns a list of descriptions, one per image.
    """
    from .config import requests as req_lib
    if not req_lib:
        return names

    import base64 as b64mod

    content: list[dict[str, Any]] = []
    for path in image_paths:
        try:
            with open(path, "rb") as f:
                b64 = b64mod.b64encode(f.read()).decode()
            ext = os.path.splitext(path)[1].lstrip(".") or "png"
            mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
        except Exception:
            continue

    if not content:
        return names

    names_str = ", ".join(names)
    content.append({
        "type": "text",
        "text": (
            f"These are {len(image_paths)} symbol artwork images named: {names_str}. "
            "For each image, write a brief (10-15 word) description of what it "
            "depicts and its artistic style. Return a JSON object with a "
            "'descriptions' key containing a list of strings, one per image, "
            "in the same order."
        ),
    })

    try:
        resp = req_lib.post(
            Config.VENICE_TEXT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": Config.DEFAULT_VISION_MODEL,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.3,
                "max_tokens": 4000,
            },
            timeout=90,
        )
        resp.raise_for_status()
        raw = _extract_text_content(resp.json())

        import json as json_mod
        import re
        match = re.search(r'```(?:json)?\s*(.*?)```', raw, re.DOTALL)
        parsed_content = match.group(1).strip() if match else raw
        data = json_mod.loads(parsed_content)
        descriptions = data.get("descriptions", [])

        # Pad if we got fewer than expected
        while len(descriptions) < len(names):
            descriptions.append(names[len(descriptions)])
        return descriptions[:len(names)]

    except Exception as e:
        from .config import logger as _logger
        _logger.warning(f"Auto-describe failed: {e}")
        return names


@mcp.tool()
def describe_symbols(
    image_paths: list[str],
) -> dict[str, Any]:
    """Analyze symbol artwork images and suggest names and descriptions.

    Use this BEFORE register_symbols when the user sends images but
    doesn't provide names. The agent can show the suggestions to the
    user for confirmation before registering.

    Args:
        image_paths: List of absolute paths to symbol image files
    """
    venice_key = _get_venice_key()

    try:
        from .config import requests as req_lib
    except ImportError:
        return {"error": "requests library not available"}
    if not req_lib:
        return {"error": "requests library not available"}

    import base64 as b64mod

    content: list[dict[str, Any]] = []
    valid_paths = []
    for path in image_paths:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "rb") as f:
                b64 = b64mod.b64encode(f.read()).decode()
            ext = os.path.splitext(path)[1].lstrip(".") or "png"
            mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
            valid_paths.append(path)
        except Exception:
            continue

    if not content:
        return {"error": "No valid images found", "suggestions": []}

    content.append({
        "type": "text",
        "text": (
            f"These are {len(valid_paths)} artwork images intended as recurring "
            "symbols for a custom tarot card deck. For each image, suggest:\n"
            "1. A short symbolic name (1-2 words)\n"
            "2. A description of what it depicts (10-15 words)\n"
            "3. What it could symbolize in a tarot context\n\n"
            "Return a JSON object with a 'symbols' key containing a list of "
            "objects, each with 'name', 'description', and 'symbolism' fields. "
            "Same order as the images."
        ),
    })

    try:
        resp = req_lib.post(
            Config.VENICE_TEXT_URL,
            headers={"Authorization": f"Bearer {venice_key}"},
            json={
                "model": Config.DEFAULT_VISION_MODEL,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.5,
                "max_tokens": 4000,
            },
            timeout=90,
        )
        resp.raise_for_status()
        raw = _extract_text_content(resp.json())

        import json as json_mod
        import re
        match = re.search(r'```(?:json)?\s*(.*?)```', raw, re.DOTALL)
        parsed_content = match.group(1).strip() if match else raw
        data = json_mod.loads(parsed_content)

        suggestions = data.get("symbols", [])
        # Attach image paths
        for i, suggestion in enumerate(suggestions):
            if i < len(valid_paths):
                suggestion["image_path"] = valid_paths[i]

        return {
            "count": len(suggestions),
            "suggestions": suggestions,
            "hint": (
                "Review these with the user, then call register_symbols() "
                "with the confirmed names and image_paths."
            ),
        }

    except Exception as e:
        return {"error": f"Symbol analysis failed: {e}"}


# ==================== TRADITIONAL TAROT & ARTIST TOOLING ====================

@mcp.tool()
def get_traditional_symbols(
    query: str = "",
    card_name: str = "",
    suit: str = "",
    arcana_type: str = "all",
) -> dict[str, Any]:
    """Browse or search canonical traditional tarot symbols and archetypes.

    Artists and AI agents can query canonical Rider-Waite-Smith and esoteric
    symbolism to plan custom deck art, inspect archetype descriptions, or
    identify which symbols belong to specific cards or suits.

    Args:
        query: Search string to match in symbol names, descriptions, or keywords
        card_name: Specific card title (e.g., 'The Fool', 'Three of Cups', 'The World')
        suit: Filter by suit ('Wands', 'Cups', 'Swords', 'Pentacles')
        arcana_type: Filter by arcana category ('all', 'major', 'suit', 'court')
    """
    from .symbols import TraditionalDeckRegistry

    all_symbols = TraditionalDeckRegistry.get_all_symbols()
    results = all_symbols

    if card_name:
        results = TraditionalDeckRegistry.get_symbols_for_card(card_name)

    if suit:
        suit_lower = suit.lower()
        results = [
            s for s in results
            if s.get("category") == f"suit_{suit_lower}"
            or any(suit_lower in c.lower() for c in s.get("cards", []))
        ]

    if arcana_type and arcana_type != "all":
        if arcana_type == "major":
            results = [s for s in results if s.get("category") == "major_arcana"]
        elif arcana_type == "suit":
            results = [s for s in results if s.get("category", "").startswith("suit_")]
        elif arcana_type == "court":
            results = [s for s in results if s.get("category") == "court"]

    if query:
        q = query.lower().strip()
        filtered = []
        for s in results:
            name = s.get("name", "").lower()
            desc = s.get("description", "").lower()
            kws = " ".join(s.get("keywords", [])).lower()
            cards_str = " ".join(s.get("cards", [])).lower()
            if q in name or q in desc or q in kws or q in cards_str:
                filtered.append(s)
        results = filtered

    return {
        "count": len(results),
        "total_canonical": len(all_symbols),
        "symbols": results,
    }


@mcp.tool()
def match_symbols(
    symbols: list[dict[str, str]] = None,
    symbols_file: str = "",
    target_scope: str = "full",
) -> dict[str, Any]:
    """Match artist-provided symbols against canonical traditional tarot archetypes.

    Analyzes a list of artist symbols or an existing symbols.json file.
    Reports which traditional tarot symbols are satisfied, which cards
    they correspond to, what traditional symbols remain missing, and
    overall deck coverage statistics.

    Args:
        symbols: List of symbol dicts (each with 'name' and optional 'description')
        symbols_file: Path to symbols.json file (used if symbols is not provided)
        target_scope: 'full' (all 78 cards), 'major' (22 Major Arcana), or 'suits' (4 suits)
    """
    from .symbols import TraditionalDeckRegistry, load_symbols_config

    symbol_list = []
    if symbols:
        symbol_list = symbols
    elif symbols_file:
        cfg = load_symbols_config(symbols_file)
        symbol_list = cfg.get("symbols", [])

    if not symbol_list:
        return {"error": "No symbols provided or symbols file empty", "count": 0}

    analysis = TraditionalDeckRegistry.match_artist_symbols(symbol_list)

    missing = analysis["missing_traditional"]
    if target_scope == "major":
        missing = [s for s in missing if s.get("category") == "major_arcana"]
    elif target_scope == "suits":
        missing = [s for s in missing if s.get("category", "").startswith("suit_")]

    return {
        "success": True,
        "provided_count": len(symbol_list),
        "matched_count": analysis["matched_count"],
        "unmatched_count": analysis["unmatched_count"],
        "missing_count": len(missing),
        "coverage": analysis["coverage"],
        "matched": [
            {
                "traditional_name": m["traditional_name"],
                "traditional_category": m["traditional_category"],
                "associated_cards": m["associated_cards"],
                "match_score": m["match_score"],
                "artist_symbol": m["artist_symbol"]["name"],
            }
            for m in analysis["matched"]
        ],
        "unmatched_artist_symbols": [
            s.get("name", "") for s in analysis["unmatched_artist"]
        ],
        "missing_traditional_sample": [
            {"name": s["name"], "category": s["category"], "cards": s["cards"][:3]}
            for s in missing[:15]
        ],
        "recommendation": (
            "Call complete_symbols() to auto-generate reference artwork for missing symbols, "
            "or proceed directly to create_deck(traditional_mode=True)."
        ),
    }


@mcp.tool()
def complete_symbols(
    deck_name: str,
    symbols_file: str = "",
    style_prompt: str = "",
    target_scope: str = "full",
    max_generate: int = 15,
) -> dict[str, Any]:
    """Generate missing traditional tarot symbols in the artist's visual style using Venice AI.

    Takes an artist's partial symbol set, identifies unfulfilled traditional tarot
    archetypes, and generates cohesive reference images using Venice AI (qwen-image-3-pro).
    Saves an updated symbols.json manifest marking which symbols are artist-supplied
    and which were AI-generated.

    Args:
        deck_name: Name of the deck
        symbols_file: Path to existing symbols.json (or default symbols if omitted)
        style_prompt: Visual aesthetic description to harmonize generated symbols
        target_scope: 'full' (all cards), 'major' (22 Major Arcana), or 'suits'
        max_generate: Maximum number of missing symbols to generate (default 15)
    """
    from .storage import validate_deck_name
    from .symbols import TraditionalDeckRegistry, load_symbols_config, symbols_dir_for

    try:
        validate_deck_name(deck_name)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    if target_scope not in ("full", "major", "suits"):
        return {"success": False, "error": "target_scope must be 'full', 'major' or 'suits'"}
    if symbols_file and not os.path.isfile(symbols_file):
        return {"success": False, "error": f"symbols_file not found: {symbols_file}"}

    symbols_dir = symbols_dir_for(deck_name)
    manifest_file = os.path.join(symbols_dir, "symbols.json")
    # Default to the symbols this deck's artist already registered.
    if not symbols_file and os.path.isfile(manifest_file):
        symbols_file = manifest_file

    venice_key = _get_venice_key()
    cfg = load_symbols_config(symbols_file or None)
    if style_prompt:
        cfg["style_prompt"] = style_prompt

    completed_cfg = TraditionalDeckRegistry.complete_deck_symbols(
        symbols_config=cfg,
        deck_name=deck_name,
        deck_prompt="",
        api_key=venice_key,
        image_model=Config.DEFAULT_IMAGE_MODEL,
        target_scope=target_scope,
        max_missing=max_generate,
        rate_limit=1.5,
    )

    generated = completed_cfg.get("generated_symbol_count", 0)
    failed = completed_cfg.get("failed_symbol_count", 0)
    result: dict[str, Any] = {
        "success": failed == 0 or generated > 0,
        "deck_name": deck_name,
        "symbols_file": os.path.abspath(manifest_file),
        "total_symbols": len(completed_cfg.get("symbols", [])),
        "artist_symbols_count": completed_cfg.get("artist_symbol_count", 0),
        "generated_symbols_count": generated,
        "failed_symbols_count": failed,
        "failed_symbols": [f["name"] for f in completed_cfg.get("failed_symbols", [])],
        "usage_hint": (
            f'Call create_deck(name="{deck_name}", symbol_mode="provide", '
            f'symbols_file="{os.path.abspath(manifest_file)}", traditional_mode=True)'
        ),
    }
    if failed:
        result["error"] = (
            f"{failed} symbol(s) failed to generate; call complete_symbols again to retry them."
        )
    return result


@mcp.tool()
def get_deck_traditional_coverage(deck_name: str) -> dict[str, Any]:
    """Audit traditional tarot symbolism coverage for an existing deck.

    Inspects all cards in the deck, checks which canonical traditional
    archetypes are present in card symbols and prompts, and determines
    whether artist symbols or AI-completed symbols were used.

    Args:
        deck_name: Name of the deck to audit
    """
    from .storage import load_deck
    from .symbols import TraditionalDeckRegistry

    deck = load_deck(deck_name)
    if not deck:
        return {"error": f"Deck '{deck_name}' not found"}

    all_canonical = TraditionalDeckRegistry.get_all_symbols()
    card_reports = []
    canonical_hits: set[str] = set()

    for card in sorted(deck, key=lambda c: c.position or 0):
        c_symbols = card.symbols or []
        card_canons = TraditionalDeckRegistry.get_symbols_for_card(card.title)
        matched_canons_for_card = []

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

    coverage_pct = round((len(canonical_hits) / len(all_canonical)) * 100.0, 1) if all_canonical else 0.0

    return {
        "deck_name": deck_name,
        "total_cards": len(deck),
        "total_canonical_symbols": len(all_canonical),
        "canonical_symbols_covered": len(canonical_hits),
        "traditional_coverage_percentage": coverage_pct,
        "cards": card_reports,
    }


# ==================== AGENTIC WORKFLOW TOOLS ====================

@mcp.tool()
def estimate_cost(
    cards: int = 78,
    analyze: bool = True,
    generate_images: bool = True,
    previews: int = 3,
    image_model: str = "",
    text_model: str = "",
) -> dict[str, Any]:
    """Estimate API usage and cost BEFORE starting generation.

    Call this first so you can tell the user: "This will cost ~$2.50
    and take ~15 minutes. Want to proceed?"

    Args:
        cards: Number of cards to generate
        analyze: Whether text analysis will be used
        generate_images: Whether image generation will be used
        previews: Number of preview cards (0 to skip)
        image_model: Image model (default: flux-2-pro)
        text_model: Text model (default: llama-3.3-70b)
    """
    from .usage import PRICING

    img_model = image_model or Config.DEFAULT_IMAGE_MODEL
    txt_model = text_model or Config.DEFAULT_TEXT_MODEL

    # Count API calls
    text_calls = 0
    image_calls = 0

    if analyze:
        text_calls += cards          # 1 analysis call per card
    if generate_images:
        text_calls += cards          # 1 prompt refinement per card
        text_calls += 1              # 1 style extraction
        image_calls += cards         # 1 image per card
        image_calls += previews      # preview images

    # Estimate tokens (based on typical usage)
    avg_prompt_tokens = 450
    avg_completion_tokens = 200
    total_prompt = text_calls * avg_prompt_tokens
    total_completion = text_calls * avg_completion_tokens

    # Cost calculation
    txt_pricing = PRICING["text"].get(txt_model, PRICING["text"]["_default"])
    text_cost = (
        (total_prompt / 1000) * txt_pricing["input"]
        + (total_completion / 1000) * txt_pricing["output"]
    )
    img_price = PRICING["image"].get(img_model, PRICING["image"]["_default"])
    image_cost = image_calls * img_price
    total_cost = text_cost + image_cost

    # Estimate time (rate limit + processing)
    seconds_per_image = 3.5   # generation + rate limit
    seconds_per_text = 2.0    # analysis + rate limit
    est_seconds = (
        image_calls * seconds_per_image
        + text_calls * seconds_per_text
    )
    est_minutes = round(est_seconds / 60, 1)

    return {
        "cards": cards,
        "api_calls": {
            "text": text_calls,
            "image": image_calls,
            "total": text_calls + image_calls,
        },
        "estimated_tokens": {
            "prompt": total_prompt,
            "completion": total_completion,
            "total": total_prompt + total_completion,
        },
        "estimated_cost_usd": {
            "text": round(text_cost, 4),
            "image": round(image_cost, 4),
            "total": round(total_cost, 4),
        },
        "estimated_time_minutes": est_minutes,
        "models": {
            "text": txt_model,
            "image": img_model,
        },
    }


@mcp.tool()
def preview_style(
    name: str,
    vibe: str = "ethereal dreamscape",
    deck_prompt: str = "",
    symbol_mode: str = "generate",
    symbols_file: str = "",
    traditional_mode: bool = True,
) -> dict[str, Any]:
    """Generate 3 preview cards to test a deck's visual style.

    Call this BEFORE create_deck. Send the preview images to the user
    in Telegram. If they approve, call create_deck with the same params.
    If they want changes, adjust vibe/deck_prompt and call again.

    Args:
        name: Deck name (for file naming)
        vibe: Artistic style/aesthetic
        deck_prompt: Additional theme instructions
        symbol_mode: "generate" or "provide"
        symbols_file: Path to symbols.json if symbol_mode="provide"
        traditional_mode: If True, preview cards feature traditional tarot symbols
    """
    from .generator import (
        _PREVIEW_CARDS,
        build_card_prompt,
        generate_card,
    )
    from .overlay import get_card_number_text, overlay_card_text
    from .style import extract_deck_style, refine_card_prompt
    from .symbols import load_symbols_config
    from .venice import generate_image_with_venice

    venice_key = _get_venice_key()
    symbols_config = load_symbols_config(symbols_file or None)

    # Build symbol images lookup
    symbol_images = {}
    for s in symbols_config["symbols"]:
        if s.get("image") and os.path.exists(str(s["image"])):
            symbol_images[s["name"]] = s["image"]

    # Extract style
    symbol_descs = [
        s.get("description", s.get("name", ""))
        for s in symbols_config["symbols"]
    ]
    deck_style = extract_deck_style(
        symbol_images=symbol_images,
        symbol_descriptions=symbol_descs,
        vibe=vibe,
        deck_prompt=deck_prompt,
        api_key=venice_key,
        text_model=Config.DEFAULT_TEXT_MODEL,
    )

    if not deck_style:
        return {"error": "Style extraction failed", "previews": []}

    # Generate 3 preview cards
    preview_dir = os.path.join(Config.IMAGES_DIR, "previews")
    os.makedirs(preview_dir, exist_ok=True)

    previews = []
    for i, card_def in enumerate(_PREVIEW_CARDS):
        card = generate_card(
            position=i + 1, total=3, card_def=card_def,
            deck_vibe=vibe, deck_prompt=deck_prompt,
            symbols=symbols_config["symbols"],
            traditional_mode=traditional_mode,
        )

        if deck_style:
            card.prompt = refine_card_prompt(
                card, deck_style, venice_key, Config.DEFAULT_TEXT_MODEL,
            )
        else:
            card.prompt = build_card_prompt(card, deck_style)

        result = generate_image_with_venice(
            card, venice_key, Config.DEFAULT_IMAGE_MODEL,
            image_size=Config.DEFAULT_IMAGE_SIZE,
            rate_limit_delay=1.5,
            symbol_mode=symbol_mode,
            symbol_images=symbol_images,
        )
        card.update(result)

        if card.image_path:
            import shutil
            preview_name = (
                f"{name}_preview_{i + 1}_"
                f"{card_def['title'].replace(' ', '_')}.png"
            )
            preview_path = os.path.join(preview_dir, preview_name)
            shutil.copy2(card.image_path, preview_path)
            overlay_card_text(
                preview_path, card.display_title(),
                get_card_number_text(card),
            )
            previews.append({
                "card": card_def["title"],
                "image_path": os.path.abspath(preview_path),
            })
        else:
            previews.append({
                "card": card_def["title"],
                "error": result.get("image_error", "generation failed"),
            })

    return {
        "deck_name": name,
        "vibe": vibe,
        "style_prompt": deck_style[:300],
        "previews": previews,
        "success_count": sum(1 for p in previews if "image_path" in p),
    }


@mcp.tool()
def generate_single_card(
    deck_name: str,
    card_num: int,
) -> dict[str, Any]:
    """Generate or regenerate a single card in an existing deck.

    Use this for incremental generation — generate one card at a time
    and send each to the user in Telegram as it completes.

    Args:
        deck_name: Name of the deck
        card_num: Card position number (1-based)
    """
    from .generator import build_card_prompt
    from .overlay import get_card_number_text, overlay_card_text
    from .storage import load_deck, load_decks_index, save_deck
    from .style import refine_card_prompt
    from .symbols import load_symbols_config
    from .venice import analyze_with_venice, generate_image_with_venice

    venice_key = _get_venice_key()

    deck = load_deck(deck_name)
    if not deck:
        return {"error": f"Deck '{deck_name}' not found"}

    card = next((c for c in deck if c.position == card_num), None)
    if not card:
        return {"error": f"Card {card_num} not found in deck"}

    # Get deck metadata for style
    index = load_decks_index()
    meta = index.get(deck_name, {})
    usage = meta.get("usage", {})
    deck_style = usage.get("style_prompt", "")

    # Refine prompt
    if deck_style:
        card.prompt = refine_card_prompt(
            card, deck_style, venice_key, Config.DEFAULT_TEXT_MODEL,
        )
    elif card.prompt:
        pass  # keep existing prompt
    else:
        card.prompt = build_card_prompt(card, "")

    # Analyze
    result = analyze_with_venice(card, venice_key, Config.DEFAULT_TEXT_MODEL)
    card.update(result)

    # Generate image
    symbols_config = load_symbols_config(None)
    symbol_images = {}
    for s in symbols_config["symbols"]:
        if s.get("image") and os.path.exists(str(s["image"])):
            symbol_images[s["name"]] = s["image"]

    img_result = generate_image_with_venice(
        card, venice_key, Config.DEFAULT_IMAGE_MODEL,
        image_size=Config.DEFAULT_IMAGE_SIZE,
        rate_limit_delay=1.5,
        symbol_images=symbol_images,
    )
    card.update(img_result)

    if card.image_path:
        overlay_card_text(
            card.image_path, card.display_title(),
            get_card_number_text(card),
        )

    # Save updated deck
    save_deck(deck, deck_name)

    return {
        "card_num": card_num,
        "title": card.display_title(),
        "has_image": bool(
            card.image_path and os.path.exists(str(card.image_path))
        ),
        "image_path": os.path.abspath(card.image_path) if card.image_path else None,
        "has_analysis": bool(card.description and not card.venice_error),
        "description": (card.description or "")[:200],
        "error": card.venice_error or card.image_error or None,
    }


@mcp.tool()
def get_all_images(deck_name: str) -> dict[str, Any]:
    """Get all card image paths for a deck in one call.

    Returns paths sorted by card position. Use this to batch-send
    all card images to the user in Telegram.
    """
    from .storage import load_deck, load_decks_index

    deck = load_deck(deck_name)
    if not deck:
        return {"error": f"Deck '{deck_name}' not found"}

    sorted_deck = sorted(deck, key=lambda c: c.position or 0)

    images = []
    missing = []
    for card in sorted_deck:
        if card.image_path and os.path.exists(str(card.image_path)):
            images.append({
                "position": card.position,
                "title": card.display_title(),
                "path": os.path.abspath(card.image_path),
            })
        else:
            missing.append({
                "position": card.position,
                "title": card.display_title(),
            })

    # Include back image
    index = load_decks_index()
    meta = index.get(deck_name, {})
    back_path = meta.get("back_image", "")

    result = {
        "deck_name": deck_name,
        "total": len(sorted_deck),
        "images": images,
        "images_count": len(images),
        "missing": missing,
        "missing_count": len(missing),
    }
    if back_path and os.path.exists(back_path):
        result["back_image"] = os.path.abspath(back_path)

    return result


@mcp.tool()
def suggest_deck(user_description: str) -> dict[str, Any]:
    """Generate a structured deck configuration from a casual user description.

    Turn natural language like "something dark and gothic with roses"
    into a proper vibe, deck_prompt, recommended card count, and
    suggested back prompt.

    Args:
        user_description: The user's casual description of what they want
    """
    import json as json_mod

    venice_key = _get_venice_key()

    try:
        import requests as req
    except ImportError:
        return {"error": "requests library not available"}

    system = (
        "You are a tarot deck creative director. Given a casual description, "
        "produce a structured deck configuration. Respond with valid JSON only."
    )
    user_prompt = f"""A user wants a custom tarot deck. Their description: "{user_description}"

Return a JSON object with:
- "name": a short deck name (letters/underscores only, max 20 chars)
- "cards": recommended card count (22 for focused/major-only, 78 for full)
- "vibe": a rich artistic vibe string (15-30 words describing the visual aesthetic)
- "deck_prompt": a detailed theme prompt (2-3 sentences about the deck's narrative)
- "back_prompt": a prompt for the card back design (15-20 words)
- "symbol_suggestions": list of 4-6 symbol names that fit the theme
- "reasoning": 1 sentence explaining your creative choices"""

    try:
        resp = req.post(
            Config.VENICE_TEXT_URL,
            headers={"Authorization": f"Bearer {venice_key}"},
            json={
                "model": Config.DEFAULT_TEXT_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.8,
                "max_tokens": 4000,
            },
            timeout=90,
        )
        resp.raise_for_status()
        raw = _extract_text_content(resp.json())

        import re
        match = re.search(r'```(?:json)?\s*(.*?)```', raw, re.DOTALL)
        content = match.group(1).strip() if match else raw
        suggestion = json_mod.loads(content)

        # Add cost estimate
        cards = suggestion.get("cards", 78)
        cost = estimate_cost(cards=cards)
        suggestion["estimated_cost"] = cost["estimated_cost_usd"]
        suggestion["estimated_time_minutes"] = cost["estimated_time_minutes"]

        return suggestion

    except Exception as e:
        return {"error": f"Suggestion generation failed: {e}"}


@mcp.tool()
def deck_progress(deck_name: str) -> dict[str, Any]:
    """Lightweight progress check for a deck being generated.

    Returns completion counts without heavy processing. Use this
    to poll progress and update the user in Telegram.

    Args:
        deck_name: Name of the deck to check
    """
    from .storage import load_deck

    deck = load_deck(deck_name)
    if not deck:
        return {"error": f"Deck '{deck_name}' not found", "exists": False}

    sorted_deck = sorted(deck, key=lambda c: c.position or 0)
    total = len(sorted_deck)

    images_done = 0
    analysis_done = 0
    errors = 0
    latest_title = ""

    for card in sorted_deck:
        if card.image_path and os.path.exists(str(card.image_path)):
            images_done += 1
            latest_title = card.display_title()
        if card.description and not card.venice_error:
            analysis_done += 1
        if card.venice_error or card.image_error:
            errors += 1

    complete = min(images_done, analysis_done)
    pct = round((complete / total) * 100) if total else 0

    return {
        "deck_name": deck_name,
        "exists": True,
        "total": total,
        "images_done": images_done,
        "analysis_done": analysis_done,
        "complete": complete,
        "errors": errors,
        "percent": pct,
        "latest_card": latest_title,
        "ready_to_finalize": complete == total and errors == 0,
    }


# ==================== ENTRY POINT ====================

def main():
    """Run the MCP server."""
    transport = "stdio"
    if "--sse" in sys.argv:
        transport = "sse"
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
