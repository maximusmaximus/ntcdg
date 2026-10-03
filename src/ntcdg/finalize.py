"""Deck finalization: completeness validation and print-ready PDF with crop marks.

Generates press-ready PDFs with cards laid out on sheets (letter or tabloid),
CMYK color space, crop/trim marks, and bleed margins.

Standard tarot card: 2.75" x 4.75" with 0.125" bleed on each side.
"""

from __future__ import annotations

import math
import os
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
# Standard tarot card dimensions (inches) - 70mm x 120mm trim
CARD_TRIM_W = 2.75
CARD_TRIM_H = 4.75
BLEED = 0.125  # 1/8" per side

CARD_BLEED_W = CARD_TRIM_W + 2 * BLEED  # 3.0"
CARD_BLEED_H = CARD_TRIM_H + 2 * BLEED  # 5.0"
TAROT_BLEED_ASPECT = CARD_BLEED_W / CARD_BLEED_H  # 3.0 / 5.0 = 0.60

# Crop mark styling (high precision hairline marks)
MARK_LENGTH = 0.20    # line length (inches) - fits cleanly within cell gaps
MARK_GAP = 0.04       # gap between bleed edge and mark start (inches)
MARK_LINE_W = 0.4     # hairline stroke width (points)

# Sheet layout
CELL_GAP = 0.25       # gap between card cells (1/4") — room for marks and double-cuts
SHEET_MARGIN = 0.375  # page edge margin (inches)

SHEET_SIZES = {
    "letter": (8.5, 11.0),
    "tabloid": (11.0, 17.0),
    "a4": (8.27, 11.69),
    "a3": (11.69, 16.54),
}

COLOR_MODES = ("color", "bw")
DUPLEX_FLIPS = ("long_edge", "short_edge")


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

    # Positions identify cards in QR URLs / slot labels -- they must be unique.
    seen: dict[int, int] = {}
    for card in deck:
        if not card.position or int(card.position) < 1:
            errors.append(f"Card '{card.title or '?'}': missing or invalid position")
            continue
        seen[int(card.position)] = seen.get(int(card.position), 0) + 1
    for pos, n in sorted(seen.items()):
        if n > 1:
            errors.append(f"Position {pos} is used by {n} cards (positions must be unique)")

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


# ==================== CROP MARKS & SHEET GUIDES ====================
def _draw_crop_marks(
    c,
    trim_x: float,
    trim_y: float,
    trim_w: float,
    trim_h: float,
    gutter_right: bool = False,
    gutter_left: bool = False,
    gutter_top: bool = False,
    gutter_bottom: bool = False,
):
    """
    Draw precision crop marks at all 4 corners of a card's trim area.

    Marks sit outside the bleed area, indicating exactly where to cut.
    Gutter constraints prevent marks from overlapping between adjacent cards.
    """
    bleed_pt = BLEED * inch
    gap_pt = MARK_GAP * inch
    base_mark_len = MARK_LENGTH * inch

    # Gutter clamp: half of cell gap minus bleed to avoid collision
    gutter_limit = max(0.08 * inch, (CELL_GAP * inch + 2 * bleed_pt) / 2 - gap_pt - 1)
    len_r = min(base_mark_len, gutter_limit) if gutter_right else base_mark_len
    len_l = min(base_mark_len, gutter_limit) if gutter_left else base_mark_len
    len_t = min(base_mark_len, gutter_limit) if gutter_top else base_mark_len
    len_b = min(base_mark_len, gutter_limit) if gutter_bottom else base_mark_len

    c.setStrokeColorCMYK(0, 0, 0, 1)  # Registration / Key black
    c.setLineWidth(MARK_LINE_W)

    # (corner_x, corner_y, horizontal_direction, vertical_direction, h_len, v_len)
    corners = [
        (trim_x, trim_y, -1, -1, len_l, len_b),                     # bottom-left
        (trim_x + trim_w, trim_y, 1, -1, len_r, len_b),             # bottom-right
        (trim_x, trim_y + trim_h, -1, 1, len_l, len_t),             # top-left
        (trim_x + trim_w, trim_y + trim_h, 1, 1, len_r, len_t),     # top-right
    ]

    for cx, cy, hd, vd, h_len, v_len in corners:
        # Horizontal mark — strictly on line y = cy
        h_start = cx + hd * (bleed_pt + gap_pt)
        c.line(h_start, cy, h_start + hd * h_len, cy)
        # Vertical mark — strictly on line x = cx
        v_start = cy + vd * (bleed_pt + gap_pt)
        c.line(cx, v_start, cx, v_start + vd * v_len)


def _draw_sheet_guides(
    c, layout: dict, sheet_w_in: float, sheet_h_in: float,
):
    """
    Draw continuous cutting guide ticks and registration marks at sheet margins.

    Printers and artists using a guillotine or straightedge ruler can align
    across the entire sheet for straight, continuous cuts without losing reference.
    """
    sheet_w = sheet_w_in * inch
    sheet_h = sheet_h_in * inch

    c.setStrokeColorCMYK(0, 0, 0, 1)
    c.setLineWidth(0.4)

    # Collect all unique vertical trim lines (x coordinates)
    v_cuts = []
    for col in range(layout["cols"]):
        b_x = (layout["start_x"] + col * (CARD_BLEED_W + CELL_GAP)) * inch
        t_left = b_x + BLEED * inch
        t_right = t_left + CARD_TRIM_W * inch
        v_cuts.extend([t_left, t_right])

    # Collect all unique horizontal trim lines (y coordinates)
    h_cuts = []
    for row in range(layout["rows"]):
        b_y = (
            sheet_h_in
            - layout["start_y"]
            - (row + 1) * CARD_BLEED_H
            - row * CELL_GAP
        ) * inch
        t_bottom = b_y + BLEED * inch
        t_top = t_bottom + CARD_TRIM_H * inch
        h_cuts.extend([t_bottom, t_top])

    # Margin tick length
    tick_len = 0.18 * inch

    # Vertical cut ticks at sheet top and bottom margins
    for x in set(v_cuts):
        # Bottom edge
        c.line(x, 0.04 * inch, x, 0.04 * inch + tick_len)
        # Top edge
        c.line(x, sheet_h - 0.04 * inch, x, sheet_h - 0.04 * inch - tick_len)

    # Horizontal cut ticks at sheet left and right margins
    for y in set(h_cuts):
        # Left edge
        c.line(0.04 * inch, y, 0.04 * inch + tick_len, y)
        # Right edge
        c.line(sheet_w - 0.04 * inch, y, sheet_w - 0.04 * inch - tick_len, y)

    # Registration crosshairs at center of sheet edges
    def _draw_registration_target(cx, cy):
        r = 5
        c.setLineWidth(0.3)
        c.circle(cx, cy, r, stroke=1, fill=0)
        c.line(cx - r - 3, cy, cx + r + 3, cy)
        c.line(cx, cy - r - 3, cx, cy + r + 3)

    _draw_registration_target(sheet_w / 2, 0.18 * inch)
    _draw_registration_target(sheet_w / 2, sheet_h - 0.18 * inch)
    _draw_registration_target(0.18 * inch, sheet_h / 2)
    _draw_registration_target(sheet_w - 0.18 * inch, sheet_h / 2)


# ==================== IMAGE PREPARATION ====================
def _prepare_image(
    image_path: str,
    color_mode: str,
    tmp_dir: str,
    target_aspect: float = TAROT_BLEED_ASPECT,
) -> str:
    """
    Convert card image for print output.

    - Crops to exact bleed aspect ratio (3.0 / 5.0) via center-crop so artwork
      fills the entire bleed rectangle without pillarbox/letterbox gaps.
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

    # Crop to exact bleed aspect ratio if necessary
    if target_aspect:
        w, h = img.size
        current_aspect = w / h
        if abs(current_aspect - target_aspect) > 0.005:
            if current_aspect > target_aspect:
                new_w = round(h * target_aspect)
                offset = (w - new_w) // 2
                img = img.crop((offset, 0, offset + new_w, h))
            else:
                new_h = round(w / target_aspect)
                offset = (h - new_h) // 2
                img = img.crop((0, offset, w, offset + new_h))

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
    Generate a print-ready CMYK PDF of card fronts (side A).

    Uses the same shared slot plan as the backs/duplex PDFs (see
    :mod:`ntcdg.duplex`), so fronts printed from this file register with the
    backs file. A card whose image cannot be prepared gets a placeholder
    instead of being skipped -- skipping would shift every later card and
    break front/back alignment.

    Args:
        deck: List of Card objects.
        deck_name: Name for the output file.
        sheet_size: "letter" (8.5x11), "tabloid" (11x17), "a4", or "a3".
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

    printable = [
        card for card in deck
        if card.image_path and os.path.exists(str(card.image_path))
    ]
    if not printable:
        logger.error("No cards with images found — cannot create print PDF")
        return ""

    from .duplex import create_duplex_pdfs
    written = create_duplex_pdfs(
        printable, deck_name, sheet_size, color_mode, outputs=("fronts",),
    )
    return written.get("fronts", "")


# ==================== CARD BACKS PDF ====================
def create_backs_pdf(
    num_cards: int,
    deck_name: str,
    back_image_path: str,
    sheet_size: str = "letter",
    color_mode: str = "color",
    duplex_flip: str = "long_edge",
    back_offset_mm: tuple[float, float] = (0.0, 0.0),
) -> str:
    """
    Generate a print-ready PDF of identical card backs (side B).

    Registered for ``duplex_flip``: ``long_edge`` mirrors columns,
    ``short_edge`` mirrors rows and rotates each back 180 degrees (so cut cards
    read upright when turned over sideways). For per-card backs with QR codes
    use :func:`ntcdg.duplex.create_duplex_pdfs` (``finalize_deck`` does).
    """
    if not HAS_REPORTLAB or not HAS_PILLOW:
        logger.error("reportlab and Pillow required for backs PDF")
        return ""

    if not os.path.exists(back_image_path):
        logger.error(f"Card back image not found: {back_image_path}")
        return ""

    from .duplex import create_duplex_pdfs
    written = create_duplex_pdfs(
        None, deck_name, sheet_size, color_mode, duplex_flip,
        back_image_path=back_image_path, back_offset_mm=back_offset_mm,
        outputs=("backs",), num_cards=num_cards,
    )
    return written.get("backs", "")


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
def create_booklet_pdf(deck: list[Card], deck_name: str) -> str:
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


# ==================== EXPORT BUNDLE ====================
def export_deck_bundle(deck_name: str) -> str:
    """Create a zip bundle with all deck assets for distribution.

    Bundle contents:
    - All card PNG images
    - Print PDF (if exists)
    - Backs PDF (if exists)
    - Booklet PDF (if exists)
    - Spreadsheet (if exists)
    - Deck JSON data
    """
    import zipfile

    deck = load_deck(deck_name)
    if not deck:
        print(f"Deck '{deck_name}' not found.")
        return ""

    zip_path = os.path.join(Config.OUTPUT_DIR, f"{deck_name}_BUNDLE.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Card images
        for card in deck:
            if card.image_path and os.path.exists(str(card.image_path)):
                arcname = f"images/{os.path.basename(card.image_path)}"
                zf.write(card.image_path, arcname)

        # Back image
        from .storage import load_decks_index
        meta = load_decks_index().get(deck_name, {})
        back = meta.get("back_image", "")
        if back and os.path.exists(back):
            zf.write(back, f"images/{os.path.basename(back)}")

        # PDFs and spreadsheet (exact-match so similarly named decks never leak in)
        from .storage import deck_artifact_files
        for filepath in deck_artifact_files(deck_name):
            zf.write(filepath, os.path.basename(filepath))

        # Deck JSON
        json_path = os.path.join(Config.OUTPUT_DIR, f"{deck_name}.json")
        if os.path.exists(json_path):
            zf.write(json_path, f"{deck_name}.json")

    print(f"\nExport bundle created: {zip_path}")
    logger.info(f"Bundle saved: {zip_path}")
    return zip_path


# ==================== FINALIZATION WORKFLOW ====================
def validate_print_options(sheet_size: str, color_mode: str, duplex_flip: str = "long_edge") -> None:
    """Raise ``ValueError`` with a helpful message for unsupported print options."""
    if sheet_size not in SHEET_SIZES:
        raise ValueError(
            f"Unknown sheet_size {sheet_size!r}; choose one of {sorted(SHEET_SIZES)}"
        )
    if color_mode not in COLOR_MODES:
        raise ValueError(f"Unknown color_mode {color_mode!r}; choose one of {list(COLOR_MODES)}")
    if duplex_flip not in DUPLEX_FLIPS:
        raise ValueError(
            f"Unknown duplex_flip {duplex_flip!r}; choose one of {list(DUPLEX_FLIPS)}"
        )


def finalize_deck_report(
    deck_name: str,
    sheet_size: str = "letter",
    color_mode: str = "color",
    duplex_flip: str = "long_edge",
    *,
    qr_codes: bool = True,
    public_base_url: str | None = None,
    rebase_url: bool = False,
    allow_local_url: bool = False,
    back_offset_mm: tuple[float, float] = (0.0, 0.0),
) -> dict:
    """
    Finalize a deck and return a structured report.

    Steps:
    1. Load deck and validate completeness
    2. Report errors (block) and warnings (inform)
    3. Assign the deck's stable public slug/URL (for QR codes on the backs)
    4. Render fronts, per-card backs and an interleaved DUPLEX PDF from one
       shared slot plan, registered for ``duplex_flip`` (see :mod:`ntcdg.duplex`)
    5. Generate companion booklet PDF (card-sized)
    6. Print summary

    Returns ``{"success", "error", "print_pdf", "backs_pdf", "duplex_pdf",
    "booklet_pdf", "pages", "validation": {"errors", "warnings"},
    "qr": {"enabled", "base_url", "deck_slug", "reason"}, "warnings"}``.
    Raises ``ValueError`` for unsupported sheet/color/duplex/offset options or an
    invalid ``public_base_url``.
    """
    from .duplex import create_duplex_pdfs, validate_offsets

    validate_print_options(sheet_size, color_mode, duplex_flip)
    back_offset_mm = validate_offsets(back_offset_mm)

    result: dict = {
        "success": False,
        "error": "",
        "print_pdf": "",
        "backs_pdf": "",
        "duplex_pdf": "",
        "booklet_pdf": "",
        "pages": 0,
        "validation": {"errors": [], "warnings": []},
        "qr": {"enabled": False, "base_url": "", "deck_slug": "", "reason": ""},
        "warnings": [],
    }

    deck = load_deck(deck_name)
    if not deck:
        print(f"Deck '{deck_name}' not found.")
        result["error"] = f"Deck '{deck_name}' not found"
        return result

    sheet_w, sheet_h = SHEET_SIZES[sheet_size]
    layout = _calculate_grid(sheet_w, sheet_h)

    print(f"\n{'=' * 60}")
    print(f"FINALIZING: {deck_name} ({len(deck)} cards)")
    print(f"Sheet: {sheet_size.title()} ({sheet_w}\" x {sheet_h}\")")
    print(f"Color: {color_mode.upper()} CMYK")
    print(f"Layout: {layout['cols']}x{layout['rows']} cards per sheet")
    print(f"Duplex: flip on {duplex_flip.replace('_', ' ')}")
    print(f"{'=' * 60}")

    # --- Validate ---
    report = validate_deck(deck)
    result["validation"] = {"errors": list(report["errors"]), "warnings": list(report["warnings"])}

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
        result["error"] = "Deck failed validation"
        return result

    if not report["warnings"]:
        print("\nDeck passes all completeness checks.")

    printable = sorted(
        (c for c in deck if c.image_path and os.path.exists(str(c.image_path))),
        key=lambda c: c.position or 0,
    )
    if not printable:
        print("\nNo card images found on disk -- nothing to print.")
        result["error"] = "No card images found to print"
        return result
    total_pages = math.ceil(len(printable) / layout["cards_per_page"])
    result["pages"] = total_pages

    # --- Public identity / QR codes ---
    urls: dict[int, str] = {}
    if qr_codes:
        from .public import card_urls, ensure_public_identity
        identity = ensure_public_identity(
            deck_name, public_base_url, rebase=rebase_url, allow_local=allow_local_url,
        )
        result["warnings"].extend(identity["warnings"])
        result["qr"] = {
            "enabled": identity["enabled"], "base_url": identity["base_url"],
            "deck_slug": identity["slug"], "reason": identity["reason"],
        }
        if identity["enabled"]:
            urls = card_urls(identity, printable)
            print(f"QR codes: {identity['base_url']} (deck slug {identity['slug']})")
        else:
            print(f"QR codes skipped: {identity['reason']}")
            result["warnings"].append(identity["reason"])
        for w in identity["warnings"]:
            print(f"   ! {w}")
    else:
        result["qr"]["reason"] = "QR codes disabled"

    # --- Fronts, per-card backs and interleaved duplex, from one slot plan ---
    from .storage import load_decks_index
    back_image = load_decks_index().get(deck_name, {}).get("back_image", "")
    if not (back_image and os.path.exists(back_image)):
        back_image = ""
        print("No card back image -- using the generated default back design.")
        print("   (Use --set-back DeckName --back-prompt '...' to generate one)")

    print(f"\nGenerating print PDFs ({len(printable)} cards -> {total_pages} sheets, 2-sided)...")
    written = create_duplex_pdfs(
        printable, deck_name, sheet_size, color_mode, duplex_flip,
        back_image_path=back_image or None, card_urls=urls, back_offset_mm=back_offset_mm,
    )
    pdf_path = written.get("fronts", "")
    backs_path = written.get("backs", "")
    duplex_path = written.get("duplex", "")

    # --- Generate companion booklet ---
    print("Generating companion booklet...")
    booklet_path = create_booklet_pdf(deck, deck_name)

    result.update(
        print_pdf=pdf_path or "",
        backs_pdf=backs_path or "",
        duplex_pdf=duplex_path or "",
        booklet_pdf=booklet_path or "",
        success=bool(pdf_path and duplex_path),
    )
    if not result["success"]:
        result["error"] = "Print PDFs could not be generated (are reportlab and Pillow installed?)"

    if result["success"]:
        print(f"\n{'=' * 60}")
        print(f"FINALIZED: {deck_name}")
        print(f"   Duplex PDF: {duplex_path}  <- print this 2-sided, flip on "
              f"{duplex_flip.replace('_', ' ')}, 100% scale")
        print(f"   Fronts PDF: {pdf_path}")
        print(f"   Backs PDF:  {backs_path}")
        if booklet_path:
            print(f"   Booklet:    {booklet_path}")
        print(f"   Sheets: {total_pages}")
        print(f"   Card trim: {CARD_TRIM_W}\" x {CARD_TRIM_H}\"")
        print(f"   Bleed: {BLEED}\" per side")
        print(f"   Color space: CMYK ({color_mode})")
        print(f"{'=' * 60}\n")

    return result


def finalize_deck(
    deck_name: str,
    sheet_size: str = "letter",
    color_mode: str = "color",
    duplex_flip: str = "long_edge",
    **kwargs,
) -> str:
    """Finalize a deck (see :func:`finalize_deck_report`).

    Returns path to the fronts print PDF, or "" on failure.
    Raises ``ValueError`` for unsupported sheet/color/duplex options.
    """
    return finalize_deck_report(
        deck_name, sheet_size, color_mode, duplex_flip, **kwargs,
    )["print_pdf"]
