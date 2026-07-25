"""Tests for MCP server tool functions."""


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
