"""Tests for storage module: deck save/load roundtrip and spreadsheet export."""

import json
from unittest.mock import patch

from ntcdg.config import Config
from ntcdg.models import Card
from ntcdg.storage import is_novel, load_deck, save_deck


class TestDeckRoundtrip:
    """Test saving and loading decks preserves Card data."""

    def test_save_and_load_roundtrip(self, tmp_path):
        deck = [
            Card(position=1, title="The Fool", card_type="Major Arcana", arcana_number=0,
                 symbols=["dog", "cliff"], description="A figure at the edge"),
            Card(position=2, title="Ace of Wands", card_type="Minor Arcana",
                 suit="Wands", rank="Ace", symbols=["wand", "fire"]),
        ]

        with patch.object(Config, "OUTPUT_DIR", str(tmp_path)):
            save_deck(deck, "test_deck")
            loaded = load_deck("test_deck")

        assert len(loaded) == 2
        assert loaded[0].title == "The Fool"
        assert loaded[0].card_type == "Major Arcana"
        assert loaded[0].symbols == ["dog", "cliff"]
        assert loaded[0].description == "A figure at the edge"
        assert loaded[1].title == "Ace of Wands"
        assert loaded[1].suit == "Wands"
        assert loaded[1].rank == "Ace"

    def test_load_nonexistent_deck(self, tmp_path):
        with patch.object(Config, "OUTPUT_DIR", str(tmp_path)):
            result = load_deck("nonexistent")
        assert result == []

    def test_save_creates_json_file(self, tmp_path):
        deck = [Card(position=1, title="Test", card_type="Major Arcana")]

        with patch.object(Config, "OUTPUT_DIR", str(tmp_path)):
            save_deck(deck, "test_deck")

        json_path = tmp_path / "test_deck.json"
        assert json_path.exists()

        with open(json_path) as f:
            raw = json.load(f)
        assert len(raw) == 1
        assert raw[0]["title"] == "Test"
        assert raw[0]["type"] == "Major Arcana"  # key should be "type" not "card_type"

    def test_backward_compat_with_raw_dicts(self, tmp_path):
        """Verify we can load JSON written by the old dict-based code."""
        raw_data = [
            {
                "position": 1,
                "title": "The Neon Origin",
                "type": "Major Arcana",
                "suit": None,
                "rank": None,
                "symbols": ["glowing crown", "fractal patterns"],
                "layout": "dynamic central vortex spiral",
                "image_path": "/img/001.png",
            }
        ]
        json_path = tmp_path / "legacy_deck.json"
        with open(json_path, "w") as f:
            json.dump(raw_data, f)

        with patch.object(Config, "OUTPUT_DIR", str(tmp_path)):
            loaded = load_deck("legacy_deck")

        assert len(loaded) == 1
        assert loaded[0].title == "The Neon Origin"
        assert loaded[0].card_type == "Major Arcana"
        assert loaded[0].image_path == "/img/001.png"


class TestNovelty:
    """Test card novelty checking."""

    def test_novel_card(self):
        card = Card(symbols=["dog", "moon", "star", "crown"])
        history = {"cards": [{"symbols": ["flower", "path", "water"]}]}
        assert is_novel(card, history) is True

    def test_duplicate_card(self):
        card = Card(symbols=["dog", "moon", "star", "crown"])
        history = {"cards": [{"symbols": ["dog", "moon", "star", "crown"]}]}
        assert is_novel(card, history) is False

    def test_empty_history(self):
        card = Card(symbols=["dog", "moon"])
        history = {"cards": []}
        assert is_novel(card, history) is True
