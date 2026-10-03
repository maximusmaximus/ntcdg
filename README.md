# NTCDG — Novel Tarot Card Deck Generator

A modular Python tool for generating unique psychedelic/glitch/vortex tarot-style decks with [Venice.ai](https://venice.ai) integration.

## Features

- **Full 78-card canonical decks** — 22 Major Arcana + 56 Minor Arcana, zero duplicates
- **Venice.ai text analysis** — titles, descriptions, upright/reversed meanings
- **Venice.ai image generation** — card artwork with cohesive visual style
- **User-defined symbols** — provide your own images or let AI generate them cohesively
- **Multi-page PDF proof sheets** — paginated card thumbnails for review
- **Interactive review** — select cards to regenerate (text / images / both)
- **Modern TUI** — browse, edit, and regenerate decks from a terminal UI
- **Master spreadsheet export** — `.xlsx` with all card data
- **Progress bars, logging, rate limiting** — production-ready generation pipeline

## Installation

```bash
git clone https://github.com/maximusmaximus/ntcdg.git
cd ntcdg
pip install -e .
```

Set your Venice API key:

```bash
export VENICE_API_KEY="sk-..."
```

## Quick Start

### Generate a deck (CLI)

```bash
ntcdg --deck --name MyPsycheDeck --cards 78 \
  --analyze --generate-images \
  --deck-prompt "A cyber-psychedelic journey through digital mysticism"
```

### Launch the TUI

```bash
ntcdg-tui
```

### Other commands

```bash
ntcdg --list-decks                    # List all generated decks
ntcdg --deck-info MyPsycheDeck        # Show deck details
ntcdg --review-existing MyPsycheDeck  # Interactive review + regeneration
```

## Symbol System

NTCDG supports two modes for the recurring symbols that appear across your deck:

### Generate Mode (default)

AI generates all symbol artwork **before** card generation begins, using a shared style prompt so every symbol has a cohesive visual identity.

```bash
ntcdg --deck --name MyDeck --cards 78 \
  --symbols-file symbols.json \
  --analyze --generate-images
```

### Provide Mode

Supply your own images for each symbol. The system generates base cards then uses Venice's Edit API to inject your art style.

```bash
ntcdg --deck --name MyDeck --cards 78 \
  --symbol-mode provide \
  --symbols-file my_symbols.json \
  --analyze --generate-images
```

### symbols.json format

```json
{
  "style_prompt": "psychedelic neon glitch vortex art, intricate linework",
  "symbols": [
    {"name": "loyal small dog", "description": "A small loyal dog gazing upward"},
    {"name": "crescent moon", "description": "A luminous crescent moon", "image": "assets/moon.png"}
  ]
}
```

- `style_prompt` — shared visual style for AI-generated symbols
- `symbols[].name` — symbol name (used in card prompts)
- `symbols[].description` — detailed description for image generation
- `symbols[].image` — (optional) path to your own image; required in `provide` mode

An example `symbols.json` is included in the repo.

All of a deck's symbol images and manifests live in `generated_decks/symbols/<deck>/`
(artist uploads via `register_symbols`, AI-completed traditional symbols, and
cohesive generated symbols). Registering symbols again **merges** with earlier
batches (same name = replaced); pass `replace=True` to start over.

## Reliability

- **Checkpointing & resume** — the deck is saved after every card. If a run is
  interrupted, `ntcdg --retry-failed MyDeck` (or the MCP `retry_failed` tool)
  resumes to the originally requested size and never duplicates cards.
- **Safe metadata** — saving a deck merges into the index instead of overwriting,
  so vibe, theme, back image and usage stats are preserved; writes are atomic and
  locked for concurrent callers.
- **Safe names** — deck names must match `^[A-Za-z0-9_-]{1,100}$` (no path tricks),
  and deleting/bundling a deck only touches files that belong to exactly that deck.
- **No silent overwrites** — MCP `create_deck` refuses to replace an existing deck
  unless `overwrite=True`.
- **Failures are reported** — failed symbol generations are listed separately
  (`failed_symbols`), and `finalize_deck` returns `success`, the exact output files
  and the validation errors/warnings.

## Project Structure

```
ntcdg/
├── src/ntcdg/
│   ├── __init__.py       # Package init (v0.2.0)
│   ├── models.py         # Card dataclass
│   ├── config.py         # Config, dependencies, retry logic
│   ├── storage.py        # Deck load/save, index, spreadsheet
│   ├── symbols.py        # Symbol config + cohesive generation
│   ├── venice.py         # Venice API (text/image/edit)
│   ├── generator.py      # Deck generation, proof sheets, review
│   ├── cli.py            # CLI entry point
│   └── tui.py            # Textual TUI
├── tests/
│   └── test_models.py    # Card model + canonical deck tests
├── symbols.json          # Example symbol definitions
└── pyproject.toml        # Package config + console scripts
```

## Dependencies

All dependencies are managed via `pyproject.toml`. Install with `pip install -e .`:

| Package | Purpose |
|---------|---------|
| `requests` | Venice.ai API calls |
| `pandas` + `openpyxl` | Spreadsheet export |
| `reportlab` | PDF proof sheets |
| `tqdm` | Progress bars |
| `textual` | TUI |

Dev dependencies (`pip install -e ".[dev]"`): `pytest`, `ruff`, `mypy`

## Running Tests

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT

---

Built with ❤️ for creative tarot deck prototyping.
