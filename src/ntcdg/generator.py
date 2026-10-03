"""Core deck generation logic: canonical deck building, card enrichment, PDF proof sheets."""

import os
import random
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .config import HAS_REPORTLAB, HAS_TQDM, Config, logger
from .models import Card
from .overlay import compose_card, get_card_number_text
from .storage import (
    deck_images_dir,
    load_deck,
    preview_raw_dir,
    save_deck,
    update_deck_index,
    update_deck_meta,
)
from .style import extract_deck_style, refine_card_prompt
from .symbols import generate_symbol_images, load_symbols_config
from .usage import UsageTracker
from .venice import analyze_with_venice, generate_image_with_venice

if HAS_TQDM:
    from tqdm import tqdm


# ==================== CANONICAL DECK STRUCTURE ====================
def build_canonical_deck(num_cards: int = 78) -> list[dict[str, Any]]:
    """
    Build the canonical tarot deck structure (22 Major + 56 Minor Arcana).
    Returns a list of card definition dicts with type/title/suit/rank.

    If num_cards < 78, prioritises all 22 Major Arcana then fills with Minor.
    If num_cards > 78, wraps around and creates additional cards.
    """
    cards = []

    # 22 Major Arcana
    for number, name in Config.MAJOR_ARCANA:
        cards.append({
            "type": "Major Arcana",
            "title": name,
            "arcana_number": number,
            "suit": None,
            "rank": None,
        })

    # 56 Minor Arcana (4 suits × 14 ranks)
    for suit in Config.SUITS:
        for rank in Config.MINOR_RANKS:
            title = f"{rank} of {suit}"
            cards.append({
                "type": "Minor Arcana",
                "title": title,
                "arcana_number": None,
                "suit": suit,
                "rank": rank,
            })

    # Adjust to requested size
    if num_cards < len(cards):
        if num_cards >= 22:
            selected = cards[:22]
            minor = cards[22:]
            random.shuffle(minor)
            selected.extend(minor[:num_cards - 22])
        else:
            selected = cards[:num_cards]
        cards = selected
    elif num_cards > 78:
        extra_needed = num_cards - 78
        extra = [cards[i % 78].copy() for i in range(extra_needed)]
        cards.extend(extra)

    return cards


def _card_def_from_card(card: Card) -> dict[str, Any]:
    return {
        "type": card.card_type,
        "title": card.title,
        "arcana_number": card.arcana_number,
        "suit": card.suit,
        "rank": card.rank,
    }


def align_card_defs_with_existing(
    card_defs: list[dict[str, Any]],
    existing_cards: dict[int, Card],
) -> list[dict[str, Any]]:
    """Make a freshly built card list agree with cards saved by a previous run.

    Partial decks (< 78 cards) shuffle the Minor Arcana, so rebuilding on resume
    can assign different titles to positions -- or duplicate a title that an
    already-saved card holds. Saved positions keep their identity and any
    remaining collisions are swapped for unused canonical cards.
    """
    aligned = [dict(d) for d in card_defs]
    for pos, card in existing_cards.items():
        if 1 <= pos <= len(aligned) and card.title:
            aligned[pos - 1] = _card_def_from_card(card)

    taken = {
        aligned[pos - 1]["title"] for pos in existing_cards if 1 <= pos <= len(aligned)
    }
    spares = [d for d in build_canonical_deck(78) if d["title"] not in taken]
    seen: set[str] = set(taken)
    for i, d in enumerate(aligned):
        if (i + 1) in existing_cards:
            continue
        if d["title"] in seen and len(aligned) <= 78:
            replacement = next((s for s in spares if s["title"] not in seen), None)
            if replacement:
                aligned[i] = dict(replacement)
        seen.add(aligned[i]["title"])
    return aligned


# ==================== CARD GENERATION ====================
def generate_card(
    position: int,
    total: int,
    card_def: dict[str, Any],
    deck_vibe: str,
    deck_prompt: str = "",
    symbols: list[dict[str, Any]] = None,
    traditional_mode: bool = True,
    artist_analysis: dict[str, Any] | None = None,
) -> Card:
    """
    Enrich a card definition with symbols, layout, and prompt.
    Returns a fully populated Card object.
    """
    is_first = position == 1
    is_last = position == total

    suit = card_def.get("suit")
    rank = card_def.get("rank")

    # Pip count / suit emblem always leads for minor arcana: it is what makes
    # a "Three of Cups" recognisable regardless of symbol mode.
    card_symbols: list[str] = []
    if suit and isinstance(rank, int):
        card_symbols.append(f"{rank} glowing {suit.lower()}")
    elif suit:
        card_symbols.append(f"prominent {suit.lower()}")

    if traditional_mode:
        from .symbols import TraditionalDeckRegistry
        card_symbols.extend(TraditionalDeckRegistry.assign_symbols_for_card(
            card_def=card_def,
            available_symbols=symbols,
            traditional_mode=True,
            max_symbols=4,
            analysis=artist_analysis,
        ))
    else:
        # Select symbols from user-defined list (or defaults)
        available = symbols or Config.DEFAULT_SYMBOLS
        symbol_names = [s["name"] if isinstance(s, dict) else s for s in available]
        num_pick = min(4, len(symbol_names))
        card_symbols.extend(random.sample(symbol_names, k=num_pick))

    if is_first:
        layout = "expansive opening spiral vortex, light emerging outward"
    elif is_last:
        layout = "dense harmonious grand vortex, symbols fully integrated"
    else:
        layout = random.choice([
            "dynamic central vortex spiral",
            "ascending symbolic path",
            "chaotic energetic glitch burst",
        ])

    card = Card(
        position=position,
        title=card_def["title"],
        card_type=card_def["type"],
        suit=suit,
        rank=rank,
        arcana_number=card_def.get("arcana_number"),
        symbols=card_symbols,
        layout=layout,
        deck_vibe=deck_vibe,
        deck_prompt=deck_prompt,
        is_first=is_first,
        is_last=is_last,
        generated_at=datetime.now().isoformat(),
    )

    card.prompt = build_card_prompt(card)
    return card


def build_card_prompt(card: Card, deck_style: str = "") -> str:
    """Build the image generation prompt for a card.

    When a deck_style is available, it is used as the foundation.
    Otherwise, falls back to a generic stylistic template.
    """
    if deck_style:
        # Style-driven prompt
        base = (
            f"{deck_style} "
            f"Tarot card in portrait orientation. "
            f"{card.card_type}: '{card.title}'. "
            f"Visual elements: {', '.join(card.symbols)}. "
            f"Composition: {card.layout}. "
        )
    else:
        # Legacy fallback
        base = (
            f"Highly detailed symbolic tarot card artwork in "
            f"portrait orientation. "
            f"Scene: {card.card_type} -- '{card.title}'. "
            f"Visual elements: {', '.join(card.symbols)}. "
            f"Composition and layout: {card.layout}. "
        )

    if card.is_first:
        base += "First card of the deck -- origins and new beginnings. "
    if card.is_last:
        base += "Final card of the deck -- culmination and synthesis. "

    if card.deck_prompt:
        base += f"Theme: {card.deck_prompt}. "

    if not deck_style:
        # Only add generic style when no deck style is set
        base += (
            "Rich cinematic lighting, high symbolic density, "
            "professional quality, dramatic composition. "
        )

    base += (
        "Do NOT render any text, letters, numbers, titles, or words "
        "on the card."
    )
    return base


# ==================== PROOF SHEET (PDF) ====================
def create_proof_sheet_pdf(deck: list[Card], deck_name: str) -> str:
    if not HAS_REPORTLAB:
        logger.warning("reportlab not installed. Cannot generate PDF proof sheet.")
        return ""

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Image,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
    pdf_path = os.path.join(Config.OUTPUT_DIR, f"{deck_name}_PROOF_SHEET.pdf")

    doc = SimpleDocTemplate(pdf_path, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle', parent=styles['Heading1'],
        fontSize=16, alignment=TA_CENTER, spaceAfter=20,
    )
    card_style = ParagraphStyle(
        'CardTitle', parent=styles['Normal'],
        fontSize=9, alignment=TA_CENTER, leading=11,
    )

    COLS = 4
    ROWS_PER_PAGE = 3

    story = []
    story.append(Paragraph(f"Proof Sheet - {deck_name}", title_style))
    story.append(Spacer(1, 0.3 * inch))

    sorted_deck = sorted(deck, key=lambda c: c.position)

    all_cells = []
    for card in sorted_deck:
        title = card.display_title()
        cell_content = [Paragraph(f"<b>{card.position:02d}</b> - {title}", card_style)]

        if card.image_path and os.path.exists(card.image_path):
            try:
                img = Image(card.image_path, width=1.6 * inch, height=2.4 * inch)
                cell_content.append(img)
            except Exception:
                cell_content.append(Paragraph("[Image Error]", card_style))
        else:
            cell_content.append(Paragraph("[No Image]", card_style))

        all_cells.append(cell_content)

    cards_per_page = COLS * ROWS_PER_PAGE
    page_number = 0
    for page_start in range(0, len(all_cells), cards_per_page):
        if page_number > 0:
            story.append(PageBreak())
        page_number += 1

        page_cells = all_cells[page_start:page_start + cards_per_page]
        table_data = []
        row = []
        for cell in page_cells:
            row.append(cell)
            if len(row) == COLS:
                table_data.append(row)
                row = []
        if row:
            while len(row) < COLS:
                row.append([""])
            table_data.append(row)

        if table_data:
            table = Table(table_data, colWidths=[2.2 * inch] * COLS)
            table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(table)

    doc.build(story)
    logger.info(f"PDF Proof Sheet saved: {pdf_path} ({page_number} pages)")
    return pdf_path


# ==================== INTERACTIVE REVIEW ====================
def interactive_review(
    deck: list[Card],
    deck_name: str,
    venice_key: str | None,
    text_model: str,
    image_model: str,
    image_size: str,
    negative_prompt: str,
    rate_limit: float,
    font_path: str = None,
):
    pdf_path = create_proof_sheet_pdf(deck, deck_name)
    if pdf_path:
        print(f"\n📄 Proof sheet generated: {pdf_path}")

    print("\n--- Interactive Review ---")
    print("Enter card numbers to review (e.g. 3,7,12,42) or press Enter to finish:")

    user_input = input("> ").strip()
    if not user_input:
        print("Review complete. No changes made.")
        return deck

    try:
        positions = [int(x.strip()) for x in user_input.split(",")]
    except ValueError:
        print("Invalid input. Please use numbers only.")
        return deck

    print("\nWhat would you like to regenerate?")
    print("  1) Text analysis only")
    print("  2) Images only")
    print("  3) Both text and images")
    choice = input("Choice (1/2/3): ").strip()

    regenerate_text = choice in ["1", "3"]
    regenerate_images = choice in ["2", "3"]

    updated = False
    for pos in positions:
        card = next((c for c in deck if c.position == pos), None)
        if not card:
            print(f"Card {pos} not found. Skipping.")
            continue

        print(f"\nRegenerating card {pos}...")

        if regenerate_text and venice_key:
            result = analyze_with_venice(card, venice_key, text_model)
            card.update(result)
            print("  → Text analysis updated")

        if regenerate_images and venice_key:
            result = generate_image_with_venice(
                card, venice_key, image_model,
                image_size=image_size,
                negative_prompt=negative_prompt,
                rate_limit_delay=rate_limit,
                symbol_mode="generate",
                symbol_images={},
                output_dir=deck_images_dir(deck_name),
            )
            card.update(result)
            if card.image_path:
                compose_card(
                    image_path=card.image_path,
                    title=card.display_title(),
                    card_number=get_card_number_text(card),
                    card_type=card.card_type,
                    font_path=font_path,
                )
                print("  → New image generated + text overlay applied")

        updated = True

    if updated:
        save_deck(deck, deck_name)
        create_proof_sheet_pdf(deck, deck_name)
        print("\n✅ Files updated and new proof sheet generated.")

    return deck


def review_existing_deck(
    deck_name: str,
    venice_key: str | None,
    text_model: str,
    image_model: str,
    image_size: str,
    negative_prompt: str,
    rate_limit: float,
    font_path: str = None,
):
    deck = load_deck(deck_name)
    if not deck:
        print(f"Deck '{deck_name}' not found.")
        return

    print(f"\nLoaded existing deck: {deck_name} ({len(deck)} cards)")
    interactive_review(
        deck, deck_name, venice_key, text_model, image_model,
        image_size, negative_prompt, rate_limit, font_path=font_path,
    )


# ==================== STYLE PREVIEW ====================
_PREVIEW_CARDS = [
    {"title": "The Fool", "type": "Major Arcana", "arcana_number": 0},
    {"title": "Queen of Cups", "type": "Minor Arcana", "suit": "Cups", "rank": "Queen"},
    {"title": "Five of Swords", "type": "Minor Arcana", "suit": "Swords", "rank": 5},
]


def preview_deck_style(
    deck_style: str,
    deck_vibe: str,
    deck_prompt: str,
    deck_name: str,
    venice_key: str,
    text_model: str,
    image_model: str,
    image_size: str,
    negative_prompt: str,
    rate_limit: float,
    symbols: list[dict[str, Any]] = None,
    symbol_mode: str = "generate",
    symbol_images: dict[str, str] = None,
    font_path: str = None,
    traditional_mode: bool = True,
) -> tuple[bool, str, str]:
    """Generate 3 preview cards and ask user to approve the style.

    Returns (approved, new_vibe, new_prompt):
    - approved=True: proceed with full generation
    - approved=False: user cancelled
    - new_vibe/new_prompt: updated values if user chose to adjust
    """
    preview_dir = os.path.join(Config.IMAGES_DIR, "previews")
    os.makedirs(preview_dir, exist_ok=True)

    print("\nGenerating 3 preview cards to validate style...")
    print(f"Style: {deck_style[:80]}..." if len(deck_style) > 80 else f"Style: {deck_style}")

    preview_paths = []
    for i, card_def in enumerate(_PREVIEW_CARDS):
        card = generate_card(
            position=i + 1, total=3, card_def=card_def,
            deck_vibe=deck_vibe, deck_prompt=deck_prompt,
            symbols=symbols or Config.DEFAULT_SYMBOLS,
            traditional_mode=traditional_mode,
        )

        # Refine prompt with style
        if deck_style and venice_key:
            card.prompt = refine_card_prompt(
                card, deck_style, venice_key, text_model,
            )
        else:
            card.prompt = build_card_prompt(card, deck_style)

        # Generate the preview image
        result = generate_image_with_venice(
            card, venice_key, image_model,
            image_size=image_size,
            negative_prompt=negative_prompt,
            rate_limit_delay=rate_limit,
            symbol_mode=symbol_mode,
            symbol_images=symbol_images or {},
            output_dir=preview_raw_dir(deck_name),
        )
        card.update(result)

        if card.image_path:
            # Move to preview dir with descriptive name
            import shutil
            preview_name = f"{deck_name}_preview_{i + 1}_{card_def['title'].replace(' ', '_')}.png"
            preview_path = os.path.join(preview_dir, preview_name)
            shutil.copy2(card.image_path, preview_path)
            # Apply text overlay to preview
            compose_card(
                image_path=preview_path,
                title=card.display_title(),
                card_number=get_card_number_text(card),
                card_type=card.card_type,
                font_path=font_path,
            )
            preview_paths.append(preview_path)
            print(f"  Preview {i + 1}: {card_def['title']:<20} -> {preview_path}")
        else:
            err = result.get("image_error", "unknown error")
            print(f"  Preview {i + 1}: {card_def['title']:<20} -> FAILED ({err})")

    if not preview_paths:
        print("\nAll previews failed. Check your API key and settings.")
        return False, deck_vibe, deck_prompt

    # Ask user what to do
    print(f"\n{'=' * 55}")
    print(f"  {len(preview_paths)} preview cards generated")
    print(f"  Check them in: {preview_dir}/")
    print(f"{'=' * 55}")

    while True:
        print("\nWhat would you like to do?")
        print("  1. Approve  -- continue generating all cards")
        print("  2. Adjust   -- change vibe/prompt, regenerate previews")
        print("  3. Cancel   -- stop generation")

        choice = input("\nChoose [1-3]: ").strip()

        if choice == "1":
            return True, deck_vibe, deck_prompt

        elif choice == "2":
            print(f"\nCurrent vibe: {deck_vibe}")
            new_vibe = input("New vibe (or Enter to keep): ").strip()
            if not new_vibe:
                new_vibe = deck_vibe

            print(f"Current prompt: {deck_prompt or '(none)'}")
            new_prompt = input("New prompt (or Enter to keep): ").strip()
            if not new_prompt:
                new_prompt = deck_prompt

            return True, new_vibe, new_prompt  # caller will re-extract style

        elif choice == "3":
            print("Generation cancelled.")
            return False, deck_vibe, deck_prompt

        else:
            print("  Please enter 1, 2, or 3.")


# ==================== MAIN GENERATION ====================
def generate_deck(
    name: str,
    num_cards: int,
    vibe: str | None,
    deck_prompt: str,
    venice_key: str | None,
    analyze: bool,
    text_model: str,
    generate_images: bool,
    image_model: str,
    image_size: str,
    negative_prompt: str,
    rate_limit: float,
    interactive: bool = True,
    symbol_mode: str = "generate",
    symbols_file: str = None,
    font_path: str = None,
    resume: bool = False,
    preview: bool = True,
    traditional_mode: bool = True,
    auto_complete_symbols: bool = False,
    on_event: Callable[[dict[str, Any]], None] | None = None,
):
    """Generate (or resume) a full deck.

    ``on_event`` receives dicts such as ``{"type": "card_started", ...}``,
    ``{"type": "card_prompt", ...}``, ``{"type": "card_done", ...}`` so a UI
    can show each step's inputs and outputs as they happen. Exceptions raised
    by the callback are logged and never abort generation.
    """
    if on_event is None:
        from .runtime import current_event_sink
        on_event = current_event_sink()

    def emit(event_type: str, **payload: Any) -> None:
        if on_event is None:
            return
        try:
            on_event({"type": event_type, **payload})
        except Exception as e:  # never let a UI hook kill a long run
            logger.warning(f"on_event callback failed: {e}")

    os.makedirs(Config.IMAGES_DIR, exist_ok=True)
    # Each deck's card art lives in its own folder; card file names are only
    # unique within a deck, so a shared folder let decks overwrite each other.
    card_images_dir = deck_images_dir(name)
    deck_vibe = vibe or random.choice(["cyber-vortex synthesis", "neon fractal journey"])

    # --- Initialize usage tracker ---
    tracker = UsageTracker()
    tracker.text_model = text_model
    tracker.image_model = image_model
    tracker.image_size = image_size

    logger.info(f"Starting deck: {name} ({num_cards} cards)")

    # --- Validate API key ---
    if (analyze or generate_images) and not venice_key:
        if not interactive:
            raise ValueError("A Venice API key is required for analysis or image generation.")
        print("\n" + "=" * 60)
        print("  ERROR: Venice API key is required")
        print("=" * 60)
        print("  You requested --analyze and/or --generate-images but no")
        print("  Venice API key was found.")
        print("")
        print("  Set it via:")
        print("    export VENICE_API_KEY='your-key-here'")
        print("    or: ntcdg --venice-key 'your-key-here' ...")
        print("    or: add venice_api_key to ~/.ntcdgrc")
        print("=" * 60 + "\n")
        raise SystemExit(1)

    # --- Load and prepare symbols ---
    symbols_config = load_symbols_config(symbols_file)

    if auto_complete_symbols and generate_images and venice_key:
        from .symbols import TraditionalDeckRegistry
        logger.info("Auto-completing missing traditional symbols using Venice AI...")
        scope = "major" if num_cards <= 22 else "full"
        symbols_config = TraditionalDeckRegistry.complete_deck_symbols(
            symbols_config=symbols_config,
            deck_name=name,
            deck_prompt=deck_prompt,
            api_key=venice_key,
            image_model=image_model,
            target_scope=scope,
            rate_limit=rate_limit,
        )
    elif symbol_mode == "generate" and generate_images and venice_key:
        logger.info("Generating cohesive symbol images before card generation...")
        symbols_config = generate_symbol_images(
            symbols_config, name, deck_prompt, venice_key, image_model, rate_limit,
        )
    elif symbol_mode == "provide":
        missing = [
            s["name"] for s in symbols_config["symbols"]
            if not (s.get("image") and os.path.exists(str(s["image"])))
        ]
        if missing:
            logger.warning(f"Symbol mode is 'provide' but missing images for: {missing}")

    # Record symbol info in tracker
    tracker.symbol_mode = symbol_mode
    tracker.symbol_names = [s["name"] for s in symbols_config["symbols"]]
    tracker.symbols_file = symbols_file or ""

    # Build symbol_images lookup {name -> path} — HOISTED out of loop
    symbol_images = {}
    for s in symbols_config["symbols"]:
        if s.get("image") and os.path.exists(str(s["image"])):
            symbol_images[s["name"]] = s["image"]

    # Build canonical deck structure -- guarantees unique cards
    card_defs = build_canonical_deck(num_cards)
    logger.info(
        f"Canonical deck: "
        f"{sum(1 for c in card_defs if c['type'] == 'Major Arcana')} Major + "
        f"{sum(1 for c in card_defs if c['type'] == 'Minor Arcana')} Minor Arcana"
    )

    # --- Extract deck style (meta prompt for all artwork) ---
    deck_style = ""
    if generate_images and venice_key:
        symbol_descs = [
            s.get("description", s.get("name", ""))
            for s in symbols_config["symbols"]
        ]
        logger.info("Extracting deck style...")
        deck_style = extract_deck_style(
            symbol_images=symbol_images,
            symbol_descriptions=symbol_descs,
            vibe=deck_vibe,
            deck_prompt=deck_prompt,
            api_key=venice_key,
            text_model=text_model,
        )
        if deck_style:
            logger.info(f"Deck style locked ({len(deck_style)} chars)")
            tracker.record_style_call(deck_style)
            # Persist style in deck index
            update_deck_index(
                name, num_cards, vibe=deck_vibe, theme=deck_prompt,
            )
        else:
            logger.warning("Style extraction failed, using template prompts")

    # --- Style preview: generate 3 samples before full run ---
    if generate_images and venice_key and deck_style and preview and interactive:
        approved = False
        while not approved:
            approved, new_vibe, new_prompt = preview_deck_style(
                deck_style=deck_style,
                deck_vibe=deck_vibe,
                deck_prompt=deck_prompt,
                deck_name=name,
                venice_key=venice_key,
                text_model=text_model,
                image_model=image_model,
                image_size=image_size,
                negative_prompt=negative_prompt,
                rate_limit=rate_limit,
                symbols=symbols_config["symbols"],
                symbol_mode=symbol_mode,
                symbol_images=symbol_images,
                font_path=font_path,
                traditional_mode=traditional_mode,
            )
            if not approved:
                return  # User cancelled

            # If user adjusted vibe/prompt, re-extract style
            if new_vibe != deck_vibe or new_prompt != deck_prompt:
                deck_vibe = new_vibe
                deck_prompt = new_prompt
                logger.info("Re-extracting deck style with updated inputs...")
                symbol_descs = [
                    s.get("description", s.get("name", ""))
                    for s in symbols_config["symbols"]
                ]
                deck_style = extract_deck_style(
                    symbol_images=symbol_images,
                    symbol_descriptions=symbol_descs,
                    vibe=deck_vibe,
                    deck_prompt=deck_prompt,
                    api_key=venice_key,
                    text_model=text_model,
                )
                approved = False  # Loop back to preview with new style
            # else: approved=True, break loop

    deck: list[Card] = []

    # --- Resume: load existing deck and skip completed cards ---
    existing_cards = {}
    if resume:
        existing = load_deck(name)
        if existing:
            existing_cards = {c.position: c for c in existing}
            card_defs = align_card_defs_with_existing(card_defs, existing_cards)
            logger.info(
                f"Resuming: found {len(existing)} existing cards, "
                f"will skip completed ones"
            )

    # Remember the requested size so an interrupted run can be resumed in full
    # (the per-card checkpoint would otherwise shrink num_cards in the index).
    update_deck_meta(name, target_cards=len(card_defs), vibe=deck_vibe, theme=deck_prompt)

    stats = {"venice_success": 0, "venice_fail": 0, "image_success": 0, "image_fail": 0}

    # Match the artist's symbols against the traditional archetypes ONCE,
    # instead of once per card.
    artist_analysis = None
    if traditional_mode:
        from .symbols import TraditionalDeckRegistry
        artist_analysis = TraditionalDeckRegistry.match_artist_symbols(symbols_config["symbols"])

    emit("deck_started", deck=name, num_cards=len(card_defs), vibe=deck_vibe,
         theme=deck_prompt, deck_style=deck_style)

    iterator = range(len(card_defs))
    if HAS_TQDM:
        iterator = tqdm(iterator, desc="Generating Deck", unit="card", ncols=110)

    for i in iterator:
        position = i + 1
        card_def = card_defs[i]
        if HAS_TQDM:
            iterator.set_description(f"Card {position}/{num_cards} - {card_def['title'][:25]}")

        # Resume: skip cards that already have results
        if position in existing_cards:
            existing_card = existing_cards[position]
            has_analysis = existing_card.description and not existing_card.venice_error
            has_image = existing_card.image_path and os.path.exists(
                str(existing_card.image_path)
            )
            skip_analysis = (not analyze) or has_analysis
            skip_image = (not generate_images) or has_image
            if skip_analysis and skip_image:
                deck.append(existing_card)
                if has_analysis:
                    stats["venice_success"] += 1
                if has_image:
                    stats["image_success"] += 1
                emit("card_skipped", position=position, title=existing_card.title,
                     reason="already complete")
                continue

        emit("card_started", position=position, total=len(card_defs), title=card_def["title"])
        card = generate_card(
            position, num_cards, card_def, deck_vibe, deck_prompt,
            symbols=symbols_config["symbols"],
            traditional_mode=traditional_mode,
            artist_analysis=artist_analysis,
        )

        # --- Refine prompt with LLM (style-aware) ---
        if generate_images and venice_key and deck_style:
            if HAS_TQDM:
                iterator.set_description(
                    f"Card {position}/{num_cards} - Prompt"
                )
            card.prompt = refine_card_prompt(
                card, deck_style, venice_key, text_model,
            )
        else:
            card.prompt = build_card_prompt(card, deck_style)
        emit("card_prompt", position=position, symbols=list(card.symbols), prompt=card.prompt)

        if analyze and venice_key:
            if HAS_TQDM:
                iterator.set_description(f"Card {position}/{num_cards} - Venice Text")
            result = analyze_with_venice(
                card, venice_key, text_model, tracker=tracker,
            )
            card.update(result)
            if "venice_error" not in result:
                stats["venice_success"] += 1
            else:
                stats["venice_fail"] += 1
            emit("card_analysis", position=position, result=result)

        if generate_images and venice_key:
            if HAS_TQDM:
                iterator.set_description(f"Card {position}/{num_cards} - Image")
            result = generate_image_with_venice(
                card, venice_key, image_model,
                image_size=image_size,
                negative_prompt=negative_prompt,
                rate_limit_delay=rate_limit,
                symbol_mode=symbol_mode,
                symbol_images=symbol_images,
                tracker=tracker,
                output_dir=card_images_dir,
            )
            card.update(result)
            if card.image_path:
                compose_card(
                    image_path=card.image_path,
                    title=card.display_title(),
                    card_number=get_card_number_text(card),
                    card_type=card.card_type,
                    font_path=font_path,
                )
                stats["image_success"] += 1
            else:
                stats["image_fail"] += 1
            emit("card_image", position=position, image_path=card.image_path,
                 error=card.image_error)

        deck.append(card)
        # Checkpoint so a crash / cancelled job can be resumed without losing work.
        # Keep cards not yet reached in this run (from a previous partial run).
        checkpoint = deck + [
            c for p, c in sorted(existing_cards.items()) if p > position
        ]
        save_deck(checkpoint, name, export=False)
        emit("card_done", position=position, card=card.to_dict())

    save_deck(deck, name)

    # --- Finalize and persist usage stats ---
    tracker.finalize()
    update_deck_index(name, len(deck), vibe=deck_vibe, theme=deck_prompt)
    update_deck_meta(name, usage=tracker.to_dict())
    emit("deck_done", deck=name, num_cards=len(deck), stats=dict(stats),
         usage=tracker.to_dict())

    if interactive:
        deck = interactive_review(
            deck, name, venice_key, text_model, image_model,
            image_size, negative_prompt, rate_limit, font_path=font_path,
        )

    costs = tracker.estimate_cost()
    elapsed = tracker.elapsed_seconds
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)

    print("\n" + "=" * 65)
    print(f"DECK GENERATION COMPLETE: {name}")
    print(f"   Total Cards: {len(deck)}")
    if analyze:
        print(
            f"   Venice Analysis: "
            f"{stats['venice_success']} success | "
            f"{stats['venice_fail']} failed"
        )
    if generate_images:
        print(
            f"   Images Generated: "
            f"{stats['image_success']} success | "
            f"{stats['image_fail']} failed"
        )
    print(f"   Tokens used: {tracker.total_tokens:,}")
    print(f"   Estimated cost: ${costs['total']:.4f}")
    print(f"   Time: {mins}m {secs}s")
    print(f"   Output folder: {Config.OUTPUT_DIR}/")
    print(f"   Run --deck-stats {name} for full breakdown")
    print("=" * 65 + "\n")
