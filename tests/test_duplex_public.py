"""Tests for duplex registration, per-card QR backs and stable public slugs."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from ntcdg import duplex, public
from ntcdg.duplex import Rect, back_grid_pos, back_rect, back_rotation, plan_slots
from ntcdg.finalize import SHEET_SIZES
from ntcdg.models import Card

_PUBLIC_ENV = (
    "NTCDG_PUBLIC_BASE_URL", "NTCDG_PUBLIC_ROOT_DOMAIN",
    "NTCDG_PUBLIC_SUBDOMAIN", "NTCDG_PUBLIC_SCHEME",
)


@pytest.fixture
def out(tmp_path, monkeypatch):
    out_dir = tmp_path / "generated_decks"
    out_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr("ntcdg.config.Config.IMAGES_DIR", str(out_dir / "images"))
    monkeypatch.delenv("VENICE_API_KEY", raising=False)
    for var in _PUBLIC_ENV:
        monkeypatch.delenv(var, raising=False)
    return out_dir


def _png(path, color=(10, 20, 30), size=(60, 100)):
    Image.new("RGB", size, color).save(path)
    return str(path)


def _cards(tmp_path, n, missing=()):
    cards = []
    for pos in range(1, n + 1):
        img = _png(tmp_path / f"c{pos}.png") if pos not in missing else str(tmp_path / "nope.png")
        cards.append(Card(
            position=pos, title=f"Card {pos}", card_type="Major Arcana", image_path=img,
            description="d", upright_interpretation="u", reversed_interpretation="r",
        ))
    return cards


def _page_count(path) -> int:
    data = Path(path).read_bytes()
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", data))


# ==================== GEOMETRY ====================

class TestBackGeometry:
    @pytest.mark.parametrize("sheet", sorted(SHEET_SIZES))
    @pytest.mark.parametrize("flip", ["long_edge", "short_edge"])
    def test_back_rect_is_an_involution(self, sheet, flip):
        w, h = SHEET_SIZES[sheet]
        slots, _ = plan_slots(9, sheet)
        for s in slots:
            twice = back_rect(back_rect(s.front, w, h, flip), w, h, flip)
            assert twice.x == pytest.approx(s.front.x)
            assert twice.y == pytest.approx(s.front.y)

    @pytest.mark.parametrize("sheet", sorted(SHEET_SIZES))
    def test_long_edge_mirrors_x_keeps_y(self, sheet):
        w, h = SHEET_SIZES[sheet]
        for s in plan_slots(8, sheet)[0]:
            b = back_rect(s.front, w, h, "long_edge")
            assert b.y == pytest.approx(s.front.y)
            # same distance from the opposite edge
            assert b.x == pytest.approx(w - s.front.x - s.front.w)
            assert (b.w, b.h) == (s.front.w, s.front.h)

    @pytest.mark.parametrize("sheet", sorted(SHEET_SIZES))
    def test_short_edge_mirrors_y_keeps_x(self, sheet):
        w, h = SHEET_SIZES[sheet]
        for s in plan_slots(8, sheet)[0]:
            b = back_rect(s.front, w, h, "short_edge")
            assert b.x == pytest.approx(s.front.x)
            assert b.y == pytest.approx(h - s.front.y - s.front.h)

    @pytest.mark.parametrize("sheet", sorted(SHEET_SIZES))
    @pytest.mark.parametrize("flip", ["long_edge", "short_edge"])
    def test_backs_land_on_grid_cells(self, sheet, flip):
        """Centred grid => each back coincides with the mirrored grid cell."""
        w, h = SHEET_SIZES[sheet]
        per_page = plan_slots(1, sheet)[1]["cards_per_page"]
        slots, layout = plan_slots(per_page, sheet)
        assert len(slots) == per_page
        cells = {(s.row, s.col): s.front for s in slots}
        for s in slots:
            b = back_rect(s.front, w, h, flip)
            cell = cells[back_grid_pos(s.row, s.col, layout, flip)]
            assert b.x == pytest.approx(cell.x, abs=1e-9)
            assert b.y == pytest.approx(cell.y, abs=1e-9)

    def test_partial_last_page_back_goes_to_mirrored_column(self):
        w, h = SHEET_SIZES["letter"]
        slots, layout = plan_slots(5, "letter")  # 4 per sheet -> card 5 alone on sheet 2
        assert layout["cols"] == 2
        last = slots[-1]
        assert (last.page, last.row, last.col) == (1, 0, 0)
        b = back_rect(last.front, w, h, "long_edge")
        right_col_x = slots[1].front.x  # sheet 1, row 0, col 1
        assert b.x == pytest.approx(right_col_x)
        assert b.y == pytest.approx(last.front.y)

    def test_offsets_are_applied_after_mirroring(self):
        r = Rect(1.0, 2.0, 3.0, 5.0)
        b = back_rect(r, 8.5, 11.0, "long_edge", 0.1, -0.2)
        assert b.x == pytest.approx(8.5 - 1.0 - 3.0 + 0.1)
        assert b.y == pytest.approx(2.0 - 0.2)

    def test_unknown_flip_rejected(self):
        with pytest.raises(ValueError):
            back_rect(Rect(0, 0, 1, 1), 8.5, 11, "none")

    def test_rotation(self):
        assert back_rotation("long_edge") == 0
        assert back_rotation("short_edge") == 180

    @pytest.mark.parametrize("bad", [(10.1, 0), (0, -11), (float("nan"), 0), (0, float("inf"))])
    def test_offsets_out_of_range(self, bad):
        with pytest.raises(ValueError):
            duplex.validate_offsets(bad)

    def test_offsets_in_range(self):
        assert duplex.validate_offsets((10, -10)) == (10.0, -10.0)
        assert duplex.validate_offsets(("1.5", 0)) == (1.5, 0.0)


# ==================== PDF RENDERING ====================

class TestDuplexPdfs:
    def test_page_counts_and_names(self, out, tmp_path):
        cards = _cards(tmp_path, 5)  # letter: 4/sheet -> 2 sheets
        written = duplex.create_duplex_pdfs(cards, "Deck", "letter", "color", "long_edge")
        assert set(written) == {"duplex", "fronts", "backs"}
        assert written["duplex"].endswith("Deck_DUPLEX_letter_color_long_edge.pdf")
        assert written["fronts"].endswith("Deck_PRINT_letter_color.pdf")
        assert written["backs"].endswith("Deck_BACKS_letter_color_long_edge.pdf")
        assert _page_count(written["duplex"]) == 4
        assert _page_count(written["fronts"]) == 2
        assert _page_count(written["backs"]) == 2

    def test_every_card_gets_its_own_qr_url(self, out, tmp_path):
        cards = _cards(tmp_path, 3)
        urls = {c.position: f"https://t.example.com/c/d/{c.position:02d}" for c in cards}
        seen = []
        real = duplex.draw_qr

        def spy(c, url, x, y, size):
            seen.append(url)
            real(c, url, x, y, size)

        with patch.object(duplex, "draw_qr", spy):
            duplex.create_duplex_pdfs(cards, "Q", "letter", "color", "short_edge",
                                      card_urls=urls, outputs=("backs",))
        assert sorted(seen) == sorted(urls.values())

    def test_qr_widget_encodes_url(self):
        from reportlab.graphics.barcode.qr import QrCodeWidget
        url = "https://tarot.example.com/c/moon-k7m2qx/01-the-fool"
        assert QrCodeWidget(url).value == url

    def test_no_urls_means_no_qr(self, out, tmp_path):
        with patch.object(duplex, "draw_qr") as m:
            duplex.create_duplex_pdfs(_cards(tmp_path, 2), "N", outputs=("backs",))
        m.assert_not_called()

    def test_missing_and_corrupt_images_keep_their_slot(self, out, tmp_path):
        cards = _cards(tmp_path, 4, missing={2})
        (tmp_path / "c3.png").write_bytes(b"not a png")
        placeholders = []
        real = duplex._draw_placeholder

        def spy(c, label):
            placeholders.append(label)
            real(c, label)

        urls = {c.position: f"https://e.com/c/x/{c.position}" for c in cards}
        qr_order = []
        with patch.object(duplex, "_draw_placeholder", spy), \
                patch.object(duplex, "draw_qr", lambda c, u, *a: qr_order.append(u)):
            written = duplex.create_duplex_pdfs(cards, "M", card_urls=urls, outputs=("duplex",))
        assert sorted(placeholders) == ["MISSING #2", "MISSING #3"]
        assert qr_order == [urls[p] for p in (1, 2, 3, 4)]  # no slot shifted
        assert _page_count(written["duplex"]) == 2

    def test_cards_sorted_by_position(self, out, tmp_path):
        cards = list(reversed(_cards(tmp_path, 3)))
        order = []
        with patch.object(duplex, "draw_qr", lambda c, u, *a: order.append(u)):
            duplex.create_duplex_pdfs(cards, "S", card_urls={1: "u1", 2: "u2", 3: "u3"},
                                      outputs=("backs",))
        assert order == ["u1", "u2", "u3"]

    def test_backs_only_with_num_cards(self, out):
        written = duplex.create_duplex_pdfs(None, "B", "tabloid", num_cards=7, outputs=("backs",))
        assert _page_count(written["backs"]) == 1  # tabloid holds 8+

    def test_fronts_require_cards(self, out):
        with pytest.raises(ValueError):
            duplex.create_duplex_pdfs(None, "B", num_cards=2, outputs=("fronts",))

    def test_nothing_to_print(self, out):
        assert duplex.create_duplex_pdfs([], "E") == {}

    def test_bad_back_image_falls_back_to_default_design(self, out, tmp_path):
        bad = tmp_path / "back.png"
        bad.write_bytes(b"garbage")
        with patch.object(duplex, "_draw_default_back", wraps=duplex._draw_default_back) as m:
            duplex.create_duplex_pdfs(_cards(tmp_path, 2), "BB", back_image_path=str(bad),
                                      outputs=("backs",))
        assert m.call_count == 2

    def test_invalid_options(self, out, tmp_path):
        with pytest.raises(ValueError):
            duplex.create_duplex_pdfs(_cards(tmp_path, 1), "X", duplex_flip="none")
        with pytest.raises(ValueError):
            duplex.create_duplex_pdfs(_cards(tmp_path, 1), "X", back_offset_mm=(20, 0))

    @pytest.mark.parametrize("flip", ["long_edge", "short_edge"])
    def test_calibration_pdf(self, out, flip):
        path = duplex.create_calibration_pdf("a4", flip, (0.5, -0.5))
        assert path.endswith(f"CALIBRATION_a4_{flip}.pdf")
        assert _page_count(path) == 2


# ==================== SLUGS / URLS ====================

class TestSlugs:
    @pytest.mark.parametrize("text,expected", [
        ("The Fool", "the-fool"),
        ("  Ace of   Cups!! ", "ace-of-cups"),
        ("Élan Vital", "elan-vital"),
        ("月", "deck"),
        ("", "deck"),
        ("a" * 80, "a" * 40),
    ])
    def test_slugify(self, text, expected):
        assert public.slugify(text) == expected

    def test_card_slug_uses_canonical_title(self):
        c = Card(position=7, title="The Chariot", venice_title="Neon Racer")
        assert public.card_slug(c) == "07-the-chariot"
        assert public.card_slug(Card(position=0, title="")) == "00-card"

    @pytest.mark.parametrize("slug,pos", [
        ("07-the-chariot", 7), ("78", 78), ("7", 7), ("007-x", 7),
        ("the-fool", None), ("", None), ("12-UPPER", 12), ("1234-x", None), ("../1", None),
    ])
    def test_parse_card_position(self, slug, pos):
        assert public.parse_card_position(slug) == pos

    def test_new_deck_slug_unique_and_dns_safe(self):
        taken: set[str] = set()
        for _ in range(200):
            s = public.new_deck_slug("My_Moon Garden Deck " * 5, taken)
            assert s not in taken
            assert public.is_valid_deck_slug(s)
            assert len(s) <= 63
            taken.add(s)

    def test_new_deck_slug_retries_on_collision(self):
        with patch.object(public.secrets, "choice", side_effect=list("aaaaaa" + "bbbbbb")):
            assert public.new_deck_slug("x", {"x-aaaaaa"}) == "x-bbbbbb"

    @pytest.mark.parametrize("slug", ["", "-a", "a-", "A", "a_b", "a" * 64, "a/b"])
    def test_invalid_deck_slugs(self, slug):
        assert not public.is_valid_deck_slug(slug)


class TestBaseUrl:
    @pytest.mark.parametrize("url", [
        "http://localhost:8000", "https://127.0.0.1", "https://192.168.1.5", "https://10.0.0.2",
        "ftp://example.com", "https://example.com/?a=1", "https://example.com/#x",
        "https://user:pw@example.com", "https://example.com/{deck}", "https://tarot.{deck}.com",
        "https://", "", "https://bad_host.com", "https://printer.local",
    ])
    def test_rejects(self, url):
        with pytest.raises(ValueError):
            public.validate_base_url(url)

    def test_allow_local(self):
        assert public.validate_base_url("http://localhost:8000/", allow_local=True) == \
            "http://localhost:8000"

    @pytest.mark.parametrize("url,expected", [
        ("https://tarot.example.com/", "https://tarot.example.com"),
        ("https://{deck}.example.com", "https://{deck}.example.com"),
        ("https://example.com/tarot", "https://example.com/tarot"),
    ])
    def test_accepts(self, url, expected):
        assert public.validate_base_url(url) == expected

    def test_env_composition(self):
        assert public.base_url_from_env({}) == ""
        assert public.base_url_from_env({"NTCDG_PUBLIC_ROOT_DOMAIN": "Example.com."}) == \
            "https://example.com"
        assert public.base_url_from_env({
            "NTCDG_PUBLIC_ROOT_DOMAIN": "example.com", "NTCDG_PUBLIC_SUBDOMAIN": "tarot",
        }) == "https://tarot.example.com"
        assert public.base_url_from_env({
            "NTCDG_PUBLIC_ROOT_DOMAIN": "example.com", "NTCDG_PUBLIC_SUBDOMAIN": "{deck}",
            "NTCDG_PUBLIC_SCHEME": "http",
        }) == "http://{deck}.example.com"
        assert public.base_url_from_env({
            "NTCDG_PUBLIC_BASE_URL": "https://a.b", "NTCDG_PUBLIC_ROOT_DOMAIN": "x.y",
        }) == "https://a.b"

    def test_url_building_modes(self):
        assert public.build_card_url("https://t.example.com", "moon-abc", "01-the-fool") == \
            "https://t.example.com/c/moon-abc/01-the-fool"
        assert public.build_deck_url("https://t.example.com", "moon-abc") == \
            "https://t.example.com/c/moon-abc"
        assert public.build_card_url("https://{deck}.example.com", "moon-abc", "01-x") == \
            "https://moon-abc.example.com/c/01-x"
        assert public.build_deck_url("https://{deck}.example.com", "moon-abc") == \
            "https://moon-abc.example.com/"
        assert public.url_mode("https://{deck}.example.com") == "subdomain"
        assert public.url_mode("https://example.com") == "path"


class TestPublicIdentity:
    def _deck(self, tmp_path, name="Moon", n=3):
        from ntcdg.storage import save_deck
        save_deck(_cards(tmp_path, n), name)
        return name

    def test_disabled_without_config(self, out, tmp_path):
        from ntcdg.storage import load_decks_index
        name = self._deck(tmp_path)
        ident = public.ensure_public_identity(name)
        assert ident["enabled"] is False and ident["reason"]
        assert not load_decks_index()[name].get("published")

    def test_bakes_once_and_is_stable(self, out, tmp_path, monkeypatch):
        from ntcdg.storage import load_decks_index
        name = self._deck(tmp_path)
        monkeypatch.setenv("NTCDG_PUBLIC_BASE_URL", "https://tarot.example.com")
        first = public.ensure_public_identity(name)
        assert first["enabled"] and first["mode"] == "path"
        assert first["slug"].startswith("moon-")
        meta = load_decks_index()[name]
        assert meta["public_slug"] == first["slug"]
        assert meta["published"] is True
        again = public.ensure_public_identity(name)
        assert again["slug"] == first["slug"] and again["warnings"] == []

    def test_changed_url_keeps_old_unless_rebase(self, out, tmp_path):
        name = self._deck(tmp_path)
        first = public.ensure_public_identity(name, "https://old.example.com")
        kept = public.ensure_public_identity(name, "https://new.example.com")
        assert kept["base_url"] == "https://old.example.com"
        assert kept["slug"] == first["slug"]
        assert any("rebase" in w for w in kept["warnings"])
        moved = public.ensure_public_identity(name, "https://new.example.com", rebase=True)
        assert moved["base_url"] == "https://new.example.com"
        assert moved["slug"] == first["slug"]  # slug never changes
        assert moved["warnings"]

    def test_baked_url_used_when_env_unset(self, out, tmp_path):
        name = self._deck(tmp_path)
        public.ensure_public_identity(name, "https://tarot.example.com")
        assert public.ensure_public_identity(name)["base_url"] == "https://tarot.example.com"

    def test_invalid_url_raises(self, out, tmp_path):
        name = self._deck(tmp_path)
        with pytest.raises(ValueError):
            public.ensure_public_identity(name, "http://localhost")

    def test_slugs_unique_across_decks(self, out, tmp_path):
        a = self._deck(tmp_path, "Same")
        b = self._deck(tmp_path, "same")
        sa = public.ensure_public_identity(a, "https://e.com")["slug"]
        sb = public.ensure_public_identity(b, "https://e.com")["slug"]
        assert sa != sb
        assert public.find_deck_by_slug(sa)[0] == a
        assert public.find_deck_by_slug(sb)[0] == b
        assert public.find_deck_by_slug("../etc") is None

    def test_public_links(self, out, tmp_path):
        name = self._deck(tmp_path)
        assert public.public_links(name)["enabled"] is False
        ident = public.ensure_public_identity(name, "https://{deck}.example.com")
        links = public.public_links(name)
        assert links["deck_url"] == f"https://{ident['slug']}.example.com/"
        assert [c["card_slug"] for c in links["cards"]] == ["01-card-1", "02-card-2", "03-card-3"]
        assert links["cards"][0]["url"] == f"https://{ident['slug']}.example.com/c/01-card-1"


# ==================== FINALIZE / MCP / CLI ====================

class TestFinalizeWithQr:
    def test_report_includes_qr_and_publishes(self, out, tmp_path):
        from ntcdg.finalize import finalize_deck_report
        from ntcdg.storage import load_decks_index, save_deck
        save_deck(_cards(tmp_path, 5), "Fin")
        urls = []
        with patch.object(duplex, "draw_qr", lambda c, u, *a: urls.append(u)):
            report = finalize_deck_report("Fin", public_base_url="https://tarot.example.com")
        assert report["success"], report
        assert report["qr"]["enabled"] is True
        slug = report["qr"]["deck_slug"]
        assert load_decks_index()["Fin"]["published"] is True
        # duplex + backs files each draw one QR per card
        expected = [f"https://tarot.example.com/c/{slug}/{p:02d}-card-{p}" for p in range(1, 6)]
        assert urls == expected * 2
        assert _page_count(report["duplex_pdf"]) == 4

    def test_report_without_url_warns_and_still_prints(self, out, tmp_path):
        from ntcdg.finalize import finalize_deck_report
        from ntcdg.storage import save_deck
        save_deck(_cards(tmp_path, 2), "NoUrl")
        report = finalize_deck_report("NoUrl")
        assert report["success"]
        assert report["qr"]["enabled"] is False
        assert any("QR" in w for w in report["warnings"])

    def test_no_qr_flag(self, out, tmp_path):
        from ntcdg.finalize import finalize_deck_report
        from ntcdg.storage import load_decks_index, save_deck
        save_deck(_cards(tmp_path, 2), "Plain")
        report = finalize_deck_report("Plain", qr_codes=False, public_base_url="https://e.com")
        assert report["success"] and report["qr"]["reason"] == "QR codes disabled"
        assert not load_decks_index()["Plain"].get("public_slug")

    def test_duplicate_positions_block_finalize(self, out, tmp_path):
        from ntcdg.finalize import finalize_deck_report
        from ntcdg.storage import load_decks_index, save_deck
        cards = _cards(tmp_path, 3)
        cards[2].position = 2
        save_deck(cards, "Dup")
        report = finalize_deck_report("Dup", public_base_url="https://e.com")
        assert not report["success"]
        assert any("Position 2" in e for e in report["validation"]["errors"])
        assert not load_decks_index()["Dup"].get("published")

    def test_local_url_rejected(self, out, tmp_path):
        from ntcdg.finalize import finalize_deck_report
        from ntcdg.storage import save_deck
        save_deck(_cards(tmp_path, 1), "Loc")
        with pytest.raises(ValueError):
            finalize_deck_report("Loc", public_base_url="http://192.168.0.10")


class TestMcpPublicTools:
    def _published(self, tmp_path, n=3):
        from ntcdg.storage import save_deck
        save_deck(_cards(tmp_path, n), "Pub")
        return public.ensure_public_identity("Pub", "https://tarot.example.com")["slug"]

    def test_get_card_by_slug_wraps(self, out, tmp_path):
        from ntcdg.mcp_server import get_card_by_slug
        slug = self._published(tmp_path)
        first = get_card_by_slug(slug, "01-card-1")
        assert first["title"] == "Card 1" and first["total"] == 3
        assert first["prev_card_slug"] == "03-card-3"
        assert first["next_card_slug"] == "02-card-2"
        last = get_card_by_slug(slug, "03-card-3")
        assert last["next_card_slug"] == "01-card-1"
        assert "image_path" not in first  # never leak server paths

    def test_get_card_by_slug_resolves_by_position(self, out, tmp_path):
        from ntcdg.mcp_server import get_card_by_slug
        slug = self._published(tmp_path)
        res = get_card_by_slug(slug, "2")
        assert res["card_slug"] == "02-card-2"

    def test_single_card_deck_wraps_to_itself(self, out, tmp_path):
        from ntcdg.mcp_server import get_card_by_slug
        slug = self._published(tmp_path, n=1)
        res = get_card_by_slug(slug, "01-card-1")
        assert res["prev_card_slug"] == res["next_card_slug"] == "01-card-1"

    @pytest.mark.parametrize("card", ["99-nope", "bad", ""])
    def test_get_card_by_slug_not_found(self, out, tmp_path, card):
        from ntcdg.mcp_server import get_card_by_slug
        slug = self._published(tmp_path)
        assert get_card_by_slug(slug, card) == {"error": "Card not found"}

    def test_unpublished_deck_hidden(self, out, tmp_path):
        from ntcdg.mcp_server import get_card_by_slug
        from ntcdg.storage import update_deck_meta
        slug = self._published(tmp_path)
        update_deck_meta("Pub", published=False)
        assert get_card_by_slug(slug, "01-card-1") == {"error": "Card not found"}
        assert get_card_by_slug("no-such-deck", "01") == {"error": "Card not found"}

    def test_get_public_links_tool(self, out, tmp_path):
        from ntcdg.mcp_server import get_public_links
        assert "error" in get_public_links("Missing")
        slug = self._published(tmp_path)
        links = get_public_links("Pub")
        assert links["enabled"] and links["deck_slug"] == slug and len(links["cards"]) == 3

    def test_duplex_calibration_tool(self, out):
        from ntcdg.mcp_server import duplex_calibration
        res = duplex_calibration("letter", "short_edge", 1.0, -1.0)
        assert res["success"] and res["calibration_pdf"].endswith("CALIBRATION_letter_short_edge.pdf")
        assert duplex_calibration("letter", "sideways")["success"] is False
        assert duplex_calibration("letter", "long_edge", 50.0)["success"] is False

    def test_finalize_tool_reports_qr(self, out, tmp_path):
        from ntcdg.mcp_server import finalize_deck
        from ntcdg.storage import save_deck
        save_deck(_cards(tmp_path, 2), "Tool")
        res = finalize_deck("Tool", public_base_url="https://tarot.example.com",
                            back_offset_x_mm=0.5)
        assert res["success"] and res["qr"]["enabled"]
        assert res["duplex_pdf"] in res["pdfs"]
        bad = finalize_deck("Tool", back_offset_y_mm=99)
        assert bad["success"] is False and "offset" in bad["error"]


class TestCli:
    def _run(self, monkeypatch, *argv):
        from ntcdg import cli
        monkeypatch.setattr(sys, "argv", ["ntcdg", *argv])
        return cli.main()

    def test_rejects_unknown_flip(self, out, monkeypatch):
        with pytest.raises(SystemExit) as e:
            self._run(monkeypatch, "--calibration-sheet", "--duplex-flip", "none")
        assert e.value.code == 2

    def test_calibration_sheet(self, out, monkeypatch, capsys):
        self._run(monkeypatch, "--calibration-sheet", "--sheet-size", "a4")
        assert (out / "CALIBRATION_a4_long_edge.pdf").exists()

    def test_calibration_offset_out_of_range(self, out, monkeypatch):
        with pytest.raises(SystemExit) as e:
            self._run(monkeypatch, "--calibration-sheet", "--back-offset-x-mm", "30")
        assert e.value.code == 2

    def test_finalize_and_public_links(self, out, tmp_path, monkeypatch, capsys):
        from ntcdg.storage import save_deck
        save_deck(_cards(tmp_path, 2), "Cli")
        self._run(monkeypatch, "--finalize", "Cli", "--public-base-url", "https://t.example.com")
        capsys.readouterr()
        self._run(monkeypatch, "--public-links", "Cli")
        text = capsys.readouterr().out
        assert "https://t.example.com/c/cli-" in text and "01-card-1" in text

    def test_finalize_failure_exit_code(self, out, monkeypatch):
        with pytest.raises(SystemExit) as e:
            self._run(monkeypatch, "--finalize", "Nope")
        assert e.value.code == 1
