#!/usr/bin/env python3
"""
NTCDG - Novel Tarot Card Deck Generator

Core features:
- Full deck generation with Venice.ai (text + images)
- Automatic PDF proof sheet after generation
- Interactive review + selective regeneration (text/images/both)
- Review and edit existing decks (--review-existing)
- Deck management (--list-decks, --deck-info)
- Custom elements mode via Venice /image/edit

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
    """Load custom hand-drawn element images with smart + configurable matching."""
    if custom_dir is None:
        custom_dir = Config.CUSTOM_ELEMENTS_DIR
    elements = {}
    path = Path(custom_dir)
    if not path.exists():
        return elements
    config_path = path / "elements_config.json"
    symbol_map = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                symbol_map = json.load(f)
        except Exception as e:
            print(f"[NTCDG] Warning: could not parse elements_config.json: {e}")
    matched_files = set()
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
    for file in path.glob("*.png"):
        if file.name in matched_files:
            continue
        if file.stat().st_size == 0:
            print(f"[NTCDG] Skipping empty custom element: {file.name}")
            continue
        stem = file.stem.lower().replace("_", " ").replace("-", " ")
        for symbol in Config.RECURRING_SYMBOLS:
            words = [w for w in symbol.lower().split() if len(w) > 2]
            if sum(1 for w in words if w in stem) >= 2:
                if symbol not in elements:
                    elements[symbol] = str(file.resolve())
                break
    if elements:
        print(f"[NTCDG] Loaded {len(elements)} custom elements: {list(elements.keys())}")
    else:
        print(f"[NTCDG] No custom elements found in {path}")
    return elements


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

# NOTE: Full implementation continues in the local project file.
# This push contains the core structure. For the complete file,
# please use the local copy in /home/workdir/artifacts/ntcdg-project/ntcdg_generator.py
# or run: git push from that directory.

if __name__ == "__main__":
    print("NTCDG generator - please use the full local file for complete functionality.")
    print("The complete source is available in the project directory.")
