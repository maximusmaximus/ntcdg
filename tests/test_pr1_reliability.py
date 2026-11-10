"""Regression tests for PR 1: Venice retry engine, partial-card resume, UTF-8/rc parsing, and PDF safety."""

from __future__ import annotations

import base64
import os
from unittest.mock import MagicMock, patch

import pytest

from ntcdg.config import Config
from ntcdg.models import Card
from ntcdg.storage import load_deck, load_decks_index, save_deck, update_deck_meta
from ntcdg.usage import merge_usage_dicts
from ntcdg.userconfig import _parse_rc_file
from ntcdg.venice import (
    analyze_with_venice,
    generate_image_with_venice,
    parse_json_response,
)


@pytest.fixture()
def isolated_dirs(tmp_path, monkeypatch):
    out_dir = tmp_path / "decks"
    img_dir = out_dir / "images"
    out_dir.mkdir()
    img_dir.mkdir()
    monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr("ntcdg.config.Config.IMAGES_DIR", str(img_dir))
    monkeypatch.setattr("ntcdg.config.Config.DECKS_INDEX_FILE", str(out_dir / "decks_index.json"))
    monkeypatch.setattr("ntcdg.finalize.Config.OUTPUT_DIR", str(out_dir))
    return out_dir


class TestVeniceRetryEngine:
    """Verify Venice endpoints actually retry transient errors and fail fast on 4xx."""

    def test_analyze_retries_on_429_and_respects_retry_after(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr("ntcdg.venice.time.sleep", lambda s: sleeps.append(s))

        rate_resp = MagicMock()
        rate_resp.status_code = 429
        rate_resp.headers = {"Retry-After": "3.5"}

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {
            "choices": [{
                "message": {
                    "content": '```json\n{"new_title": "The Awakened", "description": "Dawn", '
                               '"serial": "VNX-1", "upright_interpretation": "Up", '
                               '"reversed_interpretation": "Rev"}\n```'
                }
            }],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }

        mock_req = MagicMock()
        mock_req.post.side_effect = [rate_resp, ok_resp]

        card = Card(position=1, title="The Fool", card_type="Major Arcana", symbols=["sun"])
        with patch("ntcdg.venice.requests", mock_req):
            result = analyze_with_venice(card, "sk-key", Config.DEFAULT_TEXT_MODEL)

        assert "venice_error" not in result
        assert result["new_title"] == "The Awakened"
        assert mock_req.post.call_count == 2
        assert sleeps == [3.5]

    def test_analyze_fails_fast_on_401_without_retrying(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr("ntcdg.venice.time.sleep", lambda s: sleeps.append(s))

        err_resp = MagicMock()
        err_resp.status_code = 401
        err_resp.headers = {}
        auth_exc = RuntimeError("401 Unauthorized")
        auth_exc.response = err_resp
        err_resp.raise_for_status.side_effect = auth_exc

        mock_req = MagicMock()
        mock_req.post.return_value = err_resp

        card = Card(position=1, title="The Fool", card_type="Major Arcana")
        with patch("ntcdg.venice.requests", mock_req):
            result = analyze_with_venice(card, "sk-bad", Config.DEFAULT_TEXT_MODEL)

        assert "venice_error" in result
        assert mock_req.post.call_count == 1
        assert sleeps == []

    def test_generate_image_retries_on_503_then_succeeds(self, isolated_dirs, monkeypatch):
        monkeypatch.setattr("ntcdg.venice.time.sleep", lambda _s: None)

        bad_resp = MagicMock()
        bad_resp.status_code = 503
        bad_resp.headers = {}

        png_bytes = b"\x89PNG\r\n\x1a\nok"
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"images": [base64.b64encode(png_bytes).decode()]}

        mock_req = MagicMock()
        mock_req.post.side_effect = [bad_resp, ok_resp]

        card = Card(position=1, title="The Fool", prompt="fool art")
        with patch("ntcdg.venice.requests", mock_req):
            res = generate_image_with_venice(
                card, "sk-key", Config.DEFAULT_IMAGE_MODEL,
                rate_limit_delay=0, output_dir=str(isolated_dirs / "images"),
            )

        assert "image_error" not in res
        assert os.path.isfile(res["image_path"])
        assert mock_req.post.call_count == 2

    def test_parse_json_response_variants(self):
        assert parse_json_response('{"a": 1}') == {"a": 1}
        assert parse_json_response("Here is JSON:\n```json\n{\"b\": 2}\n```") == {"b": 2}
        assert parse_json_response("Sure! {\"c\": 3} Hope that helps.") == {"c": 3}


class TestResumeAndRetryPreservation:
    """Verify retry_failed / resume keeps partial card stages, deck_style, and cumulative usage."""

    def test_resume_preserves_existing_analysis_when_only_image_failed(self, isolated_dirs, monkeypatch):
        from PIL import Image

        from ntcdg.generator import generate_deck

        # Card 1 has completed text analysis, but its image failed earlier
        partial = Card(
            position=1,
            title="The Fool",
            card_type="Major Arcana",
            arcana_number=0,
            symbols=["small white dog", "cliff"],
            layout="spiral",
            new_title="The Quantum Leap",
            description="Existing rich description — must not be overwritten!",
            upright_interpretation="Bold beginning.",
            reversed_interpretation="Reckless step.",
            image_error="503 Service Unavailable",
        )
        save_deck([partial], "ResumeDeck")
        update_deck_meta(
            "ResumeDeck",
            target_cards=1,
            vibe="celestial ink",
            theme="stars",
            deck_style="Locked celestial ink style",
            usage={
                "text_calls": 1,
                "prompt_tokens": 200,
                "completion_tokens": 120,
                "total_tokens": 320,
                "image_calls": 1,
                "image_calls_failed": 1,
                "elapsed_seconds": 4.2,
                "estimated_cost_usd": {"text": 0.0005, "image": 0.01, "total": 0.0105},
            },
        )

        analyze_spy = MagicMock()
        style_spy = MagicMock()

        def fake_gen_image(card, api_key, model, **kwargs):
            out_dir = kwargs["output_dir"]
            os.makedirs(out_dir, exist_ok=True)
            img_path = os.path.join(out_dir, "001_The_Fool.png")
            Image.new("RGB", (120, 200), (30, 40, 80)).save(img_path)
            if kwargs.get("tracker"):
                kwargs["tracker"].record_image_call(model, "768x1280", success=True)
            return {"image_path": img_path, "image_model": model, "image_size": "768x1280"}

        monkeypatch.setattr("ntcdg.generator.analyze_with_venice", analyze_spy)
        monkeypatch.setattr("ntcdg.generator.extract_deck_style", style_spy)
        monkeypatch.setattr("ntcdg.generator.refine_card_prompt", lambda c, s, *_a: f"{s} | {c.title}")
        monkeypatch.setattr("ntcdg.generator.generate_image_with_venice", fake_gen_image)

        generate_deck(
            name="ResumeDeck",
            num_cards=1,
            venice_key="sk-key",
            analyze=True,
            generate_images=True,
            interactive=False,
            resume=True,
            preview=False,
        )

        # Analysis and style extraction must NOT have been re-called
        analyze_spy.assert_not_called()
        style_spy.assert_not_called()

        reloaded = load_deck("ResumeDeck")
        assert len(reloaded) == 1
        c = reloaded[0]
        assert c.new_title == "The Quantum Leap"
        assert c.description == "Existing rich description — must not be overwritten!"
        assert c.image_error is None
        assert c.image_path and os.path.isfile(c.image_path)

        # Usage stats must have merged additively rather than wiping text_calls
        meta = load_decks_index()["ResumeDeck"]
        assert meta["usage"]["text_calls"] == 1
        assert meta["usage"]["image_calls"] == 2

    def test_mcp_retry_failed_restores_saved_symbol_and_model_config(self, isolated_dirs, monkeypatch):
        from ntcdg.mcp_server import retry_failed

        monkeypatch.setenv("VENICE_API_KEY", "sk-key")
        sym_file = isolated_dirs / "my_syms.json"
        sym_file.write_text('{"symbols": [{"name": "rose", "description": "red rose"}]}', encoding="utf-8")

        save_deck([Card(position=1, title="The Fool")], "CustomCfg")
        update_deck_meta(
            "CustomCfg",
            target_cards=22,
            symbol_mode="provide",
            symbols_file=str(sym_file),
            traditional_mode=False,
            image_model="flux-2-max",
            text_model="llama-3.3-70b",
            image_size="768x1280",
        )

        with patch("ntcdg.generator.generate_deck") as gen:
            retry_failed("CustomCfg")

        kw = gen.call_args.kwargs
        assert kw["symbol_mode"] == "provide"
        assert kw["symbols_file"] == str(sym_file)
        assert kw["traditional_mode"] is False
        assert kw["image_model"] == "flux-2-max"

    def test_merge_usage_dicts(self):
        prev = {
            "text_calls": 2,
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "image_calls": 1,
            "elapsed_seconds": 5.0,
            "estimated_cost_usd": {"text": 0.01, "image": 0.02, "total": 0.03},
        }
        curr = {
            "text_calls": 1,
            "prompt_tokens": 40,
            "completion_tokens": 20,
            "total_tokens": 60,
            "image_calls": 2,
            "elapsed_seconds": 3.2,
            "estimated_cost_usd": {"text": 0.005, "image": 0.04, "total": 0.045},
        }
        merged = merge_usage_dicts(prev, curr)
        assert merged["text_calls"] == 3
        assert merged["total_tokens"] == 210
        assert merged["image_calls"] == 3
        assert merged["elapsed_seconds"] == 8.2
        assert merged["estimated_cost_usd"]["total"] == 0.075


class TestConfigAndPdfEdgeCases:
    def test_rc_file_parses_windows_drive_path_and_utf8(self, tmp_path):
        rc = tmp_path / ".ntcdgrc"
        rc.write_text(
            'default_font = C:\\Windows\\Fonts\\georgia.ttf\n'
            'default_vibe: "Étoile — Astral Tarot ✨"\n',
            encoding="utf-8",
        )
        parsed = _parse_rc_file(str(rc))
        assert parsed["default_font"] == r"C:\Windows\Fonts\georgia.ttf"
        assert parsed["default_vibe"] == "Étoile — Astral Tarot ✨"

    def test_proof_sheet_escapes_xml_special_chars(self, isolated_dirs):
        from ntcdg.generator import create_proof_sheet_pdf

        cards = [
            Card(position=1, title="The Fool", new_title="Chaos & Order <Alpha>"),
        ]
        pdf = create_proof_sheet_pdf(cards, "Ampersand_&_Deck")
        assert pdf and os.path.isfile(pdf)

    def test_finalize_does_not_publish_when_pdf_generation_fails(self, isolated_dirs, monkeypatch):
        from PIL import Image

        from ntcdg.finalize import finalize_deck_report

        img = isolated_dirs / "images" / "001_The_Fool.png"
        Image.new("RGB", (300, 500), (20, 20, 20)).save(img)
        card = Card(
            position=1,
            title="The Fool",
            description="Desc",
            upright_interpretation="Up",
            reversed_interpretation="Rev",
            image_path=str(img),
        )
        save_deck([card], "FailPrint")

        monkeypatch.setattr("ntcdg.duplex.create_duplex_pdfs", lambda *_a, **_kw: {})
        res = finalize_deck_report(
            "FailPrint",
            public_base_url="https://decks.grok.me",
        )
        assert res["success"] is False
        meta = load_decks_index()["FailPrint"]
        assert not meta.get("published")
