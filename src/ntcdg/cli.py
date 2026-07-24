"""CLI entry point for NTCDG."""

import argparse
import os
import re

from .config import Config, logger, setup_logging
from .generator import generate_deck, review_existing_deck
from .storage import get_deck_info, list_decks


def main():
    setup_logging()

    parser = argparse.ArgumentParser(description="NTCDG - Tarot Deck Generator")

    parser.add_argument("--deck", action="store_true", help="Generate a new deck")
    parser.add_argument("--review-existing", type=str, default=None, help="Review an existing deck")
    parser.add_argument("--list-decks", action="store_true", help="List all decks")
    parser.add_argument("--deck-info", type=str, default=None, help="Show info about a deck")

    parser.add_argument("--name", type=str, default="New_Deck")
    parser.add_argument("--cards", type=int, default=78)
    parser.add_argument("--vibe", type=str, default=None)
    parser.add_argument("--deck-prompt", type=str, default="")

    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--venice-text-model", type=str, default=Config.DEFAULT_TEXT_MODEL)
    parser.add_argument("--generate-images", action="store_true")
    parser.add_argument("--venice-image-model", type=str, default=Config.DEFAULT_IMAGE_MODEL)
    parser.add_argument("--image-size", type=str, default="1024x1536")
    parser.add_argument("--negative-prompt", type=str, default="")
    parser.add_argument("--rate-limit", type=float, default=1.5)

    parser.add_argument(
        "--symbol-mode", type=str, default="generate",
        choices=["generate", "provide"],
        help="'generate' creates cohesive symbol images via AI; "
             "'provide' uses your own images (paths in symbols file)",
    )
    parser.add_argument(
        "--symbols-file", type=str, default=None,
        help="Path to symbols.json defining symbol names, descriptions, and optional image paths",
    )

    parser.add_argument("--venice-key", type=str, default=None)
    parser.add_argument("--no-interactive", action="store_true")

    args = parser.parse_args()

    # --- Input validation ---
    if args.deck:
        if args.cards < 1:
            parser.error("--cards must be at least 1")
        if args.cards > 200:
            parser.error("--cards must be 200 or fewer")
        if not re.match(r'^[A-Za-z0-9_-]+$', args.name):
            parser.error("--name must contain only letters, numbers, underscores, and hyphens")
        valid_sizes = ("512x512", "512x768", "768x512", "1024x1024", "1024x1536", "1536x1024")
        if args.image_size not in valid_sizes:
            logger.warning(f"Non-standard image size '{args.image_size}' — Venice may reject it")
        if args.symbols_file and not os.path.exists(args.symbols_file):
            parser.error(f"Symbols file not found: {args.symbols_file}")

    venice_key = args.venice_key or os.getenv("VENICE_API_KEY")

    if args.list_decks:
        list_decks()
    elif args.deck_info:
        get_deck_info(args.deck_info)
    elif args.review_existing:
        review_existing_deck(
            deck_name=args.review_existing,
            venice_key=venice_key,
            text_model=args.venice_text_model,
            image_model=args.venice_image_model,
            image_size=args.image_size,
            negative_prompt=args.negative_prompt,
            rate_limit=args.rate_limit,
        )
    elif args.deck:
        generate_deck(
            name=args.name,
            num_cards=args.cards,
            vibe=args.vibe,
            deck_prompt=args.deck_prompt,
            venice_key=venice_key,
            analyze=args.analyze,
            text_model=args.venice_text_model,
            generate_images=args.generate_images,
            image_model=args.venice_image_model,
            image_size=args.image_size,
            negative_prompt=args.negative_prompt,
            rate_limit=args.rate_limit,
            interactive=not args.no_interactive,
            symbol_mode=args.symbol_mode,
            symbols_file=args.symbols_file,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
