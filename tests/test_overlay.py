"""Tests for the overlay module: Roman numerals, card number text, and image overlay."""

from PIL import Image

from ntcdg.models import Card
from ntcdg.overlay import get_card_number_text, overlay_card_text, to_roman


class TestRomanNumerals:
    """Test integer → Roman numeral conversion."""

    def test_zero(self):
        assert to_roman(0) == "0"

    def test_basic(self):
        assert to_roman(1) == "I"
        assert to_roman(4) == "IV"
        assert to_roman(5) == "V"
        assert to_roman(9) == "IX"
        assert to_roman(10) == "X"
        assert to_roman(14) == "XIV"
        assert to_roman(21) == "XXI"

    def test_major_arcana_range(self):
        # All 22 Major Arcana numbers should produce valid Roman numerals
        results = [to_roman(i) for i in range(22)]
        assert results[0] == "0"       # The Fool
        assert results[1] == "I"       # The Magician
        assert results[13] == "XIII"   # Death
        assert results[21] == "XXI"    # The World


class TestGetCardNumberText:
    """Test card number/designation logic."""

    def test_major_arcana(self):
        card = Card(card_type="Major Arcana", arcana_number=0)
        assert get_card_number_text(card) == "0"

        card = Card(card_type="Major Arcana", arcana_number=14)
        assert get_card_number_text(card) == "XIV"

    def test_minor_arcana_pip(self):
        card = Card(card_type="Minor Arcana", rank=7)
        assert get_card_number_text(card) == "VII"

    def test_minor_arcana_ace(self):
        card = Card(card_type="Minor Arcana", rank="Ace")
        assert get_card_number_text(card) == "I"

    def test_minor_arcana_court(self):
        card = Card(card_type="Minor Arcana", rank="Queen")
        assert get_card_number_text(card) == "QUEEN"

        card = Card(card_type="Minor Arcana", rank="Knight")
        assert get_card_number_text(card) == "KNIGHT"

    def test_fallback_to_position(self):
        card = Card(position=42)
        assert get_card_number_text(card) == "42"


class TestOverlayCardText:
    """Test image overlay compositing."""

    def test_overlay_modifies_image(self, tmp_path):
        # Create a test image
        img = Image.new("RGB", (512, 768), color=(100, 50, 150))
        img_path = str(tmp_path / "test_card.png")
        img.save(img_path)

        # Apply overlay
        result = overlay_card_text(img_path, "The Fool", "0")
        assert result == img_path

        # Verify the image was modified (top-left should be darker from banner)
        modified = Image.open(img_path)
        assert modified.size == (512, 768)
        top_pixel = modified.getpixel((256, 5))  # Near top center
        # The banner should have darkened the pixel
        assert top_pixel[0] < 100  # R should be darker
        assert top_pixel[1] < 50   # G should be darker

    def test_overlay_with_tall_image(self, tmp_path):
        img = Image.new("RGB", (1024, 1536), color=(200, 200, 200))
        img_path = str(tmp_path / "tall_card.png")
        img.save(img_path)

        result = overlay_card_text(img_path, "Queen of Swords", "QUEEN")
        assert result == img_path

        modified = Image.open(img_path)
        assert modified.size == (1024, 1536)

    def test_overlay_nonexistent_image(self, tmp_path):
        result = overlay_card_text("/nonexistent/path.png", "Test", "I")
        assert result == "/nonexistent/path.png"  # Returns path unchanged
