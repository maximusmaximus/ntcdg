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

        from PIL import Image
        img1 = tmp_path / "chalice.png"
        Image.new("RGB", (4, 4), "gold").save(img1)

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
        """finalize_deck must really run with sheet_size + duplex_flip (no mocks).

        The previous version of this test mocked finalize and so hid a
        TypeError: the duplex_flip keyword was not accepted downstream.
        """
        from PIL import Image

        from ntcdg.mcp_server import finalize_deck
        from ntcdg.storage import save_deck, update_deck_meta

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        deck = []
        for i in range(1, 4):
            img = tmp_path / f"card_{i}.png"
            Image.new("RGB", (60, 100), (i * 40, 20, 90)).save(img)
            deck.append(Card(
                position=i, title=f"Card {i}", card_type="Major Arcana",
                image_path=str(img), description="d",
                upright_interpretation="u", reversed_interpretation="r",
            ))
        save_deck(deck, "FinalizeTestDeck")
        back = tmp_path / "back.png"
        Image.new("RGB", (60, 100), "black").save(back)
        update_deck_meta("FinalizeTestDeck", back_image=str(back))

        for flip in ("long_edge", "short_edge"):
            result = finalize_deck(
                deck_name="FinalizeTestDeck", sheet_size="a4", duplex_flip=flip,
            )
            assert result["success"] is True, result
            assert result["print_pdf"].endswith("FinalizeTestDeck_PRINT_a4_color.pdf")
            assert result["backs_pdf"].endswith(f"FinalizeTestDeck_BACKS_a4_color_{flip}.pdf")
            assert result["duplex_pdf"].endswith(f"FinalizeTestDeck_DUPLEX_a4_color_{flip}.pdf")
            assert result["validation"]["errors"] == []
            assert result["pages"] == 1

    def test_finalize_deck_rejects_bad_options(self, tmp_path, monkeypatch):
        from ntcdg.mcp_server import finalize_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        for kwargs in (
            {"sheet_size": "postcard"},
            {"duplex_flip": "none"},
            {"color_mode": "rainbow"},
        ):
            result = finalize_deck(deck_name="Whatever", **kwargs)
            assert result["success"] is False
            assert "Unknown" in result["error"]

    def test_finalize_deck_reports_validation_failure(self, tmp_path, monkeypatch):
        from ntcdg.mcp_server import finalize_deck
        from ntcdg.storage import save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        save_deck([Card(position=1, title="The Fool")], "NoImages")

        result = finalize_deck(deck_name="NoImages")
        assert result["success"] is False
        assert result["validation"]["errors"]
        assert result["print_pdf"] is None
