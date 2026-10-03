"""Tests for new and updated traditional tarot MCP tools."""

from __future__ import annotations

import json
from unittest.mock import patch

from ntcdg.models import Card


class TestMCPTraditionalTools:
    """Test get_traditional_symbols, match_symbols, complete_symbols, and get_deck_traditional_coverage."""

    def test_get_traditional_symbols_unfiltered(self):
        """Should return all canonical symbols."""
        from ntcdg.mcp_server import get_traditional_symbols

        result = get_traditional_symbols()
        assert result["count"] > 30
        assert result["total_canonical"] == result["count"]

    def test_get_traditional_symbols_filter_card(self):
        """Should filter symbols by specific card name."""
        from ntcdg.mcp_server import get_traditional_symbols

        result = get_traditional_symbols(card_name="The Fool")
        assert result["count"] >= 1
        for s in result["symbols"]:
            assert "The Fool" in s.get("cards", [])

    def test_get_traditional_symbols_filter_suit(self):
        """Should filter symbols by suit."""
        from ntcdg.mcp_server import get_traditional_symbols

        result = get_traditional_symbols(suit="Cups")
        assert result["count"] >= 1
        for s in result["symbols"]:
            assert s.get("category") == "suit_cups" or any("Cups" in c for c in s.get("cards", []))

    def test_get_traditional_symbols_query_search(self):
        """Should search symbols by keyword."""
        from ntcdg.mcp_server import get_traditional_symbols

        result = get_traditional_symbols(query="dog")
        assert result["count"] >= 1
        found_dog = any("dog" in s["name"].lower() or "dog" in s["keywords"] for s in result["symbols"])
        assert found_dog

    def test_match_symbols_direct_list(self):
        """Should analyze artist symbols and report coverage."""
        from ntcdg.mcp_server import match_symbols

        artist_symbols = [
            {"name": "Golden Chalice", "description": "A chalice of wine"},
            {"name": "Stone Ram", "description": "Ram head on granite throne"},
        ]

        result = match_symbols(symbols=artist_symbols)
        assert result["success"] is True
        assert result["provided_count"] == 2
        assert result["matched_count"] >= 1
        assert "coverage" in result

    def test_match_symbols_with_file(self, tmp_path):
        """Should load and analyze symbols from file."""
        from ntcdg.mcp_server import match_symbols

        sym_file = tmp_path / "symbols.json"
        with open(sym_file, "w") as f:
            json.dump({
                "symbols": [
                    {"name": "Mystic Sword", "description": "Double edged steel blade"},
                ],
            }, f)

        result = match_symbols(symbols_file=str(sym_file))
        assert result["success"] is True
        assert result["provided_count"] == 1
        assert result["matched_count"] == 1

    def test_complete_symbols_tool(self, tmp_path, monkeypatch):
        """Should generate missing symbols and return summary."""
        from ntcdg.mcp_server import complete_symbols

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("VENICE_API_KEY", "test-key")

        with patch("ntcdg.symbols._generate_single_symbol") as mock_gen:
            mock_gen.return_value = str(tmp_path / "symbol_gen.png")

            result = complete_symbols(
                deck_name="GothicTarot",
                style_prompt="dark gothic realism",
                target_scope="suits",
                max_generate=2,
            )

            assert result["success"] is True
            assert result["deck_name"] == "GothicTarot"
            assert result["total_symbols"] >= 2
            assert result["generated_symbols_count"] == 2

    def test_get_deck_traditional_coverage(self, tmp_path, monkeypatch):
        """Should inspect deck cards and compute traditional coverage."""
        from ntcdg.mcp_server import get_deck_traditional_coverage
        from ntcdg.storage import save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        cards = [
            Card(
                position=1,
                title="The Fool",
                card_type="Major Arcana",
                symbols=["small white dog", "white rose"],
            ),
            Card(
                position=2,
                title="Ace of Cups",
                card_type="Minor Arcana",
                suit="Cups",
                symbols=["golden chalice of living water"],
            ),
        ]
        save_deck(cards, "CoverageDeck")

        result = get_deck_traditional_coverage("CoverageDeck")
        assert result["deck_name"] == "CoverageDeck"
        assert result["total_cards"] == 2
        assert result["canonical_symbols_covered"] >= 2
        assert result["traditional_coverage_percentage"] > 0

    def test_register_symbols_returns_traditional_coverage(self, tmp_path, monkeypatch):
        """register_symbols should include traditional_coverage in response."""
        from ntcdg.mcp_server import register_symbols

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        img1 = tmp_path / "chalice.png"
        img1.write_bytes(b"chalice image")

        result = register_symbols(
            deck_name="SymbolDeck",
            symbols=[
                {"name": "Chalice", "image_path": str(img1), "description": "Golden cup of water"},
            ],
            auto_describe=False,
            traditional_match=True,
        )

        assert result["success"] is True
        assert "traditional_coverage" in result
        assert "matched_traditional" in result
        assert len(result["matched_traditional"]) >= 1

    def test_finalize_deck_accepts_sheet_size_and_duplex(self, tmp_path, monkeypatch):
        """finalize_deck should accept updated sheet_size and duplex_flip options."""
        from ntcdg.mcp_server import finalize_deck
        from ntcdg.storage import save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        deck = [
            Card(position=1, title="The Fool", card_type="Major Arcana"),
        ]
        save_deck(deck, "FinalizeTestDeck")

        with patch("ntcdg.finalize.finalize_deck") as mock_fin:
            result = finalize_deck(
                deck_name="FinalizeTestDeck",
                sheet_size="a4",
                duplex_flip="long_edge",
            )
            assert result["success"] is True
            mock_fin.assert_called_once_with(
                "FinalizeTestDeck",
                sheet_size="a4",
                color_mode="color",
                duplex_flip="long_edge",
            )
