"""Core deck generation logic: canonical deck building, card enrichment, PDF proof sheets."""

import os
import random
from datetime import datetime
from typing import Dict, List, Any, Optional

from .config import Config, logger, HAS_TQDM, HAS_REPORTLAB
from .models import Card
from .storage import load_deck, save_deck, load_history
from .symbols import load_symbols_config, generate_symbol_images
from .venice import analyze_with_venice, generate_image_with_venice

if HAS_TQDM:
    from tqdm import tqdm


# ==================== CANONICAL DECK STRUCTURE ====================
def build_canonical_deck(num_cards: int = 78) -> List[Dict[str, Any]]:
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


# ==================== CARD GENERATION ====================
def generate_card(
    position: int,
    total: int,
    card_def: Dict[str, Any],
    deck_vibe: str,
    deck_prompt: str = "",
    symbols: List[Dict[str, Any]] = None,
) -> Card:
    """
    Enrich a card definition with symbols, layout, and prompt.
    Returns a fully populated Card object.
    """
    is_first = position == 1
    is_last = position == total

    suit = card_def.get("suit")
    rank = card_def.get("rank")

    card_symbols = []
    if suit and isinstance(rank, int):
        card_symbols.append(f"{rank} glowing {suit.lower()}")
    elif suit:
        card_symbols.append(f"prominent {suit.lower()}")

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


def build_card_prompt(card: Card) -> str:
    """Build the image generation prompt for a card."""
    base = (
        f"Highly detailed symbolic tarot card in portrait orientation. "
        f"Title at bottom: '{card.title}'. "
        f"Scene: {card.card_type} featuring {', '.join(card.symbols)}. "
        f"Composition and layout: {card.layout}. "
    )

    if card.is_first:
        base += "This is the FIRST card of the deck — representing origins and new beginnings. "
    if card.is_last:
        base += "This is the FINAL card of the deck — representing culmination and full synthesis. "

    if card.deck_prompt:
        base += f"Overall deck theme: {card.deck_prompt}. "

    base += (
        "Psychedelic neon glitch vortex meme aesthetics fused with intricate Rider-Waite symbolic linework. "
        "High symbolic density, electric colors, dramatic cinematic lighting, glowing energy flows."
    )
    return base


# ==================== PROOF SHEET (PDF) ====================
def create_proof_sheet_pdf(deck: List[Card], deck_name: str) -> str:
    if not HAS_REPORTLAB:
        logger.warning("reportlab not installed. Cannot generate PDF proof sheet.")
        return ""

    from reportlab.platypus import PageBreak
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER

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
    deck: List[Card],
    deck_name: str,
    venice_key: Optional[str],
    text_model: str,
    image_model: str,
    image_size: str,
    negative_prompt: str,
    rate_limit: float,
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
            )
            card.update(result)
            if card.image_path:
                print("  → New image generated")

        updated = True

    if updated:
        save_deck(deck, deck_name)
        create_proof_sheet_pdf(deck, deck_name)
        print("\n✅ Files updated and new proof sheet generated.")

    return deck


def review_existing_deck(
    deck_name: str,
    venice_key: Optional[str],
    text_model: str,
    image_model: str,
    image_size: str,
    negative_prompt: str,
    rate_limit: float,
):
    deck = load_deck(deck_name)
    if not deck:
        print(f"Deck '{deck_name}' not found.")
        return

    print(f"\nLoaded existing deck: {deck_name} ({len(deck)} cards)")
    interactive_review(
        deck, deck_name, venice_key, text_model, image_model,
        image_size, negative_prompt, rate_limit,
    )


# ==================== MAIN GENERATION ====================
def generate_deck(
    name: str,
    num_cards: int,
    vibe: Optional[str],
    deck_prompt: str,
    venice_key: Optional[str],
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
):
    os.makedirs(Config.IMAGES_DIR, exist_ok=True)
    deck_vibe = vibe or random.choice(["cyber-vortex synthesis", "neon fractal journey"])

    logger.info(f"Starting deck: {name} ({num_cards} cards)")

    # --- Load and prepare symbols ---
    symbols_config = load_symbols_config(symbols_file)

    if symbol_mode == "generate" and generate_images and venice_key:
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

    # Build symbol_images lookup {name -> path} — HOISTED out of loop
    symbol_images = {}
    for s in symbols_config["symbols"]:
        if s.get("image") and os.path.exists(str(s["image"])):
            symbol_images[s["name"]] = s["image"]

    # Build canonical deck structure — guarantees unique cards
    card_defs = build_canonical_deck(num_cards)
    logger.info(
        f"Canonical deck: "
        f"{sum(1 for c in card_defs if c['type'] == 'Major Arcana')} Major + "
        f"{sum(1 for c in card_defs if c['type'] == 'Minor Arcana')} Minor Arcana"
    )

    deck: List[Card] = []
    stats = {"venice_success": 0, "venice_fail": 0, "image_success": 0, "image_fail": 0}

    iterator = range(len(card_defs))
    if HAS_TQDM:
        iterator = tqdm(iterator, desc="Generating Deck", unit="card", ncols=110)

    for i in iterator:
        position = i + 1
        card_def = card_defs[i]
        if HAS_TQDM:
            iterator.set_description(f"Card {position}/{num_cards} - {card_def['title'][:25]}")

        card = generate_card(
            position, num_cards, card_def, deck_vibe, deck_prompt,
            symbols=symbols_config["symbols"],
        )

        if analyze and venice_key:
            if HAS_TQDM:
                iterator.set_description(f"Card {position}/{num_cards} - Venice Text")
            result = analyze_with_venice(card, venice_key, text_model)
            card.update(result)
            if "venice_error" not in result:
                stats["venice_success"] += 1
            else:
                stats["venice_fail"] += 1

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
            )
            card.update(result)
            if card.image_path:
                stats["image_success"] += 1
            else:
                stats["image_fail"] += 1

        deck.append(card)

    save_deck(deck, name)

    if interactive:
        deck = interactive_review(
            deck, name, venice_key, text_model, image_model,
            image_size, negative_prompt, rate_limit,
        )

    print("\n" + "=" * 65)
    print(f"✅ DECK GENERATION COMPLETE: {name}")
    print(f"   Total Cards: {len(deck)}")
    if analyze:
        print(f"   Venice Analysis: {stats['venice_success']} success | {stats['venice_fail']} failed")
    if generate_images:
        print(f"   Images Generated: {stats['image_success']} success | {stats['image_fail']} failed")
    print(f"   Output folder: {Config.OUTPUT_DIR}/")
    print("=" * 65 + "\n")
