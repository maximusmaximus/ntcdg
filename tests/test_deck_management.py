"""Tests for user config, deck management, and wizard settings."""

from argparse import Namespace

from ntcdg.models import Card
from ntcdg.userconfig import _parse_rc_file, apply_config_defaults


class TestParseRcFile:
    """Test .ntcdgrc file parsing."""

    def test_basic_parsing(self, tmp_path):
        """Should parse key: value pairs."""
        rc = tmp_path / ".ntcdgrc"
        rc.write_text('venice_api_key: sk-test\nrate_limit: 2.0\n')
        result = _parse_rc_file(str(rc))
        assert result["venice_api_key"] == "sk-test"
        assert result["rate_limit"] == "2.0"

    def test_quoted_values(self, tmp_path):
        """Should strip surrounding quotes."""
        rc = tmp_path / ".ntcdgrc"
        rc.write_text('default_vibe: "cosmic horror"\n')
        result = _parse_rc_file(str(rc))
        assert result["default_vibe"] == "cosmic horror"

    def test_comments_and_blanks(self, tmp_path):
        """Should skip comments and blank lines."""
        rc = tmp_path / ".ntcdgrc"
        rc.write_text("# comment\n\nvenice_api_key: test\n# another\n")
        result = _parse_rc_file(str(rc))
        assert len(result) == 1
        assert result["venice_api_key"] == "test"

    def test_missing_file(self):
        """Should return empty dict for missing file."""
        result = _parse_rc_file("/nonexistent/.ntcdgrc")
        assert result == {}


class TestApplyConfigDefaults:
    """Test applying config to argparse args."""

    def test_fills_missing_values(self):
        """Config should fill in None/empty args."""
        args = Namespace(
            venice_key=None, vibe=None, venice_image_model=None,
            venice_text_model=None, image_size=None, font=None,
            negative_prompt="", rate_limit=None, deck_prompt="",
        )
        config = {
            "venice_api_key": "sk-from-config",
            "default_vibe": "dark art deco",
            "rate_limit": "2.5",
        }
        apply_config_defaults(args, config)
        assert args.venice_key == "sk-from-config"
        assert args.vibe == "dark art deco"
        assert args.rate_limit == 2.5

    def test_does_not_override_explicit(self):
        """CLI-provided values should not be overridden."""
        args = Namespace(
            venice_key="sk-explicit", vibe="my-vibe",
            venice_image_model=None, venice_text_model=None,
            image_size=None, font=None, negative_prompt="",
            rate_limit=None, deck_prompt="",
        )
        config = {
            "venice_api_key": "sk-from-config",
            "default_vibe": "should-not-apply",
        }
        apply_config_defaults(args, config)
        assert args.venice_key == "sk-explicit"
        assert args.vibe == "my-vibe"


class TestListCards:
    """Test card listing."""

    def test_list_cards_output(self, tmp_path, monkeypatch, capsys):
        """Should print card status table."""
        from ntcdg.storage import list_cards, save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        deck = [
            Card(position=1, title="The Fool", card_type="Major Arcana",
                 description="A youth", upright_interpretation="new beginnings",
                 reversed_interpretation="recklessness"),
            Card(position=2, title="The Magician", card_type="Major Arcana",
                 venice_error="API timeout"),
        ]
        save_deck(deck, "TestDeck")
        list_cards("TestDeck")

        output = capsys.readouterr().out
        assert "The Fool" in output
        assert "The Magician" in output
        assert "Error" in output

    def test_list_cards_missing_deck(self, tmp_path, monkeypatch, capsys):
        """Missing deck should show error."""
        from ntcdg.storage import list_cards

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        list_cards("NoDeck")
        assert "not found" in capsys.readouterr().out


class TestDeleteDeck:
    """Test deck deletion."""

    def test_delete_removes_files(self, tmp_path, monkeypatch):
        """Deletion should remove JSON and index entry."""
        from ntcdg.storage import (
            delete_deck,
            load_deck,
            load_decks_index,
            save_deck,
        )

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        deck = [Card(position=1, title="Test")]
        save_deck(deck, "DelTest")

        # Verify it exists
        assert load_deck("DelTest")

        # Delete without confirmation
        result = delete_deck("DelTest", confirm=False)
        assert result is True
        assert not load_deck("DelTest")
        assert "DelTest" not in load_decks_index()


class TestCloneDeck:
    """Test deck cloning."""

    def test_clone_creates_copy(self, tmp_path, monkeypatch):
        """Clone should create an independent copy."""
        from ntcdg.storage import clone_deck, load_deck, save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr("ntcdg.config.Config.IMAGES_DIR",
                            str(tmp_path / "images"))

        deck = [Card(position=1, title="Test Card", description="original")]
        save_deck(deck, "Original")

        result = clone_deck("Original", "Clone")
        assert result is True

        cloned = load_deck("Clone")
        assert len(cloned) == 1
        assert cloned[0].title == "Test Card"
        assert cloned[0].description == "original"

    def test_clone_rejects_existing(self, tmp_path, monkeypatch):
        """Should not overwrite existing deck."""
        from ntcdg.storage import clone_deck, save_deck

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        save_deck([Card(position=1, title="A")], "DeckA")
        save_deck([Card(position=1, title="B")], "DeckB")

        result = clone_deck("DeckA", "DeckB")
        assert result is False
