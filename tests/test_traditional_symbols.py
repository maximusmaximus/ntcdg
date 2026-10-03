"""Tests for canonical traditional tarot symbol registry, matching, and completion."""

from __future__ import annotations

import json
from unittest.mock import patch

from ntcdg.config import Config
from ntcdg.symbols import TRADITIONAL_TAROT_SYMBOLS, TraditionalDeckRegistry


class TestTraditionalDeckRegistry:
    """Test traditional tarot registry methods and canonical data."""

    def test_canonical_symbols_integrity(self):
        """All canonical symbols must have required fields and non-empty values."""
        assert len(TRADITIONAL_TAROT_SYMBOLS) >= 40
        ids = set()
        for sym in TRADITIONAL_TAROT_SYMBOLS:
            assert sym.get("id")
            assert sym["id"] not in ids, f"Duplicate symbol ID: {sym['id']}"
            ids.add(sym["id"])
            assert sym.get("name")
            assert sym.get("category")
            assert "cards" in sym and isinstance(sym["cards"], list)
            assert sym.get("description")
            assert "keywords" in sym and isinstance(sym["keywords"], list)

    def test_major_arcana_representation(self):
        """All 22 Major Arcana cards must have canonical symbol associations."""
        for _, major_title in Config.MAJOR_ARCANA:
            symbols = TraditionalDeckRegistry.get_symbols_for_card(major_title)
            assert len(symbols) >= 1, f"Major Arcana '{major_title}' has no canonical symbols"

    def test_suit_representation(self):
        """All 4 suits must have canonical suit and elemental symbols."""
        for suit in Config.SUITS:
            symbols = TraditionalDeckRegistry.get_symbols_for_card(f"Ace of {suit}")
            assert len(symbols) >= 1, f"Suit '{suit}' has no symbols for Ace"
            court_symbols = TraditionalDeckRegistry.get_symbols_for_card(f"Queen of {suit}")
            assert len(court_symbols) >= 2, f"Court card Queen of {suit} should have suit and court symbols"

    def test_match_artist_symbols(self):
        """Artist symbols should match canonical archetypes by keywords and names."""
        artist_symbols = [
            {
                "name": "Obsidian Chalice",
                "description": "Dark carved chalice filled with glowing water",
            },
            {
                "name": "White Wolf Pup",
                "description": "A small white wolf bounding alongside the wanderer",
            },
            {
                "name": "Twin Columns",
                "description": "Two pillars, one obsidian, one alabaster at the gate",
            },
            {
                "name": "Quantum Singularity",
                "description": "An abstract pulsing void vortex",
            },
        ]

        result = TraditionalDeckRegistry.match_artist_symbols(artist_symbols)

        assert result["matched_count"] >= 3
        assert result["unmatched_count"] == 1
        assert result["unmatched_artist"][0]["name"] == "Quantum Singularity"

        # Check matched specifics
        matched_canon_ids = {m["traditional_id"] for m in result["matched"]}
        assert "suit_golden_chalice" in matched_canon_ids
        assert "small_white_dog" in matched_canon_ids
        assert "twin_pillars_boaz_jachin" in matched_canon_ids

        # Check coverage
        cov = result["coverage"]
        assert "Cups" in cov["suits_covered"]
        assert "The Fool" in cov["major_arcana_covered"]
        assert "The High Priestess" in cov["major_arcana_covered"]

    def test_get_missing_symbols_by_scope(self):
        """Should filter missing symbols according to scope ('full', 'major', 'suits')."""
        provided = [
            {"name": "golden chalice of living water", "description": "cup"},
        ]

        missing_full = TraditionalDeckRegistry.get_missing_symbols(provided, target_scope="full")
        missing_major = TraditionalDeckRegistry.get_missing_symbols(provided, target_scope="major")
        missing_suits = TraditionalDeckRegistry.get_missing_symbols(provided, target_scope="suits")

        assert len(missing_full) > len(missing_major)
        assert all(s["category"] == "major_arcana" for s in missing_major)
        assert all(s["category"].startswith("suit_") for s in missing_suits)

    def test_assign_symbols_for_card_prioritizes_artist(self):
        """Card symbol assignment should prioritize artist symbols matching the card archetype."""
        card_def = {
            "title": "The Fool",
            "type": "Major Arcana",
            "arcana_number": 0,
        }
        artist_symbols = [
            {
                "name": "Cyber Hound",
                "description": "A small mechanical white dog with neon blue eyes",
            },
            {
                "name": "Cosmic Singularity",
                "description": "Pulsing dark star",
            },
        ]

        assigned = TraditionalDeckRegistry.assign_symbols_for_card(
            card_def=card_def,
            available_symbols=artist_symbols,
            traditional_mode=True,
            max_symbols=4,
        )

        assert len(assigned) <= 4
        # The Cyber Hound should be included as it matches 'small white dog'
        assert any("Cyber Hound" in s for s in assigned)

    def test_assign_symbols_for_card_legacy_fallback(self):
        """When traditional_mode is False, random sampling from available symbols is used."""
        card_def = {
            "title": "The Magician",
            "type": "Major Arcana",
            "arcana_number": 1,
        }
        symbols = [
            {"name": "Symbol Alpha"},
            {"name": "Symbol Beta"},
            {"name": "Symbol Gamma"},
        ]

        assigned = TraditionalDeckRegistry.assign_symbols_for_card(
            card_def=card_def,
            available_symbols=symbols,
            traditional_mode=False,
            max_symbols=2,
        )

        assert len(assigned) == 2
        assert all(s in ["Symbol Alpha", "Symbol Beta", "Symbol Gamma"] for s in assigned)

    def test_complete_deck_symbols(self, tmp_path, monkeypatch):
        """complete_deck_symbols should generate missing symbols and save manifest."""
        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        initial_config = {
            "style_prompt": "cyberpunk oil painting",
            "symbols": [
                {
                    "name": "Cyber Hound",
                    "description": "A small mechanical dog",
                    "image": str(tmp_path / "hound.png"),
                },
            ],
        }

        with patch("ntcdg.symbols._generate_single_symbol") as mock_gen:
            mock_gen.return_value = str(tmp_path / "gen_symbol.png")

            completed = TraditionalDeckRegistry.complete_deck_symbols(
                symbols_config=initial_config,
                deck_name="TestDeck",
                deck_prompt="neon grid",
                api_key="fake-key",
                image_model="qwen-image-3-pro",
                target_scope="suits",
                max_missing=3,
            )

            assert completed["artist_symbol_count"] == 1
            assert completed["generated_symbol_count"] == 3
            assert len(completed["symbols"]) == 4

            # Verify manifest file on disk
            manifest = tmp_path / "TestDeck" / "symbols" / "symbols.json"
            assert manifest.exists()
            with open(manifest) as f:
                saved = json.load(f)
            assert len(saved["symbols"]) == 4
            assert saved["symbols"][0]["source"] == "artist"
            assert saved["symbols"][1]["source"] == "generated"
