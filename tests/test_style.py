"""Tests for the deck style extraction and prompt refinement module."""

from ntcdg.models import Card
from ntcdg.style import _build_fallback_prompt, refine_card_prompt


class TestFallbackPrompt:
    """Test template-based prompt generation."""

    def test_with_deck_style(self):
        """Fallback prompt should start with the deck style."""
        card = Card(
            position=1, title="The Fool", card_type="Major Arcana",
            symbols=["dog", "cliff", "sun"], layout="expansive spiral",
        )
        result = _build_fallback_prompt(card, "oil painting, warm tones")
        assert result.startswith("oil painting, warm tones")
        assert "The Fool" in result
        assert "dog" in result

    def test_without_deck_style(self):
        """Fallback prompt should use generic template without deck style."""
        card = Card(
            position=5, title="The Hierophant", card_type="Major Arcana",
            symbols=["keys", "pillars"], layout="symmetric central",
        )
        result = _build_fallback_prompt(card, "")
        assert "Tarot card" in result
        assert "The Hierophant" in result
        assert "cinematic lighting" in result

    def test_first_card_flag(self):
        """First card should mention origins."""
        card = Card(
            position=1, title="The Fool", card_type="Major Arcana",
            symbols=["dog"], layout="spiral", is_first=True,
        )
        result = _build_fallback_prompt(card, "dark watercolor")
        assert "origins" in result.lower() or "beginnings" in result.lower()

    def test_last_card_flag(self):
        """Last card should mention culmination."""
        card = Card(
            position=78, title="King of Pentacles", card_type="Minor Arcana",
            symbols=["crown"], layout="dense", is_last=True,
        )
        result = _build_fallback_prompt(card, "")
        assert "culmination" in result.lower() or "synthesis" in result.lower()

    def test_deck_prompt_included(self):
        """User's deck prompt/theme should be included."""
        card = Card(
            position=3, title="The Empress", card_type="Major Arcana",
            symbols=["wheat"], layout="flowing",
            deck_prompt="cosmic horror meets art nouveau",
        )
        result = _build_fallback_prompt(card, "")
        assert "cosmic horror" in result

    def test_no_text_instruction(self):
        """All prompts should forbid text rendering."""
        card = Card(
            position=1, title="Test", card_type="Major Arcana",
            symbols=["star"], layout="center",
        )
        result = _build_fallback_prompt(card, "any style")
        assert "no text" in result.lower() or "not render" in result.lower()


class TestRefineCardPrompt:
    """Test LLM prompt refinement with no API (fallback)."""

    def test_no_api_key_uses_fallback(self):
        """Without API key, should return a valid fallback prompt."""
        card = Card(
            position=1, title="The Magician", card_type="Major Arcana",
            symbols=["wand", "cup", "sword", "pentacle"],
            layout="central figure",
        )
        result = refine_card_prompt(card, "dark oil painting style", None, None)
        assert "dark oil painting style" in result
        assert "The Magician" in result

    def test_empty_style_still_works(self):
        """Empty deck style should still produce a valid prompt."""
        card = Card(
            position=5, title="Test Card", card_type="Major Arcana",
            symbols=["star"], layout="centered",
        )
        result = refine_card_prompt(card, "", None, None)
        assert "Test Card" in result
        assert len(result) > 50


class TestBuildCardPrompt:
    """Test the updated build_card_prompt with style support."""

    def test_with_style(self):
        """Style-driven prompt should use deck style."""
        from ntcdg.generator import build_card_prompt

        card = Card(
            position=1, title="The Sun", card_type="Major Arcana",
            symbols=["sun", "child", "horse"], layout="radiant center",
        )
        result = build_card_prompt(card, "vibrant gouache illustration")
        assert "vibrant gouache illustration" in result
        assert "portrait orientation" in result.lower()

    def test_without_style(self):
        """No-style prompt should use legacy template."""
        from ntcdg.generator import build_card_prompt

        card = Card(
            position=1, title="The Moon", card_type="Major Arcana",
            symbols=["moon", "dogs"], layout="mysterious",
        )
        result = build_card_prompt(card, "")
        assert "professional quality" in result or "cinematic" in result
