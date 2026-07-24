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
- New Deck dialog
- Refresh after regeneration

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


class DeckDetailScreen(Screen):
    def __init__(self, deck_name: str):
        super().__init__()
        self.deck_name = deck_name
        self.deck = load_deck(deck_name)
        self.filtered = self.deck[:]

    def compose(self) -> ComposeResult:
        yield Header(f"Deck: {self.deck_name}")
        yield Input(placeholder="Filter cards by title...", id="filter")
        yield DataTable(id="card_table", cursor_type="row")
        yield Horizontal(
            Button("Edit Card", id="edit"),
            Button("Regenerate", id="regenerate"),
            Button("Refresh", id="refresh"),
            Button("Open Proof Sheet", id="proof"),
            Button("Back", id="back"),
        )
        yield Footer()

    def on_mount(self):
        self.reload_deck()

    def reload_deck(self):
        self.deck = load_deck(self.deck_name)
        self.refresh_table()

    def refresh_table(self, filter_text: str = ""):
        table = self.query_one(DataTable)
        table.clear()
        table.add_columns("Pos", "Title", "Type", "Image")
        self.filtered = [
            c for c in self.deck
            if filter_text.lower() in (c.get("venice_title") or c.get("title", "")).lower()
        ]
        for card in sorted(self.filtered, key=lambda x: x.get("position", 0)):
            pos = card.get("position", "?")
            title = card.get("venice_title") or card.get("title", "Untitled")
            ctype = card.get("type", "")
            has_img = "Yes" if card.get("image_path") else "No"
            table.add_row(str(pos), title, ctype, has_img)

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "filter":
            self.refresh_table(event.value)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "refresh":
            self.reload_deck()
            self.notify("Deck refreshed")
            return
        if event.button.id == "back":
            self.app.pop_screen()
            return
        if event.button.id == "proof":
            self.open_proof_sheet()
            return
        table = self.query_one(DataTable)
        if table.cursor_row is None:
            self.notify("Select a card first")
            return
        row = table.get_row_at(table.cursor_row)
        pos = int(row[0])
        if event.button.id == "edit":
            self.app.push_screen(CardEditorScreen(self.deck_name, pos))
        elif event.button.id == "regenerate":
            self.app.push_screen(RegenerateDialog(self.deck_name, [pos], on_complete=self.reload_deck))

    def open_proof_sheet(self):
        pdf_path = DECKS_DIR / f"{self.deck_name}_PROOF_SHEET.pdf"
        if pdf_path.exists():
            try:
                if os.name == "nt":
                    os.startfile(pdf_path)
                else:
                    subprocess.run(["xdg-open", str(pdf_path)])
            except Exception as e:
                self.notify(f"Could not open: {e}")
        else:
            self.notify("Proof sheet not found.")


class CardEditorScreen(ModalScreen):
    def __init__(self, deck_name: str, position: int):
        super().__init__()
        self.deck_name = deck_name
        self.position = position
        self.deck = load_deck(deck_name)
        self.card = next((c for c in self.deck if c.get("position") == position), {})

    def compose(self) -> ComposeResult:
        yield Label(f"Editing Card #{self.position}")
        yield Input(value=self.card.get("venice_title") or self.card.get("title", ""), id="title")
        yield Input(value=self.card.get("description", ""), id="description")
        yield Input(value=self.card.get("upright_interpretation", ""), id="upright")
        yield Input(value=self.card.get("reversed_interpretation", ""), id="reversed")
        yield Horizontal(
            Button("Save", id="save"),
            Button("Cancel", id="cancel"),
        )

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "save":
            for card in self.deck:
                if card.get("position") == self.position:
                    card["venice_title"] = self.query_one("#title", Input).value
                    card["description"] = self.query_one("#description", Input).value
                    card["upright_interpretation"] = self.query_one("#upright", Input).value
                    card["reversed_interpretation"] = self.query_one("#reversed", Input).value
                    break
            save_deck(self.deck_name, self.deck)
            self.dismiss()
            self.app.notify("Card saved!")
        elif event.button.id == "cancel":
            self.dismiss()


class RegenerateDialog(ModalScreen):
    def __init__(self, deck_name: str, positions: list, on_complete=None):
        super().__init__()
        self.deck_name = deck_name
        self.positions = positions
        self.on_complete = on_complete

    def compose(self) -> ComposeResult:
        yield Label(f"Regenerate cards: {', '.join(map(str, self.positions))}")
        yield RadioSet(
            RadioButton("Text Analysis Only", id="text"),
            RadioButton("Images Only", id="images"),
            RadioButton("Both", id="both", value=True),
        )
        yield Horizontal(
            Button("Start Regeneration", id="start"),
            Button("Cancel", id="cancel"),
        )

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "start":
            if not HAS_CORE:
                self.app.notify("Core module not found.")
                self.dismiss()
                return
            radio = self.query_one(RadioSet)
            choice = radio.pressed_button.id if radio.pressed_button else "both"
            regenerate_text = choice in ["text", "both"]
            regenerate_images = choice in ["images", "both"]
            settings = load_settings()
            venice_key = settings.get("venice_api_key") or os.getenv("VENICE_API_KEY")
            if not venice_key:
                self.app.notify("No Venice API key found!")
                self.dismiss()
                return
            deck = load_deck(self.deck_name)
            if not deck:
                self.app.notify("Could not load deck.")
                self.dismiss()
                return
            success_count = 0
            text_model = settings.get("text_model", "llama-3.1-405b")
            image_model = settings.get("image_model", "venice-sd3")
            image_size = settings.get("image_size", "1024x1536")
            element_mode = settings.get("element_mode", "text")
            custom_dir = settings.get("custom_elements_dir", "custom_elements")
            custom_elements = {}
            if element_mode == "custom" and load_custom_elements:
                custom_elements = load_custom_elements(custom_dir)
            self.notify("Regenerating...")
            for pos in self.positions:
                card = next((c for c in deck if c.get("position") == pos), None)
                if not card:
                    continue
                try:
                    if regenerate_text:
                        analysis = analyze_with_venice(card, venice_key, text_model)
                        if "venice_error" not in analysis:
                            card.update(analysis)
                            success_count += 1
                    if regenerate_images:
                        img_result = generate_image_with_venice(
                            card, venice_key, image_model,
                            image_size=image_size,
                            element_mode=element_mode,
                            custom_elements=custom_elements
                        )
                        if img_result.get("image_path"):
                            card.update(img_result)
                            success_count += 1
                except Exception as e:
                    self.app.notify(f"Error on card {pos}: {str(e)[:80]}")
            save_deck(self.deck_name, deck)
            self.app.notify(f"Regeneration complete! Updated {success_count} operation(s).")
            self.dismiss()
            if self.on_complete:
                self.on_complete()
        elif event.button.id == "cancel":
            self.dismiss()


class NewDeckDialog(ModalScreen):
    def compose(self) -> ComposeResult:
        settings = load_settings()
        yield Label("Create a New Deck")
        yield Label("Deck Name")
        yield Input(value="New_Deck", id="deck_name")
        yield Label("Number of Cards")
        yield Input(value="78", id="num_cards")
        yield Label("Deck Theme / Prompt")
        yield Input(value="cyber-psychedelic journey", id="deck_prompt")
        yield Label(f"Element Mode (current: {settings.get('element_mode', 'text')})")
        yield Input(value=settings.get("element_mode", "text"), id="element_mode")
        yield Horizontal(
            Button("Generate", id="generate"),
            Button("Cancel", id="cancel"),
        )

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel":
            self.dismiss()
            return
        if event.button.id == "generate":
            name = self.query_one("#deck_name", Input).value.strip() or "New_Deck"
            try:
                num_cards = int(self.query_one("#num_cards", Input).value.strip() or "78")
            except ValueError:
                num_cards = 78
            prompt = self.query_one("#deck_prompt", Input).value.strip()
            mode = self.query_one("#element_mode", Input).value.strip().lower()
            if mode not in ("text", "custom"):
                mode = "text"
            settings = load_settings()
            custom_dir = settings.get("custom_elements_dir", "custom_elements")
            cmd = [
                "python", "ntcdg_generator.py",
                "--deck", "--name", name, "--cards", str(num_cards),
                "--deck-prompt", prompt, "--element-mode", mode,
                "--analyze", "--generate-images",
            ]
            if mode == "custom":
                cmd.extend(["--custom-elements-dir", custom_dir])
            self.notify(f"Starting generation of '{name}'...")
            try:
                subprocess.Popen(cmd)
                self.app.notify(f"Deck generation started for '{name}'.")
            except Exception as e:
                self.app.notify(f"Failed to start generation: {e}")
            self.dismiss()


class SettingsScreen(Screen):
    def compose(self) -> ComposeResult:
        settings = load_settings()
        yield Header("NTCDG Settings")
        yield Label("Venice API Key (optional - can also use env var)")
        yield Input(value=settings.get("venice_api_key", ""), id="api_key", password=True)
        yield Label("Default Text Model")
        yield Input(value=settings.get("text_model", "llama-3.1-405b"), id="text_model")
        yield Label("Default Image Model")
        yield Input(value=settings.get("image_model", "venice-sd3"), id="image_model")
        yield Label("Default Image Size")
        yield Input(value=settings.get("image_size", "1024x1536"), id="image_size")
        yield Label("Element Mode (text or custom)")
        yield Input(value=settings.get("element_mode", "text"), id="element_mode")
        yield Label("Custom Elements Directory")
        yield Input(value=settings.get("custom_elements_dir", "custom_elements"), id="custom_elements_dir")
        yield Horizontal(
            Button("Save Settings", id="save"),
            Button("Back", id="back"),
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "save":
            mode = self.query_one("#element_mode", Input).value.strip().lower()
            if mode not in ("text", "custom"):
                mode = "text"
            new_settings = {
                "venice_api_key": self.query_one("#api_key", Input).value,
                "text_model": self.query_one("#text_model", Input).value,
                "image_model": self.query_one("#image_model", Input).value,
                "image_size": self.query_one("#image_size", Input).value,
                "element_mode": mode,
                "custom_elements_dir": self.query_one("#custom_elements_dir", Input).value.strip() or "custom_elements",
            }
            save_settings(new_settings)
            self.app.notify("Settings saved successfully!")
            self.app.pop_screen()
        elif event.button.id == "back":
            self.app.pop_screen()


class NTCDGApp(App):
    CSS = """
    Screen { align: center middle; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("d", "toggle_dark", "Dark Mode"),
    ]
    def on_mount(self):
        self.push_screen(DeckListScreen())


if __name__ == "__main__":
    NTCDGApp().run()
