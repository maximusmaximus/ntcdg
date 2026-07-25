---
name: ntcdg
description: |
  Novel Tarot Card Deck Generator (NTCDG) — generate custom AI-powered tarot
  card decks via the Venice.ai API. Use this skill when the user wants to create,
  manage, review, or export tarot card decks from a Telegram chat.
---

# NTCDG CLI Integration

You can control the NTCDG deck generator by running CLI commands.
The binary is `ntcdg` (or `python -m ntcdg.cli` if not installed).

## Prerequisites

- `VENICE_API_KEY` must be set in the environment
- Python 3.10+ with `ntcdg` package installed
- Working directory should have write access for `generated_decks/`

## Quick Reference

### Create a New Deck (Guided)
```bash
# Non-interactive mode (for agent use — avoids stdin prompts)
ntcdg --deck \
  --name "DeckName" \
  --cards 78 \
  --vibe "cosmic horror meets art nouveau" \
  --deck-prompt "A deck exploring transformation through darkness" \
  --analyze \
  --generate-images \
  --no-interactive \
  --no-preview \
  --venice-key "$VENICE_API_KEY"
```

**Important flags for agent use:**
- `--no-interactive` — prevents stdin prompts (critical for non-TTY)
- `--no-preview` — skips the 3-card approval step
- `--analyze` — enables Venice text analysis for card meanings
- `--generate-images` — enables image generation

### Check Deck Status
```bash
# List all decks
ntcdg --list-decks

# Detailed status (completion %, readiness, errors)
ntcdg --deck-info DeckName

# Per-card status table
ntcdg --list-cards DeckName

# API usage and cost breakdown
ntcdg --deck-stats DeckName
```

### Fix Failed Cards
```bash
# Re-run only incomplete/errored cards
ntcdg --retry-failed DeckName \
  --no-interactive \
  --venice-key "$VENICE_API_KEY"
```

### Generate Card Back
```bash
ntcdg --set-back DeckName \
  --back-prompt "Sacred geometry mandala with gold filigree on deep purple" \
  --venice-key "$VENICE_API_KEY"
```

### Edit a Card
```bash
ntcdg --edit-card DeckName \
  --card-num 5 \
  --field description \
  --value "A towering figure wreathed in shadow and starlight"
```

Valid fields: `title`, `new_title`, `description`, `upright_interpretation`, `reversed_interpretation`

### Finalize for Print
```bash
# Generate print-ready PDFs (fronts + backs + booklet)
ntcdg --finalize DeckName \
  --sheet-size letter \
  --color-mode color
```

Sheet sizes: `letter` (8.5×11) or `tabloid` (11×17)
Color modes: `color` or `bw` (both output CMYK)

### Export Bundle
```bash
# Zip all assets (images, PDFs, JSON)
ntcdg --export DeckName
```
Output: `generated_decks/DeckName_BUNDLE.zip`

### Deck Management
```bash
# Clone a deck
ntcdg --clone-deck OriginalName NewName

# Delete a deck (requires typing DELETE to confirm)
# For agent use, pipe confirmation:
echo "DELETE" | ntcdg --delete-deck DeckName
```

## Custom Symbols

Users can provide their own symbol artwork via a `symbols.json`:
```json
{
  "symbols": [
    {
      "name": "Serpent",
      "description": "Coiled serpent representing transformation",
      "image": "/path/to/serpent.png"
    }
  ]
}
```

Use with:
```bash
ntcdg --deck ... \
  --symbol-mode provide \
  --symbols-file /path/to/symbols.json
```

When `--symbol-mode provide` is used, the provided artwork defines the
entire deck's visual style. All generated card art will inherit the
aesthetic from the symbol images.

## File Locations

| File | Path |
|------|------|
| Card images | `generated_decks/images/*.png` |
| Preview images | `generated_decks/images/previews/*.png` |
| Deck JSON | `generated_decks/DeckName.json` |
| Print PDFs | `generated_decks/DeckName_PRINT_*.pdf` |
| Backs PDF | `generated_decks/DeckName_BACKS_*.pdf` |
| Booklet PDF | `generated_decks/DeckName_BOOKLET.pdf` |
| Spreadsheet | `generated_decks/DeckName_MASTER.xlsx` |
| Export bundle | `generated_decks/DeckName_BUNDLE.zip` |
| Back image | `generated_decks/images/DeckName_BACK.png` |

## Typical Agent Workflow

1. User says "make me a cyberpunk tarot deck"
2. Run `ntcdg --deck --name Cyberpunk --cards 22 --vibe "neon cyberpunk" --analyze --generate-images --no-interactive --no-preview`
3. Check progress: `ntcdg --deck-info Cyberpunk`
4. If errors: `ntcdg --retry-failed Cyberpunk --no-interactive`
5. Generate back: `ntcdg --set-back Cyberpunk --back-prompt "circuit board mandala"`
6. Finalize: `ntcdg --finalize Cyberpunk`
7. Export: `ntcdg --export Cyberpunk`
8. Send the bundle zip or individual images back to the user

## Sending Results to User

After generation, send the user:
- Individual card images from `generated_decks/images/`
- The deck stats via `ntcdg --deck-stats DeckName`
- The bundle zip from `ntcdg --export DeckName`

## Error Handling

- All commands exit 0 on success, non-zero on failure
- Check stderr for error messages
- `--deck-info` shows which cards have errors
- `--list-cards` shows per-card error details
- `--retry-failed` re-processes only broken cards
