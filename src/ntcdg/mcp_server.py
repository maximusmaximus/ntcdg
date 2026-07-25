"""MCP (Model Context Protocol) server for NTCDG.

Exposes all deck management functions as MCP tools so AI agents
(like Hermes on Telegram) can control deck generation programmatically.

Run with:
    python -m ntcdg.mcp_server            # stdio transport (default)
    python -m ntcdg.mcp_server --sse      # SSE transport for web clients

Requires: pip install "mcp[cli]"
"""

import io
import os
import sys
from contextlib import redirect_stdout
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

def _capture_print(func, *args, **kwargs) -> str:
    """Call a function that prints to stdout and capture the output."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        func(*args, **kwargs)
    return buf.getvalue().strip()


def _get_venice_key() -> str:
    """Get Venice API key from environment."""
    key = os.getenv("VENICE_API_KEY", "")
    if not key:
        raise ValueError(
            "VENICE_API_KEY environment variable is not set. "
            "Set it before running the MCP server."
        )
    return key


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
) -> dict[str, Any]:
    """Create a new tarot card deck with AI-generated art and meanings.

    Args:
        name: Deck name (letters, numbers, underscores, hyphens)
        cards: Number of cards (22 for Major Arcana only, 78 for full)
        vibe: Artistic style/aesthetic (e.g., "cosmic horror meets art nouveau")
        deck_prompt: Additional theme instructions
        symbol_mode: "generate" (AI creates) or "provide" (user artwork)
        symbols_file: Path to symbols.json (when symbol_mode="provide")
        image_size: Image dimensions (default: 1024x1792)
    """
    from .generator import generate_deck

    venice_key = _get_venice_key()
    size = image_size or Config.DEFAULT_IMAGE_SIZE

    generate_deck(
        name=name,
        num_cards=cards,
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
    from .storage import load_decks_index

    venice_key = _get_venice_key()

    index = load_decks_index()
    meta = index.get(deck_name, {})

    generate_deck(
        name=deck_name,
        num_cards=meta.get("num_cards", 78),
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
    from .storage import load_decks_index, update_deck_index
    from .venice import generate_card_back

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
        idx = load_decks_index()
        meta = idx.get(deck_name, {})
        update_deck_index(
            deck_name,
            num_cards=meta.get("num_cards", 0),
            vibe=meta.get("vibe", ""),
            theme=meta.get("theme", ""),
            back_image=back_path,
            back_prompt=prompt,
        )
        return {"success": True, "back_image_path": back_path}

    return {"success": False, "error": "Failed to generate card back"}


@mcp.tool()
def finalize_deck(
    deck_name: str,
    sheet_size: str = "letter",
    color_mode: str = "color",
) -> dict[str, Any]:
    """Generate print-ready PDFs for a deck (fronts, backs, booklet).

    Args:
        deck_name: Name of the deck to finalize
        sheet_size: "letter" (8.5x11) or "tabloid" (11x17)
        color_mode: "color" or "bw" (both output as CMYK)
    """
    from .finalize import finalize_deck as _finalize

    output = _capture_print(
        _finalize, deck_name, sheet_size=sheet_size, color_mode=color_mode,
    )

    # Collect output file paths
    import glob
    pdfs = glob.glob(os.path.join(Config.OUTPUT_DIR, f"{deck_name}_*.pdf"))
    booklet = os.path.join(Config.OUTPUT_DIR, f"{deck_name}_BOOKLET.pdf")

    return {
        "success": True,
        "deck_name": deck_name,
        "pdfs": pdfs,
        "booklet": booklet if os.path.exists(booklet) else None,
        "output": output,
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

    success = edit_card_field(deck_name, card_num, field, value)
    return {"success": success, "card_num": card_num, "field": field}


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


# ==================== ENTRY POINT ====================

def main():
    """Run the MCP server."""
    transport = "stdio"
    if "--sse" in sys.argv:
        transport = "sse"
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
