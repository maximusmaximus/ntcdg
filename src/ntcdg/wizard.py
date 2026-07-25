"""Interactive wizard for easy deck creation.

Guides new users through the setup process step-by-step,
collecting all needed inputs before launching generation.
"""

import os
import re

from .config import Config


def _ask(prompt: str, default: str = "", required: bool = False) -> str:
    """Ask the user a question with optional default."""
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"{prompt}{suffix}: ").strip()
        if not answer and default:
            return default
        if answer:
            return answer
        if required:
            print("  This field is required.")
        else:
            return ""


def _ask_choice(prompt: str, choices: list[str], default: str = "") -> str:
    """Ask the user to pick from a list of options."""
    print(f"\n{prompt}")
    for i, choice in enumerate(choices, 1):
        marker = " *" if choice == default else ""
        print(f"  {i}. {choice}{marker}")
    while True:
        answer = input(f"Choose [1-{len(choices)}]: ").strip()
        if not answer and default:
            return default
        try:
            idx = int(answer)
            if 1 <= idx <= len(choices):
                return choices[idx - 1]
        except ValueError:
            # Allow typing the choice directly
            if answer in choices:
                return answer
        print(f"  Please enter a number 1-{len(choices)}.")


def _ask_yn(prompt: str, default: bool = True) -> bool:
    """Ask a yes/no question."""
    hint = "Y/n" if default else "y/N"
    answer = input(f"{prompt} [{hint}]: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def run_wizard():
    """Interactive wizard for creating a new tarot deck."""
    print("\n" + "=" * 55)
    print("  NTCDG — New Deck Wizard")
    print("  Novel Tarot Card Deck Generator")
    print("=" * 55)

    # --- Step 1: Basics ---
    print("\n--- Step 1: Basics ---")

    name = ""
    while not name:
        name = _ask("Deck name", required=True)
        # Sanitize
        name = re.sub(r'[^A-Za-z0-9_-]', '_', name)
        if not name:
            print("  Name must contain letters or numbers.")

    deck_size = _ask_choice(
        "Deck size:",
        ["78 — Full deck (22 Major + 56 Minor Arcana)",
         "22 — Major Arcana only",
         "Custom"],
        default="78 — Full deck (22 Major + 56 Minor Arcana)",
    )
    if "78" in deck_size:
        num_cards = 78
    elif "22" in deck_size:
        num_cards = 22
    else:
        while True:
            try:
                num_cards = int(_ask("Number of cards", "78"))
                if 1 <= num_cards <= 200:
                    break
                print("  Must be 1-200.")
            except ValueError:
                print("  Enter a number.")

    # --- Step 2: Theme & Style ---
    print("\n--- Step 2: Theme & Style ---")

    print("\nDescribe the vibe/aesthetic of your deck.")
    print("Examples: 'cosmic horror meets art nouveau',")
    print("          'neon cyberpunk tarot',")
    print("          'medieval woodcut with gold leaf'")
    vibe = _ask("Deck vibe", required=True)

    deck_prompt = _ask(
        "Additional theme/instructions (optional)",
    )

    # --- Step 3: Symbols ---
    print("\n--- Step 3: Symbols ---")

    has_symbols = _ask_yn(
        "Do you have a symbols.json with custom symbols?",
        default=False,
    )
    symbols_file = None
    symbol_mode = "generate"
    if has_symbols:
        symbols_file = _ask("Path to symbols.json", required=True)
        if not os.path.exists(symbols_file):
            print(f"  Warning: '{symbols_file}' not found.")
            symbols_file = None
        else:
            has_art = _ask_yn(
                "Does your symbols.json include artwork image paths?",
                default=False,
            )
            if has_art:
                symbol_mode = "provide"
                print("  Your artwork will define the deck's visual style.")

    # --- Step 4: Font ---
    print("\n--- Step 4: Card Overlay ---")

    font_path = None
    has_font = _ask_yn(
        "Do you have a custom font (.ttf/.otf) for card titles?",
        default=False,
    )
    if has_font:
        font_path = _ask("Path to font file")
        if font_path and not os.path.exists(font_path):
            print(f"  Warning: '{font_path}' not found. Will use default.")
            font_path = None

    # --- Step 5: API Key ---
    print("\n--- Step 5: Venice API ---")

    venice_key = os.getenv("VENICE_API_KEY", "")
    if venice_key:
        print("  Found VENICE_API_KEY in environment.")
    else:
        venice_key = _ask("Venice API key", required=True)

    # --- Summary ---
    print("\n" + "=" * 55)
    print("  Ready to generate!")
    print("=" * 55)
    print(f"  Deck name:    {name}")
    print(f"  Cards:        {num_cards}")
    print(f"  Vibe:         {vibe}")
    if deck_prompt:
        print(f"  Theme:        {deck_prompt[:50]}")
    print(f"  Symbols:      {'Custom' if symbols_file else 'Auto-generated'}")
    if symbol_mode == "provide":
        print("  Style from:   Your artwork")
    print(f"  Font:         {font_path or 'Default'}")
    print(f"  Image size:   {Config.DEFAULT_IMAGE_SIZE}")
    print()
    print(f"  This will make ~{num_cards} image generation API calls")
    print(f"  and ~{num_cards} text analysis API calls.")
    print()

    if not _ask_yn("Start generation?", default=True):
        print("Cancelled.")
        return None

    # Return settings dict for the caller to use
    return {
        "name": name,
        "num_cards": num_cards,
        "vibe": vibe,
        "deck_prompt": deck_prompt,
        "venice_key": venice_key,
        "analyze": True,
        "generate_images": True,
        "text_model": Config.DEFAULT_TEXT_MODEL,
        "image_model": Config.DEFAULT_IMAGE_MODEL,
        "image_size": Config.DEFAULT_IMAGE_SIZE,
        "negative_prompt": "",
        "rate_limit": 1.5,
        "interactive": True,
        "symbol_mode": symbol_mode,
        "symbols_file": symbols_file,
        "font_path": font_path,
    }
