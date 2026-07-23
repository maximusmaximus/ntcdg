#!/usr/bin/env python3
"""
NTCDG TUI - Full Text User Interface

Features implemented:
- Deck list with search
- Card browser with filtering
- Card editor (title, description, upright/reversed)
- Regeneration dialog (text / images / both)
- Settings screen
- Quick proof sheet opening

Run: python tui.py
Requires: pip install textual
"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Header, Footer, DataTable, Button, Static, Input, Label, RadioSet, RadioButton
)
from textual.screen import ModalScreen, Screen
from textual.binding import Binding
import json
import os
import subprocess
from pathlib import Path

# Import core generation functions
try:
    from ntcdg_generator import (
        analyze_with_venice,
        generate_image_with_venice,
        load_custom_elements,
        Config,
    )
    HAS_CORE = True
except ImportError:
    HAS_CORE = False
    load_custom_elements = None

DECKS_DIR = Path("generated_decks")
SETTINGS_FILE = DECKS_DIR / "ntcdg_settings.json"


def load_settings():
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return {
        "venice_api_key": "",
        "text_model": "llama-3.1-405b",
        "image_model": "venice-sd3",
        "image_size": "1024x1536",
        "element_mode": "text",
        "custom_elements_dir": "custom_elements",
    }


def save_settings(settings: dict):
    DECKS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


def load_decks_index():
    index_file = DECKS_DIR / "decks_index.json"
    if index_file.exists():
        with open(index_file) as f:
            return json.load(f)
    return {}


def load_deck(name: str):
    path = DECKS_DIR / f"{name}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def save_deck(name: str, deck: list):
    path = DECKS_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(deck, f, indent=2)


# ==================== SCREENS ====================
class DeckListScreen(Screen):
    BINDINGS = [Binding("q", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header("NTCDG - Deck Manager")
        yield Input(placeholder="Search decks...", id="search")
        yield DataTable(id="deck_table", cursor_type="row")
        yield Horizontal(
            Button("Open Deck", id="open"),
            Button("New Deck", id="new_deck"),
            Button("Settings", id="settings"),
            Button("Quit", id="quit"),
        )
        yield Footer()

    def on_mount(self):
        self.refresh_deck_list()

    def refresh_deck_list(self, filter_text: str = ""):
        table = self.query_one(DataTable)
        table.clear()
        table.add_columns("Name", "Cards", "Last Modified", "Theme")

        index = load_decks_index()
        for name, info in sorted(index.items()):
            if filter_text.lower() not in name.lower():
                continue
            last_mod = info.get("last_modified", "")[:19]
            theme = (info.get("theme") or info.get("vibe") or "")[:45]
            table.add_row(name, str(info.get("num_cards", 0)), last_mod, theme)

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "search":
            self.refresh_deck_list(event.value)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "open":
            table = self.query_one(DataTable)
            if table.cursor_row is not None:
                row = table.get_row_at(table.cursor_row)
                self.app.push_screen(DeckDetailScreen(row[0]))
        elif event.button.id == "new_deck":
            self.app.push_screen(NewDeckDialog())
        elif event.button.id == "settings":
            self.app.push_screen(SettingsScreen())
        elif event.button.id == "quit":
            self.app.exit()
