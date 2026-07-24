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


# ==================== FINALIZATION WORKFLOW ====================
def finalize_deck(
    deck_name: str,
    sheet_size: str = "letter",
    color_mode: str = "color",
) -> str:
    """
    Finalize a deck: validate completeness and generate print-ready PDF.

    Steps:
    1. Load deck and validate completeness
    2. Report errors (block) and warnings (inform)
    3. Generate CMYK print PDF with crop marks
    4. Print summary

    Returns path to the print PDF, or "" on failure.
    """
    deck = load_deck(deck_name)
    if not deck:
        print(f"❌ Deck '{deck_name}' not found.")
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
        print(f"\n⚠  {len(report['warnings'])} warning(s):")
        shown = report["warnings"][:10]
        for w in shown:
            print(f"   ◦ {w}")
        if len(report["warnings"]) > 10:
            print(f"   ... and {len(report['warnings']) - 10} more")

    if report["errors"]:
        print(f"\n✗  {len(report['errors'])} error(s) — these must be fixed:")
        for e in report["errors"]:
            print(f"   ✗ {e}")
        print("\n❌ Cannot finalize. Fix errors above first.")
        return ""

    if not report["warnings"]:
        print("\n✅ Deck passes all completeness checks.")

    # --- Generate print PDF ---
    printable = [c for c in deck if c.image_path and os.path.exists(str(c.image_path))]
    total_pages = math.ceil(len(printable) / layout["cards_per_page"])

    print(f"\n📄 Generating print PDF ({len(printable)} cards → {total_pages} pages)...")
    pdf_path = create_print_pdf(deck, deck_name, sheet_size, color_mode)

    if pdf_path:
        print(f"\n{'=' * 60}")
        print(f"✅ FINALIZED: {deck_name}")
        print(f"   Print PDF: {pdf_path}")
        print(f"   Pages: {total_pages}")
        print(f"   Card trim: {CARD_TRIM_W}\" x {CARD_TRIM_H}\"")
        print(f"   Bleed: {BLEED}\" per side")
        print(f"   Color space: CMYK ({color_mode})")
        print(f"{'=' * 60}\n")

    return pdf_path
