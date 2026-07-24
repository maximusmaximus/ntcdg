#!/usr/bin/env python3
"""
NTCDG - Novel Tarot Card Deck Generator

Core features:
- Full deck generation with Venice.ai (text + images)
- Automatic PDF proof sheet after generation
- Interactive review + selective regeneration (text/images/both)
- Review and edit existing decks (--review-existing)
- Deck management (--list-decks, --deck-info)

================================================================================
DEPENDENCIES
================================================================================

Core (required for basic generation):
    - Python 3.10+

Optional but recommended (script degrades gracefully if missing):

1. requests          → Venice.ai API calls (text analysis + image generation)
2. pandas + openpyxl → Master spreadsheet export (.xlsx)
3. reportlab         → PDF proof sheet generation
4. tqdm              → Beautiful progress bars during generation

TUI (separate file tui.py):
    - textual          → Modern Text User Interface

Install all dependencies:
    pip install requests pandas openpyxl reportlab tqdm textual

Environment variable:
    export VENICE_API_KEY="your_venice_api_key"
================================================================================
"""

import json
import random
import os
import base64
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
import argparse
import time
from pathlib import Path
from functools import wraps


def retry_on_failure(max_retries: int = 2, delay: float = 1.5):
    """Simple retry decorator for Venice API calls."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(f"{func.__name__} failed (attempt {attempt+1}/{max_retries+1}). Retrying in {delay}s...")
                        time.sleep(delay)
            logger.error(f"{func.__name__} failed after {max_retries+1} attempts: {last_exception}")
            raise last_exception
        return wrapper
    return decorator


# --- Optional Dependencies (graceful fallback) ---
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

try:
    import requests
except ImportError:
    requests = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


# ==================== CONFIG ====================
class Config:
    HISTORY_FILE = "ntcdg_history.json"
    OUTPUT_DIR = "generated_decks"
    IMAGES_DIR = os.path.join(OUTPUT_DIR, "images")
    LOGS_DIR = os.path.join(OUTPUT_DIR, "logs")
    DECKS_INDEX_FILE = os.path.join(OUTPUT_DIR, "decks_index.json")

    DEFAULT_TEXT_MODEL = "llama-3.1-405b"
    DEFAULT_IMAGE_MODEL = "venice-sd3"

    VENICE_TEXT_URL = "https://api.venice.ai/api/v1/chat/completions"
    VENICE_IMAGE_URL = "https://api.venice.ai/api/v1/image/generations"
    VENICE_EDIT_URL = "https://api.venice.ai/api/v1/image/edit"

    NOVELTY_THRESHOLD = 0.55

    CUSTOM_ELEMENTS_DIR = "custom_elements"

    DEFAULT_NEGATIVE_PROMPT = (
        "text, letters, watermark, signature, blurry, low quality, deformed, "
        "extra limbs, mutated hands, poorly drawn face, bad anatomy, artifacts"
    )

    RECURRING_SYMBOLS = [
        "loyal small dog gazing upward", "psychedelic flowers blooming",
        "crescent moon", "scattered stars", "ornate ancient keys",
        "angel wings", "winding path dissolving into light",
        "glowing crown", "subtle flames or energy wisps",
        "flowing water or liquid light", "distant mountains",
        "fractal patterns", "glitch digital particles"
    ]

    SUITS = ["Wands", "Cups", "Swords", "Pentacles"]
    RANKS_PIP = list(range(1, 11))
    COURT_RANKS = ["Page", "Knight", "Queen", "King"]


def load_custom_elements(custom_dir: str = None) -> Dict[str, str]:
    """
    Load custom hand-drawn element images with smart + configurable matching.

    Supports an optional elements_config.json for explicit control:

    {
      "loyal small dog gazing upward": "dog.png",
      "psychedelic flowers blooming": "flowers.png",
      "crescent moon": "moon.png"
    }

    Returns a dict mapping symbol names -> absolute path to PNG.
    """
    if custom_dir is None:
        custom_dir = Config.CUSTOM_ELEMENTS_DIR

    elements = {}
    path = Path(custom_dir)

    if not path.exists():
        return elements

    # Optional explicit mapping config
    config_path = path / "elements_config.json"
    symbol_map = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                symbol_map = json.load(f)
        except Exception as e:
            print(f"[NTCDG] Warning: could not parse elements_config.json: {e}")

    matched_files = set()

    # 1. Prefer explicit mappings from config
    for symbol_key, filename_pattern in symbol_map.items():
        for file in path.glob("*.png"):
            stem = file.stem.lower()
            pattern = str(filename_pattern).lower().replace(".png", "")
            if pattern in stem or stem in pattern:
                if file.stat().st_size == 0:
                    print(f"[NTCDG] Skipping empty custom element: {file.name}")
                    continue
                elements[symbol_key] = str(file.resolve())
                matched_files.add(file.name)
                break

    # 2. Fuzzy match remaining files against RECURRING_SYMBOLS
    for file in path.glob("*.png"):
        if file.name in matched_files:
            continue
        if file.stat().st_size == 0:
            print(f"[NTCDG] Skipping empty custom element: {file.name}")
            continue

        stem = file.stem.lower().replace("_", " ").replace("-", " ")
        for symbol in Config.RECURRING_SYMBOLS:
            # Require at least two significant words to match to reduce false positives
            words = [w for w in symbol.lower().split() if len(w) > 2]
            if sum(1 for w in words if w in stem) >= 2:
                if symbol not in elements:  # don't overwrite explicit mappings
                    elements[symbol] = str(file.resolve())
                break

    if elements:
        print(f"[NTCDG] Loaded {len(elements)} custom elements: {list(elements.keys())}")
    else:
        print(f"[NTCDG] No custom elements found in {path}")

    return elements


# ==================== LOGGING ====================
def setup_logging():
    os.makedirs(Config.LOGS_DIR, exist_ok=True)
    log_file = os.path.join(Config.LOGS_DIR, f"ntcdg_{datetime.now().strftime('%Y%m%d')}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()]
    )
    return logging.getLogger("NTCDG")


logger = setup_logging()


# ==================== DECK INDEX ====================
def load_decks_index() -> Dict[str, Any]:
    if os.path.exists(Config.DECKS_INDEX_FILE):
        with open(Config.DECKS_INDEX_FILE, "r") as f:
            return json.load(f)
    return {}


def save_decks_index(index: Dict[str, Any]):
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
        "created": index.get(deck_name, {}).get("created", datetime.now().isoformat())
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
    print(f"First card: {deck[0].get('title', 'N/A') if deck else 'N/A'}")
    print(f"Last card:  {deck[-1].get('title', 'N/A') if deck else 'N/A'}")

    has_images = sum(1 for c in deck if c.get("image_path"))
    print(f"Images generated: {has_images}/{len(deck)}")


# ==================== DECK LOADING / SAVING ====================
def load_deck(deck_name: str) -> List[Dict[str, Any]]:
    json_path = os.path.join(Config.OUTPUT_DIR, f"{deck_name}.json")
    if os.path.exists(json_path):
        with open(json_path, "r") as f:
            return json.load(f)
    return []


def save_deck(deck: List[Dict[str, Any]], deck_name: str):
    json_path = os.path.join(Config.OUTPUT_DIR, f"{deck_name}.json")
    with open(json_path, "w") as f:
        json.dump(deck, f, indent=2)
    export_spreadsheet(deck, deck_name)
    update_deck_index(deck_name, len(deck))


# ==================== HISTORY ====================
def load_history() -> Dict[str, Any]:
    if os.path.exists(Config.HISTORY_FILE):
        with open(Config.HISTORY_FILE, "r") as f:
            return json.load(f)
    return {"cards": [], "decks": []}


def is_novel(card: Dict[str, Any], history: Dict[str, Any]) -> bool:
    new_symbols = set(card.get("symbols", []))
    for past in history.get("cards", []):
        overlap = len(new_symbols & set(past.get("symbols", []))) / max(len(new_symbols), 1)
        if overlap > Config.NOVELTY_THRESHOLD:
            return False
    return True


# ==================== CARD GENERATION ====================
def generate_card(position: int, total: int, history: Dict[str, Any], deck_vibe: str, deck_prompt: str = "") -> Dict[str, Any]:
    is_first = position == 1
    is_last = position == total

    if random.random() < 0.28:
        card_type = "Major Arcana"
        titles = ["The Neon Origin", "The Fractal Weaver", "The Glitch Star",
                  "The Luminous Nexus", "The Vortex Fool", "The Eternal Return"]
        title = random.choice(titles)
        suit = rank = None
    else:
        card_type = "Minor Arcana"
        suit = random.choice(Config.SUITS)
        if random.random() < 0.75:
            rank = random.choice(Config.RANKS_PIP)
            title = f"{rank} of {suit}"
        else:
            rank = random.choice(Config.COURT_RANKS)
            title = f"{rank} of {suit}"

    symbols = []
    if suit and isinstance(rank, int):
        symbols.append(f"{rank} glowing {suit.lower()}")
    elif suit:
        symbols.append(f"prominent {suit.lower()}")

    symbols.extend(random.sample(Config.RECURRING_SYMBOLS, k=4))

    if is_first:
        layout = "expansive opening spiral vortex, light emerging outward"
    elif is_last:
        layout = "dense harmonious grand vortex, symbols fully integrated"
    else:
        layout = random.choice(["dynamic central vortex spiral", "ascending symbolic path", "chaotic energetic glitch burst"])

    card = {
        "position": position,
        "title": title,
        "type": card_type,
        "suit": suit,
        "rank": rank,
        "symbols": symbols,
        "layout": layout,
        "deck_vibe": deck_vibe,
        "deck_prompt": deck_prompt,
        "is_first": is_first,
        "is_last": is_last,
        "generated_at": datetime.now().isoformat()
    }

    card["prompt"] = build_card_prompt(card, is_first, is_last)
    return card


def build_card_prompt(card: Dict[str, Any], is_first: bool, is_last: bool) -> str:
    base = (
        f"Highly detailed symbolic tarot card in portrait orientation. "
        f"Title at bottom: '{card['title']}'. "
        f"Scene: {card['type']} featuring {', '.join(card['symbols'])}. "
        f"Composition and layout: {card['layout']}. "
    )

    if is_first:
        base += "This is the FIRST card of the deck — representing origins and new beginnings. "
    if is_last:
        base += "This is the FINAL card of the deck — representing culmination and full synthesis. "

    if card.get("deck_prompt"):
        base += f"Overall deck theme: {card['deck_prompt']}. "

    base += (
        "Psychedelic neon glitch vortex meme aesthetics fused with intricate Rider-Waite symbolic linework. "
        "High symbolic density, electric colors, dramatic cinematic lighting, glowing energy flows."
    )
    return base


# ==================== VENICE INTEGRATION ====================
@retry_on_failure(max_retries=2, delay=1.5)
def analyze_with_venice(card: Dict[str, Any], api_key: str, model: str) -> Dict[str, Any]:
    if not api_key or not requests:
        return {"venice_error": "Missing API key or requests library"}

    system = "You are an expert tarot symbologist. Focus on how visual elements combine and interact. Return only valid JSON."
    user = f"""Analyze this tarot card:

Title: {card['title']}
Type: {card['type']}
Symbols: {', '.join(card['symbols'])}
Layout: {card['layout']}
Deck Theme: {card.get('deck_prompt', 'None')}

Return ONLY this JSON:
{{
  "new_title": "evocative title",
  "description": "rich description of imagery and element interactions",
  "serial": "unique serial like VNX-042-007",
  "upright_interpretation": "positive/upright meaning",
  "reversed_interpretation": "reversed meaning"
}}"""

    try:
        resp = requests.post(
            Config.VENICE_TEXT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                "temperature": 0.7,
                "max_tokens": 850
            },
            timeout=90
        )
        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("```")[1].strip()
        analysis = json.loads(content)
        analysis["venice_text_model"] = model
        return analysis
    except Exception as e:
        logger.error(f"Venice text analysis failed for card {card.get('position')}: {e}")
        return {"venice_error": str(e)}


@retry_on_failure(max_retries=2, delay=2.0)
def generate_image_with_venice(
    card: Dict[str, Any],
    api_key: str,
    model: str,
    image_size: str = "1024x1536",
    negative_prompt: str = "",
    rate_limit_delay: float = 1.5,
    element_mode: str = "text",
    custom_elements: Dict[str, str] = None
) -> Dict[str, Any]:
    if not api_key or not requests:
        return {"image_error": "Missing API key or requests"}

    time.sleep(rate_limit_delay)

    full_prompt = card["prompt"]
    neg_prompt = negative_prompt or Config.DEFAULT_NEGATIVE_PROMPT

    try:
        # === TEXT MODE (default) ===
        if element_mode == "text" or not custom_elements:
            resp = requests.post(
                Config.VENICE_IMAGE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "prompt": full_prompt,
                    "negative_prompt": neg_prompt,
                    "n": 1,
                    "size": image_size,
                    "response_format": "b64_json"
                },
                timeout=180
            )
            resp.raise_for_status()
            data = resp.json()

            if "data" in data and data["data"]:
                b64 = data["data"][0].get("b64_json")
                if b64:
                    img_data = base64.b64decode(b64)
                    safe_title = str(card['title']).replace(' ', '_')[:40]
                    filename = f"{card['position']:03d}_{safe_title}.png"
                    filepath = os.path.join(Config.IMAGES_DIR, filename)
                    with open(filepath, "wb") as f:
                        f.write(img_data)
                    return {
                        "image_path": filepath,
                        "image_model": model,
                        "image_size": image_size,
                        "element_mode": "text"
                    }

        # === CUSTOM ELEMENTS MODE (using /image/edit) ===
        else:
            # First generate a strong base image
            base_resp = requests.post(
                Config.VENICE_IMAGE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "prompt": full_prompt,
                    "negative_prompt": neg_prompt,
                    "n": 1,
                    "size": image_size,
                    "response_format": "b64_json"
                },
                timeout=180
            )
            base_resp.raise_for_status()
            base_data = base_resp.json()

            if "data" not in base_data or not base_data["data"]:
                return {"image_error": "Failed to generate base image"}

            b64 = base_data["data"][0].get("b64_json")
            if not b64:
                return {"image_error": "No base image data"}

            # Save temporary base image
            temp_path = os.path.join(Config.IMAGES_DIR, f"temp_{card['position']}.png")
            with open(temp_path, "wb") as f:
                f.write(base64.b64decode(b64))

            # Build edit prompt based on available custom elements
            edit_prompt_parts = ["Keep the overall psychedelic neon glitch vortex tarot style and composition."]
            for symbol_name, element_path in custom_elements.items():
                if any(keyword in card.get("prompt", "").lower() for keyword in symbol_name.split()):
                    edit_prompt_parts.append(
                        f"Redraw the {symbol_name} using the provided hand-drawn element style. "
                        "Make it look like a traditional hand-drawn tarot illustration element."
                    )

            if len(edit_prompt_parts) > 1:
                edit_prompt = " ".join(edit_prompt_parts)
                edit_result = edit_image_with_venice(
                    temp_path, edit_prompt, api_key, model="firered-image-edit", image_size=image_size
                )
                if edit_result.get("image_path"):
                    # Clean up temp
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                    return {
                        "image_path": edit_result["image_path"],
                        "image_model": model,
                        "image_size": image_size,
                        "element_mode": "custom",
                        "used_custom_elements": list(custom_elements.keys())
                    }

            # Fallback to base if no edits applied
            final_path = temp_path.replace("temp_", "")
            os.rename(temp_path, final_path)
            return {
                "image_path": final_path,
                "image_model": model,
                "image_size": image_size,
                "element_mode": "custom_fallback"
            }

        return {"image_error": "Unexpected response from Venice"}

    except Exception as e:
        logger.error(f"Image generation failed for card {card.get('position')}: {e}")
        return {"image_error": str(e)}


@retry_on_failure(max_retries=2, delay=2.0)
def edit_image_with_venice(
    base_image_path: str,
    edit_prompt: str,
    api_key: str,
    model: str = "firered-image-edit",
    image_size: str = "1024x1536",
    rate_limit_delay: float = 2.0
) -> Dict[str, Any]:
    """
    Use Venice's /image/edit endpoint to modify an existing image
    based on text instructions (great for injecting custom hand-drawn elements).
    """
    if not api_key or not requests:
        return {"image_error": "Missing API key or requests"}

    time.sleep(rate_limit_delay)

    try:
        # Read the base image as base64
        with open(base_image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "model": model,
            "prompt": edit_prompt,
            "image": f"data:image/png;base64,{image_b64}",
            "size": image_size,
            "response_format": "b64_json"
        }

        resp = requests.post(
            Config.VENICE_EDIT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=180
        )
        resp.raise_for_status()
        data = resp.json()

        if "data" in data and data["data"]:
            b64 = data["data"][0].get("b64_json")
            if b64:
                img_data = base64.b64decode(b64)
                # Overwrite or create new version
                final_path = base_image_path.replace(".png", "_edited.png")
                with open(final_path, "wb") as f:
                    f.write(img_data)
                return {
                    "image_path": final_path,
                    "image_model": model,
                    "edited": True
                }
        return {"image_error": "Unexpected response from Venice Edit"}

    except Exception as e:
        logger.error(f"Image edit failed: {e}")
        return {"image_error": str(e)}


# ==================== PROOF SHEET (PDF) ====================
def create_proof_sheet_pdf(deck: List[Dict[str, Any]], deck_name: str) -> str:
    if not HAS_REPORTLAB:
        logger.warning("reportlab not installed. Cannot generate PDF proof sheet.")
        return ""

    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
    pdf_path = os.path.join(Config.OUTPUT_DIR, f"{deck_name}_PROOF_SHEET.pdf")

    doc = SimpleDocTemplate(pdf_path, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=16, alignment=TA_CENTER, spaceAfter=20)
    card_style = ParagraphStyle('CardTitle', parent=styles['Normal'], fontSize=9, alignment=TA_CENTER, leading=11)

    story = []
    story.append(Paragraph(f"Proof Sheet - {deck_name}", title_style))
    story.append(Spacer(1, 0.3*inch))

    table_data = []
    row = []

    for card in sorted(deck, key=lambda x: x.get("position", 0)):
        pos = card.get("position", "?")
        title = card.get("venice_title") or card.get("title", "Untitled")
        img_path = card.get("image_path")

        cell_content = [Paragraph(f"<b>{pos:02d}</b> - {title}", card_style)]

        if img_path and os.path.exists(img_path):
            try:
                img = Image(img_path, width=1.6*inch, height=2.4*inch)
                cell_content.append(img)
            except:
                cell_content.append(Paragraph("[Image Error]", card_style))
        else:
            cell_content.append(Paragraph("[No Image]", card_style))

        row.append(cell_content)

        if len(row) == 4:
            table_data.append(row)
            row = []

    if row:
        while len(row) < 4:
            row.append([""])
        table_data.append(row)

    if table_data:
        table = Table(table_data, colWidths=[2.2*inch]*4)
        table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(table)

    doc.build(story)
    logger.info(f"PDF Proof Sheet saved: {pdf_path}")
    return pdf_path


# ==================== INTERACTIVE REVIEW ====================
def interactive_review(deck: List[Dict[str, Any]], deck_name: str, venice_key: Optional[str],
                       text_model: str, image_model: str, image_size: str,
                       negative_prompt: str, rate_limit: float):

    pdf_path = create_proof_sheet_pdf(deck, deck_name)
    if pdf_path:
        print(f"\n📄 Proof sheet generated: {pdf_path}")

    print("\n--- Interactive Review ---")
    print("Enter card numbers to review (e.g. 3,7,12,42) or press Enter to finish:")

    user_input = input("> ").strip()
    if not user_input:
        print("Review complete. No changes made.")
        return deck

    try:
        positions = [int(x.strip()) for x in user_input.split(",")]
    except ValueError:
        print("Invalid input. Please use numbers only.")
        return deck

    print("\nWhat would you like to regenerate?")
    print("  1) Text analysis only")
    print("  2) Images only")
    print("  3) Both text and images")
    choice = input("Choice (1/2/3): ").strip()

    regenerate_text = choice in ["1", "3"]
    regenerate_images = choice in ["2", "3"]

    updated = False
    for pos in positions:
        card = next((c for c in deck if c.get("position") == pos), None)
        if not card:
            print(f"Card {pos} not found. Skipping.")
            continue

        print(f"\nRegenerating card {pos}...")

        if regenerate_text and venice_key:
            result = analyze_with_venice(card, venice_key, text_model)
            card.update(result)
            print(f"  → Text analysis updated")

        if regenerate_images and venice_key:
            # Use text mode by default in interactive review for simplicity
            result = generate_image_with_venice(
                card, venice_key, image_model,
                image_size=image_size,
                negative_prompt=negative_prompt,
                rate_limit_delay=rate_limit,
                element_mode="text",
                custom_elements={}
            )
            card.update(result)
            if result.get("image_path"):
                print(f"  → New image generated")

        updated = True

    if updated:
        save_deck(deck, deck_name)
        create_proof_sheet_pdf(deck, deck_name)
        print("\n✅ Files updated and new proof sheet generated.")

    return deck


# ==================== REVIEW EXISTING DECK ====================
def review_existing_deck(deck_name: str, venice_key: Optional[str],
                         text_model: str, image_model: str, image_size: str,
                         negative_prompt: str, rate_limit: float):

    deck = load_deck(deck_name)
    if not deck:
        print(f"Deck '{deck_name}' not found.")
        return

    print(f"\nLoaded existing deck: {deck_name} ({len(deck)} cards)")
    interactive_review(deck, deck_name, venice_key, text_model, image_model,
                       image_size, negative_prompt, rate_limit)


# ==================== SPREADSHEET ====================
def export_spreadsheet(deck: List[Dict[str, Any]], deck_name: str) -> str:
    if pd is None:
        logger.warning("pandas not installed — skipping spreadsheet")
        return ""
    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
    path = os.path.join(Config.OUTPUT_DIR, f"{deck_name}_MASTER.xlsx")

    rows = []
    for card in deck:
        rows.append({
            "Position": card.get("position"),
            "Title": card.get("venice_title") or card.get("title"),
            "Description": card.get("description", ""),
            "Upright": card.get("upright_interpretation", ""),
            "Reversed": card.get("reversed_interpretation", ""),
            "Type": card.get("type"),
            "Suit": card.get("suit"),
            "Symbols": " | ".join(card.get("symbols", [])),
            "Is_First": card.get("is_first"),
            "Is_Last": card.get("is_last"),
            "Image_Path": card.get("image_path", ""),
        })

    df = pd.DataFrame(rows)
    df.to_excel(path, index=False, sheet_name="Deck")
    logger.info(f"Spreadsheet saved: {path}")
    return path


# ==================== MAIN ====================
def generate_deck(name: str, num_cards: int, vibe: Optional[str], deck_prompt: str,
                  venice_key: Optional[str], analyze: bool, text_model: str,
                  generate_images: bool, image_model: str, image_size: str,
                  negative_prompt: str, rate_limit: float, interactive: bool = True,
                  element_mode: str = "text", custom_elements_dir: str = None):

    os.makedirs(Config.IMAGES_DIR, exist_ok=True)
    history = load_history()
    deck_vibe = vibe or random.choice(["cyber-vortex synthesis", "neon fractal journey"])

    logger.info(f"Starting deck: {name} ({num_cards} cards)")

    deck = []
    stats = {"venice_success": 0, "venice_fail": 0, "image_success": 0, "image_fail": 0}

    iterator = range(1, num_cards + 1)
    if HAS_TQDM:
        iterator = tqdm(iterator, desc="Generating Deck", unit="card", ncols=110)

    for i in iterator:
        if HAS_TQDM:
            iterator.set_description(f"Card {i}/{num_cards} - Generating")

        card = generate_card(i, num_cards, history, deck_vibe, deck_prompt)

        if analyze and venice_key:
            if HAS_TQDM:
                iterator.set_description(f"Card {i}/{num_cards} - Venice Text")
            result = analyze_with_venice(card, venice_key, text_model)
            card.update(result)
            if "venice_error" not in result:
                stats["venice_success"] += 1
            else:
                stats["venice_fail"] += 1

        if generate_images and venice_key:
            if HAS_TQDM:
                iterator.set_description(f"Card {i}/{num_cards} - Generating Image")
            custom_elements = load_custom_elements(custom_elements_dir) if element_mode == "custom" else {}
            result = generate_image_with_venice(
                card, venice_key, image_model,
                image_size=image_size,
                negative_prompt=negative_prompt,
                rate_limit_delay=rate_limit,
                element_mode=element_mode,
                custom_elements=custom_elements
            )
            card.update(result)
            if result.get("image_path"):
                stats["image_success"] += 1
            else:
                stats["image_fail"] += 1

        deck.append(card)

    save_deck(deck, name)

    if interactive:
        deck = interactive_review(deck, name, venice_key, text_model, image_model,
                                  image_size, negative_prompt, rate_limit)

    print("\n" + "=" * 65)
    print(f"✅ DECK GENERATION COMPLETE: {name}")
    print(f"   Total Cards: {len(deck)}")
    if analyze:
        print(f"   Venice Analysis: {stats['venice_success']} success | {stats['venice_fail']} failed")
    if generate_images:
        print(f"   Images Generated: {stats['image_success']} success | {stats['image_fail']} failed")
    print(f"   Output folder: {Config.OUTPUT_DIR}/")
    print("=" * 65 + "\n")


# ==================== CLI ====================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NTCDG - Tarot Deck Generator")

    parser.add_argument("--deck", action="store_true", help="Generate a new deck")
    parser.add_argument("--review-existing", type=str, default=None, help="Review an existing deck")
    parser.add_argument("--list-decks", action="store_true", help="List all decks")
    parser.add_argument("--deck-info", type=str, default=None, help="Show info about a deck")

    parser.add_argument("--name", type=str, default="New_Deck")
    parser.add_argument("--cards", type=int, default=78)
    parser.add_argument("--vibe", type=str, default=None)
    parser.add_argument("--deck-prompt", type=str, default="")

    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--venice-text-model", type=str, default=Config.DEFAULT_TEXT_MODEL)
    parser.add_argument("--generate-images", action="store_true")
    parser.add_argument("--venice-image-model", type=str, default=Config.DEFAULT_IMAGE_MODEL)
    parser.add_argument("--image-size", type=str, default="1024x1536")
    parser.add_argument("--negative-prompt", type=str, default="")
    parser.add_argument("--rate-limit", type=float, default=1.5)

    parser.add_argument("--element-mode", type=str, default="text", choices=["text", "custom"],
                        help="Element generation mode: 'text' (default) or 'custom' (uses hand-drawn elements via Edit API)")
    parser.add_argument("--custom-elements-dir", type=str, default=None,
                        help="Path to folder containing custom hand-drawn element PNGs")

    parser.add_argument("--venice-key", type=str, default=None)
    parser.add_argument("--no-interactive", action="store_true")

    args = parser.parse_args()
    venice_key = args.venice_key or os.getenv("VENICE_API_KEY")

    if args.list_decks:
        list_decks()
    elif args.deck_info:
        get_deck_info(args.deck_info)
    elif args.review_existing:
        review_existing_deck(
            deck_name=args.review_existing,
            venice_key=venice_key,
            text_model=args.venice_text_model,
            image_model=args.venice_image_model,
            image_size=args.image_size,
            negative_prompt=args.negative_prompt,
            rate_limit=args.rate_limit
        )
    elif args.deck:
        generate_deck(
            name=args.name,
            num_cards=args.cards,
            vibe=args.vibe,
            deck_prompt=args.deck_prompt,
            venice_key=venice_key,
            analyze=args.analyze,
            text_model=args.venice_text_model,
            generate_images=args.generate_images,
            image_model=args.venice_image_model,
            image_size=args.image_size,
            negative_prompt=args.negative_prompt,
            rate_limit=args.rate_limit,
            interactive=not args.no_interactive,
            element_mode=args.element_mode,
            custom_elements_dir=args.custom_elements_dir
        )
    else:
        print("Use --deck, --review-existing, --list-decks, or --deck-info")
