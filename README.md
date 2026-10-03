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
- **Web app** — profiles, guided deck creation, a workbench for every MCP tool with live
  input/output, duplex printing, and a mobile card viewer behind every QR code ([Web App](#web-app))

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

## Web App

A multi-user website for the whole workflow: artists create a profile, add their own
Venice key, build a deck step by step, watch generation live, print duplex sheets — and
the people they give the cards to scan the back and read their card on their phone.

- **Guided pages** — landing page and philosophy, sign-up/login, dashboard, a new-deck
  wizard (plan → your own symbols → style preview → create), a deck page (cards, card back,
  retries, stats, clone, delete), per-card editing, and a print & share page (calibration,
  finalize, downloads, public links with QR previews).
- **Workbench** — every MCP tool with a form generated from its signature and docstring.
  Each run shows the exact **input** sent and the **output** returned; slow tools run as
  background jobs with a live event feed, log and image gallery (Server-Sent Events, with a
  polling fallback). A test fails if a new MCP tool is not wired into the web app.
- **Public card viewer** — `/c/<deck-slug>/<card-slug>` (or `https://<deck-slug>.<root>/c/<card-slug>`
  in subdomain mode) shows the card image and its sections (upright, reversed, description,
  symbols). Swipe, use ← → or the buttons to move through the deck (wrapping), or tap
  **Scan another card**. Works without JavaScript; only *published* (finalized) decks resolve.

### Install & run

```bash
pip install -e ".[web]"
export NTCDG_WEB_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export NTCDG_PUBLIC_BASE_URL="https://tarot.example.com"   # what printed QR codes point to
ntcdg-web --host 127.0.0.1 --port 8000 --proxy-headers
# or: uvicorn --factory ntcdg.web.app:create_app --host 127.0.0.1 --port 8000 --proxy-headers
```

Local development (throwaway secret, cookies over plain HTTP):

```bash
NTCDG_WEB_DEV=1 ntcdg-web          # then open http://127.0.0.1:8000
```

| Variable | Meaning |
|----------|---------|
| `NTCDG_WEB_SECRET` | **Required** (unless dev). Signs sessions and encrypts stored Venice keys — keep it stable and secret; changing it logs everyone out and users must re-enter their keys. |
| `NTCDG_WEB_DEV` | `1` = development mode: random secret if none, non-secure cookies, API docs at `/api/docs`. |
| `NTCDG_WEB_DB` | SQLite path (default `<OUTPUT_DIR>/web.sqlite3`). |
| `NTCDG_WEB_MAX_UPLOAD_MB` | Upload size limit per file (default 15). |
| `NTCDG_WEB_WORKERS` | Background job threads (default 4). |
| `NTCDG_WEB_ALLOW_LOCAL_URL` | Dev only: allow a localhost/LAN `NTCDG_PUBLIC_BASE_URL` for testing QR codes. |
| `NTCDG_PUBLIC_*` | Public base URL for QR codes (see above). The web app **always** uses this configured URL, never the request's Host header. |

### Security model

- Passwords are hashed with scrypt; sessions are signed, `HttpOnly`, `SameSite=Lax` and
  `Secure` outside dev mode. Every state-changing request needs a CSRF token; failed logins
  are rate limited per username + IP.
- Each user's Venice key is stored Fernet-encrypted and only its last 4 characters are ever
  shown. Users without a key **cannot** fall back to the server's `VENICE_API_KEY`.
- Decks are stored as `<username>__<deck>` and every route checks ownership; public slugs are
  derived from the short deck name, so usernames never appear in printed URLs.
- Path inputs accept only the user's own uploads (`upload:<id>`, images are verified) or their
  registered symbol sets; outputs are rewritten to authenticated download URLs, never server paths.
- One generation job per user at a time; jobs are owner-only and survive in history across
  restarts (unfinished jobs are marked *interrupted*).

### Deployment notes

- Serve it **behind HTTPS** (the camera scanner and secure cookies require it). Put a reverse
  proxy (Caddy, nginx, …) in front, pass the original `Host` header and `X-Forwarded-Proto`,
  and run with `--proxy-headers`.
- **Subdomain mode** (`NTCDG_PUBLIC_BASE_URL="https://{deck}.example.com"`) needs a wildcard DNS
  record (`*.example.com`) and a wildcard TLS certificate pointing at the same app; the app
  recognises the deck from the Host header.
- Data lives in `generated_decks/` under the server's **working directory** (decks, images,
  PDFs, `web_uploads/`, and the SQLite DB unless `NTCDG_WEB_DB` is set): start the server from a
  directory on a persistent volume and back it up. Run a single process (jobs run in-process threads).

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
│   ├── tui.py            # Textual TUI
│   └── web/              # Web app (FastAPI + Jinja2 + vanilla JS), `ntcdg-web`
│       ├── app.py        # App factory, security headers, entry point
│       ├── settings.py   # NTCDG_WEB_* configuration
│       ├── auth.py       # scrypt passwords, encrypted keys, CSRF, rate limit
│       ├── db.py         # SQLite: users, uploads, job history
│       ├── namespace.py  # Per-user deck names (username__deck)
│       ├── files.py      # Uploads, owned-file serving, output sanitising, QR SVG
│       ├── tools.py      # Workbench registry: every MCP tool + safe input mapping
│       ├── jobs.py       # Background jobs with live events/log
│       ├── pages.py      # HTML pages (accounts, dashboard, decks, workbench)
│       ├── api.py        # Tool API, SSE job stream, uploads, downloads
│       ├── public_views.py  # Public card viewer (path + subdomain modes)
│       ├── templates/    # Jinja2 templates
│       └── static/       # app.css, app.js, viewer.js, scanner.js, logo.svg
├── tests/                # pytest suite (duplex, public URLs, web app, workflow edge cases, ...)
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

Dev dependencies (`pip install -e ".[dev]"`): `pytest`, `ruff`, `mypy`, `httpx`

Web app (`pip install -e ".[web]"`): `fastapi`, `uvicorn`, `jinja2`, `python-multipart`,
`itsdangerous`, `cryptography`

## Running Tests

```bash
pip install -e ".[dev,web]"
pytest
```

The web tests are skipped automatically if the `web` extra is not installed.

## License

MIT

---

Built with ❤️ for creative tarot deck prototyping.
