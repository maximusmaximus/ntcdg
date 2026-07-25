"""CLI entry point for NTCDG."""

import argparse
import os
import re

from .config import Config, setup_logging
from .userconfig import apply_config_defaults, load_user_config


def main():
    setup_logging()

    parser = argparse.ArgumentParser(
        description="NTCDG — Novel Tarot Card Deck Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Quick start:
  ntcdg --new                          Guided wizard for first-time users
  ntcdg --deck --name MyDeck --analyze --generate-images

Typical workflow:
  1. ntcdg --new                       Create a deck interactively
  2. ntcdg --list-cards MyDeck         Check card completion status
  3. ntcdg --retry-failed MyDeck       Fix any failed cards
  4. ntcdg --set-back MyDeck --back-prompt "sacred geometry..."
  5. ntcdg --finalize MyDeck           Generate print-ready PDFs
  6. ntcdg --export MyDeck             Bundle everything into a zip

Config: Save defaults in ~/.ntcdgrc (run --init-config for a template)
""",
    )

    # === COMMANDS (mutually exclusive actions) ===
    cmds = parser.add_argument_group("Commands")
    cmds.add_argument(
        "--new", action="store_true",
        help="Launch the guided new-deck wizard",
    )
    cmds.add_argument(
        "--deck", action="store_true",
        help="Generate a new deck (advanced — use --new for guided)",
    )
    cmds.add_argument(
        "--list-decks", action="store_true",
        help="List all saved decks",
    )
    cmds.add_argument(
        "--deck-info", type=str, default=None, metavar="DECK",
        help="Show deck status and readiness report",
    )
    cmds.add_argument(
        "--list-cards", type=str, default=None, metavar="DECK",
        help="Show all cards with completion status",
    )
    cmds.add_argument(
        "--review-existing", type=str, default=None, metavar="DECK",
        help="Interactive review of an existing deck",
    )
    cmds.add_argument(
        "--retry-failed", type=str, default=None, metavar="DECK",
        help="Retry only failed/incomplete cards in a deck",
    )
    cmds.add_argument(
        "--finalize", type=str, default=None, metavar="DECK",
        help="Generate print-ready PDFs (fronts + backs + booklet)",
    )
    cmds.add_argument(
        "--export", type=str, default=None, metavar="DECK",
        help="Bundle all deck assets into a zip",
    )
    cmds.add_argument(
        "--delete-deck", type=str, default=None, metavar="DECK",
        help="Delete a deck and all its files",
    )
    cmds.add_argument(
        "--clone-deck", type=str, nargs=2, default=None,
        metavar=("SOURCE", "NEW_NAME"),
        help="Clone a deck under a new name",
    )
    cmds.add_argument(
        "--deck-stats", type=str, default=None, metavar="DECK",
        help="Show API usage, cost estimate, and style prompt for a deck",
    )
    cmds.add_argument(
        "--init-config", action="store_true",
        help="Create a sample ~/.ntcdgrc config file",
    )

    # === DECK CREATION OPTIONS ===
    gen = parser.add_argument_group("Deck creation (used with --deck)")
    gen.add_argument("--name", type=str, default="New_Deck")
    gen.add_argument("--cards", type=int, default=78)
    gen.add_argument("--vibe", type=str, default=None)
    gen.add_argument("--deck-prompt", type=str, default="")
    gen.add_argument("--analyze", action="store_true")
    gen.add_argument("--generate-images", action="store_true")
    gen.add_argument("--no-interactive", action="store_true")
    gen.add_argument(
        "--resume", action="store_true",
        help="Resume generation, skipping completed cards",
    )
    gen.add_argument(
        "--no-preview", action="store_true",
        help="Skip the 3-card style preview (generate all cards immediately)",
    )

    # === VENICE API OPTIONS ===
    api = parser.add_argument_group("Venice API")
    api.add_argument("--venice-key", type=str, default=None)
    api.add_argument(
        "--venice-text-model", type=str, default=None,
    )
    api.add_argument(
        "--venice-image-model", type=str, default=None,
    )
    api.add_argument(
        "--image-size", type=str, default=None,
    )
    api.add_argument("--negative-prompt", type=str, default="")
    api.add_argument(
        "--rate-limit", type=float, default=None,
        help="Seconds between API calls (default: 1.5)",
    )

    # === SYMBOLS & STYLING ===
    style = parser.add_argument_group("Symbols & styling")
    style.add_argument(
        "--symbol-mode", type=str, default="generate",
        choices=["generate", "provide"],
        help="'generate' = AI creates symbols; 'provide' = your artwork",
    )
    style.add_argument(
        "--symbols-file", type=str, default=None,
        help="Path to symbols.json",
    )
    style.add_argument(
        "--font", type=str, default=None,
        help="Path to .ttf/.otf font for card overlay",
    )

    # === CARD BACK ===
    back = parser.add_argument_group("Card back")
    back.add_argument(
        "--set-back", type=str, default=None, metavar="DECK",
        help="Generate card back for a deck",
    )
    back.add_argument(
        "--back-prompt", type=str, default=None,
        help="Prompt for card back design",
    )

    # === CARD EDITING ===
    edit = parser.add_argument_group("Card editing (used with --edit-card)")
    edit.add_argument(
        "--edit-card", type=str, default=None, metavar="DECK",
        help="Edit a card field in a deck",
    )
    edit.add_argument(
        "--card-num", type=int, default=None,
        help="Card position number",
    )
    edit.add_argument(
        "--field", type=str, default=None,
        help="Field to edit (title, description, upright/reversed)",
    )
    edit.add_argument(
        "--value", type=str, default=None,
        help="New value for the field",
    )

    # === FINALIZATION OPTIONS ===
    fin = parser.add_argument_group("Finalization options")
    fin.add_argument(
        "--sheet-size", type=str, default="letter",
        choices=["letter", "tabloid"],
        help="'letter' (8.5x11) or 'tabloid' (11x17)",
    )
    fin.add_argument(
        "--color-mode", type=str, default="color",
        choices=["color", "bw"],
        help="'color' or 'bw' (both output as CMYK)",
    )

    args = parser.parse_args()

    # --- Load user config and apply defaults ---
    user_config = load_user_config()
    apply_config_defaults(args, user_config)

    # Fill remaining defaults that config didn't set
    if args.venice_text_model is None:
        args.venice_text_model = Config.DEFAULT_TEXT_MODEL
    if args.venice_image_model is None:
        args.venice_image_model = Config.DEFAULT_IMAGE_MODEL
    if args.image_size is None:
        args.image_size = Config.DEFAULT_IMAGE_SIZE
    if args.rate_limit is None:
        args.rate_limit = 1.5

    # --- Input validation ---
    if args.deck:
        if args.cards < 1:
            parser.error("--cards must be at least 1")
        if args.cards > 200:
            parser.error("--cards must be 200 or fewer")
        if not re.match(r'^[A-Za-z0-9_-]+$', args.name):
            parser.error("--name: letters, numbers, underscores, hyphens only")
        if args.symbols_file and not os.path.exists(args.symbols_file):
            parser.error(f"Symbols file not found: {args.symbols_file}")
        if args.font and not os.path.exists(args.font):
            parser.error(f"Font file not found: {args.font}")

    venice_key = args.venice_key or os.getenv("VENICE_API_KEY")

    # ============ COMMAND DISPATCH ============

    if args.init_config:
        from .userconfig import create_sample_config
        create_sample_config()

    elif args.new:
        from .wizard import run_wizard
        settings = run_wizard()
        if settings:
            from .generator import generate_deck
            generate_deck(
                name=settings["name"],
                num_cards=settings["num_cards"],
                vibe=settings["vibe"],
                deck_prompt=settings["deck_prompt"],
                venice_key=settings["venice_key"],
                analyze=settings["analyze"],
                text_model=settings["text_model"],
                generate_images=settings["generate_images"],
                image_model=settings["image_model"],
                image_size=settings["image_size"],
                negative_prompt=settings["negative_prompt"],
                rate_limit=settings["rate_limit"],
                interactive=settings["interactive"],
                symbol_mode=settings["symbol_mode"],
                symbols_file=settings["symbols_file"],
                font_path=settings["font_path"],
            )

    elif args.list_decks:
        from .storage import list_decks
        list_decks()

    elif args.deck_info:
        from .storage import get_deck_info
        get_deck_info(args.deck_info)

    elif args.deck_stats:
        from .usage import display_deck_stats
        display_deck_stats(args.deck_stats)

    elif args.list_cards:
        from .storage import list_cards
        list_cards(args.list_cards)

    elif args.review_existing:
        from .generator import review_existing_deck
        review_existing_deck(
            deck_name=args.review_existing,
            venice_key=venice_key,
            text_model=args.venice_text_model,
            image_model=args.venice_image_model,
            image_size=args.image_size,
            negative_prompt=args.negative_prompt,
            rate_limit=args.rate_limit,
            font_path=args.font,
        )

    elif args.retry_failed:
        from .generator import generate_deck
        if not venice_key:
            parser.error("--retry-failed requires VENICE_API_KEY")
        print(f"\nRetrying failed cards in '{args.retry_failed}'...")
        generate_deck(
            name=args.retry_failed,
            num_cards=args.cards,
            vibe=args.vibe,
            deck_prompt=args.deck_prompt,
            venice_key=venice_key,
            analyze=True,
            text_model=args.venice_text_model,
            generate_images=True,
            image_model=args.venice_image_model,
            image_size=args.image_size,
            negative_prompt=args.negative_prompt,
            rate_limit=args.rate_limit,
            interactive=not args.no_interactive,
            symbol_mode=args.symbol_mode,
            symbols_file=args.symbols_file,
            font_path=args.font,
            resume=True,  # resume mode skips completed cards
            preview=False,  # no preview for retries
        )

    elif args.set_back:
        if not args.back_prompt:
            parser.error("--set-back requires --back-prompt")
        if not venice_key:
            parser.error("--set-back requires VENICE_API_KEY")
        from .venice import generate_card_back
        print(f"\nGenerating card back for {args.set_back}...")
        back_path = generate_card_back(
            prompt=args.back_prompt,
            api_key=venice_key,
            model=args.venice_image_model,
            deck_name=args.set_back,
            image_size=args.image_size,
            negative_prompt=args.negative_prompt,
            rate_limit_delay=args.rate_limit,
        )
        if back_path:
            from .storage import load_decks_index, update_deck_index
            idx = load_decks_index()
            meta = idx.get(args.set_back, {})
            update_deck_index(
                args.set_back,
                num_cards=meta.get("num_cards", 0),
                vibe=meta.get("vibe", ""),
                theme=meta.get("theme", ""),
                back_image=back_path,
                back_prompt=args.back_prompt,
            )
            print(f"Card back saved: {back_path}")
        else:
            print("Failed to generate card back.")

    elif args.edit_card:
        if not all([args.card_num, args.field, args.value]):
            parser.error("--edit-card requires --card-num, --field, --value")
        from .storage import edit_card_field
        edit_card_field(args.edit_card, args.card_num, args.field, args.value)

    elif args.export:
        from .finalize import export_deck_bundle
        export_deck_bundle(args.export)

    elif args.delete_deck:
        from .storage import delete_deck
        delete_deck(args.delete_deck)

    elif args.clone_deck:
        from .storage import clone_deck
        clone_deck(args.clone_deck[0], args.clone_deck[1])

    elif args.finalize:
        from .finalize import finalize_deck
        finalize_deck(
            deck_name=args.finalize,
            sheet_size=args.sheet_size,
            color_mode=args.color_mode,
        )

    elif args.deck:
        from .generator import generate_deck
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
            font_path=args.font,
            resume=args.resume,
            preview=not args.no_preview,
        )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
