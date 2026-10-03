"""Post-processing text overlay for card images.

Composites the card number (top) and title (bottom) onto generated
card artwork using gradient banners and configurable fonts. This avoids
relying on AI text rendering (which is unreliable) and guarantees
uniform placement across the entire deck.
"""

from __future__ import annotations

import os

from .config import logger

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


# System font paths tried in order (cross-platform)
_FONT_SEARCH_PATHS = [
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/Library/Fonts/Georgia Bold.ttf",
    # Windows
    "C:/Windows/Fonts/timesbd.ttf",
    "C:/Windows/Fonts/georgiab.ttf",
]

# Default text color — warm gold that works on dark and busy backgrounds
DEFAULT_TEXT_COLOR = (232, 213, 163, 255)


# ==================== HELPERS ====================
def to_roman(n: int) -> str:
    """Convert integer to Roman numeral string. 0 returns '0'."""
    if n == 0:
        return "0"
    vals = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    result = ""
    for val, numeral in vals:
        while n >= val:
            result += numeral
            n -= val
    return result


def get_card_number_text(card) -> str:
    """
    Get the display number/designation for a card.

    - Major Arcana: Roman numeral (0, I, II ... XXI)
    - Minor Arcana pip: Roman numeral of rank (I for Ace, II, III ... X)
    - Minor Arcana court: rank name (PAGE, KNIGHT, QUEEN, KING)
    """
    if card.card_type == "Major Arcana" and card.arcana_number is not None:
        return to_roman(card.arcana_number)
    if card.card_type == "Minor Arcana" and card.rank is not None:
        if isinstance(card.rank, int):
            return to_roman(card.rank)
        if str(card.rank).upper() == "ACE":
            return "I"
        return str(card.rank).upper()
    return str(card.position)


def _find_font(font_path: str | None = None, size: int = 40):
    """Find and load a TrueType font. Tries custom → system → Pillow default."""
    if font_path and os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)

    for path in _FONT_SEARCH_PATHS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)

    logger.warning("No TrueType fonts found — using Pillow default (text may look rough)")
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Older Pillow versions don't accept size= in load_default
        return ImageFont.load_default()


def _draw_text_with_shadow(
    draw: ImageDraw.Draw,
    text: str,
    position: tuple,
    font,
    fill: tuple = DEFAULT_TEXT_COLOR,
    shadow_color: tuple = (0, 0, 0, 200),
    shadow_offset: int = 2,
):
    """Draw text centered at position with a drop shadow for depth."""
    x, y = position
    # Shadow
    draw.text(
        (x + shadow_offset, y + shadow_offset), text,
        font=font, fill=shadow_color, anchor="mm",
    )
    # Main text
    draw.text((x, y), text, font=font, fill=fill, anchor="mm")


# ==================== MAIN OVERLAY ====================
def overlay_card_text(
    image_path: str,
    title: str,
    number_text: str,
    font_path: str = None,
    text_color: tuple = DEFAULT_TEXT_COLOR,
) -> str:
    """
    DEPRECATED: Use compose_card() instead.

    Overlay title and number onto a card image with gradient banners.

    Layout:
    ┌──────────────────────┐
    │ ▓▓▓  NUMBER  ▓▓▓▓▓▓ │  ← gradient fading down
    │                      │
    │     (card art)        │
    │                      │
    │ ▓▓▓  TITLE   ▓▓▓▓▓▓ │  ← gradient fading up
    └──────────────────────┘

    Modifies image in-place and returns the path.
    """
    if not HAS_PILLOW:
        logger.warning("Pillow not installed — skipping text overlay (pip install Pillow)")
        return image_path

    if not os.path.exists(image_path):
        logger.warning(f"Image not found for overlay: {image_path}")
        return image_path

    img = Image.open(image_path).convert("RGBA")
    width, height = img.size

    # Scale font sizes to image dimensions
    number_font_size = max(20, int(height * 0.045))
    title_font_size = max(16, int(height * 0.032))
    number_font = _find_font(font_path, size=number_font_size)
    title_font = _find_font(font_path, size=title_font_size)

    shadow_offset = max(2, int(height * 0.002))

    # Create transparent overlay
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    banner_height = int(height * 0.08)

    # Top gradient banner (dark → transparent going down)
    for y in range(banner_height):
        alpha = int(170 * (1 - y / banner_height) ** 1.5)
        draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    # Bottom gradient banner (transparent → dark going down)
    for y in range(height - banner_height, height):
        progress = (y - (height - banner_height)) / banner_height
        alpha = int(170 * progress**1.5)
        draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    # Number at top center
    _draw_text_with_shadow(
        draw, number_text,
        position=(width // 2, int(banner_height * 0.5)),
        font=number_font, fill=text_color,
        shadow_offset=shadow_offset,
    )

    # Title at bottom center
    _draw_text_with_shadow(
        draw, title.upper(),
        position=(width // 2, height - int(banner_height * 0.5)),
        font=title_font, fill=text_color,
        shadow_offset=shadow_offset,
    )

    # Composite and save
    result = Image.alpha_composite(img, overlay).convert("RGB")
    result.save(image_path, quality=95)

    logger.debug(f"Text overlay applied: {number_text} / {title} → {image_path}")
    return image_path


# ==================== CARD COMPOSITION ====================

def _draw_corner_ornament(draw, x, y, size, color, corner):
    """Draw art deco style corner accents."""
    thickness = 2
    if corner == "top_left":
        draw.line([(x, y + size), (x, y), (x + size, y)], fill=color, width=thickness)
        draw.ellipse([(x - 3, y - 3), (x + 3, y + 3)], fill=color)
    elif corner == "top_right":
        draw.line([(x - size, y), (x, y), (x, y + size)], fill=color, width=thickness)
        draw.ellipse([(x - 3, y - 3), (x + 3, y + 3)], fill=color)
    elif corner == "bottom_left":
        draw.line([(x, y - size), (x, y), (x + size, y)], fill=color, width=thickness)
        draw.ellipse([(x - 3, y - 3), (x + 3, y + 3)], fill=color)
    elif corner == "bottom_right":
        draw.line([(x - size, y), (x, y), (x, y - size)], fill=color, width=thickness)
        draw.ellipse([(x - 3, y - 3), (x + 3, y + 3)], fill=color)


def _draw_separator(draw, y, width, color):
    """Draw decorative line between art and title."""
    center_x = width // 2
    draw.line([(60, y), (width - 60, y)], fill=color, width=1)
    # Draw small diamond in center
    draw.polygon([
        (center_x, y - 4), (center_x + 4, y),
        (center_x, y + 4), (center_x - 4, y)
    ], fill=color)


def _crop_to_fill(img, target_w, target_h):
    """Crop and resize artwork to fill frame area."""
    img_w, img_h = img.size
    img_aspect = img_w / img_h
    target_aspect = target_w / target_h

    if img_aspect > target_aspect:
        # Image is wider than target, crop width
        new_w = int(img_h * target_aspect)
        offset = (img_w - new_w) // 2
        img = img.crop((offset, 0, offset + new_w, img_h))
    elif img_aspect < target_aspect:
        # Image is taller than target, crop height
        new_h = int(img_w / target_aspect)
        offset = (img_h - new_h) // 2
        img = img.crop((0, offset, img_w, offset + new_h))

    # Fallback to LANCZOS directly if available, or just resize
    resample = Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS
    return img.resize((target_w, target_h), resample)

def compose_card(
    image_path: str,
    title: str,
    card_number: str = "",
    card_type: str = "",
    font_path: str = "",
    frame_color: tuple = (200, 180, 130),  # warm gold
    bg_color: tuple = (10, 10, 10),  # near black
    text_color: tuple = (212, 195, 150),  # gold text
    canvas_size: tuple[int, int] = (768, 1280),  # Standard 3:5 tarot bleed ratio
) -> None:
    """Compose a framed tarot card with decorative border and title.

    Modifies the image file in-place, adding an art deco style frame,
    corner ornaments, and a title panel. The layout strictly observes
    standard tarot card dimensions (2.75" x 4.75" trim inside 3.0" x 5.0" bleed)
    with safe zone margins so cutting along crop marks never clips the borders.
    """
    if not HAS_PILLOW:
        logger.warning("Pillow not installed — skipping card composition")
        return

    if not os.path.exists(image_path):
        logger.warning(f"Image not found for composition: {image_path}")
        return

    # Base canvas (768x1280 standard tarot 3:5 bleed ratio)
    canvas_w, canvas_h = canvas_size
    canvas = Image.new("RGB", (canvas_w, canvas_h), bg_color)
    draw = ImageDraw.Draw(canvas)

    # Bleed calculation (0.125" bleed per side on 3.0" card = ~4.17% of width)
    bleed_px = round(canvas_w * (0.125 / 3.0))  # 32px on 768w canvas

    # Outer frame is drawn inside the safe area (16px inside the trim cut line)
    frame_margin = bleed_px + 16
    draw.rectangle(
        [frame_margin, frame_margin, canvas_w - frame_margin - 1, canvas_h - frame_margin - 1],
        outline=frame_color, width=2,
    )

    # Inner border line (10px inside outer frame)
    inner_margin = frame_margin + 10
    inner_color = (160, 140, 100)
    draw.rectangle([
        inner_margin, inner_margin,
        canvas_w - inner_margin - 1, canvas_h - inner_margin - 1
    ], outline=inner_color, width=1)

    # Corner ornaments inside inner border
    ornament_size = 10
    _draw_corner_ornament(draw, inner_margin + 4, inner_margin + 4, ornament_size, inner_color, "top_left")
    _draw_corner_ornament(
        draw, canvas_w - inner_margin - 5, inner_margin + 4,
        ornament_size, inner_color, "top_right"
    )
    _draw_corner_ornament(
        draw, inner_margin + 4, canvas_h - inner_margin - 5,
        ornament_size, inner_color, "bottom_left"
    )
    _draw_corner_ornament(
        draw, canvas_w - inner_margin - 5, canvas_h - inner_margin - 5,
        ornament_size, inner_color, "bottom_right"
    )

    # Artwork area inside the frame
    art_x = inner_margin + 4
    art_y = inner_margin + 4
    title_height = int(canvas_h * 0.086)  # ~110px on 1280h
    art_w = canvas_w - 2 * art_x
    art_h = canvas_h - art_y - frame_margin - 12 - title_height

    # Load and resize artwork to fill art box
    img = Image.open(image_path).convert("RGB")
    art_img = _crop_to_fill(img, art_w, art_h)
    canvas.paste(art_img, (art_x, art_y))

    # Inner border around artwork itself
    draw.rectangle([art_x - 1, art_y - 1, art_x + art_w, art_y + art_h], outline=inner_color, width=1)

    # Decorative separator between artwork and title panel
    separator_y = art_y + art_h + 14
    _draw_separator(draw, separator_y, canvas_w, inner_color)

    # Title panel text
    title_font_size = max(22, int(canvas_h * 0.025))
    number_font_size = max(14, int(canvas_h * 0.016))
    title_font = _find_font(font_path, size=title_font_size)
    number_font = _find_font(font_path, size=number_font_size)

    # Draw Title
    title_y = separator_y + int(title_height * 0.32)
    _draw_text_with_shadow(
        draw, title.upper(),
        position=(canvas_w // 2, title_y),
        font=title_font, fill=text_color,
        shadow_offset=2,
    )

    # Draw Number/Type
    number_color = (160, 145, 110)
    subtitle = ""
    if card_number:
        subtitle += str(card_number)
    if subtitle and card_type:
        subtitle += " - "
    if card_type:
        subtitle += card_type

    _draw_text_with_shadow(
        draw, subtitle.upper(),
        position=(canvas_w // 2, title_y + int(title_height * 0.32)),
        font=number_font, fill=number_color,
        shadow_offset=1,
    )

    # Save
    canvas.save(image_path, quality=95)
    logger.debug(f"Card composed: {title} → {image_path}")
