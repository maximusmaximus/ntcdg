"""Tests for the finalize module: validation, layout calculation, and PDF generation."""

import os

from ntcdg.finalize import (
    CARD_BLEED_H,
    CARD_BLEED_W,
    CELL_GAP,
    SHEET_MARGIN,
    SHEET_SIZES,
    _calculate_grid,
    validate_deck,
)
from ntcdg.models import Card


class TestValidation:
    """Test deck completeness validation."""

    def test_valid_deck(self):
        deck = [
            Card(
                position=1, title="The Fool",
                image_path=__file__,  # use this test file as a stand-in
                description="A fool walks",
                upright_interpretation="New beginnings",
                reversed_interpretation="Recklessness",
            ),
        ]
        report = validate_deck(deck)
        assert len(report["errors"]) == 0
        assert len(report["warnings"]) == 0

    def test_missing_title(self):
        deck = [Card(position=1, image_path=__file__)]
        report = validate_deck(deck)
        assert any("missing title" in e for e in report["errors"])

    def test_missing_image(self):
        deck = [Card(position=1, title="Test")]
        report = validate_deck(deck)
        assert any("no image generated" in e for e in report["errors"])

    def test_image_file_missing(self):
        deck = [Card(position=1, title="Test", image_path="/nonexistent/card.png")]
        report = validate_deck(deck)
        assert any("image file missing" in e for e in report["errors"])

    def test_missing_meanings_are_warnings(self):
        deck = [Card(position=1, title="Test", image_path=__file__, description="desc")]
        report = validate_deck(deck)
        assert len(report["errors"]) == 0
        assert any("upright" in w for w in report["warnings"])
        assert any("reversed" in w for w in report["warnings"])


class TestLayoutCalculation:
    """Test card grid layout math."""

    def test_letter_layout(self):
        """Letter sheet (8.5x11) should fit 2x2 = 4 cards."""
        layout = _calculate_grid(8.5, 11.0)
        assert layout["cols"] == 2
        assert layout["rows"] == 2
        assert layout["cards_per_page"] == 4

    def test_tabloid_layout(self):
        """Tabloid sheet (11x17) should fit 3x3 = 9 cards."""
        layout = _calculate_grid(11.0, 17.0)
        assert layout["cols"] == 3
        assert layout["rows"] == 3
        assert layout["cards_per_page"] == 9

    def test_grid_fits_within_sheet(self):
        """Verify the calculated grid doesn't exceed sheet bounds."""
        for name, (w, h) in SHEET_SIZES.items():
            layout = _calculate_grid(w, h)
            grid_w = layout["cols"] * CARD_BLEED_W + max(0, layout["cols"] - 1) * CELL_GAP
            grid_h = layout["rows"] * CARD_BLEED_H + max(0, layout["rows"] - 1) * CELL_GAP
            usable_w = w - 2 * SHEET_MARGIN
            usable_h = h - 2 * SHEET_MARGIN
            assert grid_w <= usable_w + 0.001, f"{name}: grid too wide"
            assert grid_h <= usable_h + 0.001, f"{name}: grid too tall"

    def test_start_position_centers_grid(self):
        """Start position should center the grid on the sheet."""
        layout = _calculate_grid(11.0, 17.0)
        grid_w = layout["cols"] * CARD_BLEED_W + max(0, layout["cols"] - 1) * CELL_GAP
        expected_start_x = (11.0 - grid_w) / 2
        assert abs(layout["start_x"] - expected_start_x) < 0.001


class TestPrintPdf:
    """Test print PDF generation (integration)."""

    def test_create_print_pdf_with_images(self, tmp_path, monkeypatch):
        """Generate a small print PDF with real test images."""
        from PIL import Image as PILImage

        from ntcdg.finalize import create_print_pdf

        # Point output to tmp
        monkeypatch.setattr("ntcdg.finalize.Config.OUTPUT_DIR", str(tmp_path))

        # Create fake card images
        cards = []
        for i in range(3):
            img = PILImage.new("RGB", (300, 450), color=(100 + i * 50, 50, 150))
            img_path = str(tmp_path / f"card_{i}.png")
            img.save(img_path)
            cards.append(Card(position=i + 1, title=f"Card {i+1}", image_path=img_path))

        pdf_path = create_print_pdf(cards, "TestDeck", sheet_size="letter", color_mode="color")
        assert pdf_path
        assert os.path.exists(pdf_path)
        assert pdf_path.endswith(".pdf")
        assert "PRINT_letter_color" in pdf_path

    def test_create_print_pdf_bw(self, tmp_path, monkeypatch):
        """B&W mode should also produce a valid PDF."""
        from PIL import Image as PILImage

        from ntcdg.finalize import create_print_pdf

        monkeypatch.setattr("ntcdg.finalize.Config.OUTPUT_DIR", str(tmp_path))

        img = PILImage.new("RGB", (300, 450), color=(200, 100, 50))
        img_path = str(tmp_path / "card_bw.png")
        img.save(img_path)
        cards = [Card(position=1, title="BW Test", image_path=img_path)]

        pdf_path = create_print_pdf(cards, "BWDeck", sheet_size="tabloid", color_mode="bw")
        assert pdf_path
        assert os.path.exists(pdf_path)
        assert "PRINT_tabloid_bw" in pdf_path

    def test_no_images_returns_empty(self, tmp_path, monkeypatch):
        """Deck with no images should return empty string."""
        from ntcdg.finalize import create_print_pdf

        monkeypatch.setattr("ntcdg.finalize.Config.OUTPUT_DIR", str(tmp_path))
        cards = [Card(position=1, title="No Image")]
        result = create_print_pdf(cards, "EmptyDeck")
        assert result == ""


class TestBookletPdf:
    """Test companion booklet PDF generation."""

    def test_booklet_with_card_data(self, tmp_path, monkeypatch):
        """Booklet should generate with card descriptions."""
        from ntcdg.finalize import create_booklet_pdf

        monkeypatch.setattr("ntcdg.finalize.Config.OUTPUT_DIR", str(tmp_path))

        cards = [
            Card(
                position=1, title="The Fool", card_type="Major Arcana",
                arcana_number=0, description="A young traveler steps forward.",
                upright_interpretation="New beginnings and adventure.",
                reversed_interpretation="Recklessness and poor judgment.",
            ),
            Card(
                position=23, title="Ace of Wands", card_type="Minor Arcana",
                suit="Wands", rank="Ace",
                description="A hand holds a sprouting wand.",
                upright_interpretation="Inspiration and new opportunities.",
                reversed_interpretation="Delays and lack of direction.",
            ),
        ]

        pdf_path = create_booklet_pdf(cards, "TestBooklet")
        assert pdf_path
        assert os.path.exists(pdf_path)
        assert "BOOKLET" in pdf_path

    def test_booklet_empty_deck(self, tmp_path, monkeypatch):
        """Booklet should handle an empty deck gracefully."""
        from ntcdg.finalize import create_booklet_pdf

        monkeypatch.setattr("ntcdg.finalize.Config.OUTPUT_DIR", str(tmp_path))
        pdf_path = create_booklet_pdf([], "EmptyBooklet")
        assert pdf_path  # Still generates (cover + credits pages)
        assert os.path.exists(pdf_path)
