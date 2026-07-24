"""Deck storage, index management, history, and spreadsheet export."""

import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional

from .config import Config, logger, pd
from .models import Card


# ==================== DECK INDEX ====================
def load_decks_index() -> Dict[str, Any]:
    if os.path.exists(Config.DECKS_INDEX_FILE):
        with open(Config.DECKS_INDEX_FILE, "r") as f:
            return json.load(f)
    return {}


def save_decks_index(index: Dict[str, Any]):
    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
    with open(Config.DECKS_INDEX_FILE, "w") as f:
        json.dump(index, f, indent=2)


def update_deck_index(deck_name: str, num_cards: int, vibe: str = "", theme: str = ""):
    index = load_decks_index()
    index[deck_name] = {
        "name": deck_name,
        "num_cards": num_cards,
        "vibe": vibe,
        "theme": theme,
        "last_modified": datetime.now().isoformat(),
        "created": index.get(deck_name, {}).get("created", datetime.now().isoformat()),
    }
    save_decks_index(index)


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
    deck = load_deck(deck_name)
    if not deck:
        print(f"Deck '{deck_name}' not found.")
        return

    print(f"\nDeck: {deck_name}")
    print(f"Cards: {len(deck)}")
    print(f"First card: {deck[0].title if deck else 'N/A'}")
    print(f"Last card:  {deck[-1].title if deck else 'N/A'}")

    has_images = sum(1 for c in deck if c.image_path)
    print(f"Images generated: {has_images}/{len(deck)}")


# ==================== DECK LOADING / SAVING ====================
def load_deck(deck_name: str) -> List[Card]:
    """Load a deck from JSON, returning a list of Card objects."""
    json_path = os.path.join(Config.OUTPUT_DIR, f"{deck_name}.json")
    if os.path.exists(json_path):
        with open(json_path, "r") as f:
            raw = json.load(f)
        return [Card.from_dict(d) for d in raw]
    return []


def save_deck(deck: List[Card], deck_name: str):
    """Save a deck to JSON, update spreadsheet and index."""
    json_path = os.path.join(Config.OUTPUT_DIR, f"{deck_name}.json")
    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump([c.to_dict() for c in deck], f, indent=2)
    export_spreadsheet(deck, deck_name)
    update_deck_index(deck_name, len(deck))


# ==================== HISTORY ====================
def load_history() -> Dict[str, Any]:
    if os.path.exists(Config.HISTORY_FILE):
        with open(Config.HISTORY_FILE, "r") as f:
            return json.load(f)
    return {"cards": [], "decks": []}


def is_novel(card: Card, history: Dict[str, Any]) -> bool:
    """Check if a card's symbols are sufficiently different from history."""
    new_symbols = set(card.symbols)
    for past in history.get("cards", []):
        overlap = len(new_symbols & set(past.get("symbols", []))) / max(len(new_symbols), 1)
        if overlap > Config.NOVELTY_THRESHOLD:
            return False
    return True


# ==================== SPREADSHEET ====================
def export_spreadsheet(deck: List[Card], deck_name: str) -> str:
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
