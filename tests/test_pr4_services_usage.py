"""Regression tests for PR 4: dynamic Config, per-call UsageTracker, services & cleanup."""

from __future__ import annotations

import base64
import io
import json
import os
import threading
from unittest.mock import MagicMock

from PIL import Image

from ntcdg.config import Config
from ntcdg.models import Card
from ntcdg.runtime import usage_tracker_scope
from ntcdg.services import audit_traditional_coverage, get_deck_summary
from ntcdg.storage import (
    deck_images_dir,
    delete_deck,
    edit_card_field,
    is_novel,
    load_deck,
    load_decks_index,
    load_history,
    preview_raw_dir,
    record_deck_history,
    save_deck,
    update_deck_index,
)
from ntcdg.style import extract_style_from_images, refine_card_prompt
from ntcdg.symbols import TRADITIONAL_TAROT_SYMBOLS, _generate_single_symbol, symbols_dir_for
from ntcdg.usage import PRICING, UsageTracker
from ntcdg.venice import generate_card_back


def _png_b64(w: int = 64, h: int = 96) -> str:
    im = Image.new("RGB", (w, h), (30, 50, 90))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class TestDynamicConfigPaths:
    """Verify Config derived paths dynamically track OUTPUT_DIR while supporting overrides."""

    def test_derived_paths_track_output_dir_and_restore_cleanly(self, tmp_path, monkeypatch):
        custom_out = str(tmp_path / "custom_out")
        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", custom_out)

        assert str(Config.IMAGES_DIR) == os.path.join(custom_out, "images")
        assert str(Config.LOGS_DIR) == os.path.join(custom_out, "logs")
        assert str(Config.DECKS_INDEX_FILE) == os.path.join(custom_out, "decks_index.json")
        assert str(Config.HISTORY_FILE) == os.path.join(custom_out, "ntcdg_history.json")

        # Explicit override on IMAGES_DIR still works and can be undone cleanly
        override_imgs = str(tmp_path / "override_imgs")
        with monkeypatch.context() as mp:
            mp.setattr("ntcdg.config.Config.IMAGES_DIR", override_imgs)
            assert str(Config.IMAGES_DIR) == override_imgs

        # After inner monkeypatch teardown, dynamic resolution resumes!
        assert str(Config.IMAGES_DIR) == os.path.join(custom_out, "images")


class TestPerCallUsageTrackerAndScopedWiring:
    """Verify accurate mixed-model per-call cost estimation & scoped auto-tracking."""

    def test_mixed_model_cost_excludes_failures_and_prices_each_model(self):
        t = UsageTracker()
        # Vision style call (qwen3-vl-235b-a22b: $0.0018/1K in, $0.0035/1K out)
        t.record_text_call(
            "qwen3-vl-235b-a22b", prompt_tokens=1000, completion_tokens=1000, purpose="style_vision",
        )
        # Text analysis call (llama-3.3-70b: $0.0015/1K in, $0.0030/1K out)
        t.record_text_call(
            "llama-3.3-70b", prompt_tokens=1000, completion_tokens=1000, purpose="analysis",
        )
        # Failed text call must NOT add cost
        t.record_text_call(
            "llama-3.3-70b", prompt_tokens=5000, completion_tokens=5000, success=False,
        )

        # Base card image (qwen-image-3-pro: $0.030) + Multi-edit (nano-banana-pro-edit: $0.035)
        t.record_image_call("qwen-image-3-pro", "768x1280", success=True, purpose="card_base")
        t.record_image_call("nano-banana-pro-edit", "768x1280", success=True, purpose="edit")
        # Failed image call must NOT be billed!
        t.record_image_call("flux-3-image", "768x1280", success=False, purpose="card")

        costs = t.estimate_cost()
        expected_text = round((0.0018 + 0.0035) + (0.0015 + 0.0030), 4)  # 0.0098
        expected_image = round(
            PRICING["image"]["qwen-image-3-pro"] + PRICING["image"]["nano-banana-pro-edit"], 4,
        )  # 0.065
        assert costs["text"] == expected_text
        assert costs["image"] == expected_image
        assert costs["total"] == round(expected_text + expected_image, 4)

        # Round-trip through to_dict / from_dict preserves per-call cost accuracy
        restored = UsageTracker.from_dict(t.to_dict())
        assert restored.estimate_cost() == costs

    def test_usage_tracker_scope_captures_style_symbol_and_card_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        ref_img = tmp_path / "ref.png"
        Image.new("RGB", (32, 32), (100, 120, 140)).save(ref_img)

        def fake_venice_post(url, api_key, payload, **kwargs):
            resp = MagicMock()
            if url.endswith("/chat/completions"):
                resp.json.return_value = {
                    "choices": [{"message": {"content": "Luminous woodcut style prompt"}}],
                    "usage": {"prompt_tokens": 400, "completion_tokens": 120},
                }
            else:
                resp.json.return_value = {"images": [_png_b64()]}
            return resp

        monkeypatch.setattr("ntcdg.style.venice_post", fake_venice_post)
        monkeypatch.setattr("ntcdg.venice.venice_post", fake_venice_post)

        tracker = UsageTracker()
        with usage_tracker_scope(tracker):
            style = extract_style_from_images([str(ref_img)], "test-key")
            assert "woodcut" in style

            card = Card(position=1, title="The Fool", card_type="Major Arcana", symbols=["dog"])
            refined = refine_card_prompt(card, style, "test-key", "llama-3.3-70b")
            assert refined

            sym_out = str(tmp_path / "syms")
            os.makedirs(sym_out, exist_ok=True)
            sym_path = _generate_single_symbol(
                "Golden key symbol", "Key", sym_out, "test-key", "qwen-image-3-pro", 0.0,
            )
            assert sym_path and os.path.isfile(sym_path)

            back_path = generate_card_back(
                "Sacred geometry back", "test-key", "qwen-image-3-pro", "SelfContained",
                rate_limit_delay=0.0,
            )
            assert back_path == os.path.join(
                deck_images_dir("SelfContained"), "SelfContained_BACK.png",
            )
            assert os.path.isfile(back_path)

        purposes = [entry["purpose"] for entry in tracker.call_log]
        assert purposes == ["style_vision", "prompt_refinement", "symbol", "card_back"]
        assert tracker.text_calls == 2
        assert tracker.image_calls == 2


class TestStorageCleanupHistoryAndServices:
    """Verify full delete_deck cleanup, novelty history persistence, locks & services."""

    def test_delete_deck_removes_symbols_previews_and_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        img_dir = deck_images_dir("CleanupDeck")
        os.makedirs(img_dir, exist_ok=True)
        card_img = os.path.join(img_dir, "001_The_Fool.png")
        Image.new("RGB", (64, 96), (20, 30, 40)).save(card_img)
        back_img = os.path.join(img_dir, "CleanupDeck_BACK.png")
        Image.new("RGB", (64, 96), (40, 20, 30)).save(back_img)

        sym_dir = symbols_dir_for("CleanupDeck")
        os.makedirs(sym_dir, exist_ok=True)
        with open(os.path.join(sym_dir, "symbols.json"), "w", encoding="utf-8") as f:
            json.dump({"symbols": [{"name": "dog", "description": "loyal dog"}]}, f)

        raw_prev = preview_raw_dir("CleanupDeck")
        os.makedirs(raw_prev, exist_ok=True)
        Image.new("RGB", (32, 48)).save(os.path.join(raw_prev, "001.png"))

        prev_dir = os.path.join(Config.IMAGES_DIR, "previews")
        os.makedirs(prev_dir, exist_ok=True)
        my_prev = os.path.join(prev_dir, "CleanupDeck_preview_1_The_Fool.png")
        other_prev = os.path.join(prev_dir, "OtherDeck_preview_1_The_Fool.png")
        Image.new("RGB", (32, 48)).save(my_prev)
        Image.new("RGB", (32, 48)).save(other_prev)

        deck = [Card(position=1, title="The Fool", card_type="Major Arcana", image_path=card_img)]
        save_deck(deck, "CleanupDeck", export=False)
        update_deck_index("CleanupDeck", 1, back_image=back_img)

        assert delete_deck("CleanupDeck", confirm=False) is True
        assert not os.path.exists(img_dir)
        assert not os.path.exists(sym_dir)
        assert not os.path.exists(raw_prev)
        assert not os.path.exists(my_prev)
        assert os.path.exists(other_prev)  # other decks' previews untouched!
        assert "CleanupDeck" not in load_decks_index()

    def test_record_deck_history_and_concurrent_card_edits(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))

        cards = [
            Card(
                position=1,
                title="The Fool",
                card_type="Major Arcana",
                symbols=["small white dog", "white rose of purity", "cliff"],
                description="Wanderer at dawn",
                upright_interpretation="Beginnings",
                reversed_interpretation="Recklessness",
            ),
            Card(
                position=2,
                title="The Magician",
                card_type="Major Arcana",
                symbols=["infinity lemniscate", "altar"],
                description="Conduit of will",
                upright_interpretation="Mastery",
                reversed_interpretation="Illusion",
            ),
        ]
        save_deck(cards, "HistDeck", export=False)
        record_deck_history("HistDeck", cards)

        hist = load_history()
        assert "HistDeck" in hist["decks"]
        assert is_novel(Card(symbols=["small white dog", "white rose of purity", "cliff"]), hist) is False
        assert is_novel(Card(symbols=["quantum prism", "obsidian spire", "nebula"]), hist) is True

        # Concurrent edits to different cards on the same deck serialized cleanly by deck_lock
        errors: list[Exception] = []

        def edit_worker(pos: int, new_title: str) -> None:
            try:
                assert edit_card_field("HistDeck", pos, "title", new_title) is True
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        t1 = threading.Thread(target=edit_worker, args=(1, "The Starlit Wanderer"))
        t2 = threading.Thread(target=edit_worker, args=(2, "The Sovereign Architect"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert not errors

        reloaded = load_deck("HistDeck")
        assert reloaded[0].title == "The Starlit Wanderer"
        assert reloaded[0].canonical_title == "The Fool"
        assert reloaded[1].title == "The Sovereign Architect"
        assert reloaded[1].canonical_title == "The Magician"

        # Shared services inspect canonical_title so edited titles still match traditional archetypes!
        summary = get_deck_summary("HistDeck")
        assert summary["total_cards"] == 2
        assert summary["analysis"] == 2
        assert summary["meanings"] == 2

        audit = audit_traditional_coverage("HistDeck")
        assert audit["total_canonical_symbols"] == len(TRADITIONAL_TAROT_SYMBOLS) == 85
        assert audit["canonical_symbols_covered"] >= 3
