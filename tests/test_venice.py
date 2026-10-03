"""Tests for Venice.ai API integration: model defaults, image edit, and response parsing."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

from ntcdg.config import Config
from ntcdg.venice import (
    _build_image_request,
    _extract_text_content,
    _parse_image_size,
    edit_image_with_venice,
)


class TestVeniceModelsAndDefaults:
    """Test Venice model configurations and dimensions."""

    def test_default_models(self):
        """Verify SOTA 2026 default models are configured."""
        assert Config.DEFAULT_IMAGE_MODEL == "qwen-image-3-pro"
        assert Config.DEFAULT_EDIT_MODEL == "qwen-image-3-pro"
        assert Config.DEFAULT_VISION_MODEL == "qwen3-vl-235b-a22b"
        assert Config.DEFAULT_TEXT_MODEL == "llama-3.3-70b"

    def test_default_image_size_is_tarot_ratio(self):
        """Default image size 768x1280 matches standard tarot 3:5 bleed ratio."""
        assert Config.DEFAULT_IMAGE_SIZE == "768x1280"
        w, h = _parse_image_size(Config.DEFAULT_IMAGE_SIZE)
        assert w == 768
        assert h == 1280
        assert w / h == 0.60
        # Venice constraint: max 1280 and multiple of 8
        assert w <= 1280 and h <= 1280
        assert w % 8 == 0 and h % 8 == 0

    def test_build_image_request_clamping(self):
        """Dimensions exceeding 1280 should be scaled down preserving ratio."""
        req = _build_image_request("qwen-image-3-pro", "test prompt", "1500x2500")
        assert req["width"] <= 1280
        assert req["height"] <= 1280
        assert req["width"] % 8 == 0
        assert req["height"] % 8 == 0
        assert req["model"] == "qwen-image-3-pro"


class TestVeniceImageEdit:
    """Test Venice /image/edit endpoint handling."""

    def test_edit_handles_binary_stream(self, tmp_path):
        """edit_image_with_venice should save raw binary PNG/JPEG responses."""
        img_path = str(tmp_path / "base.png")
        with open(img_path, "wb") as f:
            f.write(b"fake_base_image")

        fake_binary_png = b"\x89PNG\r\n\x1a\nfake_edited_bytes"
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "image/png"}
        mock_resp.content = fake_binary_png

        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_resp

        with patch("ntcdg.venice.requests", mock_requests):
            result = edit_image_with_venice(
                base_image_path=img_path,
                edit_prompt="Add gothic details",
                api_key="sk-test-key",
                model="qwen-image-3-pro",
                enhance_prompt=True,
                rate_limit_delay=0,
            )

        assert result.get("edited") is True
        assert result.get("image_model") == "qwen-image-3-pro"
        edited_path = result["image_path"]
        with open(edited_path, "rb") as f:
            assert f.read() == fake_binary_png

    def test_edit_handles_json_payload(self, tmp_path):
        """edit_image_with_venice should extract base64 from JSON responses."""
        img_path = str(tmp_path / "base2.png")
        with open(img_path, "wb") as f:
            f.write(b"fake_base_image_2")

        fake_edited = b"new_edited_content"
        b64_content = base64.b64encode(fake_edited).decode()

        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.content = b'{"images": ["test"]}'
        mock_resp.json.return_value = {"images": [b64_content]}

        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_resp

        with patch("ntcdg.venice.requests", mock_requests):
            result = edit_image_with_venice(
                base_image_path=img_path,
                edit_prompt="Add chalice",
                api_key="sk-test-key",
                rate_limit_delay=0,
            )

        assert result.get("edited") is True
        edited_path = result["image_path"]
        with open(edited_path, "rb") as f:
            assert f.read() == fake_edited


class TestVeniceResponseParsing:
    """Test text response parsing for regular and reasoning models."""

    def test_extract_text_standard(self):
        resp = {"choices": [{"message": {"content": "Standard response"}}]}
        assert _extract_text_content(resp) == "Standard response"

    def test_extract_text_reasoning_fallback(self):
        resp = {"choices": [{"message": {"content": "", "reasoning_content": "Reasoned response"}}]}
        assert _extract_text_content(resp) == "Reasoned response"
