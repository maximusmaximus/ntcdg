"""
NTCDG TUI - Full Text User Interface

Features implemented:
- Deck list with search (dynamically rooted at Config.OUTPUT_DIR)
- Card browser with filtering
- Card editor (title, description, upright/reversed with live frame recomposition)
- Non-blocking background regeneration dialog (text / images / both)
- Settings screen integrated with ~/.ntcdgrc defaults
- Quick proof sheet opening
- New Deck dialog passing configured models & safe environment API key

Run: ntcdg-tui  (or: python -m ntcdg.tui)
Requires: pip install textual
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
)

from .config import Config, setup_logging
from .models import Card
from .overlay import compose_card, get_card_number_text, recompose_card
from .storage import (
    deck_images_dir,
    load_deck,
    load_decks_index,
    save_deck,
)
from .symbols import load_symbols_config
from .userconfig import load_user_config
from .venice import analyze_with_venice, generate_image_with_venice


def _decks_dir() -> Path:
    """Resolve the active decks directory dynamically from ``Config.OUTPUT_DIR``."""
    return Path(Config.OUTPUT_DIR)


def _settings_file() -> Path:
    return _decks_dir() / "ntcdg_settings.json"


def load_settings() -> dict[str, Any]:
    """Load TUI settings, seeding defaults from ``~/.ntcdgrc`` when present."""
    rc = load_user_config()
    defaults: dict[str, Any] = {
        "venice_api_key": rc.get("venice_api_key", ""),
        "text_model": rc.get("default_text_model") or Config.DEFAULT_TEXT_MODEL,
        "image_model": rc.get("default_image_model") or Config.DEFAULT_IMAGE_MODEL,
        "edit_model": Config.DEFAULT_EDIT_MODEL,
        "image_size": rc.get("default_image_size") or Config.DEFAULT_IMAGE_SIZE,
        "symbol_mode": "generate",
        "symbols_file": "",
        "font_path": rc.get("default_font", ""),
    }
    sf = _settings_file()
    if sf.exists():
        try:
            with open(sf, encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if v != "" or k not in defaults or not defaults[k]:
                        defaults[k] = v
        except (OSError, json.JSONDecodeError):
            pass
    return defaults


def save_settings(settings: dict[str, Any]) -> None:
    """Persist TUI settings without clobbering unspecified keys."""
    merged = load_settings()
    merged.update(settings)
    decks_dir = _decks_dir()
    decks_dir.mkdir(parents=True, exist_ok=True)
    with open(_settings_file(), "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)


class DeckListScreen(Screen):
    TITLE = "NTCDG - Deck Manager"
    BINDINGS = [Binding("q", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search decks...", id="search")
        yield DataTable(id="deck_table", cursor_type="row")
        yield Horizontal(
            Button("Open Deck", id="open"),
            Button("New Deck", id="new_deck"),
            Button("Settings", id="settings"),
            Button("Quit", id="quit"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_deck_list()

    def refresh_deck_list(self, filter_text: str = "") -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        table.add_columns("Name", "Cards", "Last Modified", "Theme")
        index = load_decks_index()
        for name, info in sorted(index.items()):
            if filter_text.lower() not in name.lower():
                continue
            last_mod = info.get("last_modified", "")[:19]
            theme = (info.get("theme") or info.get("vibe") or "")[:45]
            table.add_row(name, str(info.get("num_cards", 0)), last_mod, theme)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.refresh_deck_list(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open":
            table = self.query_one(DataTable)
            if table.cursor_row is not None and table.row_count > 0:
                row = table.get_row_at(table.cursor_row)
                self.app.push_screen(DeckDetailScreen(str(row[0])))
        elif event.button.id == "new_deck":
            self.app.push_screen(NewDeckDialog())
        elif event.button.id == "settings":
            self.app.push_screen(SettingsScreen())
        elif event.button.id == "quit":
            self.app.exit()


class DeckDetailScreen(Screen):
    def __init__(self, deck_name: str) -> None:
        super().__init__()
        self.deck_name = deck_name
        self.sub_title = f"Deck: {deck_name}"
        self.deck = load_deck(deck_name)
        self.filtered = self.deck[:]

    def compose(self) -> ComposeResult:
        yield Header()
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

    def on_mount(self) -> None:
        self.reload_deck()

    def reload_deck(self) -> None:
        self.deck = load_deck(self.deck_name)
        self.refresh_table()

    def refresh_table(self, filter_text: str = "") -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        table.add_columns("Pos", "Title", "Type", "Image")
        self.filtered = [
            c for c in self.deck
            if filter_text.lower() in c.display_title().lower()
        ]
        for card in sorted(self.filtered, key=lambda c: c.position or 0):
            has_img = "Yes" if card.image_path else "No"
            table.add_row(str(card.position), card.display_title(), card.card_type, has_img)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.refresh_table(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
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
        if table.cursor_row is None or table.row_count == 0:
            self.notify("Select a card first")
            return
        row = table.get_row_at(table.cursor_row)
        pos = int(row[0])
        if event.button.id == "edit":
            self.app.push_screen(CardEditorScreen(self.deck_name, pos, on_saved=self.reload_deck))
        elif event.button.id == "regenerate":
            self.app.push_screen(
                RegenerateDialog(self.deck_name, [pos], on_complete=self.reload_deck)
            )

    def open_proof_sheet(self) -> None:
        pdf_path = _decks_dir() / f"{self.deck_name}_PROOF_SHEET.pdf"
        if pdf_path.exists():
            try:
                startfile = getattr(os, "startfile", None)
                if os.name == "nt" and startfile is not None:
                    startfile(str(pdf_path))
                else:
                    subprocess.run(["xdg-open", str(pdf_path)], check=False)
            except Exception as e:
                self.notify(f"Could not open: {e}")
        else:
            self.notify("Proof sheet not found.")


class CardEditorScreen(ModalScreen):
    def __init__(
        self,
        deck_name: str,
        position: int,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.deck_name = deck_name
        self.position = position
        self.on_saved = on_saved
        self.deck = load_deck(deck_name)
        self.card = next((c for c in self.deck if c.position == position), Card())

    def compose(self) -> ComposeResult:
        yield Label(f"Editing Card #{self.position}")
        yield Input(value=self.card.display_title(), id="title")
        yield Input(value=self.card.description or "", id="description")
        yield Input(value=self.card.upright_interpretation or "", id="upright")
        yield Input(value=self.card.reversed_interpretation or "", id="reversed")
        yield Horizontal(
            Button("Save", id="save"),
            Button("Cancel", id="cancel"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            new_title = self.query_one("#title", Input).value
            settings = load_settings()
            for card in self.deck:
                if card.position == self.position:
                    old_display = card.display_title()
                    if card.title and not card.canonical_title:
                        card.canonical_title = card.title
                    card.venice_title = new_title
                    if card.new_title is not None:
                        card.new_title = new_title
                    card.description = self.query_one("#description", Input).value
                    card.upright_interpretation = self.query_one("#upright", Input).value
                    card.reversed_interpretation = self.query_one("#reversed", Input).value
                    if new_title != old_display:
                        recompose_card(card, font_path=settings.get("font_path") or "")
                    break
            save_deck(self.deck, self.deck_name)
            if self.on_saved:
                self.on_saved()
            self.dismiss()
            self.app.notify("Card saved!")
        elif event.button.id == "cancel":
            self.dismiss()


class RegenerateDialog(ModalScreen):
    def __init__(
        self,
        deck_name: str,
        positions: list[int],
        on_complete: Callable[[], None] | None = None,
    ) -> None:
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            radio = self.query_one(RadioSet)
            choice = radio.pressed_button.id if radio.pressed_button else "both"
            regenerate_text = choice in ("text", "both")
            regenerate_images = choice in ("images", "both")

            settings = load_settings()
            venice_key = settings.get("venice_api_key") or os.getenv("VENICE_API_KEY") or ""
            if not venice_key:
                self.app.notify("No Venice API key found!")
                self.dismiss()
                return

            if not load_deck(self.deck_name):
                self.app.notify("Could not load deck.")
                self.dismiss()
                return

            self.app.notify(f"⏳ Regenerating {len(self.positions)} card(s) in background...")
            self._run_regeneration(
                deck_name=self.deck_name,
                positions=list(self.positions),
                regenerate_text=regenerate_text,
                regenerate_images=regenerate_images,
                venice_key=venice_key,
                settings=settings,
                on_complete=self.on_complete,
            )
            self.dismiss()
        elif event.button.id == "cancel":
            self.dismiss()

    @work(thread=True, exclusive=True, group="regeneration")
    def _run_regeneration(
        self,
        *,
        deck_name: str,
        positions: list[int],
        regenerate_text: bool,
        regenerate_images: bool,
        venice_key: str,
        settings: dict[str, Any],
        on_complete: Callable[[], None] | None,
    ) -> None:
        """Execute Venice regeneration off the Textual event loop."""
        deck = load_deck(deck_name)
        if not deck:
            self.app.call_from_thread(self.app.notify, "Could not load deck.")
            return

        meta = load_decks_index().get(deck_name, {})
        text_model = settings.get("text_model") or meta.get("text_model") or Config.DEFAULT_TEXT_MODEL
        image_model = settings.get("image_model") or meta.get("image_model") or Config.DEFAULT_IMAGE_MODEL
        edit_model = settings.get("edit_model") or Config.DEFAULT_MULTI_EDIT_MODEL
        image_size = settings.get("image_size") or meta.get("image_size") or Config.DEFAULT_IMAGE_SIZE
        symbol_mode = meta.get("symbol_mode") or settings.get("symbol_mode", "generate")
        symbols_file = meta.get("symbols_file") or settings.get("symbols_file", "")
        font_path = settings.get("font_path") or ""

        symbol_images: dict[str, str] = {}
        if symbol_mode == "provide":
            symbols_config = load_symbols_config(symbols_file or None)
            for s in symbols_config.get("symbols", []):
                if s.get("image") and os.path.exists(str(s["image"])):
                    symbol_images[s["name"]] = str(s["image"])

        success_count = 0
        for pos in positions:
            card = next((c for c in deck if c.position == pos), None)
            if not card:
                continue
            try:
                if regenerate_text:
                    analysis = analyze_with_venice(card, venice_key, text_model)
                    if "venice_error" not in analysis:
                        card.update(analysis)
                        if not regenerate_images:
                            recompose_card(card, font_path=font_path)
                        success_count += 1
                if regenerate_images:
                    img_result = generate_image_with_venice(
                        card,
                        venice_key,
                        image_model,
                        image_size=image_size,
                        symbol_mode=symbol_mode,
                        symbol_images=symbol_images,
                        output_dir=deck_images_dir(deck_name),
                        edit_model=edit_model,
                    )
                    img_path = img_result.get("image_path")
                    if img_path:
                        card.update(img_result)
                        compose_card(
                            image_path=str(img_path),
                            title=card.display_title(),
                            card_number=get_card_number_text(card),
                            card_type=card.card_type or "",
                            font_path=font_path,
                        )
                        success_count += 1
            except Exception as e:
                self.app.call_from_thread(
                    self.app.notify, f"Error on card {pos}: {str(e)[:80]}",
                )

        save_deck(deck, deck_name)
        self.app.call_from_thread(
            self.app.notify,
            f"✅ Regeneration complete! Updated {success_count} operation(s).",
        )
        if on_complete is not None:
            self.app.call_from_thread(on_complete)


class NewDeckDialog(ModalScreen):
    def compose(self) -> ComposeResult:
        settings = load_settings()
        with VerticalScroll():
            yield Label("Create a New Deck")
            yield Label("Deck Name")
            yield Input(value="New_Deck", id="deck_name")
            yield Label("Number of Cards")
            yield Input(value="78", id="num_cards")
            yield Label("Deck Theme / Prompt")
            yield Input(value="cyber-psychedelic journey", id="deck_prompt")
            yield Label(f"Symbol Mode (current: {settings.get('symbol_mode', 'generate')})")
            yield Input(value=settings.get("symbol_mode", "generate"), id="symbol_mode")
            yield Label("Symbols File (optional path to symbols.json)")
            yield Input(value=settings.get("symbols_file", ""), id="symbols_file")
            yield Horizontal(
                Button("Generate", id="generate"),
                Button("Cancel", id="cancel"),
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss()
            return
        if event.button.id == "generate":
            settings = load_settings()
            name = self.query_one("#deck_name", Input).value.strip() or "New_Deck"
            try:
                num_cards = int(self.query_one("#num_cards", Input).value.strip() or "78")
            except ValueError:
                num_cards = 78
            prompt = self.query_one("#deck_prompt", Input).value.strip()
            mode = self.query_one("#symbol_mode", Input).value.strip().lower()
            if mode not in ("generate", "provide"):
                mode = "generate"
            symbols_file = self.query_one("#symbols_file", Input).value.strip()

            cmd = [
                sys.executable, "-m", "ntcdg.cli",
                "--deck", "--name", name, "--cards", str(num_cards),
                "--deck-prompt", prompt, "--symbol-mode", mode,
                "--venice-text-model", str(settings.get("text_model") or Config.DEFAULT_TEXT_MODEL),
                "--venice-image-model", str(settings.get("image_model") or Config.DEFAULT_IMAGE_MODEL),
                "--image-size", str(settings.get("image_size") or Config.DEFAULT_IMAGE_SIZE),
                "--analyze", "--generate-images", "--no-interactive", "--no-preview",
            ]
            if symbols_file:
                cmd.extend(["--symbols-file", symbols_file])
            font_path = str(settings.get("font_path") or "").strip()
            if font_path:
                cmd.extend(["--font", font_path])

            env = os.environ.copy()
            api_key = str(settings.get("venice_api_key") or "").strip()
            if api_key:
                env["VENICE_API_KEY"] = api_key

            self.app.notify(f"⏳ Generating '{name}' in background...")
            self._run_generation(cmd, name, env)
            self.dismiss()

    @work(thread=True, exclusive=True, group="generation")
    def _run_generation(self, cmd: list[str], deck_name: str, env: dict[str, str]) -> None:
        """Run deck generation in a background thread with completion feedback."""
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=3600, env=env,
            )
            if result.returncode == 0:
                self.app.call_from_thread(
                    self.app.notify, f"✅ Deck '{deck_name}' generated successfully!",
                )
            else:
                error_msg = (result.stderr or result.stdout or "Unknown error")[-200:]
                self.app.call_from_thread(
                    self.app.notify, f"❌ Generation failed: {error_msg}",
                )
        except subprocess.TimeoutExpired:
            self.app.call_from_thread(
                self.app.notify, f"⏰ Generation of '{deck_name}' timed out (1 hour).",
            )
        except Exception as e:
            self.app.call_from_thread(
                self.app.notify, f"❌ Generation error: {str(e)[:200]}",
            )


class SettingsScreen(Screen):
    TITLE = "NTCDG Settings"

    def compose(self) -> ComposeResult:
        settings = load_settings()
        yield Header()
        with VerticalScroll():
            yield Label("Venice API Key (optional — defaults from ~/.ntcdgrc or VENICE_API_KEY)")
            yield Input(value=settings.get("venice_api_key", ""), id="api_key", password=True)
            yield Label("Default Text Model")
            yield Input(value=settings.get("text_model", Config.DEFAULT_TEXT_MODEL), id="text_model")
            yield Label("Default Image Model")
            yield Input(value=settings.get("image_model", Config.DEFAULT_IMAGE_MODEL), id="image_model")
            yield Label("Default Edit Model")
            yield Input(value=settings.get("edit_model", Config.DEFAULT_EDIT_MODEL), id="edit_model")
            yield Label("Default Image Size")
            yield Input(value=settings.get("image_size", Config.DEFAULT_IMAGE_SIZE), id="image_size")
            yield Label("Symbol Mode (generate or provide)")
            yield Input(value=settings.get("symbol_mode", "generate"), id="symbol_mode")
            yield Label("Symbols File (path to symbols.json, optional)")
            yield Input(value=settings.get("symbols_file", ""), id="symbols_file")
            yield Label("Custom Font Path (.ttf/.otf, optional)")
            yield Input(value=settings.get("font_path", ""), id="font_path")
            yield Horizontal(
                Button("Save Settings", id="save"),
                Button("Back", id="back"),
            )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            mode = self.query_one("#symbol_mode", Input).value.strip().lower()
            if mode not in ("generate", "provide"):
                mode = "generate"
            new_settings = {
                "venice_api_key": self.query_one("#api_key", Input).value,
                "text_model": self.query_one("#text_model", Input).value.strip(),
                "image_model": self.query_one("#image_model", Input).value.strip(),
                "edit_model": self.query_one("#edit_model", Input).value.strip(),
                "image_size": self.query_one("#image_size", Input).value.strip(),
                "symbol_mode": mode,
                "symbols_file": self.query_one("#symbols_file", Input).value.strip(),
                "font_path": self.query_one("#font_path", Input).value.strip(),
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

    def on_mount(self) -> None:
        self.push_screen(DeckListScreen())


def main() -> None:
    setup_logging()
    NTCDGApp().run()


if __name__ == "__main__":
    main()
