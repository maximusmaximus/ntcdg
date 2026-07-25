"""Tests for usage tracking and cost estimation."""

from ntcdg.usage import UsageTracker


class TestUsageTracker:
    """Test the UsageTracker accumulation and serialization."""

    def test_empty_tracker(self):
        """Fresh tracker should have zero counts."""
        t = UsageTracker()
        assert t.text_calls == 0
        assert t.image_calls == 0
        assert t.total_tokens == 0

    def test_record_text_call(self):
        """Should accumulate text call stats."""
        t = UsageTracker()
        t.record_text_call("llama-3.3-70b", prompt_tokens=500, completion_tokens=200)
        t.record_text_call("llama-3.3-70b", prompt_tokens=300, completion_tokens=100)
        assert t.text_calls == 2
        assert t.prompt_tokens == 800
        assert t.completion_tokens == 300
        assert t.total_tokens == 1100

    def test_record_text_failure(self):
        """Failed calls should increment failure counter."""
        t = UsageTracker()
        t.record_text_call("llama-3.3-70b", success=False)
        assert t.text_calls == 1
        assert t.text_calls_failed == 1

    def test_record_image_call(self):
        """Should count image calls."""
        t = UsageTracker()
        t.record_image_call("flux-2-pro", "832x1280")
        t.record_image_call("flux-2-pro", "832x1280")
        t.record_image_call("flux-2-pro", "832x1280", success=False)
        assert t.image_calls == 3
        assert t.image_calls_failed == 1

    def test_preview_tracking(self):
        """Preview calls should be tracked separately."""
        t = UsageTracker()
        t.record_image_call("flux-2-pro", "832x1280", purpose="preview")
        t.record_image_call("flux-2-pro", "832x1280", purpose="preview")
        t.record_image_call("flux-2-pro", "832x1280", purpose="card")
        assert t.image_calls == 3
        assert t.preview_image_calls == 2

    def test_cost_estimation(self):
        """Cost should reflect token counts and image counts."""
        t = UsageTracker()
        t.text_model = "llama-3.3-70b"
        t.image_model = "flux-2-pro"
        t.record_text_call("llama-3.3-70b", prompt_tokens=1000, completion_tokens=500)
        t.record_image_call("flux-2-pro", "832x1280")
        t.record_image_call("flux-2-pro", "832x1280")
        costs = t.estimate_cost()
        assert costs["text"] > 0
        assert costs["image"] > 0
        assert costs["total"] == costs["text"] + costs["image"]
        # 2 images at $0.03 each = $0.06
        assert costs["image"] == 0.06

    def test_to_dict_round_trip(self):
        """Serialized stats should reconstruct correctly."""
        t = UsageTracker()
        t.record_text_call("llama-3.3-70b", prompt_tokens=500, completion_tokens=200)
        t.record_image_call("flux-2-pro", "832x1280")
        t.record_style_call("oil painting style")
        t.finalize()
        data = t.to_dict()

        t2 = UsageTracker.from_dict(data)
        assert t2.text_calls == 1
        assert t2.image_calls == 1
        assert t2.prompt_tokens == 500
        assert t2.style_prompt == "oil painting style"

    def test_style_call_recording(self):
        """Style extraction should be tracked."""
        t = UsageTracker()
        t.record_style_call("dark watercolor impressionism")
        assert t.style_calls == 1
        assert "watercolor" in t.style_prompt

    def test_call_log(self):
        """Each call should be logged for detailed breakdown."""
        t = UsageTracker()
        t.record_text_call("m1", purpose="analysis")
        t.record_text_call("m1", purpose="prompt_refinement")
        t.record_image_call("m2", purpose="card")
        assert len(t.call_log) == 3
        assert t.call_log[0]["purpose"] == "analysis"
        assert t.call_log[1]["purpose"] == "prompt_refinement"
        assert t.call_log[2]["type"] == "image"


class TestDisplayStats:
    """Test stats display function."""

    def test_display_no_stats(self, tmp_path, monkeypatch, capsys):
        """Should handle deck with no usage data."""
        from ntcdg.models import Card
        from ntcdg.storage import save_deck, update_deck_index
        from ntcdg.usage import display_deck_stats

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        save_deck([Card(position=1, title="Test")], "StatsTest")
        update_deck_index("StatsTest", 1)

        display_deck_stats("StatsTest")
        output = capsys.readouterr().out
        assert "No usage stats" in output

    def test_display_missing_deck(self, tmp_path, monkeypatch, capsys):
        """Should handle missing deck gracefully."""
        from ntcdg.usage import display_deck_stats

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        display_deck_stats("NoDeck")
        assert "not found" in capsys.readouterr().out
