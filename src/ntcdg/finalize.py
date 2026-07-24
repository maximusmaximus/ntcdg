"""Deck finalization: completeness validation and print-ready PDF with crop marks.

Generates press-ready PDFs with cards laid out on sheets (letter or tabloid),
CMYK color space, crop/trim marks, and bleed margins.

Standard tarot card: 2.75" x 4.75" with 0.125" bleed on each side.
"""

import math
import os
import shutil
import tempfile

from .config import HAS_REPORTLAB, Config, logger
from .models import Card
from .storage import load_deck

try:
    from PIL import Image

    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

if HAS_REPORTLAB:
    from reportlab.lib.colors import CMYKColor
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas as pdf_canvas


# ==================== PRINT CONSTANTS ====================
# Standard tarot card dimensions (inches)
CARD_TRIM_W = 2.75
CARD_TRIM_H = 4.75
BLEED = 0.125  # per side

CARD_BLEED_W = CARD_TRIM_W + 2 * BLEED  # 3.0"
CARD_BLEED_H = CARD_TRIM_H + 2 * BLEED  # 5.0"

# Crop mark styling
MARK_LENGTH = 0.25    # line length (inches)
MARK_GAP = 0.0625     # gap between bleed edge and mark start
MARK_LINE_W = 0.5     # line width (points)

# Sheet layout
CELL_GAP = 0.25       # gap between card cells (1/4") — room for marks
SHEET_MARGIN = 0.375  # page edge margin (inches)

SHEET_SIZES = {
    "letter": (8.5, 11.0),
    "tabloid": (11.0, 17.0),
}


# ==================== VALIDATION ====================
def validate_deck(deck: list[Card]) -> dict:
    """
    Check deck completeness for finalization.

    Returns {"errors": [...], "warnings": [...]}.
    Errors block finalization; warnings are informational.
    """
    errors = []
    warnings = []

    for card in deck:
        pos = card.position or "?"
        if not card.title:
            errors.append(f"Card {pos}: missing title")
        if not card.image_path:
            errors.append(f"Card {pos}: no image generated")
        elif not os.path.exists(str(card.image_path)):
            errors.append(f"Card {pos}: image file missing ({card.image_path})")
        if not card.description:
            warnings.append(f"Card {pos}: no description")
        if not getattr(card, "upright_interpretation", None):
            warnings.append(f"Card {pos}: no upright interpretation")
        if not getattr(card, "reversed_interpretation", None):
            warnings.append(f"Card {pos}: no reversed interpretation")

    return {"errors": errors, "warnings": warnings}


# ==================== LAYOUT CALCULATION ====================
def _calculate_grid(sheet_w_in: float, sheet_h_in: float) -> dict:
    """Calculate how many cards fit on a sheet and their positions."""
    usable_w = sheet_w_in - 2 * SHEET_MARGIN
    usable_h = sheet_h_in - 2 * SHEET_MARGIN

    # Find max columns: first card = CARD_BLEED_W, each additional = CARD_BLEED_W + CELL_GAP
    cols = 1
    while (cols + 1) * CARD_BLEED_W + cols * CELL_GAP <= usable_w:
        cols += 1

    rows = 1
    while (rows + 1) * CARD_BLEED_H + rows * CELL_GAP <= usable_h:
        rows += 1

    # Center the grid on the page
    grid_w = cols * CARD_BLEED_W + max(0, cols - 1) * CELL_GAP
    grid_h = rows * CARD_BLEED_H + max(0, rows - 1) * CELL_GAP
    start_x = (sheet_w_in - grid_w) / 2
    start_y = (sheet_h_in - grid_h) / 2

    return {
        "cols": cols,
        "rows": rows,
        "cards_per_page": cols * rows,
        "start_x": start_x,
        "start_y": start_y,
    }


# ==================== CROP MARKS ====================
def _draw_crop_marks(c, trim_x, trim_y, trim_w, trim_h):
    """
    Draw crop marks at all 4 corners of a card's trim area.

    Marks sit outside the bleed area, indicating where to cut.
    """
    bleed_pt = BLEED * inch
    mark_len = MARK_LENGTH * inch
    gap_pt = MARK_GAP * inch

    c.setStrokeColorCMYK(0, 0, 0, 1)  # Registration black
    c.setLineWidth(MARK_LINE_W)

    # (corner_x, corner_y, horizontal_direction, vertical_direction)
    corners = [
        (trim_x, trim_y, -1, -1),                           # bottom-left
        (trim_x + trim_w, trim_y, 1, -1),                   # bottom-right
        (trim_x, trim_y + trim_h, -1, 1),                   # top-left
        (trim_x + trim_w, trim_y + trim_h, 1, 1),           # top-right
    ]

    for cx, cy, hd, vd in corners:
        # Horizontal mark — extends outward from corner
        h_start = cx + hd * (bleed_pt + gap_pt)
        c.line(h_start, cy, h_start + hd * mark_len, cy)
        # Vertical mark
        v_start = cy + vd * (bleed_pt + gap_pt)
        c.line(cx, v_start, cx, v_start + vd * mark_len)


# ==================== IMAGE PREPARATION ====================
def _prepare_image(image_path: str, color_mode: str, tmp_dir: str) -> str:
    """
    Convert card image for print output.

    - color_mode "bw": convert to grayscale then CMYK
    - color_mode "color": convert RGB → CMYK
    - Saves as CMYK JPEG in tmp_dir
    """
    img = Image.open(image_path)

    # Handle alpha channels
    if img.mode in ("RGBA", "P", "LA"):
        # Flatten alpha onto white background
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        if img.mode in ("RGBA", "LA"):
            bg.paste(img, mask=img.split()[-1])
            img = bg

    if color_mode == "bw":
        img = img.convert("L").convert("RGB").convert("CMYK")
    else:
        if img.mode != "RGB":
            img = img.convert("RGB")
        img = img.convert("CMYK")

    basename = os.path.splitext(os.path.basename(image_path))[0]
    out_path = os.path.join(tmp_dir, f"{basename}_cmyk.jpg")
    img.save(out_path, "JPEG", quality=95)
    return out_path


# ==================== PRINT PDF GENERATION ====================
def create_print_pdf(
    deck: list[Card],
    deck_name: str,
    sheet_size: str = "letter",
    color_mode: str = "color",
) -> str:
    """
    Generate a print-ready CMYK PDF with sequential cards on sheets.

    Layout packs as many cards as possible per sheet with crop marks
    at each card's trim corners for easy cutting.

    Args:
        deck: List of Card objects.
        deck_name: Name for the output file.
        sheet_size: "letter" (8.5x11) or "tabloid" (11x17).
        color_mode: "color" or "bw" (both produce CMYK output).

    Returns:
        Path to the generated PDF, or "" on failure.
    """
    if not HAS_REPORTLAB:
        logger.error("reportlab is required for print PDFs")
        return ""
    if not HAS_PILLOW:
        logger.error("Pillow is required for print image conversion")
        return ""

    sheet_w_in, sheet_h_in = SHEET_SIZES[sheet_size]
    layout = _calculate_grid(sheet_w_in, sheet_h_in)

    sheet_w = sheet_w_in * inch
    sheet_h = sheet_h_in * inch

    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
    pdf_path = os.path.join(
        Config.OUTPUT_DIR,
        f"{deck_name}_PRINT_{sheet_size}_{color_mode}.pdf",
    )

    c = pdf_canvas.Canvas(pdf_path, pagesize=(sheet_w, sheet_h))
    c.setTitle(f"{deck_name} — Print Ready ({sheet_size.title()}, {color_mode.upper()} CMYK)")
    c.setAuthor("NTCDG — Novel Tarot Card Deck Generator")

    # Sort by position, filter to cards with existing images
    sorted_deck = sorted(deck, key=lambda card: card.position or 0)
    printable = [
        card for card in sorted_deck
        if card.image_path and os.path.exists(str(card.image_path))
    ]

    if not printable:
        logger.error("No cards with images found — cannot create print PDF")
        return ""

    cards_per_page = layout["cards_per_page"]
    total_pages = math.ceil(len(printable) / cards_per_page)

    logger.info(
        f"Print layout: {layout['cols']}x{layout['rows']} = "
        f"{cards_per_page} cards/page, {total_pages} pages for {len(printable)} cards"
    )

    tmp_dir = tempfile.mkdtemp(prefix="ntcdg_print_")

    try:
        for page_idx in range(total_pages):
            start = page_idx * cards_per_page
            page_cards = printable[start : start + cards_per_page]

            for i, card in enumerate(page_cards):
                row = i // layout["cols"]
                col = i % layout["cols"]

                # Card bleed area position (in inches, from page origin)
                bleed_x_in = layout["start_x"] + col * (CARD_BLEED_W + CELL_GAP)
                # ReportLab y=0 is bottom; lay out from top of page downward
                bleed_y_in = (
                    sheet_h_in
                    - layout["start_y"]
                    - (row + 1) * CARD_BLEED_H
                    - row * CELL_GAP
                )

                bleed_x = bleed_x_in * inch
                bleed_y = bleed_y_in * inch

                # Prepare CMYK image
                try:
                    img_path = _prepare_image(card.image_path, color_mode, tmp_dir)
                except Exception as e:
                    logger.warning(f"Image prep failed for card {card.position}: {e}")
                    continue

                # Draw card image (scaled to fill bleed area)
                c.drawImage(
                    img_path,
                    bleed_x,
                    bleed_y,
                    width=CARD_BLEED_W * inch,
                    height=CARD_BLEED_H * inch,
                    preserveAspectRatio=True,
                    anchor="c",
                )

                # Draw crop marks at trim corners
                trim_x = bleed_x + BLEED * inch
                trim_y = bleed_y + BLEED * inch
                _draw_crop_marks(c, trim_x, trim_y, CARD_TRIM_W * inch, CARD_TRIM_H * inch)

            # Page footer
            c.setFont("Helvetica", 7)
            c.setFillColorCMYK(0, 0, 0, 0.5)
            c.drawCentredString(
                sheet_w / 2,
                SHEET_MARGIN * inch * 0.4,
                f"{deck_name}  ·  Page {page_idx + 1}/{total_pages}  ·  "
                f"{sheet_size.title()}  ·  {color_mode.upper()} CMYK  ·  "
                f"Card {CARD_TRIM_W}\" x {CARD_TRIM_H}\" + {BLEED}\" bleed",
            )

            c.showPage()

        c.save()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    logger.info(f"Print PDF saved: {pdf_path}")
    return pdf_path


# ==================== BOOKLET HELPERS ====================
# Booklet page is the same size as a tarot card
_BK_W = CARD_TRIM_W * 72  # page width in points (2.75")
_BK_H = CARD_TRIM_H * 72  # page height in points (4.75")
_BK_MARGIN = 0.25 * 72    # margin in points
_BK_USABLE_W = _BK_W - 2 * _BK_MARGIN

GITHUB_URL = "github.com/maximusmaximus/ntcdg"

# Color palette (CMYK)
_INK = CMYKColor(0, 0, 0, 1) if HAS_REPORTLAB else None        # black
_GRAY = CMYKColor(0, 0, 0, 0.45) if HAS_REPORTLAB else None    # mid gray
_LGRAY = CMYKColor(0, 0, 0, 0.25) if HAS_REPORTLAB else None   # light gray
_GOLD = CMYKColor(0, 0.08, 0.35, 0.09) if HAS_REPORTLAB else None  # warm gold
_WHITE = CMYKColor(0, 0, 0, 0) if HAS_REPORTLAB else None


def _bk_wrap(c, text: str, font: str, size: float) -> list[str]:
    """Word-wrap text to fit the booklet's usable width."""
    words = (text or "").split()
    if not words:
        return [""]
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if c.stringWidth(test, font, size) <= _BK_USABLE_W:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _bk_draw_rule(c, y: float) -> float:
    """Draw a thin decorative rule across the page. Returns new y."""
    c.setStrokeColor(_LGRAY)
    c.setLineWidth(0.4)
    c.line(_BK_MARGIN, y, _BK_W - _BK_MARGIN, y)
    return y - 6


def _bk_write_text(c, y: float, text: str, font: str = "Helvetica",
                   size: float = 6.5, color=None, align: str = "left") -> float:
    """Write a single line. Returns new y position."""
    c.setFont(font, size)
    c.setFillColor(color or _INK)
    if align == "center":
        c.drawCentredString(_BK_W / 2, y, text)
    elif align == "right":
        c.drawRightString(_BK_W - _BK_MARGIN, y, text)
    else:
        c.drawString(_BK_MARGIN, y, text)
    return y - size * 1.35


def _bk_write_wrapped(c, y: float, text: str, font: str = "Helvetica",
                      size: float = 6.5, color=None) -> float:
    """Write word-wrapped text. Auto page-breaks. Returns new y."""
    lines = _bk_wrap(c, text, font, size)
    line_h = size * 1.35
    for line in lines:
        if y - line_h < _BK_MARGIN:
            c.showPage()
            y = _BK_H - _BK_MARGIN
        y = _bk_write_text(c, y, line, font, size, color)
    return y


def _bk_draw_cover(c, deck_name: str, deck, num_cards: int):
    """Draw the booklet front cover with artwork and title."""
    # Dark background
    c.setFillColorCMYK(0.15, 0.12, 0, 0.85)
    c.rect(0, 0, _BK_W, _BK_H, stroke=0, fill=1)

    # If first card has an image, draw it faded as cover art
    cover_card = next(
        (card for card in deck
         if card.image_path and os.path.exists(str(card.image_path))),
        None,
    )
    if cover_card and HAS_PILLOW:
        try:
            from PIL import ImageEnhance
            img = Image.open(cover_card.image_path)
            img = ImageEnhance.Brightness(img).enhance(0.3)
            tmp = os.path.join(tempfile.gettempdir(), "ntcdg_cover_tmp.jpg")
            img.convert("RGB").save(tmp, "JPEG", quality=80)
            c.drawImage(tmp, 0, 0, width=_BK_W, height=_BK_H,
                        preserveAspectRatio=True, anchor="c")
            os.remove(tmp)
        except Exception:
            pass  # Fall back to solid background

    # Decorative top rule
    y = _BK_H - _BK_MARGIN * 1.5
    c.setStrokeColor(_GOLD)
    c.setLineWidth(1.5)
    c.line(_BK_MARGIN, y, _BK_W - _BK_MARGIN, y)

    # Deck name
    y -= 28
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(_GOLD)
    name_display = deck_name.replace("_", " ").replace("-", " ")
    for line in _bk_wrap(c, name_display, "Helvetica-Bold", 14):
        c.drawCentredString(_BK_W / 2, y, line)
        y -= 18

    # Subtitle
    y -= 8
    c.setFont("Helvetica", 8)
    c.setFillColor(_WHITE)
    c.drawCentredString(_BK_W / 2, y, "A Novel Tarot Deck")
    y -= 14
    c.setFont("Helvetica", 7)
    c.drawCentredString(_BK_W / 2, y, f"{num_cards} Cards")

    # Bottom rule + label
    y_bottom = _BK_MARGIN * 1.5
    c.setStrokeColor(_GOLD)
    c.setLineWidth(1.5)
    c.line(_BK_MARGIN, y_bottom, _BK_W - _BK_MARGIN, y_bottom)
    c.setFont("Helvetica-Oblique", 6.5)
    c.setFillColor(_WHITE)
    c.drawCentredString(_BK_W / 2, y_bottom + 8, "Companion Guide")


def _bk_draw_credits(c):
    """Draw the inside front page: 'Made with <3' and repo link."""
    y = _BK_H / 2 + 30

    c.setFont("Helvetica", 10)
    c.setFillColor(_INK)
    c.drawCentredString(_BK_W / 2, y, "Made with <3")

    y -= 24
    c.setFont("Helvetica", 7)
    c.setFillColor(_GRAY)
    c.drawCentredString(_BK_W / 2, y, "Generated by NTCDG")
    y -= 11
    c.drawCentredString(_BK_W / 2, y, "Novel Tarot Card Deck Generator")

    y -= 22
    _bk_draw_rule(c, y)
    y -= 14

    c.setFont("Helvetica", 7)
    c.setFillColor(_INK)
    c.drawCentredString(_BK_W / 2, y, GITHUB_URL)

    y -= 20
    _bk_draw_rule(c, y)
    y -= 14

    c.setFont("Helvetica-Oblique", 6)
    c.setFillColor(_LGRAY)
    c.drawCentredString(_BK_W / 2, y, "This deck and its companion guide were")
    y -= 9
    c.drawCentredString(_BK_W / 2, y, "created with AI-assisted generation.")


def _bk_draw_section_divider(c, title: str, subtitle: str = ""):
    """Draw a full-page section divider with centered title."""
    # Light background tint
    c.setFillColorCMYK(0.03, 0.02, 0, 0.06)
    c.rect(0, 0, _BK_W, _BK_H, stroke=0, fill=1)

    y_center = _BK_H / 2

    # Decorative rules
    c.setStrokeColor(_LGRAY)
    c.setLineWidth(0.6)
    c.line(_BK_MARGIN, y_center + 20, _BK_W - _BK_MARGIN, y_center + 20)
    c.line(_BK_MARGIN, y_center - 18, _BK_W - _BK_MARGIN, y_center - 18)

    # Section title
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(_INK)
    c.drawCentredString(_BK_W / 2, y_center, title)

    if subtitle:
        c.setFont("Helvetica-Oblique", 7)
        c.setFillColor(_GRAY)
        c.drawCentredString(_BK_W / 2, y_center - 30, subtitle)


def _bk_write_card_entry(c, y: float, card) -> float:
    """Write a single card's description entry. Returns new y position."""
    from .overlay import get_card_number_text

    # Estimate space needed -- if too little room, start new page
    if y - 65 < _BK_MARGIN:
        c.showPage()
        y = _BK_H - _BK_MARGIN

    # Number + title header
    number = get_card_number_text(card)
    display_title = card.display_title()
    header = f"{number}  -  {display_title}"

    y = _bk_draw_rule(c, y)
    y -= 2
    y = _bk_write_text(c, y, header, "Helvetica-Bold", 7.5, _INK)
    y -= 2

    # Description (italic, gray)
    if card.description:
        y = _bk_write_wrapped(c, y, card.description, "Helvetica-Oblique", 6, _GRAY)
        y -= 3

    # Upright interpretation
    if card.upright_interpretation:
        y = _bk_write_text(c, y, "Upright", "Helvetica-Bold", 6, _INK)
        y = _bk_write_wrapped(c, y, card.upright_interpretation, "Helvetica", 6, _INK)
        y -= 2

    # Reversed interpretation
    if card.reversed_interpretation:
        y = _bk_write_text(c, y, "Reversed", "Helvetica-Bold", 6, _INK)
        y = _bk_write_wrapped(c, y, card.reversed_interpretation, "Helvetica", 6, _INK)

    y -= 4
    return y


# ==================== BOOKLET PDF ====================
def create_booklet_pdf(deck: list["Card"], deck_name: str) -> str:
    """
    Create a pocket-sized companion booklet (same size as a tarot card).

    Structure:
    1. Cover -- deck name with artwork from first card
    2. Credits -- "Made with <3", GitHub link
    3. Major Arcana -- section divider + card entries
    4. Minor Arcana -- divider per suit + card entries
       (Wands, Cups, Swords, Pentacles)

    Each card entry: number, title, description,
    upright interpretation, reversed interpretation.
    """
    if not HAS_REPORTLAB:
        logger.error("reportlab is required for booklet PDF")
        return ""

    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
    pdf_path = os.path.join(Config.OUTPUT_DIR, f"{deck_name}_BOOKLET.pdf")

    c = pdf_canvas.Canvas(pdf_path, pagesize=(_BK_W, _BK_H))
    c.setTitle(f"{deck_name} - Companion Guide")
    c.setAuthor("NTCDG")

    sorted_deck = sorted(deck, key=lambda card: card.position or 0)

    # --- Page 1: Cover ---
    _bk_draw_cover(c, deck_name, sorted_deck, len(deck))
    c.showPage()

    # --- Page 2: Credits ---
    _bk_draw_credits(c)
    c.showPage()

    # --- Group cards by type ---
    major = [card for card in sorted_deck if card.card_type == "Major Arcana"]
    suits = {"Wands": [], "Cups": [], "Swords": [], "Pentacles": []}
    for card in sorted_deck:
        if card.card_type == "Minor Arcana" and card.suit in suits:
            suits[card.suit].append(card)

    # --- Major Arcana section ---
    if major:
        _bk_draw_section_divider(c, "MAJOR ARCANA", f"{len(major)} Cards")
        c.showPage()
        y = _BK_H - _BK_MARGIN
        for card in major:
            y = _bk_write_card_entry(c, y, card)
        c.showPage()

    # --- Minor Arcana sections (by suit) ---
    for suit_name, cards in suits.items():
        if not cards:
            continue
        _bk_draw_section_divider(c, f"SUIT OF {suit_name.upper()}", f"{len(cards)} Cards")
        c.showPage()
        y = _BK_H - _BK_MARGIN
        for card in cards:
            y = _bk_write_card_entry(c, y, card)
        c.showPage()

    c.save()
    logger.info(f"Booklet PDF saved: {pdf_path}")
    return pdf_path


# ==================== FINALIZATION WORKFLOW ====================
def finalize_deck(
    deck_name: str,
    sheet_size: str = "letter",
    color_mode: str = "color",
) -> str:
    """
    Finalize a deck: validate, generate print PDF and companion booklet.

    Steps:
    1. Load deck and validate completeness
    2. Report errors (block) and warnings (inform)
    3. Generate CMYK print PDF with crop marks
    4. Generate companion booklet PDF (card-sized)
    5. Print summary

    Returns path to the print PDF, or "" on failure.
    """
    deck = load_deck(deck_name)
    if not deck:
        print(f"Deck '{deck_name}' not found.")
        return ""

    sheet_w, sheet_h = SHEET_SIZES[sheet_size]
    layout = _calculate_grid(sheet_w, sheet_h)

    print(f"\n{'=' * 60}")
    print(f"FINALIZING: {deck_name} ({len(deck)} cards)")
    print(f"Sheet: {sheet_size.title()} ({sheet_w}\" x {sheet_h}\")")
    print(f"Color: {color_mode.upper()} CMYK")
    print(f"Layout: {layout['cols']}x{layout['rows']} cards per sheet")
    print(f"{'=' * 60}")

    # --- Validate ---
    report = validate_deck(deck)

    if report["warnings"]:
        print(f"\n  {len(report['warnings'])} warning(s):")
        shown = report["warnings"][:10]
        for w in shown:
            print(f"   o {w}")
        if len(report["warnings"]) > 10:
            print(f"   ... and {len(report['warnings']) - 10} more")

    if report["errors"]:
        print(f"\n  {len(report['errors'])} error(s) -- these must be fixed:")
        for e in report["errors"]:
            print(f"   * {e}")
        print("\nCannot finalize. Fix errors above first.")
        return ""

    if not report["warnings"]:
        print("\nDeck passes all completeness checks.")

    # --- Generate print PDF ---
    printable = [c for c in deck if c.image_path and os.path.exists(str(c.image_path))]
    total_pages = math.ceil(len(printable) / layout["cards_per_page"])

    print(f"\nGenerating print PDF ({len(printable)} cards -> {total_pages} pages)...")
    pdf_path = create_print_pdf(deck, deck_name, sheet_size, color_mode)

    # --- Generate companion booklet ---
    print("Generating companion booklet...")
    booklet_path = create_booklet_pdf(deck, deck_name)

    if pdf_path:
        print(f"\n{'=' * 60}")
        print(f"FINALIZED: {deck_name}")
        print(f"   Print PDF:  {pdf_path}")
        if booklet_path:
            print(f"   Booklet:    {booklet_path}")
        print(f"   Pages: {total_pages}")
        print(f"   Card trim: {CARD_TRIM_W}\" x {CARD_TRIM_H}\"")
        print(f"   Bleed: {BLEED}\" per side")
        print(f"   Color space: CMYK ({color_mode})")
        print(f"{'=' * 60}\n")

    return pdf_path
