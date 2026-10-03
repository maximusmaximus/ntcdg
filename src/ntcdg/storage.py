"""Deck storage, index management, history, and spreadsheet export."""

import json
import os
import re
import tempfile
import threading
from datetime import datetime
from typing import Any

from .config import Config, logger, pd
from .models import Card

# Deck names become file names, so they must never contain path separators.
DECK_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

# Serialises read-modify-write cycles on the shared index file when several
# jobs (web workers, MCP calls) touch it concurrently in one process.
_INDEX_LOCK = threading.RLock()


def validate_deck_name(deck_name: str) -> str:
    """Raise ValueError unless ``deck_name`` is a safe file-name stem."""
    if not isinstance(deck_name, str) or not DECK_NAME_RE.match(deck_name):
        raise ValueError(
            f"Invalid deck name {deck_name!r}: use 1-100 letters, numbers, "
            "underscores or hyphens."
        )
    return deck_name


def _atomic_write_json(path: str, data: Any) -> None:
    """Write JSON via temp file + os.replace so readers never see half a file."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _get_decks_index_file() -> str:
    base = os.path.basename(Config.DECKS_INDEX_FILE) or "decks_index.json"
    return os.path.join(Config.OUTPUT_DIR, base)


# ==================== DECK INDEX ====================
def load_decks_index() -> dict[str, Any]:
    index_file = _get_decks_index_file()
    with _INDEX_LOCK:
        if os.path.exists(index_file):
            try:
                with open(index_file) as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"Deck index is corrupt ({index_file}): {e}")
                return {}
    return {}


def save_decks_index(index: dict[str, Any]):
    with _INDEX_LOCK:
        _atomic_write_json(_get_decks_index_file(), index)


def update_deck_meta(deck_name: str, **fields: Any) -> dict[str, Any]:
    """Atomically merge arbitrary metadata fields into a deck's index entry."""
    validate_deck_name(deck_name)
    with _INDEX_LOCK:
        index = load_decks_index()
        entry = index.get(deck_name, {"name": deck_name})
        entry.update(fields)
        entry["last_modified"] = datetime.now().isoformat()
        entry.setdefault("created", entry["last_modified"])
        index[deck_name] = entry
        save_decks_index(index)
        return entry


def update_deck_index(deck_name: str, num_cards: int, vibe: str | None = None,
                      theme: str | None = None, *, back_image: str | None = None,
                      back_prompt: str | None = None):
    """Merge core fields into the index entry.

    ``None`` means "leave unchanged" so that routine saves (e.g. ``save_deck``)
    no longer wipe the vibe, theme, usage stats, or public URL metadata.
    """
    fields: dict[str, Any] = {"name": deck_name, "num_cards": num_cards}
    if vibe is not None:
        fields["vibe"] = vibe
    if theme is not None:
        fields["theme"] = theme
    if back_image:
        fields["back_image"] = back_image
    if back_prompt:
        fields["back_prompt"] = back_prompt
    validate_deck_name(deck_name)
    with _INDEX_LOCK:
        existing = load_decks_index().get(deck_name, {})
        defaults = {"vibe": "", "theme": "", "back_image": "", "back_prompt": ""}
        missing = {k: v for k, v in defaults.items() if k not in existing and k not in fields}
        update_deck_meta(deck_name, **missing, **fields)


def list_decks():
    index = load_decks_index()
    if not index:
        print("No decks found.")
        return

    print("\nAvailable Decks:")
    print("-" * 85)
    print(f"{'Name':<30} {'Cards':<8} {'Last Modified':<25} {'Theme'}")
    print("-" * 85)
    for name, info in sorted(index.items()):
        last_mod = info.get("last_modified", "N/A")[:19]
        theme = (info.get("theme") or info.get("vibe") or "")[:45]
        print(f"{name:<30} {info.get('num_cards', 0):<8} {last_mod:<25} {theme}")
    print("-" * 85)


def get_deck_info(deck_name: str):
    """Show comprehensive deck status and readiness report."""
    deck = load_deck(deck_name)
    if not deck:
        print(f"Deck '{deck_name}' not found.")
        return

    index = load_decks_index()
    meta = index.get(deck_name, {})

    # Counts
    total = len(deck)
    has_images = sum(
        1 for c in deck
        if c.image_path and os.path.exists(str(c.image_path))
    )
    has_analysis = sum(
        1 for c in deck if c.description and not c.venice_error
    )
    has_meanings = sum(
        1 for c in deck
        if c.upright_interpretation and c.reversed_interpretation
    )
    has_errors = sum(
        1 for c in deck if c.venice_error or c.image_error
    )
    has_back = bool(meta.get("back_image", ""))

    print(f"\nDeck: {deck_name}")
    print(f"Cards: {total}")
    if meta.get("created"):
        print(f"Created: {meta['created'][:10]}")
    if meta.get("vibe"):
        print(f"Vibe: {meta['vibe']}")
    if meta.get("theme"):
        print(f"Theme: {meta['theme'][:60]}")

    def pct(n):
        return f"{100 * n // max(total, 1)}%"

    print("\nCompletion:")
    print(f"  Images:    {has_images}/{total} ({pct(has_images)})")
    print(f"  Analysis:  {has_analysis}/{total} ({pct(has_analysis)})")
    print(f"  Meanings:  {has_meanings}/{total} ({pct(has_meanings)})")
    print(f"  Card Back: {'Y' if has_back else 'Not generated'}")

    ready = has_images == total and has_analysis == total
    if ready:
        print("\n  Ready to finalize: Y")
    else:
        blockers = []
        if has_images < total:
            blockers.append(f"{total - has_images} missing images")
        if has_analysis < total:
            blockers.append(f"{total - has_analysis} missing analysis")
        print(f"\n  Ready to finalize: N ({', '.join(blockers)})")

    if has_errors:
        print(f"\nErrors ({has_errors}):")
        error_cards = [
            c for c in deck if c.venice_error or c.image_error
        ]
        for c in error_cards[:10]:
            err = c.venice_error or c.image_error
            print(f"  Card {c.position} - {c.display_title()}: {str(err)[:50]}")
        if len(error_cards) > 10:
            print(f"  ... and {len(error_cards) - 10} more")


def list_cards(deck_name: str):
    """Show all cards in a deck with completion status."""
    deck = load_deck(deck_name)
    if not deck:
        print(f"Deck '{deck_name}' not found.")
        return

    sorted_deck = sorted(deck, key=lambda c: c.position or 0)

    print(f"\n{deck_name} — {len(deck)} cards")
    print("-" * 90)
    print(
        f"{'#':<5} {'Title':<28} {'Type':<15} "
        f"{'Image':<7} {'Text':<6} {'Mean.':<6} {'Status'}"
    )
    print("-" * 90)

    ok = 0
    for card in sorted_deck:
        has_img = bool(
            card.image_path and os.path.exists(str(card.image_path))
        )
        has_text = bool(card.description and not card.venice_error)
        has_mean = bool(
            card.upright_interpretation and card.reversed_interpretation
        )

        img_sym = "Y" if has_img else "-"
        txt_sym = "Y" if has_text else "-"
        mean_sym = "Y" if has_mean else "-"

        if has_img and has_text and has_mean:
            status = "Complete"
            ok += 1
        elif card.venice_error or card.image_error:
            err = card.venice_error or card.image_error
            status = f"Error: {str(err)[:25]}"
        else:
            missing = []
            if not has_img:
                missing.append("image")
            if not has_text:
                missing.append("desc")
            if not has_mean:
                missing.append("meanings")
            status = f"Missing: {', '.join(missing)}"

        title = card.display_title()[:27]
        ctype = (card.card_type or "")[:14]
        print(
            f"{card.position:<5} {title:<28} {ctype:<15} "
            f"{img_sym:<7} {txt_sym:<6} {mean_sym:<6} {status}"
        )

    print("-" * 90)
    print(f"Complete: {ok}/{len(deck)} ({100*ok//max(len(deck),1)}%)")


# ==================== DECK LOADING / SAVING ====================
def load_deck(deck_name: str) -> list[Card]:
    """Load a deck from JSON, returning a list of Card objects."""
    validate_deck_name(deck_name)
    json_path = os.path.join(Config.OUTPUT_DIR, f"{deck_name}.json")
    if os.path.exists(json_path):
        with open(json_path) as f:
            raw = json.load(f)
        return [Card.from_dict(d) for d in raw]
    return []


def deck_exists(deck_name: str) -> bool:
    validate_deck_name(deck_name)
    return os.path.exists(os.path.join(Config.OUTPUT_DIR, f"{deck_name}.json"))


def deck_images_dir(deck_name: str) -> str:
    """Folder for one deck's card art: ``IMAGES_DIR/<deck>``.

    Card image file names (``001_The_Fool.png``) are only unique within a deck,
    so every deck needs its own folder or concurrent decks overwrite each other.
    """
    validate_deck_name(deck_name)
    return os.path.join(Config.IMAGES_DIR, deck_name)


def preview_raw_dir(deck_name: str) -> str:
    """Scratch folder for raw style-preview renders of ``deck_name``."""
    validate_deck_name(deck_name)
    return os.path.join(Config.IMAGES_DIR, "previews", "_raw", deck_name)


_ARTIFACT_SUFFIX_RE = re.compile(
    r"^_(?:"
    r"(?:PRINT|BACKS|DUPLEX)_[a-z0-9]+_[a-z]+(?:_[a-z_]+)?\.pdf"
    r"|BOOKLET\.pdf"
    r"|MASTER\.xlsx"
    r"|BUNDLE\.zip"
    r"|CALIBRATION_[a-z0-9]+(?:_[a-z_]+)?\.pdf"
    r")$"
)


def deck_artifact_files(
    deck_name: str, *, include_json: bool = False, include_bundle: bool = False,
) -> list[str]:
    """Return generated files that belong to exactly ``deck_name``.

    Globbing ``{deck}_*`` is unsafe: deck ``a`` would match files of a deck
    called ``a_PRINT_x``. Each candidate's suffix is checked against the known
    artifact patterns (whose sheet/colour tokens never contain upper case),
    so other decks' files are never matched.
    """
    validate_deck_name(deck_name)
    out_dir = Config.OUTPUT_DIR
    if not os.path.isdir(out_dir):
        return []
    found: list[str] = []
    prefix = deck_name
    for fname in sorted(os.listdir(out_dir)):
        if include_json and fname == f"{deck_name}.json":
            found.append(os.path.join(out_dir, fname))
            continue
        if not fname.startswith(prefix + "_"):
            continue
        suffix = fname[len(prefix):]
        if not _ARTIFACT_SUFFIX_RE.match(suffix):
            continue
        if suffix == "_BUNDLE.zip" and not include_bundle:
            continue
        found.append(os.path.join(out_dir, fname))
    return found


def save_deck(deck: list[Card], deck_name: str, *, export: bool = True):
    """Save a deck to JSON, update spreadsheet and index.

    ``export=False`` skips the spreadsheet; used for cheap per-card checkpoints
    during long generations so a crash never loses completed cards.
    """
    validate_deck_name(deck_name)
    json_path = os.path.join(Config.OUTPUT_DIR, f"{deck_name}.json")
    _atomic_write_json(json_path, [c.to_dict() for c in deck])
    if export:
        export_spreadsheet(deck, deck_name)
    update_deck_index(deck_name, len(deck))


# ==================== HISTORY ====================
def load_history() -> dict[str, Any]:
    if os.path.exists(Config.HISTORY_FILE):
        with open(Config.HISTORY_FILE) as f:
            return json.load(f)
    return {"cards": [], "decks": []}


def is_novel(card: Card, history: dict[str, Any]) -> bool:
    """Check if a card's symbols are sufficiently different from history."""
    new_symbols = set(card.symbols)
    for past in history.get("cards", []):
        overlap = len(new_symbols & set(past.get("symbols", []))) / max(len(new_symbols), 1)
        if overlap > Config.NOVELTY_THRESHOLD:
            return False
    return True


# ==================== SPREADSHEET ====================
def export_spreadsheet(deck: list[Card], deck_name: str) -> str:
    if pd is None:
        logger.warning("pandas not installed — skipping spreadsheet")
        return ""
    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
    path = os.path.join(Config.OUTPUT_DIR, f"{deck_name}_MASTER.xlsx")

    rows = []
    for card in deck:
        rows.append({
            "Position": card.position,
            "Title": card.display_title(),
            "Description": card.description or "",
            "Upright": card.upright_interpretation or "",
            "Reversed": card.reversed_interpretation or "",
            "Type": card.card_type,
            "Suit": card.suit,
            "Symbols": " | ".join(card.symbols),
            "Is_First": card.is_first,
            "Is_Last": card.is_last,
            "Image_Path": card.image_path or "",
        })

    df = pd.DataFrame(rows)
    df.to_excel(path, index=False, sheet_name="Deck")
    logger.info(f"Spreadsheet saved: {path}")
    return path


# ==================== CARD EDITING ====================
def edit_card_field(
    deck_name: str, card_position: int, field: str, value: str,
) -> bool:
    """Edit a single field of a card in a saved deck.

    Valid fields: title, new_title, venice_title, description,
    upright_interpretation, reversed_interpretation.
    ``venice_title`` is the displayed title when Venice named the card.
    Returns True on success.
    """
    valid_fields = {
        "title", "new_title", "venice_title", "description",
        "upright_interpretation", "reversed_interpretation",
    }
    if field not in valid_fields:
        print(f"Invalid field '{field}'. Valid: {', '.join(sorted(valid_fields))}")
        return False

    deck = load_deck(deck_name)
    if not deck:
        print(f"Deck '{deck_name}' not found.")
        return False

    card = next((c for c in deck if c.position == card_position), None)
    if not card:
        print(f"Card {card_position} not found in deck '{deck_name}'.")
        return False

    old_value = getattr(card, field, "")
    setattr(card, field, value)
    save_deck(deck, deck_name)
    print(f"Updated card {card_position} [{field}]:")
    print(f"  Old: {(old_value or '(empty)')[:80]}")
    print(f"  New: {value[:80]}")
    return True


def delete_deck(deck_name: str, confirm: bool = True) -> bool:
    """Delete a deck and all its associated files."""
    deck = load_deck(deck_name)
    if not deck:
        print(f"Deck '{deck_name}' not found.")
        return False

    if confirm:
        print(f"\nThis will delete deck '{deck_name}':")
        print(f"  - {len(deck)} card records")
        img_count = sum(
            1 for c in deck
            if c.image_path and os.path.exists(str(c.image_path))
        )
        print(f"  - {img_count} card images")
        print("  - All associated PDFs and spreadsheets")
        response = input("\nType 'DELETE' to confirm: ")
        if response != "DELETE":
            print("Cancelled.")
            return False

    # Remove card images
    for card in deck:
        if card.image_path and os.path.exists(str(card.image_path)):
            os.remove(card.image_path)

    # Remove deck files (JSON, PDFs, spreadsheet, bundle)
    for filepath in deck_artifact_files(deck_name, include_json=True, include_bundle=True):
        os.remove(filepath)
        logger.info(f"Removed: {filepath}")

    # Remove back image
    index = load_decks_index()
    meta = index.get(deck_name, {})
    back = meta.get("back_image", "")
    if back and os.path.exists(back):
        os.remove(back)

    # Remove the deck's own image folder if nothing else is left in it
    img_dir = deck_images_dir(deck_name)
    if os.path.isdir(img_dir) and not os.listdir(img_dir):
        os.rmdir(img_dir)

    # Remove from index
    with _INDEX_LOCK:
        index = load_decks_index()
        if deck_name in index:
            del index[deck_name]
            save_decks_index(index)

    print(f"Deck '{deck_name}' deleted.")
    return True


def clone_deck(source_name: str, dest_name: str) -> bool:
    """Clone a deck with all its images under a new name."""
    import shutil

    deck = load_deck(source_name)
    if not deck:
        print(f"Source deck '{source_name}' not found.")
        return False

    existing = load_deck(dest_name)
    if existing:
        print(f"Destination deck '{dest_name}' already exists.")
        return False

    # Clone card images with new names
    cloned_deck = []
    for card in deck:
        import copy
        new_card = copy.deepcopy(card)

        if card.image_path and os.path.exists(str(card.image_path)):
            old_basename = os.path.basename(card.image_path)
            new_basename = old_basename  # keep same filename
            new_dir = os.path.join(Config.IMAGES_DIR, dest_name)
            os.makedirs(new_dir, exist_ok=True)
            new_path = os.path.join(new_dir, new_basename)
            shutil.copy2(card.image_path, new_path)
            new_card.image_path = new_path

        cloned_deck.append(new_card)

    save_deck(cloned_deck, dest_name)

    # Clone index entry
    index = load_decks_index()
    source_meta = index.get(source_name, {})
    if source_meta:
        # Copy the back image so deleting either deck never removes the other's back.
        back = source_meta.get("back_image", "")
        new_back = ""
        if back and os.path.exists(back):
            new_dir = os.path.join(Config.IMAGES_DIR, dest_name)
            os.makedirs(new_dir, exist_ok=True)
            new_back = os.path.join(new_dir, f"back_{os.path.basename(back)}")
            shutil.copy2(back, new_back)
        update_deck_index(
            dest_name, len(cloned_deck),
            vibe=source_meta.get("vibe", ""),
            theme=source_meta.get("theme", ""),
            back_image=new_back,
            back_prompt=source_meta.get("back_prompt", ""),
        )

    print(f"Cloned '{source_name}' -> '{dest_name}' ({len(cloned_deck)} cards)")
    return True
