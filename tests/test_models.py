"""Tests for the Card data model."""

from ntcdg.generator import build_canonical_deck
from ntcdg.models import Card


class TestCard:
    """Test Card dataclass serialization and methods."""

    def test_to_dict_omits_none(self):
        card = Card(position=1, title="The Fool", card_type="Major Arcana")
        d = card.to_dict()
        assert d["position"] == 1
        assert d["title"] == "The Fool"
        assert d["type"] == "Major Arcana"  # mapped from card_type
        assert "suit" not in d  # None should be omitted
        assert "image_path" not in d

    def test_to_dict_type_mapping(self):
        card = Card(position=1, title="Test", card_type="Minor Arcana")
        d = card.to_dict()
        assert "type" in d
        assert "card_type" not in d

    def test_from_dict_type_mapping(self):
        data = {"position": 5, "title": "5 of Cups", "type": "Minor Arcana", "suit": "Cups"}
        card = Card.from_dict(data)
        assert card.card_type == "Minor Arcana"
        assert card.suit == "Cups"
        assert card.position == 5

    def test_from_dict_ignores_unknowns(self):
        data = {"position": 1, "title": "Test", "type": "Major Arcana", "unknown_field": "value"}
        card = Card.from_dict(data)
        assert card.position == 1
        assert not hasattr(card, "unknown_field")

    def test_roundtrip(self):
        original = Card(
            position=3, title="Queen of Swords", card_type="Minor Arcana",
            suit="Swords", rank="Queen", symbols=["sword", "crown"],
            description="A wise queen", image_path="/img/003.png",
        )
        d = original.to_dict()
        restored = Card.from_dict(d)
        assert restored.position == original.position
        assert restored.title == original.title
        assert restored.card_type == original.card_type
        assert restored.symbols == original.symbols
        assert restored.image_path == original.image_path

    def test_update(self):
        card = Card(position=1, title="The Fool", card_type="Major Arcana")
        card.update({
            "venice_title": "The Cosmic Fool",
            "description": "A figure at the edge",
            "image_path": "/img/001.png",
        })
        assert card.venice_title == "The Cosmic Fool"
        assert card.description == "A figure at the edge"
        assert card.image_path == "/img/001.png"

    def test_update_type_mapping(self):
        card = Card(position=1, title="Test", card_type="Major Arcana")
        card.update({"type": "Minor Arcana"})
        assert card.card_type == "Minor Arcana"

    def test_display_title_priority(self):
        card = Card(title="The Fool")
        assert card.display_title() == "The Fool"

        card.new_title = "The Neon Fool"
        assert card.display_title() == "The Neon Fool"

        card.venice_title = "The Cosmic Fool"
        assert card.display_title() == "The Cosmic Fool"


class TestCanonicalDeck:
    """Test canonical deck building."""

    def test_standard_78(self):
        deck = build_canonical_deck(78)
        assert len(deck) == 78
        titles = [c["title"] for c in deck]
        assert len(set(titles)) == 78  # All unique

    def test_major_arcana_count(self):
        deck = build_canonical_deck(78)
        majors = [c for c in deck if c["type"] == "Major Arcana"]
        assert len(majors) == 22

    def test_minor_arcana_count(self):
        deck = build_canonical_deck(78)
        minors = [c for c in deck if c["type"] == "Minor Arcana"]
        assert len(minors) == 56

    def test_all_suits_present(self):
        deck = build_canonical_deck(78)
        suits = {c["suit"] for c in deck if c["suit"]}
        assert suits == {"Wands", "Cups", "Swords", "Pentacles"}

    def test_subset_preserves_majors(self):
        deck = build_canonical_deck(30)
        assert len(deck) == 30
        majors = [c for c in deck if c["type"] == "Major Arcana"]
        assert len(majors) == 22  # All Major Arcana preserved

    def test_small_deck(self):
        deck = build_canonical_deck(5)
        assert len(deck) == 5
        # Should be first 5 Major Arcana
        assert deck[0]["title"] == "The Fool"
        assert deck[4]["title"] == "The Emperor"

    def test_oversized_deck(self):
        deck = build_canonical_deck(100)
        assert len(deck) == 100

    def test_ace_naming(self):
        deck = build_canonical_deck(78)
        aces = [c for c in deck if c.get("rank") == "Ace"]
        assert len(aces) == 4
        ace_titles = {c["title"] for c in aces}
        assert "Ace of Wands" in ace_titles
        assert "Ace of Cups" in ace_titles
