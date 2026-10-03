"""Edge-case tests for the end-to-end deck workflow.

Covers the bugs found in review: index metadata being wiped, unsafe deck
names, shared back images after cloning, the duplex_flip TypeError, lost
pip counts, resume/checkpoint behaviour, symbol-generation failures and
exact-match artifact handling.
"""

from __future__ import annotations

import json
import os
import threading
from unittest.mock import patch

import pytest
from PIL import Image

from ntcdg.models import Card


@pytest.fixture
def out(tmp_path, monkeypatch):
    """Isolated output dir (and cwd, so legacy relative paths stay in tmp)."""
    out_dir = tmp_path / "generated_decks"
    out_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr("ntcdg.config.Config.IMAGES_DIR", str(out_dir / "images"))
    monkeypatch.delenv("VENICE_API_KEY", raising=False)
    return out_dir


def _png(path, color=(10, 20, 30), size=(60, 100)):
    Image.new("RGB", size, color).save(path)
    return str(path)


def _complete_card(pos, img):
    return Card(
        position=pos, title=f"Card {pos}", card_type="Major Arcana", image_path=img,
        description="d", upright_interpretation="u", reversed_interpretation="r",
    )


def _offline_generate(name, num_cards, **kw):
    from ntcdg.generator import generate_deck
    params = dict(
        name=name, num_cards=num_cards, vibe="test vibe", deck_prompt="theme",
        venice_key=None, analyze=False, text_model="t", generate_images=False,
        image_model="i", image_size="768x1280", negative_prompt="", rate_limit=0,
        interactive=False, preview=False,
    )
    params.update(kw)
    return generate_deck(**params)


# ==================== INDEX / STORAGE ====================

class TestIndexIntegrity:
    def test_save_deck_preserves_metadata(self, out):
        from ntcdg.storage import load_decks_index, save_deck, update_deck_meta

        save_deck([Card(position=1, title="The Fool")], "Meta")
        update_deck_meta("Meta", vibe="noir", theme="rain", usage={"total": 1},
                         public_slug="meta-abc123")
        save_deck([Card(position=1, title="The Fool"), Card(position=2, title="X")], "Meta")

        meta = load_decks_index()["Meta"]
        assert meta["vibe"] == "noir"
        assert meta["theme"] == "rain"
        assert meta["usage"] == {"total": 1}
        assert meta["public_slug"] == "meta-abc123"
        assert meta["num_cards"] == 2

    def test_update_deck_index_none_means_unchanged(self, out):
        from ntcdg.storage import load_decks_index, update_deck_index

        update_deck_index("D", 3, vibe="v", theme="t", back_image="b.png", back_prompt="p")
        update_deck_index("D", 4)
        meta = load_decks_index()["D"]
        assert (meta["vibe"], meta["theme"], meta["back_image"]) == ("v", "t", "b.png")
        assert meta["num_cards"] == 4

    def test_concurrent_meta_updates_are_not_lost(self, out):
        from ntcdg.storage import load_decks_index, update_deck_meta

        def worker(i):
            for j in range(10):
                update_deck_meta(f"Deck{i}", **{f"k{j}": j})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        index = load_decks_index()
        for i in range(6):
            assert all(index[f"Deck{i}"][f"k{j}"] == j for j in range(10))

    def test_corrupt_index_does_not_crash(self, out):
        from ntcdg.storage import _get_decks_index_file, load_decks_index, update_deck_meta

        with open(_get_decks_index_file(), "w") as f:
            f.write("{not json")
        assert load_decks_index() == {}
        update_deck_meta("Fresh", vibe="x")  # recovers by rewriting atomically
        assert load_decks_index()["Fresh"]["vibe"] == "x"

    def test_no_temp_files_left_behind(self, out):
        from ntcdg.storage import save_deck

        save_deck([Card(position=1, title="A")], "Tidy")
        assert not [f for f in os.listdir(out) if f.startswith(".tmp_")]


class TestDeckNameSafety:
    @pytest.mark.parametrize("bad", ["../evil", "a/b", "a\\b", "", "x" * 101, "sp ace", ".."])
    def test_storage_rejects_unsafe_names(self, out, bad):
        from ntcdg.storage import deck_exists, load_deck, save_deck, update_deck_meta

        for fn in (lambda: load_deck(bad), lambda: deck_exists(bad),
                   lambda: save_deck([], bad), lambda: update_deck_meta(bad, a=1)):
            with pytest.raises(ValueError):
                fn()

    def test_mcp_tools_return_errors_for_unsafe_names(self, out):
        from ntcdg.mcp_server import complete_symbols, create_deck, register_symbols

        assert create_deck(name="../x")["success"] is False
        assert register_symbols("../x", [{"name": "a", "image_path": "x"}])["success"] is False
        assert complete_symbols("../x")["success"] is False


class TestCloneAndDelete:
    def test_clone_gets_independent_back_image(self, out, tmp_path):
        from ntcdg.storage import clone_deck, delete_deck, load_decks_index, save_deck, update_deck_meta

        img = _png(tmp_path / "c1.png")
        back = _png(tmp_path / "back.png")
        save_deck([_complete_card(1, img)], "Src")
        update_deck_meta("Src", back_image=back, back_prompt="stars")

        assert clone_deck("Src", "Dst")
        dst_back = load_decks_index()["Dst"]["back_image"]
        assert dst_back and dst_back != back and os.path.exists(dst_back)
        assert load_decks_index()["Dst"]["back_prompt"] == "stars"

        delete_deck("Src", confirm=False)
        assert os.path.exists(dst_back)

    def test_delete_only_touches_exact_deck_artifacts(self, out):
        from ntcdg.storage import deck_artifact_files, delete_deck, save_deck

        save_deck([Card(position=1, title="A")], "a")
        save_deck([Card(position=1, title="B")], "a_PRINT_x")
        for name in ("a_PRINT_letter_color.pdf", "a_PRINT_x_PRINT_letter_color.pdf",
                     "a_PRINT_x_BOOKLET.pdf", "a_BOOKLET.pdf", "a_notes.txt"):
            (out / name).write_bytes(b"%PDF")

        mine = {os.path.basename(p) for p in deck_artifact_files("a")}
        assert {"a_PRINT_letter_color.pdf", "a_BOOKLET.pdf"} <= mine
        assert "a_PRINT_x_PRINT_letter_color.pdf" not in mine
        assert "a_PRINT_x_BOOKLET.pdf" not in mine

        delete_deck("a", confirm=False)
        assert (out / "a_PRINT_x_PRINT_letter_color.pdf").exists()
        assert (out / "a_PRINT_x_BOOKLET.pdf").exists()
        assert (out / "a_PRINT_x.json").exists()
        assert (out / "a_notes.txt").exists()  # unknown files are never deleted
        assert not (out / "a.json").exists()


# ==================== GENERATION ====================

class TestCardSymbols:
    def test_traditional_mode_keeps_pip_count(self):
        from ntcdg.generator import generate_card

        card = generate_card(
            5, 78, {"type": "Minor Arcana", "title": "3 of Cups", "suit": "Cups", "rank": 3},
            "vibe", traditional_mode=True,
        )
        assert card.symbols[0] == "3 glowing cups"
        assert len(card.symbols) > 1

    def test_court_cards_get_suit_emblem(self):
        from ntcdg.generator import generate_card

        card = generate_card(
            5, 78, {"type": "Minor Arcana", "title": "Queen of Swords", "suit": "Swords",
                    "rank": "Queen"}, "vibe", traditional_mode=True,
        )
        assert card.symbols[0] == "prominent swords"

    def test_precomputed_analysis_matches_inline(self):
        from ntcdg.symbols import TraditionalDeckRegistry as R

        artist = [{"name": "Golden Chalice", "description": "cup"}, {"name": "Hound"}]
        card_def = {"type": "Minor Arcana", "title": "Ace of Cups", "suit": "Cups", "rank": "Ace"}
        inline = R.assign_symbols_for_card(card_def, artist)
        pre = R.assign_symbols_for_card(card_def, artist, analysis=R.match_artist_symbols(artist))
        assert inline == pre


class TestGenerateDeckWorkflow:
    def test_events_fire_in_order_and_callback_errors_are_swallowed(self, out):
        events = []

        def on_event(ev):
            events.append(ev["type"])
            if ev["type"] == "card_prompt":
                raise RuntimeError("UI hook exploded")

        _offline_generate("Ev", 3, on_event=on_event)

        assert events[0] == "deck_started"
        assert events[-1] == "deck_done"
        assert events.count("card_started") == 3
        assert events.count("card_done") == 3

    def test_artist_symbols_matched_once_per_deck(self, out):
        from ntcdg.symbols import TraditionalDeckRegistry

        with patch.object(TraditionalDeckRegistry, "match_artist_symbols",
                          wraps=TraditionalDeckRegistry.match_artist_symbols) as spy:
            _offline_generate("Once", 6)
        assert spy.call_count == 1

    def test_missing_key_non_interactive_raises_value_error(self, out):
        with pytest.raises(ValueError):
            _offline_generate("NoKey", 2, analyze=True)

    def test_checkpoint_then_resume_completes_without_duplicates(self, out):
        from ntcdg import generator
        from ntcdg.storage import load_deck, load_decks_index

        real = generator.generate_card

        def flaky(position, *a, **kw):
            if position == 3:
                raise RuntimeError("crash mid-run")
            return real(position, *a, **kw)

        with patch.object(generator, "generate_card", side_effect=flaky), \
                pytest.raises(RuntimeError):
            _offline_generate("Crash", 30)

        partial = load_deck("Crash")
        assert [c.position for c in partial] == [1, 2]  # checkpointed before the crash
        assert load_decks_index()["Crash"]["target_cards"] == 30
        assert load_decks_index()["Crash"]["vibe"] == "test vibe"

        first_two = [c.title for c in partial]
        _offline_generate("Crash", 30, resume=True)
        final = load_deck("Crash")
        assert len(final) == 30
        assert [c.title for c in final[:2]] == first_two
        titles = [c.title for c in final]
        assert len(set(titles)) == 30, "resume must not duplicate cards"

    def test_usage_written_without_wiping_back(self, out, tmp_path):
        from ntcdg.storage import load_decks_index, save_deck, update_deck_meta

        save_deck([Card(position=1, title="The Fool")], "Keep")
        update_deck_meta("Keep", back_image="b.png", back_prompt="p")
        _offline_generate("Keep", 2)
        meta = load_decks_index()["Keep"]
        assert meta["back_image"] == "b.png"
        assert "usage" in meta


def test_align_card_defs_keeps_identity_and_uniqueness():
    from ntcdg.generator import align_card_defs_with_existing, build_canonical_deck

    first = build_canonical_deck(40)
    existing = {
        i + 1: Card(position=i + 1, title=d["title"], card_type=d["type"],
                    suit=d["suit"], rank=d["rank"], arcana_number=d["arcana_number"])
        for i, d in enumerate(first[:35])
    }
    rebuilt = build_canonical_deck(40)  # minor arcana reshuffled
    aligned = align_card_defs_with_existing(rebuilt, existing)

    assert [d["title"] for d in aligned[:35]] == [d["title"] for d in first[:35]]
    assert len({d["title"] for d in aligned}) == 40


# ==================== SYMBOLS ====================

class TestSymbolGenerationFailures:
    def test_failed_symbols_counted_separately(self, out):
        from ntcdg.symbols import TraditionalDeckRegistry, symbols_dir_for

        calls = {"n": 0}

        def sometimes(**kw):
            calls["n"] += 1
            if calls["n"] % 2 == 0:
                raise RuntimeError("Venice 500")
            return os.path.join(kw["output_dir"], "ok.png")

        with patch("ntcdg.symbols._generate_single_symbol", side_effect=sometimes):
            cfg = TraditionalDeckRegistry.complete_deck_symbols(
                {"symbols": []}, "Fail", "", "k", "m", target_scope="suits",
                max_missing=4, rate_limit=0,
            )

        assert cfg["generated_symbol_count"] == 2
        assert cfg["failed_symbol_count"] == 2
        assert len(cfg["symbols"]) == 2
        assert all(s["image"] for s in cfg["symbols"])
        manifest = os.path.join(symbols_dir_for("Fail"), "symbols.json")
        assert os.path.exists(manifest)
        assert manifest.startswith(os.path.join(str(out), "symbols"))

    def test_generate_symbol_images_survives_errors(self, out):
        from ntcdg.symbols import generate_symbol_images

        cfg = {"symbols": [{"name": "A", "description": "a"}, {"name": "B", "description": "b"}]}
        with patch("ntcdg.symbols._generate_single_symbol", side_effect=RuntimeError("boom")):
            result = generate_symbol_images(cfg, "Sym", "", "k", "m", rate_limit=0)
        assert all(not s.get("image") for s in result["symbols"])

    def test_nothing_missing_still_writes_manifest(self, out):
        from ntcdg.symbols import TraditionalDeckRegistry, symbols_dir_for

        with patch.object(TraditionalDeckRegistry, "get_missing_symbols", return_value=[]):
            cfg = TraditionalDeckRegistry.complete_deck_symbols(
                {"symbols": [{"name": "Cup"}]}, "Full", "", "k", "m",
            )
        assert cfg["generated_symbol_count"] == 0
        assert os.path.exists(os.path.join(symbols_dir_for("Full"), "symbols.json"))

    def test_symbol_filenames_are_safe_and_unique(self):
        from ntcdg.symbols import symbol_filename

        a = symbol_filename("A very long symbol name that shares a prefix ONE")
        b = symbol_filename("A very long symbol name that shares a prefix TWO")
        assert a != b
        for name in (a, b, symbol_filename('bad:/\\*?"<>|name'), symbol_filename("")):
            assert all(ch.isalnum() or ch in "_." for ch in name)


class TestRegisterSymbols:
    def test_batches_merge_and_same_name_replaces(self, out, tmp_path):
        from ntcdg.mcp_server import register_symbols

        a = _png(tmp_path / "a.png")
        b = _png(tmp_path / "b.png", (200, 0, 0))
        r1 = register_symbols("Art", [{"name": "Serpent", "image_path": a}], auto_describe=False)
        r2 = register_symbols("Art", [{"name": "Eye", "image_path": b},
                                      {"name": "serpent", "image_path": b}], auto_describe=False)
        assert r1["success"] and r2["success"]
        with open(r2["symbols_file"]) as f:
            names = sorted(s["name"] for s in json.load(f)["symbols"])
        assert names == ["Eye", "serpent"]
        assert r2["total_symbols"] == 2

        r3 = register_symbols("Art", [{"name": "Moon", "image_path": a}],
                              auto_describe=False, replace=True)
        assert r3["total_symbols"] == 1

    def test_rejects_non_images_and_bad_extensions(self, out, tmp_path):
        from ntcdg.mcp_server import register_symbols

        fake = tmp_path / "fake.png"
        fake.write_bytes(b"not an image")
        script = tmp_path / "x.sh"
        script.write_text("echo hi")
        result = register_symbols("Art", [{"name": "F", "image_path": str(fake)},
                                          {"name": "S", "image_path": str(script)}],
                                  auto_describe=False)
        assert result["success"] is False
        assert len(result["errors"]) == 2

    def test_empty_symbol_list_rejected(self, out):
        from ntcdg.mcp_server import register_symbols

        assert register_symbols("Art", [])["success"] is False


# ==================== MCP TOOL GUARDS ====================

class TestMCPGuards:
    def test_retry_failed_unknown_deck_errors_without_generating(self, out):
        from ntcdg.mcp_server import retry_failed

        with patch("ntcdg.generator.generate_deck") as gen:
            result = retry_failed("Ghost")
        assert result["success"] is False
        gen.assert_not_called()

    def test_retry_failed_uses_target_size(self, out, monkeypatch):
        from ntcdg.mcp_server import retry_failed
        from ntcdg.storage import save_deck, update_deck_meta

        monkeypatch.setenv("VENICE_API_KEY", "k")
        save_deck([Card(position=1, title="The Fool")], "Partial")
        update_deck_meta("Partial", target_cards=22)
        with patch("ntcdg.generator.generate_deck") as gen:
            retry_failed("Partial")
        assert gen.call_args.kwargs["num_cards"] == 22
        assert gen.call_args.kwargs["resume"] is True

    def test_create_deck_refuses_to_overwrite(self, out, monkeypatch):
        from ntcdg.mcp_server import create_deck
        from ntcdg.storage import save_deck

        monkeypatch.setenv("VENICE_API_KEY", "k")
        save_deck([Card(position=1, title="The Fool")], "Mine")
        with patch("ntcdg.generator.generate_deck") as gen:
            result = create_deck(name="Mine")
        assert result["success"] is False and "already exists" in result["error"]
        gen.assert_not_called()

    @pytest.mark.parametrize("cards", [0, -1, 201])
    def test_create_deck_validates_card_count(self, out, cards):
        from ntcdg.mcp_server import create_deck

        assert create_deck(name="Ok", cards=cards)["success"] is False

    def test_create_deck_validates_symbol_inputs(self, out):
        from ntcdg.mcp_server import create_deck

        assert create_deck(name="Ok", symbol_mode="weird")["success"] is False
        assert create_deck(name="Ok", symbols_file="/nope.json")["success"] is False

    def test_edit_card_failure_has_message(self, out):
        from ntcdg.mcp_server import edit_card

        result = edit_card("Nope", 1, "title", "x")
        assert result["success"] is False
        assert "not found" in result["error"]
        bad_field = edit_card("Nope", 1, "image_path", "x")
        assert "Invalid field" in bad_field["error"]

    def test_generate_back_requires_deck(self, out):
        from ntcdg.mcp_server import generate_back

        assert generate_back("Nope", "stars")["success"] is False


# ==================== FINALIZE ====================

class TestFinalize:
    def test_core_finalize_validates_options(self, out):
        from ntcdg.finalize import finalize_deck

        with pytest.raises(ValueError):
            finalize_deck("X", sheet_size="postcard")
        with pytest.raises(ValueError):
            finalize_deck("X", duplex_flip="none")
        with pytest.raises(ValueError):
            finalize_deck("X", color_mode="sepia")

    def test_bundle_excludes_similarly_named_decks(self, out, tmp_path):
        import zipfile

        from ntcdg.finalize import export_deck_bundle
        from ntcdg.storage import save_deck

        save_deck([_complete_card(1, _png(tmp_path / "1.png"))], "a")
        (out / "a_PRINT_letter_color.pdf").write_bytes(b"%PDF")
        (out / "a_PRINT_x_PRINT_letter_color.pdf").write_bytes(b"%PDF")

        with zipfile.ZipFile(export_deck_bundle("a")) as zf:
            names = zf.namelist()
        assert "a_PRINT_letter_color.pdf" in names
        assert "a_PRINT_x_PRINT_letter_color.pdf" not in names
