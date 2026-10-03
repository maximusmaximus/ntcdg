"""User uploads, safe file serving and output sanitising.

Rules enforced here:

* Tools never receive arbitrary server paths from the browser. Path-type
  inputs accept only references to the user's *own* uploads (``upload:<id>``)
  or the user's own deck symbol manifests (``symbols:<deck>``).
* Tool outputs never leak server paths: every path that belongs to the user
  is rewritten to an authenticated download URL; anything else is scrubbed.
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
from collections.abc import Iterable
from typing import Any

from ..config import Config
from ..storage import deck_artifact_files, load_deck, load_decks_index
from . import namespace as ns

UPLOAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,200}$")
CALIBRATION_RE = re.compile(r"^CALIBRATION_[a-z0-9]+_[a-z_]+\.pdf$")
IMAGE_FORMATS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif", "BMP": ".bmp"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MAX_IMAGE_PIXELS = 40_000_000
MAX_SYMBOLS = 200

#: Absolute server paths (POSIX or Windows). The app's own relative URLs are not paths.
_ABS_PATH_RE = re.compile(
    r"(?<![\w:/.~-])(?:[A-Za-z]:\\|/(?!(?:files|uploads|jobs|decks|c|p|static|api)/))"
    r"(?:[\w.@+-]+[\\/])+[\w.@+-]*"
)


class FileInputError(ValueError):
    """A file reference the user may not use."""


# ==================== PATH HELPERS ====================

def _real(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def data_roots() -> list[str]:
    roots = {_real(Config.OUTPUT_DIR), _real(Config.IMAGES_DIR)}
    return sorted(roots)


def is_within(path: str, roots: Iterable[str]) -> bool:
    real = _real(path)
    for root in roots:
        try:
            if os.path.commonpath([real, root]) == root:
                return True
        except ValueError:  # different drives on Windows
            continue
    return False


def uploads_dir(user_id: int) -> str:
    return os.path.join(Config.OUTPUT_DIR, "web_uploads", str(int(user_id)))


def previews_dir() -> str:
    return os.path.join(Config.IMAGES_DIR, "previews")


def symbols_root() -> str:
    return os.path.join(Config.OUTPUT_DIR, "symbols")


# ==================== UPLOADS ====================

def _new_upload_id() -> str:
    return secrets.token_urlsafe(12)


def save_image_upload(db, user: dict[str, Any], original_name: str, data: bytes,
                      max_bytes: int) -> dict[str, Any]:
    """Validate (real image, allowed format, size) and store an image upload."""
    from PIL import Image

    if not data:
        raise FileInputError("The uploaded file is empty.")
    if len(data) > max_bytes:
        raise FileInputError(f"File too large (max {max_bytes // (1024 * 1024)} MB).")
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
            width, height = im.size
            im.verify()
    except Exception:
        raise FileInputError("That file is not a readable image.") from None
    if fmt not in IMAGE_FORMATS:
        raise FileInputError("Only PNG, JPEG, WebP, GIF or BMP images are accepted.")
    if width * height > MAX_IMAGE_PIXELS:
        raise FileInputError("Image dimensions are too large.")

    upload_id = _new_upload_id()
    filename = upload_id + IMAGE_FORMATS[fmt]
    folder = uploads_dir(user["id"])
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, filename), "wb") as f:
        f.write(data)
    name = os.path.basename(original_name or "image")[:120] or "image"
    db.add_upload(upload_id, user["id"], "image", name, filename, len(data))
    return {"id": upload_id, "kind": "image", "name": name, "size": len(data),
            "ref": f"upload:{upload_id}", "url": f"/uploads/{upload_id}"}


def save_symbols_json_upload(db, user: dict[str, Any], original_name: str, data: bytes,
                             max_bytes: int) -> dict[str, Any]:
    """Store a *sanitised* symbols.json: image references must be the user's uploads."""
    if len(data) > min(max_bytes, 2 * 1024 * 1024):
        raise FileInputError("symbols.json is too large.")
    try:
        cfg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise FileInputError("symbols.json is not valid JSON.") from None
    if not isinstance(cfg, dict) or not isinstance(cfg.get("symbols"), list):
        raise FileInputError("symbols.json must be an object with a 'symbols' list.")
    if len(cfg["symbols"]) > MAX_SYMBOLS:
        raise FileInputError(f"At most {MAX_SYMBOLS} symbols are allowed.")

    clean: list[dict[str, Any]] = []
    dropped = 0
    for entry in cfg["symbols"]:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()[:100]
        if not name:
            continue
        item: dict[str, Any] = {
            "name": name,
            "description": str(entry.get("description") or "")[:500],
            "source": "artist",
        }
        ref = entry.get("image") or entry.get("image_path")
        if ref:
            try:
                item["image"] = resolve_upload(db, user, str(ref), kind="image")
            except FileInputError:
                dropped += 1
        clean.append(item)
    if not clean:
        raise FileInputError("symbols.json contains no usable symbols.")
    sanitized = {"style_prompt": str(cfg.get("style_prompt") or "")[:2000], "symbols": clean}

    upload_id = _new_upload_id()
    filename = upload_id + ".json"
    folder = uploads_dir(user["id"])
    os.makedirs(folder, exist_ok=True)
    payload = json.dumps(sanitized, indent=2).encode("utf-8")
    with open(os.path.join(folder, filename), "wb") as f:
        f.write(payload)
    name = os.path.basename(original_name or "symbols.json")[:120] or "symbols.json"
    db.add_upload(upload_id, user["id"], "symbols_json", name, filename, len(payload))
    return {"id": upload_id, "kind": "symbols_json", "name": name, "size": len(payload),
            "ref": f"upload:{upload_id}", "symbols": len(clean),
            "dropped_image_refs": dropped}


def upload_path(user: dict[str, Any], row: dict[str, Any]) -> str:
    return os.path.join(uploads_dir(user["id"]), row["filename"])


def resolve_upload(db, user: dict[str, Any], ref: str, kind: str | None = None) -> str:
    """Absolute path of the user's upload ``upload:<id>`` (or bare id)."""
    ref = (ref or "").strip()
    upload_id = ref[len("upload:"):] if ref.startswith("upload:") else ref
    if not UPLOAD_ID_RE.match(upload_id):
        raise FileInputError(
            f"{ref!r} is not one of your uploads. Upload the file first and use its 'upload:<id>' reference."
        )
    row = db.get_upload(user["id"], upload_id)
    if not row or (kind and row["kind"] != kind):
        raise FileInputError(f"Upload {upload_id!r} not found.")
    path = upload_path(user, row)
    if not os.path.isfile(path):
        raise FileInputError(f"Upload {upload_id!r} is missing on the server.")
    return os.path.abspath(path)


def delete_upload(db, user: dict[str, Any], upload_id: str) -> bool:
    if not UPLOAD_ID_RE.match(upload_id or ""):
        return False
    row = db.get_upload(user["id"], upload_id)
    if not row:
        return False
    path = upload_path(user, row)
    if os.path.isfile(path):
        os.remove(path)
    db.delete_upload(user["id"], upload_id)
    return True


def list_symbol_manifests(username: str) -> list[dict[str, str]]:
    """The user's registered symbol manifests (``symbols:<deck>`` references)."""
    root = symbols_root()
    found = []
    if not os.path.isdir(root):
        return found
    for entry in sorted(os.listdir(root)):
        short = ns.short_name(username, entry)
        if short is None or not ns.SHORT_DECK_RE.match(short):
            continue
        if os.path.isfile(os.path.join(root, entry, "symbols.json")):
            found.append({"deck": short, "ref": f"symbols:{short}"})
    return found


def resolve_symbols_ref(db, user: dict[str, Any], ref: str) -> str:
    """Map a ``symbols_file`` input to a server path the user is allowed to use."""
    from ..symbols import symbols_dir_for

    ref = (ref or "").strip()
    if not ref:
        return ""
    if ref.startswith("symbols:"):
        short = ref[len("symbols:"):]
        try:
            internal = ns.internal_name(user["username"], short)
        except ns.NamespaceError:
            raise FileInputError(f"No registered symbols for deck {short!r}.") from None
        path = os.path.join(symbols_dir_for(internal), "symbols.json")
        if not os.path.isfile(path):
            raise FileInputError(f"No registered symbols for deck {short!r}. Use register_symbols first.")
        return os.path.abspath(path)
    return resolve_upload(db, user, ref, kind="symbols_json")


# ==================== OWNED FILE MAP / URL REWRITING ====================

def _add(mapping: dict[str, str], path: str | None, url: str) -> None:
    if path and os.path.exists(str(path)):
        mapping[_real(str(path))] = url


def owned_file_map(db, user: dict[str, Any]) -> dict[str, str]:
    """realpath -> safe URL (or reference) for every file this user owns."""
    from ..symbols import symbols_dir_for

    username = user["username"]
    pre = ns.prefix(username)
    mapping: dict[str, str] = {}
    for short, internal, meta in ns.user_decks(username):
        for card in load_deck(internal):
            if card.image_path:
                _add(mapping, card.image_path, f"/files/{short}/card/{card.position}")
        _add(mapping, meta.get("back_image"), f"/files/{short}/back/back.png")
        for path in deck_artifact_files(internal, include_bundle=True):
            suffix = os.path.basename(path)[len(internal) + 1:]
            _add(mapping, path, f"/files/{short}/artifact/{suffix}")
        mapping.setdefault(_real(os.path.join(Config.OUTPUT_DIR, f"{internal}.json")), f"deck:{short}")

    pdir = previews_dir()
    if os.path.isdir(pdir):
        for fname in os.listdir(pdir):
            if fname.startswith(pre) and SAFE_FILE_RE.match(fname[len(pre):] or "-"):
                _add(mapping, os.path.join(pdir, fname), f"/files/_previews/{fname[len(pre):]}")

    root = symbols_root()
    if os.path.isdir(root):
        for entry in os.listdir(root):
            short = ns.short_name(username, entry)
            if short is None or not ns.SHORT_DECK_RE.match(short):
                continue
            sdir = symbols_dir_for(entry)
            for fname in os.listdir(sdir) if os.path.isdir(sdir) else []:
                full = os.path.join(sdir, fname)
                if fname == "symbols.json":
                    mapping[_real(full)] = f"symbols:{short}"
                elif os.path.splitext(fname)[1].lower() in IMAGE_EXTS and SAFE_FILE_RE.match(fname):
                    _add(mapping, full, f"/files/_symbols/{short}/{fname}")
            mapping.setdefault(_real(sdir), f"symbols-dir:{short}")

    if os.path.isdir(Config.OUTPUT_DIR):
        for fname in os.listdir(Config.OUTPUT_DIR):
            if CALIBRATION_RE.match(fname):
                _add(mapping, os.path.join(Config.OUTPUT_DIR, fname), f"/files/_calibration/{fname}")

    for row in db.list_uploads(user["id"]):
        url = f"/uploads/{row['id']}" if row["kind"] == "image" else f"upload:{row['id']}"
        _add(mapping, upload_path(user, row), url)
    return mapping


class Sanitizer:
    """Rewrites tool output for one user: own paths -> URLs, everything else scrubbed."""

    def __init__(self, db, user: dict[str, Any]):
        self.db = db
        self.user = user
        self.prefix = ns.prefix(user["username"])
        self._map: dict[str, str] | None = None
        dirs = {Config.OUTPUT_DIR, Config.IMAGES_DIR, os.getcwd()}
        self._dirs = sorted(
            {d for base in dirs for d in (os.path.abspath(base), _real(base))},
            key=len, reverse=True,
        )

    @property
    def mapping(self) -> dict[str, str]:
        if self._map is None:
            self._map = owned_file_map(self.db, self.user)
        return self._map

    def refresh(self) -> None:
        self._map = None

    def _lookup(self, s: str) -> str | None:
        if len(s) > 1024 or "\n" in s or not ("/" in s or "\\" in s):
            return None
        if s.startswith(("http://", "https://", "/files/", "/uploads/")):
            return None
        try:
            real = _real(s)
        except (OSError, ValueError):
            return None
        return self.mapping.get(real)

    def text(self, s: str) -> str:
        out = s
        for d in self._dirs:
            if d and len(d) > 1:
                out = out.replace(d + os.sep, "")
        out = _ABS_PATH_RE.sub("[path]", out)
        return out.replace(self.prefix, "")

    def value(self, v: Any) -> Any:
        if isinstance(v, str):
            mapped = self._lookup(v)
            return mapped if mapped is not None else self.text(v)
        if isinstance(v, dict):
            return {self.text(str(k)) if isinstance(k, str) else k: self.value(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [self.value(x) for x in v]
        return v

    def scrub(self, v: Any) -> Any:
        """Like :meth:`value` but text-only (no file lookups) -- cheap for live events."""
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, dict):
            return {self.text(str(k)) if isinstance(k, str) else k: self.scrub(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [self.scrub(x) for x in v]
        return v


# ==================== SERVING ====================

def resolve_owned_file(user: dict[str, Any], deck: str, kind: str, name: str) -> tuple[str, str] | None:
    """``(path, download_name)`` for a file URL issued by :class:`Sanitizer`, if owned."""
    from ..symbols import symbols_dir_for

    username = user["username"]
    pre = ns.prefix(username)
    path = ""
    download = name
    if deck == "_previews":
        target = name or kind
        if not SAFE_FILE_RE.match(target or ""):
            return None
        path = os.path.join(previews_dir(), pre + target)
        download = target
    elif deck == "_calibration":
        target = name or kind
        if not CALIBRATION_RE.match(target or ""):
            return None
        path = os.path.join(Config.OUTPUT_DIR, target)
        download = target
    elif deck == "_symbols":
        short, fname = kind, name
        if not ns.SHORT_DECK_RE.match(short or "") or not SAFE_FILE_RE.match(fname or ""):
            return None
        if os.path.splitext(fname)[1].lower() not in IMAGE_EXTS:
            return None
        path = os.path.join(symbols_dir_for(ns.internal_name(username, short)), fname)
        download = fname
    else:
        try:
            internal = ns.owned_deck(username, deck)
        except ns.NamespaceError:
            return None
        if kind == "card":
            if not (name or "").isdigit():
                return None
            card = next((c for c in load_deck(internal) if c.position == int(name)), None)
            if not card or not card.image_path:
                return None
            path = str(card.image_path)
            download = f"{deck}_{int(name):03d}{os.path.splitext(path)[1] or '.png'}"
        elif kind == "back":
            path = load_decks_index().get(internal, {}).get("back_image") or ""
            download = f"{deck}_back{os.path.splitext(path)[1] or '.png'}"
        elif kind == "artifact":
            if not SAFE_FILE_RE.match(name or ""):
                return None
            wanted = f"{internal}_{name}"
            matches = [p for p in deck_artifact_files(internal, include_bundle=True)
                       if os.path.basename(p) == wanted]
            if not matches:
                return None
            path = matches[0]
            download = f"{deck}_{name}"
        else:
            return None
    if not path or not os.path.isfile(path) or not is_within(path, data_roots()):
        return None
    return path, download


# ==================== THUMBNAILS & QR ====================

_THUMB_CACHE: dict[tuple[str, float, int], bytes] = {}


def thumbnail_bytes(path: str, max_side: int = 360) -> bytes:
    """Small JPEG of an image (cached by path + mtime)."""
    from PIL import Image

    key = (_real(path), os.path.getmtime(path), max_side)
    cached = _THUMB_CACHE.get(key)
    if cached is not None:
        return cached
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82, optimize=True)
    data = buf.getvalue()
    if len(_THUMB_CACHE) > 512:
        _THUMB_CACHE.clear()
    _THUMB_CACHE[key] = data
    return data


def qr_svg(url: str) -> str:
    """SVG QR code (same encoder as the printed backs)."""
    from reportlab.graphics import renderSVG
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing

    widget = QrCodeWidget(url, barLevel="M", barBorder=2)
    x0, y0, x1, y1 = widget.getBounds()
    drawing = Drawing(x1 - x0, y1 - y0)
    drawing.add(widget)
    return renderSVG.drawToString(drawing)
