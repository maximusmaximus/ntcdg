"""Regression tests for PR 2: card framing, title model, and two-pass provide pipeline."""

from __future__ import annotations

import base64
import json
import os
from unittest.mock import MagicMock, patch

import requests
from PIL import Image

from ntcdg.config import Config
from ntcdg.models import Card
from ntcdg.overlay import compose_card, recompose_card, unframed_image_path
from ntcdg.public import card_slug
from ntcdg.storage import (
    clone_deck,
    delete_deck,
    edit_card_field,
    load_deck,
    save_deck,
    update_deck_meta,
)
from ntcdg.usage import UsageTracker
from ntcdg.venice import (
    edit_image_with_venice,
    generate_image_with_venice,
    multi_edit_image_with_venice,
)


def _make_png(path: str, color: tuple[int, int, int] = (40, 80, 160), size=(400, 640)) -> bytes:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    img = Image.new("RGB", size, color)
    img.save(path, format="PNG")
    with open(path, "rb") as f:
        return f.read()


class TestCardFramingAndTitleEdits:
    """Verify raw artwork preservation, long-title wrapping, and re-composition."""

    def test_compose_preserves_raw_and_wraps_long_titles(self, tmp_path):
        card_path = str(tmp_path / "DeckA" / "001_The_Fool.png")
        _make_png(card_path, color=(30, 120, 90))

        long_title = "The Sovereign Keeper of the Celestial Astral Labyrinth Beyond Time"
        compose_card(
            image_path=card_path,
            title=long_title,
            card_number="0",
            card_type="Major Arcana",
        )

        raw_sidecar = unframed_image_path(card_path)
        assert os.path.isfile(raw_sidecar)
        with Image.open(card_path) as framed:
            assert framed.size == (768, 1280)
            # Outer bleed margin (x=10) must stay background near-black (not clipped by text)
            for y in range(1120, 1240, 10):
                r, g, b = framed.getpixel((10, y))
                assert max(r, g, b) < 35

    def test_edit_card_updates_display_title_recomposes_png_and_keeps_slug(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr("ntcdg.config.Config.IMAGES_DIR", str(tmp_path / "images"))

        img_path = str(tmp_path / "images" / "EditDeck" / "001_The_Fool.png")
        _make_png(img_path, color=(150, 50, 80))

        card = Card(
            position=1,
            title="The Fool",
            card_type="Major Arcana",
            arcana_number=0,
            venice_title="Old AI Title",
            new_title="Old AI Title",
            image_path=img_path,
        )
        compose_card(
            image_path=img_path,
            title=card.display_title(),
            card_number="0",
            card_type="Major Arcana",
        )
        with open(img_path, "rb") as f:
            before_bytes = f.read()

        save_deck([card], "EditDeck", export=False)

        assert edit_card_field("EditDeck", 1, "title", "Starlight Pilgrim") is True
        reloaded = load_deck("EditDeck")[0]

        assert reloaded.title == "Starlight Pilgrim"
        assert reloaded.display_title() == "Starlight Pilgrim"
        assert reloaded.canonical_title == "The Fool"
        assert card_slug(reloaded) == "01-the-fool"

        with open(img_path, "rb") as f:
            after_bytes = f.read()
        assert after_bytes != before_bytes

    def test_clone_and_delete_handle_unframed_sidecars(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr("ntcdg.config.Config.IMAGES_DIR", str(tmp_path / "images"))

        img_path = str(tmp_path / "images" / "SrcDeck" / "001_The_Fool.png")
        _make_png(img_path, color=(80, 90, 110))
        compose_card(image_path=img_path, title="The Fool", card_number="0")

        save_deck([Card(position=1, title="The Fool", image_path=img_path)], "SrcDeck", export=False)
        assert clone_deck("SrcDeck", "ClonedDeck") is True

        cloned_card = load_deck("ClonedDeck")[0]
        assert os.path.isfile(unframed_image_path(cloned_card.image_path))
        assert recompose_card(cloned_card) is True

        assert delete_deck("SrcDeck", confirm=False) is True
        assert not os.path.exists(str(tmp_path / "images" / "SrcDeck"))


class TestVeniceMultiEditAndTwoPassProvide:
    """Verify /image/edit clamping + MIME, /image/multi-edit fallback, and 2-pass provide."""

    def test_edit_image_clamps_dimensions_and_preserves_jpeg_source(self, tmp_path):
        jpg_path = str(tmp_path / "sketch.jpg")
        img = Image.new("RGB", (200, 300), (200, 160, 90))
        img.save(jpg_path, format="JPEG")
        with open(jpg_path, "rb") as f:
            orig_jpg = f.read()

        captured_payloads: list[dict] = []
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "image/png"}
        mock_resp.content = b"\x89PNG\r\n\x1a\nedited_png_payload"

        def fake_post(url, headers=None, json=None, timeout=None):
            captured_payloads.append(json)
            return mock_resp

        mock_req = MagicMock()
        mock_req.post.side_effect = fake_post

        with patch("ntcdg.venice.requests", mock_req):
            res = edit_image_with_venice(
                base_image_path=jpg_path,
                edit_prompt="Add botanical linework",
                api_key="sk-test",
                image_size="1800x3000",
                rate_limit_delay=0,
            )

        assert res["edited"] is True
        assert res["image_path"] == str(tmp_path / "sketch_edited.png")
        with open(jpg_path, "rb") as f:
            assert f.read() == orig_jpg

        sent = captured_payloads[0]
        assert sent["width"] <= 1280 and sent["width"] % 8 == 0
        assert sent["height"] <= 1280 and sent["height"] % 8 == 0
        assert sent["image"].startswith("data:image/jpeg;base64,")

    def test_multi_edit_falls_back_to_single_edit_on_422(self, tmp_path):
        base_img = str(tmp_path / "base.png")
        ref_img = str(tmp_path / "serpent.png")
        _make_png(base_img)
        _make_png(ref_img, color=(20, 200, 80))

        calls: list[str] = []

        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append(url)
            if url == Config.VENICE_MULTI_EDIT_URL:
                resp_422 = MagicMock()
                resp_422.status_code = 422
                err = requests.HTTPError("422 Unprocessable")
                err.response = resp_422
                resp_422.raise_for_status.side_effect = err
                return resp_422
            resp_ok = MagicMock()
            resp_ok.status_code = 200
            resp_ok.headers = {"content-type": "image/png"}
            resp_ok.content = b"\x89PNG\r\n\x1a\nfallback_edited"
            return resp_ok

        mock_req = MagicMock()
        mock_req.post.side_effect = fake_post

        out_file = str(tmp_path / "final_card.png")
        with patch("ntcdg.venice.requests", mock_req):
            res = multi_edit_image_with_venice(
                [base_img, ref_img],
                "Integrate serpent reference",
                "sk-test",
                output_path=out_file,
                rate_limit_delay=0,
            )

        assert calls == [Config.VENICE_MULTI_EDIT_URL, Config.VENICE_EDIT_URL]
        assert res["image_path"] == out_file
        assert os.path.isfile(out_file)

    def test_two_pass_provide_uses_multi_edit_deck_vibe_and_tracks_both_calls(self, tmp_path):
        sym_serpent = str(tmp_path / "symbols" / "serpent.png")
        sym_chalice = str(tmp_path / "symbols" / "the_chalice.png")
        png_bytes = _make_png(sym_serpent, color=(10, 180, 60))
        _make_png(sym_chalice, color=(200, 180, 40))

        calls: list[tuple[str, dict]] = []

        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append((url, json))
            resp = MagicMock()
            resp.status_code = 200
            if url == Config.VENICE_IMAGE_URL:
                resp.headers = {"content-type": "application/json"}
                resp.json.return_value = {"images": [base64.b64encode(png_bytes).decode()]}
            else:
                resp.headers = {"content-type": "image/png"}
                resp.content = png_bytes
            return resp

        mock_req = MagicMock()
        mock_req.post.side_effect = fake_post

        card = Card(
            position=1,
            title="The Magician",
            card_type="Major Arcana",
            symbols=["ouroboros serpent", "infinity"],
            deck_vibe="botanical woodcut engraving",
            prompt="The Magician standing in the ritual garden with an ouroboros serpent",
        )
        tracker = UsageTracker()
        out_dir = str(tmp_path / "deck_imgs")

        with patch("ntcdg.venice.requests", mock_req):
            res = generate_image_with_venice(
                card,
                api_key="sk-test",
                model="qwen-image-3-pro",
                symbol_mode="provide",
                symbol_images={
                    "Ouroboros Serpent": sym_serpent,
                    "The Chalice": sym_chalice,  # "the" stopword must NOT match prompt!
                },
                rate_limit_delay=0,
                tracker=tracker,
                output_dir=out_dir,
            )

        assert res["symbol_mode"] == "provide"
        assert res["used_symbol_images"] == ["Ouroboros Serpent"]
        assert os.path.basename(res["image_path"]) == "001_The_Magician.png"
        assert not any(f.startswith(".tmp_pass1_") for f in os.listdir(out_dir))

        assert [u for u, _ in calls] == [Config.VENICE_IMAGE_URL, Config.VENICE_MULTI_EDIT_URL]
        multi_payload = calls[1][1]
        assert len(multi_payload["images"]) == 2  # base + 1 matched symbol
        assert "botanical woodcut engraving" in multi_payload["prompt"]
        assert "psychedelic neon glitch" not in multi_payload["prompt"]
        assert tracker.image_calls == 2

    def test_generate_single_card_uses_compose_card_and_saved_symbol_mode(
        self, tmp_path, monkeypatch
    ):
        from ntcdg.mcp_server import generate_single_card

        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr("ntcdg.config.Config.IMAGES_DIR", str(tmp_path / "images"))
        monkeypatch.setenv("VENICE_API_KEY", "sk-test")

        sym_img = str(tmp_path / "sym_rose.png")
        png_bytes = _make_png(sym_img, color=(190, 40, 70), size=(300, 300))
        sym_json = str(tmp_path / "symbols.json")
        with open(sym_json, "w", encoding="utf-8") as f:
            json.dump(
                {"symbols": [{"name": "Mystic Rose", "image": sym_img}]},
                f,
            )

        save_deck(
            [
                Card(
                    position=1,
                    title="The Fool",
                    card_type="Major Arcana",
                    arcana_number=0,
                    symbols=["Mystic Rose"],
                    deck_vibe="ink botanical",
                )
            ],
            "SingleDeck",
            export=False,
        )
        update_deck_meta(
            "SingleDeck",
            deck_style="LOCKED_INK_STYLE",
            symbol_mode="provide",
            symbols_file=sym_json,
        )

        captured_gen_kwargs: dict = {}

        def fake_gen_img(card, api_key, model, **kwargs):
            captured_gen_kwargs.update(kwargs)
            out_p = os.path.join(kwargs["output_dir"], "001_The_Fool.png")
            os.makedirs(kwargs["output_dir"], exist_ok=True)
            with open(out_p, "wb") as f:
                f.write(png_bytes)
            return {"image_path": out_p, "image_model": model, "symbol_mode": "provide"}

        with (
            patch("ntcdg.style.refine_card_prompt", side_effect=lambda c, s, *a: f"{s}:{c.title}"),
            patch(
                "ntcdg.venice.analyze_with_venice",
                return_value={
                    "new_title": "The Blooming Step",
                    "description": "Botanical fool",
                    "upright_interpretation": "Begin",
                    "reversed_interpretation": "Pause",
                },
            ),
            patch("ntcdg.venice.generate_image_with_venice", side_effect=fake_gen_img),
        ):
            out = generate_single_card("SingleDeck", 1)

        assert out["has_image"] is True
        assert out["title"] == "The Blooming Step"
        assert captured_gen_kwargs["symbol_mode"] == "provide"
        assert "Mystic Rose" in captured_gen_kwargs["symbol_images"]
        with Image.open(out["image_path"]) as im:
            assert im.size == (768, 1280)
