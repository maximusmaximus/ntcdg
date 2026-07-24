"""Configuration, optional dependencies, and shared utilities for NTCDG."""

import contextlib
import logging
import os
import time
from datetime import datetime
from functools import wraps

# --- Optional Dependencies (graceful fallback) ---
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    tqdm = None

try:
    import requests as _requests
    requests = _requests
except ImportError:
    requests = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Image as RLImage,
    )
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
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

    # --- Model defaults (best-fit per task as of 2026) ---
    # Text: deepseek-v3.2 — strong structured JSON output + reasoning
    DEFAULT_TEXT_MODEL = "deepseek-v3.2"
    # Image gen: flux-2-pro — best prompt adherence + detail for card art
    DEFAULT_IMAGE_MODEL = "flux-2-pro"
    # Image edit: flux-2-max-edit — high-quality inpainting/style transfer
    DEFAULT_EDIT_MODEL = "flux-2-max-edit"

    VENICE_BASE_URL = "https://api.venice.ai/api/v1"
    VENICE_TEXT_URL = f"{VENICE_BASE_URL}/chat/completions"
    VENICE_IMAGE_URL = f"{VENICE_BASE_URL}/image/generations"
    VENICE_EDIT_URL = f"{VENICE_BASE_URL}/image/edit"
    VENICE_MODELS_URL = f"{VENICE_BASE_URL}/models"

    NOVELTY_THRESHOLD = 0.55
    SYMBOLS_DIR = "symbols"

    DEFAULT_NEGATIVE_PROMPT = (
        "text, letters, watermark, signature, blurry, low quality, deformed, "
        "extra limbs, mutated hands, poorly drawn face, bad anatomy, artifacts"
    )

    # Default symbol definitions — used when no symbols.json is provided
    DEFAULT_SYMBOLS = [
        {"name": "loyal small dog", "description": "A small loyal dog gazing upward with devotion"},
        {"name": "psychedelic flowers", "description": "Vivid psychedelic flowers with fractal petals"},
        {"name": "crescent moon", "description": "A luminous crescent moon radiating ethereal light"},
        {"name": "scattered stars", "description": "Scattered stars twinkling with cosmic energy"},
        {"name": "ornate ancient keys", "description": "Ornate ancient keys with intricate filigree"},
        {"name": "angel wings", "description": "Translucent angel wings with feathered luminescence"},
        {"name": "winding path", "description": "A winding path dissolving into radiant light"},
        {"name": "glowing crown", "description": "A glowing crown emanating golden energy"},
        {"name": "subtle flames", "description": "Subtle flames or wisps of spiritual energy"},
        {"name": "flowing water", "description": "Flowing water or streams of liquid light"},
        {"name": "distant mountains", "description": "Distant mountains silhouetted against a mystical sky"},
        {"name": "fractal patterns", "description": "Intricate fractal patterns pulsing with energy"},
        {"name": "glitch particles", "description": "Digital glitch particles dissolving into data streams"},
    ]

    SUITS = ["Wands", "Cups", "Swords", "Pentacles"]
    MINOR_RANKS = ["Ace", 2, 3, 4, 5, 6, 7, 8, 9, 10, "Page", "Knight", "Queen", "King"]

    # Full 22 Major Arcana in canonical order
    MAJOR_ARCANA = [
        (0, "The Fool"), (1, "The Magician"), (2, "The High Priestess"),
        (3, "The Empress"), (4, "The Emperor"), (5, "The Hierophant"),
        (6, "The Lovers"), (7, "The Chariot"), (8, "Strength"),
        (9, "The Hermit"), (10, "Wheel of Fortune"), (11, "Justice"),
        (12, "The Hanged Man"), (13, "Death"), (14, "Temperance"),
        (15, "The Devil"), (16, "The Tower"), (17, "The Star"),
        (18, "The Moon"), (19, "The Sun"), (20, "Judgement"),
        (21, "The World"),
    ]


# ==================== LOGGING ====================
def setup_logging():
    """Configure file + console logging. Call once from main()."""
    os.makedirs(Config.LOGS_DIR, exist_ok=True)
    log_file = os.path.join(Config.LOGS_DIR, f"ntcdg_{datetime.now().strftime('%Y%m%d')}.log")

    log = logging.getLogger("NTCDG")
    log.setLevel(logging.INFO)

    if not log.handlers:
        fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(fh)
        log.addHandler(sh)


# Module-level logger — always available, handlers added by setup_logging()
logger = logging.getLogger("NTCDG")


# ==================== RETRY DECORATOR ====================
def retry_on_failure(max_retries: int = 2, delay: float = 1.5, backoff: float = 2.0):
    """
    Retry decorator with exponential backoff and 429 rate-limit handling.

    Args:
        max_retries: Maximum number of retry attempts.
        delay: Initial delay in seconds between retries.
        backoff: Multiplier applied to delay after each retry.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    # Handle 429 rate-limit: respect Retry-After header
                    resp = getattr(e, "response", None)
                    if resp is not None and getattr(resp, "status_code", 0) == 429:
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after:
                            with contextlib.suppress(ValueError, TypeError):
                                current_delay = max(float(retry_after), current_delay)
                            logger.warning(
                                f"{func.__name__} rate-limited (429). "
                                f"Waiting {current_delay:.1f}s..."
                            )

                    if attempt < max_retries:
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt+1}/{max_retries+1}). "
                            f"Retrying in {current_delay:.1f}s..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
            logger.error(
                f"{func.__name__} failed after {max_retries+1} attempts: {last_exception}"
            )
            raise last_exception
        return wrapper
    return decorator
