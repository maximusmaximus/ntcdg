"""Tests for MCP server tool functions."""

import os

from ntcdg.models import Card


class TestDeckSummary:
    """Test the _deck_summary helper."""

    def test_summary_with_deck(self, tmp_path, monkeypatch):
        """Should return structured summary."""
        from ntcdg.mcp_server import _deck_summary
        from ntcdg.storage import save_deck, update_deck_index

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        deck = [
            Card(position=1, title="The Fool", card_type="Major Arcana",
                 description="A youth", upright_interpretation="new",
                 reversed_interpretation="reckless"),
            Card(position=2, title="The Magician", card_type="Major Arcana",
                 venice_error="timeout"),
        ]
        save_deck(deck, "TestMCP")
        update_deck_index("TestMCP", 2, vibe="test vibe")

        result = _deck_summary("TestMCP")
        assert result["name"] == "TestMCP"
        assert result["total_cards"] == 2
        assert result["analysis"] == 1
        assert result["errors"] == 1
        assert result["vibe"] == "test vibe"
        assert result["ready_to_finalize"] is False

    def test_summary_missing_deck(self, tmp_path, monkeypatch):
        """Should return error for missing deck."""
        from ntcdg.mcp_server import _deck_summary

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        result = _deck_summary("NoSuchDeck")
        assert "error" in result


class TestMCPTools:
    """Test MCP tool functions."""

    def test_list_decks_empty(self, tmp_path, monkeypatch):
        """Should return empty list when no decks exist."""
        from ntcdg.mcp_server import list_decks

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(
            "ntcdg.config.Config.DECKS_INDEX_FILE",
            str(tmp_path / "decks_index.json"),
        )
        result = list_decks()
        assert result["count"] == 0
        assert result["decks"] == []

    def test_list_decks_with_data(self, tmp_path, monkeypatch):
        """Should list existing decks."""
        from ntcdg.mcp_server import list_decks
        from ntcdg.storage import save_deck, update_deck_index

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(
            "ntcdg.config.Config.DECKS_INDEX_FILE",
            str(tmp_path / "decks_index.json"),
        )
        save_deck([Card(position=1, title="Test")], "DeckA")
        update_deck_index("DeckA", 1, vibe="dark")

        result = list_decks()
        assert result["count"] == 1
        assert result["decks"][0]["name"] == "DeckA"

    def test_deck_info(self, tmp_path, monkeypatch):
        """Should return structured deck info."""
        from ntcdg.mcp_server import deck_info
        from ntcdg.storage import save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        save_deck([Card(position=1, title="Test")], "InfoDeck")

        result = deck_info("InfoDeck")
        assert result["total_cards"] == 1

    def test_deck_stats_no_data(self, tmp_path, monkeypatch):
        """Should handle deck with no usage stats."""
        from ntcdg.mcp_server import deck_stats
        from ntcdg.storage import save_deck, update_deck_index

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        save_deck([Card(position=1, title="Test")], "StatsDeck")
        update_deck_index("StatsDeck", 1)

        result = deck_stats("StatsDeck")
        assert "error" in result

    def test_list_cards(self, tmp_path, monkeypatch):
        """Should return per-card status."""
        from ntcdg.mcp_server import list_cards
        from ntcdg.storage import save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        deck = [
            Card(position=1, title="Fool", description="test",
                 upright_interpretation="up", reversed_interpretation="rev"),
            Card(position=2, title="Mage", venice_error="fail"),
        ]
        save_deck(deck, "CardsDeck")

        result = list_cards("CardsDeck")
        assert result["total"] == 2
        assert result["cards"][1]["error"] == "fail"

    def test_edit_card(self, tmp_path, monkeypatch):
        """Should edit card field."""
        from ntcdg.mcp_server import edit_card
        from ntcdg.storage import load_deck, save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        save_deck([Card(position=1, title="Old Title")], "EditDeck")

        result = edit_card("EditDeck", 1, "title", "New Title")
        assert result["success"] is True

        deck = load_deck("EditDeck")
        assert deck[0].title == "New Title"

    def test_clone_deck(self, tmp_path, monkeypatch):
        """Should clone deck."""
        from ntcdg.mcp_server import clone_deck
        from ntcdg.storage import load_deck, save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr("ntcdg.config.Config.IMAGES_DIR",
                            str(tmp_path / "images"))
        save_deck([Card(position=1, title="Test")], "Src")

        result = clone_deck("Src", "Dst")
        assert result["success"] is True
        assert load_deck("Dst")

    def test_delete_deck(self, tmp_path, monkeypatch):
        """Should delete deck without confirmation."""
        from ntcdg.mcp_server import delete_deck
        from ntcdg.storage import load_deck, save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        save_deck([Card(position=1, title="Test")], "DelDeck")

        result = delete_deck("DelDeck")
        assert result["success"] is True
        assert not load_deck("DelDeck")

    def test_get_card_details(self, tmp_path, monkeypatch):
        """Should return full card details."""
        from ntcdg.mcp_server import get_card_details
        from ntcdg.storage import save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        save_deck([
            Card(position=3, title="The Empress", card_type="Major Arcana",
                 description="Growth", symbols=["wheat", "stars"],
                 upright_interpretation="abundance"),
        ], "DetailDeck")

        result = get_card_details("DetailDeck", 3)
        assert result["title"] == "The Empress"
        assert "wheat" in result["symbols"]
        assert result["description"] == "Growth"

    def test_get_card_image_missing(self, tmp_path, monkeypatch):
        """Should report missing image."""
        from ntcdg.mcp_server import get_card_image
        from ntcdg.storage import save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        save_deck([Card(position=1, title="Test")], "ImgDeck")

        result = get_card_image("ImgDeck", 1)
        assert "error" in result


class TestAgenticTools:
    """Test the 6 new agentic workflow tools."""

    def test_estimate_cost_full_deck(self):
        """Should estimate cost for a 78-card deck."""
        from ntcdg.mcp_server import estimate_cost

        result = estimate_cost(cards=78, analyze=True, generate_images=True)
        assert result["cards"] == 78
        assert result["api_calls"]["text"] > 0
        assert result["api_calls"]["image"] > 0
        assert result["estimated_cost_usd"]["total"] > 0
        assert result["estimated_time_minutes"] > 0

    def test_estimate_cost_major_only(self):
        """Should estimate less for 22 cards."""
        from ntcdg.mcp_server import estimate_cost

        full = estimate_cost(cards=78)
        major = estimate_cost(cards=22)
        assert major["estimated_cost_usd"]["total"] < full["estimated_cost_usd"]["total"]
        assert major["estimated_time_minutes"] < full["estimated_time_minutes"]

    def test_estimate_cost_no_images(self):
        """Should have zero image cost when images disabled."""
        from ntcdg.mcp_server import estimate_cost

        result = estimate_cost(cards=22, generate_images=False)
        assert result["api_calls"]["image"] == 0
        assert result["estimated_cost_usd"]["image"] == 0

    def test_estimate_cost_no_previews(self):
        """Should subtract preview calls when previews=0."""
        from ntcdg.mcp_server import estimate_cost

        with_previews = estimate_cost(cards=22, previews=3)
        without = estimate_cost(cards=22, previews=0)
        assert without["api_calls"]["image"] < with_previews["api_calls"]["image"]

    def test_get_all_images(self, tmp_path, monkeypatch):
        """Should return all image paths."""
        from ntcdg.mcp_server import get_all_images
        from ntcdg.storage import save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        # Create a card with an image file
        img_path = tmp_path / "001_test.png"
        img_path.write_bytes(b"fake image")
        deck = [
            Card(position=1, title="Fool", image_path=str(img_path)),
            Card(position=2, title="Mage"),  # no image
        ]
        save_deck(deck, "ImgDeck")

        result = get_all_images("ImgDeck")
        assert result["images_count"] == 1
        assert result["missing_count"] == 1
        assert result["images"][0]["title"] == "Fool"

    def test_get_all_images_missing_deck(self, tmp_path, monkeypatch):
        """Should handle missing deck."""
        from ntcdg.mcp_server import get_all_images

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        result = get_all_images("NoDeck")
        assert "error" in result

    def test_deck_progress(self, tmp_path, monkeypatch):
        """Should return progress counts."""
        from ntcdg.mcp_server import deck_progress
        from ntcdg.storage import save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        img_path = tmp_path / "001_test.png"
        img_path.write_bytes(b"fake")
        deck = [
            Card(position=1, title="Fool", description="done",
                 image_path=str(img_path)),
            Card(position=2, title="Mage", venice_error="timeout"),
            Card(position=3, title="Priestess"),
        ]
        save_deck(deck, "ProgDeck")

        result = deck_progress("ProgDeck")
        assert result["total"] == 3
        assert result["images_done"] == 1
        assert result["analysis_done"] == 1
        assert result["errors"] == 1
        assert result["percent"] == 33
        assert result["ready_to_finalize"] is False

    def test_deck_progress_missing(self, tmp_path, monkeypatch):
        """Should handle missing deck."""
        from ntcdg.mcp_server import deck_progress

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        result = deck_progress("NoDeck")
        assert result["exists"] is False


class TestSymbolRegistration:
    """Test the register_symbols tool."""

    def test_register_symbols(self, tmp_path, monkeypatch):
        """Should copy images and create symbols.json."""
        import json

        from ntcdg.mcp_server import register_symbols

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        # Create real (tiny) symbol images -- registration verifies image files
        from PIL import Image
        img1 = tmp_path / "serpent.png"
        img2 = tmp_path / "eye.png"
        Image.new("RGB", (4, 4), "green").save(img1)
        Image.new("RGB", (4, 4), "blue").save(img2)

        result = register_symbols(
            deck_name="TestDeck",
            symbols=[
                {"name": "Serpent", "image_path": str(img1),
                 "description": "A coiled serpent"},
                {"name": "Eye", "image_path": str(img2),
                 "description": "All-seeing eye"},
            ],
            auto_describe=False,
        )

        assert result["success"] is True
        assert result["registered"] == 2
        assert len(result["errors"]) == 0
        assert os.path.exists(result["symbols_file"])

        # Verify symbols.json content
        with open(result["symbols_file"]) as f:
            config = json.load(f)
        assert len(config["symbols"]) == 2
        assert config["symbols"][0]["name"] == "Serpent"
        assert os.path.exists(config["symbols"][0]["image"])

    def test_register_missing_image(self, tmp_path, monkeypatch):
        """Should report errors for missing images."""
        from ntcdg.mcp_server import register_symbols

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        result = register_symbols(
            deck_name="TestDeck",
            symbols=[
                {"name": "Ghost", "image_path": "/nonexistent/ghost.png"},
            ],
            auto_describe=False,
        )

        assert result["registered"] == 0
        assert len(result["errors"]) == 1
        assert "not found" in result["errors"][0]["error"]

    def test_register_missing_name(self, tmp_path, monkeypatch):
        """Should report errors for missing names."""
        from ntcdg.mcp_server import register_symbols

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        img = tmp_path / "unnamed.png"
        img.write_bytes(b"data")

        result = register_symbols(
            deck_name="TestDeck",
            symbols=[
                {"image_path": str(img)},  # no name
            ],
            auto_describe=False,
        )

        assert result["registered"] == 0
        assert len(result["errors"]) == 1

    def test_register_includes_usage_hint(self, tmp_path, monkeypatch):
        """Should include usage hint for next step."""
        from ntcdg.mcp_server import register_symbols

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        from PIL import Image
        img = tmp_path / "test.png"
        Image.new("RGB", (4, 4)).save(img)

        result = register_symbols(
            deck_name="MyDeck",
            symbols=[{"name": "Test", "image_path": str(img), "description": "test"}],
            auto_describe=False,
        )

        assert "preview_style" in result["usage_hint"]
        assert "symbol_mode" in result["usage_hint"]
