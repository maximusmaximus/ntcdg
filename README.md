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

## Duplex Printing & QR Codes

`ntcdg --finalize MyDeck` (or the MCP `finalize_deck` tool) writes, from **one
shared slot plan**, so every back is printed directly behind its own front:

| File | Use |
|------|-----|
| `MyDeck_DUPLEX_<sheet>_<color>_<flip>.pdf` | **Print this 2-sided** — pages alternate front, back, front, back |
| `MyDeck_PRINT_<sheet>_<color>.pdf` | Fronts only (for print shops) |
| `MyDeck_BACKS_<sheet>_<color>_<flip>.pdf` | Backs only, same registration |
| `MyDeck_BOOKLET.pdf` | Card-sized companion booklet |

- **Flip edge** — `--duplex-flip long_edge` (default; flip like a book page) mirrors
  backs left↔right; `short_edge` (flip like a calendar) mirrors top↔bottom and rotates
  the back art 180° so a cut card still reads upright when turned over.
- **Registration never shifts** — a partial last sheet puts each back in the mirrored
  cell, and a missing/corrupt image becomes a placeholder instead of moving later cards.
- **Calibration** — `ntcdg --calibration-sheet --sheet-size letter --duplex-flip long_edge`
  (MCP `duplex_calibration`) prints crosshairs on both sides. Hold it to a light, measure
  any shift and pass it as `--back-offset-x-mm` / `--back-offset-y-mm` (±10 mm).
- **Pairing check** — tiny `#12` slot labels sit in the waste area outside the trim on
  both sides. Nothing that identifies a card is printed inside the trim on the back, so
  backs stay indistinguishable for readings.
- **No back art?** A symmetric default back is generated.

### Per-card QR codes

Each back carries a QR code that opens that card's public page (image + meaning).
Configure the public site once:

```bash
export NTCDG_PUBLIC_BASE_URL="https://tarot.example.com"   # path mode
# -> https://tarot.example.com/c/<deck-slug>/<card-slug>

export NTCDG_PUBLIC_BASE_URL="https://{deck}.example.com"  # one subdomain per deck
# -> https://<deck-slug>.example.com/c/<card-slug>

# or compose it:
export NTCDG_PUBLIC_ROOT_DOMAIN=example.com NTCDG_PUBLIC_SUBDOMAIN=tarot  # NTCDG_PUBLIC_SCHEME=https
```

- Deck slugs look like `moon-garden-k7m2qx` (random suffix, DNS-safe); card slugs like
  `01-the-fool` (position + canonical title, so renaming a card never breaks a printed code).
- The base URL is **baked into the deck on first finalize**; reprints always produce the
  same codes. Changing it needs `--rebase-url` / `rebase_url=True` (old cards keep the old URL).
- Localhost, private IPs, credentials, queries and fragments are refused — printed codes live forever.
- No URL configured → the deck still prints (no QR) and the report explains why. `--no-qr` disables them.
- `ntcdg --public-links MyDeck` / MCP `get_public_links` lists every card's URL;
  MCP `get_card_by_slug` resolves a scanned code (published decks only) with prev/next slugs.

## Project Structure

```
ntcdg/
├── src/ntcdg/
│   ├── models.py         # Card dataclass
│   ├── config.py         # Config, dependencies, retry logic
│   ├── runtime.py        # Per-call Venice key scope + stdout capture
│   ├── storage.py        # Deck load/save, locked atomic index, spreadsheet
│   ├── symbols.py        # Traditional symbol registry, artist symbols, completion
│   ├── venice.py         # Venice API (text/image/edit)
│   ├── generator.py      # Deck generation, checkpoints, proof sheets, review
│   ├── finalize.py       # Validation, print geometry, booklet, finalize report
│   ├── duplex.py         # Duplex slot plan, registered backs, QR, calibration
│   ├── public.py         # Public slugs, base-URL config, card URLs
│   ├── mcp_server.py     # MCP tools
│   ├── cli.py            # CLI entry point
│   └── tui.py            # Textual TUI
├── tests/                # pytest suite (duplex, public URLs, workflow edge cases, ...)
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
