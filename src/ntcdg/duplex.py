"""Duplex-registered print layout: fronts and (variable) backs that always line up.

One *slot plan* is computed per deck and shared by both sides, so card N's
back is always printed on the paper directly behind card N's front -- even
on a partial last sheet, and even if an image fails to load (a placeholder
is drawn instead of shifting the remaining cards).

Back position for a front bleed box ``(x, y, w, h)`` on a ``W x H`` sheet
(PDF coordinates, origin bottom-left, portrait pages):

* ``long_edge``  (flip like a book page -- most duplex printers' default):
  ``x' = W - x - w``, ``y' = y``; artwork upright.
* ``short_edge`` (flip like a wall calendar):
  ``x' = x``, ``y' = H - y - h``; artwork rotated 180 degrees so the cut card
  still reads upright when it is turned over sideways.

``back_offset_mm`` shifts every back by a measured amount to cancel printer
drift; print :func:`create_calibration_pdf` once to measure it.

Backs carry per-card variables (a QR code pointing at that card's public
page), which is why registration matters. Nothing human-readable that
identifies the card is printed inside the trim on the back -- backs must
stay indistinguishable for readings. Small slot numbers (``#12``) are
printed in the waste area outside the trim on both sides so front/back
pairing can be checked before cutting.
"""

from __future__ import annotations

import math
import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from .config import HAS_REPORTLAB, Config, logger
from .finalize import (
    BLEED,
    CARD_BLEED_H,
    CARD_BLEED_W,
    CARD_TRIM_H,
    CARD_TRIM_W,
    CELL_GAP,
    HAS_PILLOW,
    SHEET_MARGIN,
    SHEET_SIZES,
    _calculate_grid,
    _draw_crop_marks,
    _prepare_image,
    validate_print_options,
)

if HAS_REPORTLAB:
    from reportlab.lib.colors import CMYKColor
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas as pdf_canvas
else:  # pragma: no cover - reportlab is a hard dependency in practice
    inch = 72.0

MM_PER_INCH = 25.4
MAX_BACK_OFFSET_MM = 10.0

# QR placement on the back (inches, relative to the bleed box)
QR_SIZE = 0.8          # printed QR module area (>= 0.75" scans reliably at arm's length)
QR_PAD = 0.07          # white quiet-zone padding around the code
QR_SAFE_BOTTOM = 0.2   # distance from the trim line to the bottom of the white panel


@dataclass(frozen=True)
class Rect:
    """Bleed box in inches, PDF coordinates (origin bottom-left)."""

    x: float
    y: float
    w: float
    h: float

    def pts(self) -> tuple[float, float, float, float]:
        return self.x * inch, self.y * inch, self.w * inch, self.h * inch


@dataclass(frozen=True)
class Slot:
    page: int    # 0-based sheet index
    index: int   # 0-based index within the sheet
    row: int
    col: int
    front: Rect
    card_index: int  # index into the card list this slot holds


# ==================== GEOMETRY ====================

def plan_slots(num_cards: int, sheet_size: str) -> tuple[list[Slot], dict]:
    """Assign every card a (sheet, row, col, front rect). Shared by both sides."""
    sheet_w, sheet_h = SHEET_SIZES[sheet_size]
    layout = _calculate_grid(sheet_w, sheet_h)
    per_page = layout["cards_per_page"]
    slots: list[Slot] = []
    for i in range(num_cards):
        page, idx = divmod(i, per_page)
        row, col = divmod(idx, layout["cols"])
        x = layout["start_x"] + col * (CARD_BLEED_W + CELL_GAP)
        y = sheet_h - layout["start_y"] - (row + 1) * CARD_BLEED_H - row * CELL_GAP
        slots.append(Slot(page, idx, row, col, Rect(x, y, CARD_BLEED_W, CARD_BLEED_H), i))
    return slots, layout


def back_rect(
    front: Rect, sheet_w: float, sheet_h: float, duplex_flip: str,
    offset_x_in: float = 0.0, offset_y_in: float = 0.0,
) -> Rect:
    """Where the back of ``front`` must be drawn on the reverse page."""
    if duplex_flip == "long_edge":
        x, y = sheet_w - front.x - front.w, front.y
    elif duplex_flip == "short_edge":
        x, y = front.x, sheet_h - front.y - front.h
    else:
        raise ValueError(f"Unknown duplex_flip {duplex_flip!r}")
    return Rect(x + offset_x_in, y + offset_y_in, front.w, front.h)


def back_grid_pos(row: int, col: int, layout: dict, duplex_flip: str) -> tuple[int, int]:
    if duplex_flip == "long_edge":
        return row, layout["cols"] - 1 - col
    return layout["rows"] - 1 - row, col


def back_rotation(duplex_flip: str) -> int:
    return 180 if duplex_flip == "short_edge" else 0


def validate_offsets(back_offset_mm: tuple[float, float]) -> tuple[float, float]:
    ox, oy = (float(v) for v in back_offset_mm)
    for v in (ox, oy):
        if not math.isfinite(v) or abs(v) > MAX_BACK_OFFSET_MM:
            raise ValueError(
                f"back offsets must be within +/-{MAX_BACK_OFFSET_MM} mm (got {back_offset_mm})"
            )
    return ox, oy


# ==================== DRAWING HELPERS ====================

@contextmanager
def _cell(c, rect: Rect, rotation: int = 0) -> Iterator[None]:
    """Translate (and optionally rotate 180) so drawing happens in cell-local inches*pt."""
    x, y, w, h = rect.pts()
    c.saveState()
    if rotation == 180:
        c.translate(x + w, y + h)
        c.rotate(180)
    else:
        c.translate(x, y)
    try:
        yield
    finally:
        c.restoreState()


def draw_qr(c, url: str, x: float, y: float, size: float) -> None:
    """Draw a QR code for ``url`` with its lower-left corner at (x, y) points."""
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing

    widget = QrCodeWidget(url, barLevel="M", barBorder=0)
    widget.barFillColor = CMYKColor(0, 0, 0, 1)
    x0, y0, x1, y1 = widget.getBounds()
    bw, bh = x1 - x0, y1 - y0
    drawing = Drawing(size, size, transform=[size / bw, 0, 0, size / bh, 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, c, x, y)


def _draw_qr_panel(c, url: str) -> None:
    """White rounded panel + QR, bottom-centre of the card, inside the safe zone."""
    panel = (QR_SIZE + 2 * QR_PAD) * inch
    px = (CARD_BLEED_W * inch - panel) / 2
    py = (BLEED + QR_SAFE_BOTTOM) * inch
    c.setFillColorCMYK(0, 0, 0, 0)
    c.setStrokeColorCMYK(0, 0, 0, 0)
    c.roundRect(px, py, panel, panel, 0.06 * inch, stroke=0, fill=1)
    draw_qr(c, url, px + QR_PAD * inch, py + QR_PAD * inch, QR_SIZE * inch)


def _draw_default_back(c) -> None:
    """Symmetric generated back design (used when the deck has no back art)."""
    w, h = CARD_BLEED_W * inch, CARD_BLEED_H * inch
    c.setFillColorCMYK(0.85, 0.80, 0.10, 0.55)  # deep indigo
    c.rect(0, 0, w, h, stroke=0, fill=1)
    cx, cy = w / 2, h / 2
    c.setStrokeColorCMYK(0.0, 0.25, 0.85, 0.05)  # soft gold
    c.setLineWidth(0.8)
    inset = (BLEED + 0.12) * inch
    c.roundRect(inset, inset, w - 2 * inset, h - 2 * inset, 0.12 * inch, stroke=1, fill=0)
    for r in (0.35, 0.6, 0.85):
        c.circle(cx, cy, r * inch, stroke=1, fill=0)
    for k in range(8):
        ang = math.pi * k / 4
        c.line(cx, cy, cx + math.cos(ang) * 0.85 * inch, cy + math.sin(ang) * 0.85 * inch)


def _draw_slot_label(c, rect: Rect, text: str) -> None:
    """Tiny pairing label in the waste area just above the bleed box."""
    x, y, w, h = rect.pts()
    c.setFont("Helvetica", 4.5)
    c.setFillColorCMYK(0, 0, 0, 0.6)
    c.drawCentredString(x + w / 2, y + h + 0.05 * inch, text)


def _draw_placeholder(c, label: str) -> None:
    w, h = CARD_BLEED_W * inch, CARD_BLEED_H * inch
    c.setFillColorCMYK(0, 0, 0, 0.15)
    c.rect(0, 0, w, h, stroke=0, fill=1)
    c.setFillColorCMYK(0, 0, 0, 0.8)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(w / 2, h / 2, label)


def _draw_guides(c, rects: list[Rect], sheet_w_in: float, sheet_h_in: float,
                 offset: tuple[float, float] = (0.0, 0.0)) -> None:
    """Margin cut ticks for every trim line + edge registration targets."""
    sheet_w, sheet_h = sheet_w_in * inch, sheet_h_in * inch
    c.setStrokeColorCMYK(0, 0, 0, 1)
    c.setLineWidth(0.4)
    v_cuts, h_cuts = set(), set()
    for r in rects:
        left = (r.x + BLEED) * inch
        bottom = (r.y + BLEED) * inch
        v_cuts.update({round(left, 3), round(left + CARD_TRIM_W * inch, 3)})
        h_cuts.update({round(bottom, 3), round(bottom + CARD_TRIM_H * inch, 3)})
    tick = 0.18 * inch
    edge = 0.04 * inch
    for x in sorted(v_cuts):
        c.line(x, edge, x, edge + tick)
        c.line(x, sheet_h - edge, x, sheet_h - edge - tick)
    for y in sorted(h_cuts):
        c.line(edge, y, edge + tick, y)
        c.line(sheet_w - edge, y, sheet_w - edge - tick, y)

    ox, oy = offset[0] * inch, offset[1] * inch

    def target(cx, cy):
        r = 5
        c.setLineWidth(0.3)
        c.circle(cx, cy, r, stroke=1, fill=0)
        c.line(cx - r - 3, cy, cx + r + 3, cy)
        c.line(cx, cy - r - 3, cx, cy + r + 3)

    target(sheet_w / 2 + ox, 0.18 * inch + oy)
    target(sheet_w / 2 + ox, sheet_h - 0.18 * inch + oy)
    target(0.18 * inch + ox, sheet_h / 2 + oy)
    target(sheet_w - 0.18 * inch + ox, sheet_h / 2 + oy)


def _crop_marks(c, rect: Rect, row: int, col: int, layout: dict) -> None:
    x, y, _w, _h = rect.pts()
    _draw_crop_marks(
        c, x + BLEED * inch, y + BLEED * inch, CARD_TRIM_W * inch, CARD_TRIM_H * inch,
        gutter_right=(col < layout["cols"] - 1),
        gutter_left=(col > 0),
        gutter_top=(row > 0),
        gutter_bottom=(row < layout["rows"] - 1),
    )


def _footer(c, sheet_w_in: float, text: str) -> None:
    c.setFont("Helvetica", 7)
    c.setFillColorCMYK(0, 0, 0, 0.5)
    c.drawCentredString(sheet_w_in * inch / 2, SHEET_MARGIN * inch * 0.4, text)


# ==================== PAGE RENDERING ====================

@dataclass
class _Job:
    deck_name: str
    sheet_size: str
    color_mode: str
    duplex_flip: str
    offset_in: tuple[float, float]
    offset_mm: tuple[float, float]
    slots: list[Slot]
    layout: dict
    labels: list[str]               # per card index, e.g. "#12"
    front_images: list[str | None]  # prepared CMYK paths (None = placeholder)
    back_image: str | None          # prepared CMYK path (None = generated design)
    urls: list[str | None]          # per card index
    total_pages: int


def _render_front_page(c, job: _Job, page: int) -> None:
    sheet_w, sheet_h = SHEET_SIZES[job.sheet_size]
    page_slots = [s for s in job.slots if s.page == page]
    _draw_guides(c, [s.front for s in page_slots], sheet_w, sheet_h)
    for s in page_slots:
        img = job.front_images[s.card_index]
        with _cell(c, s.front):
            if img:
                c.drawImage(img, 0, 0, width=CARD_BLEED_W * inch, height=CARD_BLEED_H * inch,
                            preserveAspectRatio=False)
            else:
                _draw_placeholder(c, f"MISSING {job.labels[s.card_index]}")
        _crop_marks(c, s.front, s.row, s.col, job.layout)
        _draw_slot_label(c, s.front, job.labels[s.card_index])
    _footer(c, sheet_w, (
        f"{job.deck_name}  ·  FRONTS (side A)  ·  Sheet {page + 1}/{job.total_pages}  ·  "
        f"{job.sheet_size.title()}  ·  {job.color_mode.upper()} CMYK  ·  "
        f"Trim {CARD_TRIM_W}\" x {CARD_TRIM_H}\" + {BLEED}\" bleed"
    ))


def _render_back_page(c, job: _Job, page: int) -> None:
    sheet_w, sheet_h = SHEET_SIZES[job.sheet_size]
    rot = back_rotation(job.duplex_flip)
    page_slots = [s for s in job.slots if s.page == page]
    placed = [
        (s, back_rect(s.front, sheet_w, sheet_h, job.duplex_flip, *job.offset_in))
        for s in page_slots
    ]
    _draw_guides(c, [r for _s, r in placed], sheet_w, sheet_h, offset=job.offset_in)
    for s, rect in placed:
        with _cell(c, rect, rot):
            if job.back_image:
                c.drawImage(job.back_image, 0, 0, width=CARD_BLEED_W * inch,
                            height=CARD_BLEED_H * inch, preserveAspectRatio=False)
            else:
                _draw_default_back(c)
            url = job.urls[s.card_index]
            if url:
                _draw_qr_panel(c, url)
        brow, bcol = back_grid_pos(s.row, s.col, job.layout, job.duplex_flip)
        _crop_marks(c, rect, brow, bcol, job.layout)
        _draw_slot_label(c, rect, job.labels[s.card_index])
    ox, oy = job.offset_mm
    _footer(c, sheet_w, (
        f"{job.deck_name}  ·  BACKS (side B)  ·  Sheet {page + 1}/{job.total_pages}  ·  "
        f"Duplex: flip on {job.duplex_flip.replace('_', ' ')}  ·  "
        f"Back offset {ox:+.1f} / {oy:+.1f} mm"
    ))


def _new_canvas(path: str, sheet_size: str, title: str):
    sheet_w, sheet_h = SHEET_SIZES[sheet_size]
    c = pdf_canvas.Canvas(path, pagesize=(sheet_w * inch, sheet_h * inch))
    c.setTitle(title)
    c.setAuthor("NTCDG — Novel Tarot Card Deck Generator")
    return c


def output_paths(deck_name: str, sheet_size: str, color_mode: str, duplex_flip: str) -> dict:
    out = Config.OUTPUT_DIR
    return {
        "fronts": os.path.join(out, f"{deck_name}_PRINT_{sheet_size}_{color_mode}.pdf"),
        "backs": os.path.join(out, f"{deck_name}_BACKS_{sheet_size}_{color_mode}_{duplex_flip}.pdf"),
        "duplex": os.path.join(
            out, f"{deck_name}_DUPLEX_{sheet_size}_{color_mode}_{duplex_flip}.pdf",
        ),
    }


def create_duplex_pdfs(
    cards: list[Any] | None,
    deck_name: str,
    sheet_size: str = "letter",
    color_mode: str = "color",
    duplex_flip: str = "long_edge",
    back_image_path: str | None = None,
    card_urls: Mapping[int, str] | None = None,
    back_offset_mm: tuple[float, float] = (0.0, 0.0),
    outputs: tuple[str, ...] = ("duplex", "fronts", "backs"),
    num_cards: int | None = None,
) -> dict[str, str]:
    """Render registered fronts/backs from one shared slot plan.

    ``cards`` -- Card objects in print order (sorted by position here). Pass
    ``None`` with ``num_cards`` to render backs only (legacy backs PDF).
    ``card_urls`` -- position -> URL; each card's back gets its own QR code.
    ``outputs`` -- any of "duplex" (interleaved A/B pages, print 2-sided),
    "fronts" and "backs" (separate files for print shops).

    Returns ``{output_name: path}`` for the files written ("" values never).
    """
    validate_print_options(sheet_size, color_mode, duplex_flip)
    ox_mm, oy_mm = validate_offsets(back_offset_mm)
    if not HAS_REPORTLAB or not HAS_PILLOW:
        logger.error("reportlab and Pillow are required for print PDFs")
        return {}

    ordered = sorted(cards, key=lambda c: c.position or 0) if cards is not None else []
    count = len(ordered) if cards is not None else int(num_cards or 0)
    if count <= 0:
        logger.error("Nothing to print")
        return {}
    if cards is None and "fronts" in outputs:
        raise ValueError("fronts require cards")

    slots, layout = plan_slots(count, sheet_size)
    total_pages = math.ceil(count / layout["cards_per_page"])
    urls_map = dict(card_urls or {})

    tmp_dir = tempfile.mkdtemp(prefix="ntcdg_duplex_")
    try:
        front_images: list[str | None] = []
        labels: list[str] = []
        urls: list[str | None] = []
        for i in range(count):
            card = ordered[i] if cards is not None else None
            pos = (card.position if card is not None else None) or (i + 1)
            labels.append(f"#{pos}")
            urls.append(urls_map.get(int(pos)))
            if card is None:
                front_images.append(None)
                continue
            path = None
            if card.image_path and os.path.exists(str(card.image_path)):
                slot_dir = os.path.join(tmp_dir, f"f{i}")
                os.makedirs(slot_dir)
                try:
                    path = _prepare_image(card.image_path, color_mode, slot_dir)
                except Exception as e:  # keep the slot -- never shift registration
                    logger.warning(f"Image prep failed for card {pos}: {e}")
            front_images.append(path)

        back_img = None
        if back_image_path and os.path.exists(back_image_path):
            back_dir = os.path.join(tmp_dir, "back")
            os.makedirs(back_dir)
            try:
                back_img = _prepare_image(back_image_path, color_mode, back_dir)
            except Exception as e:
                logger.warning(f"Back image prep failed, using generated design: {e}")

        job = _Job(
            deck_name=deck_name, sheet_size=sheet_size, color_mode=color_mode,
            duplex_flip=duplex_flip, offset_in=(ox_mm / MM_PER_INCH, oy_mm / MM_PER_INCH),
            offset_mm=(ox_mm, oy_mm), slots=slots, layout=layout, labels=labels,
            front_images=front_images, back_image=back_img, urls=urls,
            total_pages=total_pages,
        )

        paths = output_paths(deck_name, sheet_size, color_mode, duplex_flip)
        os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
        written: dict[str, str] = {}
        for name in outputs:
            c = _new_canvas(paths[name], sheet_size,
                            f"{deck_name} — {name.title()} ({sheet_size}, {duplex_flip})")
            for page in range(total_pages):
                if name in ("duplex", "fronts"):
                    _render_front_page(c, job, page)
                    c.showPage()
                if name in ("duplex", "backs"):
                    _render_back_page(c, job, page)
                    c.showPage()
            c.save()
            written[name] = paths[name]
            logger.info(f"{name} PDF saved: {paths[name]}")
        return written
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ==================== CALIBRATION ====================

def create_calibration_pdf(
    sheet_size: str = "letter",
    duplex_flip: str = "long_edge",
    back_offset_mm: tuple[float, float] = (0.0, 0.0),
) -> str:
    """Two-page duplex test sheet to measure front/back registration.

    Print it 2-sided with the same settings you will use for the deck, then
    hold it up to a light: the crosshairs on both sides should coincide.
    If the back is shifted, measure the error in mm and pass it as
    ``back_offset_mm`` (x: + moves backs right, y: + moves backs up, as seen
    on the back side). The arrows show which way is up on each side: after
    cutting, turn a card over sideways -- the back arrow must point up too.
    """
    validate_print_options(sheet_size, "color", duplex_flip)
    ox_mm, oy_mm = validate_offsets(back_offset_mm)
    if not HAS_REPORTLAB:
        logger.error("reportlab is required for the calibration sheet")
        return ""
    sheet_w, sheet_h = SHEET_SIZES[sheet_size]
    slots, layout = plan_slots(_calculate_grid(sheet_w, sheet_h)["cards_per_page"], sheet_size)
    off_in = (ox_mm / MM_PER_INCH, oy_mm / MM_PER_INCH)

    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
    path = os.path.join(Config.OUTPUT_DIR, f"CALIBRATION_{sheet_size}_{duplex_flip}.pdf")
    c = _new_canvas(path, sheet_size, f"NTCDG duplex calibration ({sheet_size}, {duplex_flip})")

    def cell_marks(label: str, side: str):
        w, h = CARD_BLEED_W * inch, CARD_BLEED_H * inch
        c.setStrokeColorCMYK(0, 0, 0, 1)
        c.setLineWidth(0.3)
        c.rect(BLEED * inch, BLEED * inch, CARD_TRIM_W * inch, CARD_TRIM_H * inch)
        for fx, fy in ((0.5, 0.5), (0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8)):
            cx, cy = w * fx, h * fy
            c.line(cx - 9, cy, cx + 9, cy)
            c.line(cx, cy - 9, cx, cy + 9)
            c.circle(cx, cy, 4, stroke=1, fill=0)
        c.setFillColorCMYK(0, 0, 0, 1)
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(w / 2, h * 0.62, f"{side} {label}")
        c.setFont("Helvetica", 9)
        c.drawCentredString(w / 2, h * 0.36, "UP")
        p = c.beginPath()  # up arrow
        p.moveTo(w / 2, h * 0.44)
        p.lineTo(w / 2 - 7, h * 0.40)
        p.lineTo(w / 2 + 7, h * 0.40)
        p.close()
        c.drawPath(p, stroke=0, fill=1)

    _draw_guides(c, [s.front for s in slots], sheet_w, sheet_h)
    for s in slots:
        with _cell(c, s.front):
            cell_marks(f"#{s.index + 1}", "FRONT")
        _crop_marks(c, s.front, s.row, s.col, layout)
    c.setFont("Helvetica", 7)
    c.setFillColorCMYK(0, 0, 0, 0.8)
    c.drawCentredString(sheet_w * inch / 2, SHEET_MARGIN * inch * 0.4, (
        f"Print 2-sided, flip on {duplex_flip.replace('_', ' ')}, 100% scale (no fit-to-page). "
        "Hold to light: crosshairs must coincide. Measure any shift in mm."
    ))
    c.showPage()

    rot = back_rotation(duplex_flip)
    placed = [(s, back_rect(s.front, sheet_w, sheet_h, duplex_flip, *off_in)) for s in slots]
    _draw_guides(c, [r for _s, r in placed], sheet_w, sheet_h, offset=off_in)
    for s, rect in placed:
        with _cell(c, rect, rot):
            cell_marks(f"#{s.index + 1}", "BACK")
        brow, bcol = back_grid_pos(s.row, s.col, layout, duplex_flip)
        _crop_marks(c, rect, brow, bcol, layout)
    c.setFont("Helvetica", 7)
    c.setFillColorCMYK(0, 0, 0, 0.8)
    c.drawCentredString(sheet_w * inch / 2, SHEET_MARGIN * inch * 0.4, (
        f"Back side · offset {ox_mm:+.1f} / {oy_mm:+.1f} mm · +x moves backs right, "
        "+y moves backs up (as seen on this side)"
    ))
    c.showPage()
    c.save()
    return path
