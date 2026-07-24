"""Post-processing text overlay for card images.

Composites the card number (top) and title (bottom) onto generated
card artwork using gradient banners and configurable fonts. This avoids
relying on AI text rendering (which is unreliable) and guarantees
uniform placement across the entire deck.
"""

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
    draw: "ImageDraw.Draw",
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
