"""Symbol configuration loading and cohesive image generation."""

import json
import os
import time
import base64
from typing import Dict, Any, Optional

from .config import Config, logger, retry_on_failure, requests, HAS_TQDM

if HAS_TQDM:
    from tqdm import tqdm


# ==================== SYMBOL CONFIGURATION ====================
def load_symbols_config(symbols_file: str = None) -> Dict[str, Any]:
    """
    Load symbol definitions from a JSON file.

    Expected format:
    {
      "style_prompt": "shared visual style description (optional)",
      "symbols": [
        {"name": "...", "description": "...", "image": "path/to/img.png (optional)"},
        ...
      ]
    }

    Falls back to Config.DEFAULT_SYMBOLS if no file provided or found.
    Also supports legacy custom_elements/elements_config.json for backward compatibility.
    """
    # Try explicit symbols file
    if symbols_file and os.path.exists(symbols_file):
        try:
            with open(symbols_file) as f:
                config = json.load(f)
            if "symbols" in config and isinstance(config["symbols"], list):
                logger.info(f"Loaded {len(config['symbols'])} symbols from {symbols_file}")
                return config
            else:
                logger.warning(f"Invalid symbols file (missing 'symbols' list): {symbols_file}")
        except Exception as e:
            logger.warning(f"Could not parse symbols file {symbols_file}: {e}")

    # Try legacy elements_config.json
    legacy_path = os.path.join("custom_elements", "elements_config.json")
    if os.path.exists(legacy_path):
        try:
            with open(legacy_path) as f:
                legacy = json.load(f)
            symbols = []
            for name, filename in legacy.items():
                img_path = os.path.join("custom_elements", filename)
                symbols.append({
                    "name": name,
                    "description": name,
                    "image": img_path if os.path.exists(img_path) else None,
                })
            logger.info(f"Loaded {len(symbols)} symbols from legacy elements_config.json")
            return {"symbols": symbols, "style_prompt": ""}
        except Exception as e:
            logger.warning(f"Could not parse legacy config: {e}")

    # Default
    logger.info("Using default symbol definitions")
    return {"symbols": [s.copy() for s in Config.DEFAULT_SYMBOLS], "style_prompt": ""}


def generate_symbol_images(
    symbols_config: Dict[str, Any],
    deck_name: str,
    deck_prompt: str,
    api_key: str,
    image_model: str,
    rate_limit: float = 1.5,
) -> Dict[str, Any]:
    """
    Generate cohesive symbol reference images for every symbol that lacks an image.
    Uses a shared style prompt so all generated symbols match visually.
    Returns the updated symbols_config with image paths filled in.
    """
    if not api_key or not requests:
        logger.warning("Cannot generate symbol images: missing API key or requests library")
        return symbols_config

    symbols_dir = os.path.join(Config.OUTPUT_DIR, deck_name, "symbols")
    os.makedirs(symbols_dir, exist_ok=True)

    style = symbols_config.get("style_prompt", "")
    if not style:
        style = (
            "psychedelic neon glitch vortex style, intricate symbolic linework, "
            "electric vivid colors, dramatic cinematic lighting, high detail"
        )
    if deck_prompt:
        style = f"{deck_prompt}. {style}"

    symbols = symbols_config["symbols"]
    need_gen = [s for s in symbols if not (s.get("image") and os.path.exists(str(s["image"])))]

    if not need_gen:
        logger.info("All symbols already have images — skipping generation")
        return symbols_config

    logger.info(f"Generating {len(need_gen)} symbol images with cohesive style...")

    iterator = range(len(need_gen))
    if HAS_TQDM:
        iterator = tqdm(iterator, desc="Generating Symbols", unit="symbol", ncols=110)

    for i in iterator:
        symbol = need_gen[i]
        if HAS_TQDM:
            iterator.set_description(f"Symbol: {symbol['name'][:25]}")

        prompt = (
            f"A single isolated symbolic element: {symbol['description']}. "
            f"Visual style: {style}. "
            "Centered composition on a dark background, "
            "suitable as a recurring tarot card symbol. No text, no borders, no frames."
        )

        img_path = _generate_single_symbol(
            prompt=prompt,
            name=symbol["name"],
            output_dir=symbols_dir,
            api_key=api_key,
            model=image_model,
            rate_limit=rate_limit,
        )

        if img_path:
            symbol["image"] = img_path
            logger.info(f"  Generated symbol: {symbol['name']}")
        else:
            logger.warning(f"  Failed to generate symbol: {symbol['name']}")

    # Save manifest so symbols can be reused later
    manifest_path = os.path.join(symbols_dir, "symbols_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(symbols_config, f, indent=2)
    logger.info(f"Symbol manifest saved: {manifest_path}")

    return symbols_config


@retry_on_failure(max_retries=2, delay=2.0)
def _generate_single_symbol(
    prompt: str,
    name: str,
    output_dir: str,
    api_key: str,
    model: str,
    rate_limit: float,
) -> Optional[str]:
    """Generate a single symbol image via Venice."""
    if not api_key or not requests:
        return None

    time.sleep(rate_limit)

    resp = requests.post(
        Config.VENICE_IMAGE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "prompt": prompt,
            "negative_prompt": Config.DEFAULT_NEGATIVE_PROMPT,
            "n": 1,
            "size": "1024x1024",
            "response_format": "b64_json",
        },
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()

    if "data" in data and data["data"]:
        b64 = data["data"][0].get("b64_json")
        if b64:
            safe_name = name.replace(" ", "_").replace("/", "-")[:30]
            filename = f"symbol_{safe_name}.png"
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(b64))
            return filepath
    return None
