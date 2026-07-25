"""Tests for card editing, resume, and export bundle features."""

import os
import zipfile

from ntcdg.models import Card


class TestEditCardField:
    """Test manual card field editing."""

    def test_edit_title(self, tmp_path, monkeypatch):
        """Should update a card's title and save the deck."""
        from ntcdg.storage import edit_card_field, load_deck, save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        deck = [Card(position=1, title="Old Title", card_type="Major Arcana")]
        save_deck(deck, "TestDeck")

        result = edit_card_field("TestDeck", 1, "title", "New Title")
        assert result is True

        reloaded = load_deck("TestDeck")
        assert reloaded[0].title == "New Title"

    def test_edit_description(self, tmp_path, monkeypatch):
        """Should update a card's description."""
        from ntcdg.storage import edit_card_field, load_deck, save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        deck = [Card(position=3, title="Test", description="old")]
        save_deck(deck, "TestDeck")

        result = edit_card_field("TestDeck", 3, "description", "new description")
        assert result is True

        reloaded = load_deck("TestDeck")
        assert reloaded[0].description == "new description"

    def test_edit_invalid_field(self, tmp_path, monkeypatch):
        """Invalid field names should be rejected."""
        from ntcdg.storage import edit_card_field, save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        deck = [Card(position=1, title="Test")]
        save_deck(deck, "TestDeck")

        result = edit_card_field("TestDeck", 1, "image_path", "/hack")
        assert result is False

    def test_edit_missing_card(self, tmp_path, monkeypatch):
        """Editing a nonexistent card should fail gracefully."""
        from ntcdg.storage import edit_card_field, save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        deck = [Card(position=1, title="Test")]
        save_deck(deck, "TestDeck")

        result = edit_card_field("TestDeck", 99, "title", "Nope")
        assert result is False

    def test_edit_missing_deck(self, tmp_path, monkeypatch):
        """Editing in a nonexistent deck should fail gracefully."""
        from ntcdg.storage import edit_card_field

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        result = edit_card_field("NoDeck", 1, "title", "Nope")
        assert result is False


class TestExportBundle:
    """Test zip bundle export."""

    def test_bundle_created(self, tmp_path, monkeypatch):
        """Export should create a zip with deck assets."""
        from PIL import Image as PILImage

        from ntcdg.finalize import export_deck_bundle
        from ntcdg.storage import save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr("ntcdg.config.Config.IMAGES_DIR", str(tmp_path / "images"))
        monkeypatch.setattr("ntcdg.finalize.Config.OUTPUT_DIR", str(tmp_path))

        # Create a card with an image
        os.makedirs(tmp_path / "images", exist_ok=True)
        img = PILImage.new("RGB", (100, 150), color=(50, 50, 50))
        img_path = str(tmp_path / "images" / "card_001.png")
        img.save(img_path)

        deck = [Card(position=1, title="Test Card", image_path=img_path)]
        save_deck(deck, "BundleTest")

        zip_path = export_deck_bundle("BundleTest")
        assert zip_path
        assert os.path.exists(zip_path)
        assert zip_path.endswith("_BUNDLE.zip")

        # Verify zip contents
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert any("card_001.png" in n for n in names)
            assert any("BundleTest.json" in n for n in names)

    def test_bundle_missing_deck(self, tmp_path, monkeypatch):
        """Export of nonexistent deck should return empty string."""
        from ntcdg.finalize import export_deck_bundle

        monkeypatch.setattr("ntcdg.finalize.Config.OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        result = export_deck_bundle("NoDeck")
        assert result == ""
