# NTCDG - Novel Tarot Card Deck Generator

A clean, modular Python tool to generate unique psychedelic/glitch/vortex tarot-style decks with Venice.ai integration.

## Features

- Generate full 78-card decks with custom themes
- Venice.ai powered text analysis (title, description, upright/reversed meanings)
- Venice.ai image generation for card artwork
- Selectable models for text and images
- Automatic multi-page PDF proof sheet with card thumbnails
- Interactive review: select cards to regenerate (text/images/both)
- Review and edit existing decks
- Deck management (list, info)
- Modern TUI for browsing and editing decks
- Master spreadsheet export
- Progress bars, logging, and rate limiting

## Installation

```bash
git clone https://github.com/maximusmaximus/ntcdg.git
cd ntcdg
pip install -r requirements.txt
```

Set your Venice API key:

```bash
export VENICE_API_KEY="sk-..."
```

## Usage

### Generate a new deck

```bash
python ntcdg_generator.py --deck --name MyPsycheDeck --cards 78 \
  --analyze --generate-images \
  --deck-prompt "A cyber-psychedelic journey through digital mysticism"
```

### Review an existing deck

```bash
python ntcdg_generator.py --review-existing MyPsycheDeck
```

### List decks

```bash
python ntcdg_generator.py --list-decks
```

### Launch the TUI

```bash
python tui.py
```

**TUI features:**
- Browse and search existing decks
- Open a deck → Edit cards, Regenerate (text / images / both), Refresh, open Proof Sheet
- **New Deck** button to start generation from the TUI
- Settings panel (API key, models, Element Mode, Custom Elements directory)

## Project Structure

```
ntcdg/
├── ntcdg_generator.py   # Main CLI generator
├── tui.py               # Textual TUI for deck management
├── requirements.txt
└── README.md
```

## Using Custom Hand-Drawn Elements

NTCDG supports two generation modes:

### 1. Text Mode (Default)
Fully AI-generated cards using Venice.

### 2. Custom Elements Mode
Use your own hand-drawn images for recurring symbols (dog, flowers, moon, keys, etc.).

**How to use:**

1. Create a folder with your transparent PNG elements:
   ```
   my_elements/
   ├── loyal_small_dog.png
   ├── psychedelic_flowers.png
   ├── crescent_moon.png
   ├── ornate_ancient_keys.png
   └── elements_config.json   # optional but recommended
   ```

2. (Recommended) Create an `elements_config.json` for explicit control:
   ```json
   {
     "loyal small dog gazing upward": "loyal_small_dog.png",
     "psychedelic flowers blooming": "psychedelic_flowers.png",
     "crescent moon": "crescent_moon.png",
     "ornate ancient keys": "ornate_ancient_keys.png"
   }
   ```

3. Generate with:
   ```bash
   python ntcdg_generator.py --deck --name MyDeck \
     --element-mode custom \
     --custom-elements-dir ./my_elements \
     --analyze --generate-images
   ```

The system generates base cards then uses Venice's Edit API to redraw the matched symbols while preserving overall style.

You can also set **Element Mode = custom** and the directory path in the TUI under **Settings**.

## Dependencies

See the header in `ntcdg_generator.py` for full details. Main optional packages:

- `requests` - Venice.ai API
- `pandas` + `openpyxl` - Spreadsheet export
- `reportlab` - PDF proof sheets
- `tqdm` - Progress bars
- `textual` - TUI (for `tui.py`)

## License

MIT (or your preferred license)

---

Built with ❤️ for creative tarot deck prototyping.
