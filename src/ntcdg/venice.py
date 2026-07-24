"""Venice.ai API integration: text analysis, image generation, and image editing."""

import base64
import contextlib
import os
import re
import time
from typing import Any

from .config import Config, logger, requests, retry_on_failure
from .models import Card


# ==================== TEXT ANALYSIS ====================
@retry_on_failure(max_retries=2, delay=1.5)
def analyze_with_venice(card: Card, api_key: str, model: str) -> dict[str, Any]:
    """Analyze a card with Venice text model, returning enrichment fields."""
    if not api_key or not requests:
        return {"venice_error": "Missing API key or requests library"}

    system = (
        "You are an expert tarot symbologist and card designer. "
        "Analyze how visual elements combine and interact to create meaning. "
        "You always respond with valid JSON."
    )
    user = f"""Analyze this tarot card and provide enriched creative content:

Title: {card.title}
Type: {card.card_type}
Symbols: {', '.join(card.symbols)}
Layout: {card.layout}
Deck Theme: {card.deck_prompt or 'None'}

Return a JSON object with these fields:
- "new_title": an evocative, thematic title that captures the card's essence
- "description": rich visual description of imagery and how elements interact
- "serial": unique serial number like VNX-042-007
- "upright_interpretation": the card's positive/upright meaning (2-3 sentences)
- "reversed_interpretation": the card's reversed/shadow meaning (2-3 sentences)"""

    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
            "max_tokens": 850,
            "response_format": {"type": "json_object"},
        }
        resp = requests.post(
            Config.VENICE_TEXT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=90,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()

        # response_format should give clean JSON, but strip fences as fallback
        match = re.search(r'```(?:json)?\s*(.*?)```', raw, re.DOTALL)
        content = match.group(1).strip() if match else raw
        import json
        analysis = json.loads(content)
        analysis["venice_text_model"] = model
        return analysis
    except Exception as e:
        logger.error(f"Venice text analysis failed for card {card.position}: {e}")
        return {"venice_error": str(e)}


# ==================== IMAGE GENERATION ====================
@retry_on_failure(max_retries=2, delay=2.0)
def generate_image_with_venice(
    card: Card,
    api_key: str,
    model: str,
    image_size: str = "1024x1536",
    negative_prompt: str = "",
    rate_limit_delay: float = 1.5,
    symbol_mode: str = "generate",
    symbol_images: dict[str, str] = None,
) -> dict[str, Any]:
    """Generate a card image via Venice. Returns a dict of result fields."""
    if not api_key or not requests:
        return {"image_error": "Missing API key or requests"}

    time.sleep(rate_limit_delay)

    full_prompt = card.prompt
    neg_prompt = negative_prompt or Config.DEFAULT_NEGATIVE_PROMPT

    try:
        # === GENERATE MODE (default) ===
        if symbol_mode == "generate" or not symbol_images:
            resp = requests.post(
                Config.VENICE_IMAGE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "prompt": full_prompt,
                    "negative_prompt": neg_prompt,
                    "n": 1,
                    "size": image_size,
                    "response_format": "b64_json",
                },
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("data"):
                b64 = data["data"][0].get("b64_json")
                if b64:
                    img_data = base64.b64decode(b64)
                    safe_title = str(card.title).replace(" ", "_")[:40]
                    filename = f"{card.position:03d}_{safe_title}.png"
                    filepath = os.path.join(Config.IMAGES_DIR, filename)
                    with open(filepath, "wb") as f:
                        f.write(img_data)
                    return {
                        "image_path": filepath,
                        "image_model": model,
                        "image_size": image_size,
                        "symbol_mode": "generate",
                    }

        # === PROVIDE MODE ===
        else:
            base_resp = requests.post(
                Config.VENICE_IMAGE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "prompt": full_prompt,
                    "negative_prompt": neg_prompt,
                    "n": 1,
                    "size": image_size,
                    "response_format": "b64_json",
                },
                timeout=180,
            )
            base_resp.raise_for_status()
            base_data = base_resp.json()

            if "data" not in base_data or not base_data["data"]:
                return {"image_error": "Failed to generate base image"}

            b64 = base_data["data"][0].get("b64_json")
            if not b64:
                return {"image_error": "No base image data"}

            temp_path = os.path.join(Config.IMAGES_DIR, f"temp_{card.position}.png")
            with open(temp_path, "wb") as f:
                f.write(base64.b64decode(b64))

            edit_prompt_parts = [
                "Keep the overall psychedelic neon glitch vortex tarot style and composition."
            ]
            for symbol_name in symbol_images:
                if any(kw in card.prompt.lower() for kw in symbol_name.split()):
                    edit_prompt_parts.append(
                        f"Redraw the {symbol_name} using the provided hand-drawn element style. "
                        "Make it look like a traditional hand-drawn tarot illustration element."
                    )

            if len(edit_prompt_parts) > 1:
                edit_prompt = " ".join(edit_prompt_parts)
                edit_result = edit_image_with_venice(
                    temp_path, edit_prompt, api_key,
                    model=Config.DEFAULT_EDIT_MODEL, image_size=image_size,
                )
                if edit_result.get("image_path"):
                    with contextlib.suppress(OSError):
                        os.remove(temp_path)
                    return {
                        "image_path": edit_result["image_path"],
                        "image_model": model,
                        "image_size": image_size,
                        "symbol_mode": "provide",
                        "used_symbol_images": list(symbol_images.keys()),
                    }

            # Fallback to base if no edits applied
            final_path = temp_path.replace("temp_", "")
            os.rename(temp_path, final_path)
            return {
                "image_path": final_path,
                "image_model": model,
                "image_size": image_size,
                "symbol_mode": "provide_fallback",
            }

        return {"image_error": "Unexpected response from Venice"}

    except Exception as e:
        logger.error(f"Image generation failed for card {card.position}: {e}")
        return {"image_error": str(e)}


# ==================== IMAGE EDITING ====================
@retry_on_failure(max_retries=2, delay=2.0)
def edit_image_with_venice(
    base_image_path: str,
    edit_prompt: str,
    api_key: str,
    model: str = None,
    image_size: str = "1024x1536",
    rate_limit_delay: float = 2.0,
) -> dict[str, Any]:
    """
    Use Venice's /image/edit endpoint to modify an existing image
    based on text instructions (great for injecting custom hand-drawn elements).
    """
    if not api_key or not requests:
        return {"image_error": "Missing API key or requests"}

    model = model or Config.DEFAULT_EDIT_MODEL

    time.sleep(rate_limit_delay)

    try:
        with open(base_image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        resp = requests.post(
            Config.VENICE_EDIT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "prompt": edit_prompt,
                "image": f"data:image/png;base64,{image_b64}",
                "size": image_size,
                "response_format": "b64_json",
            },
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("data"):
            b64 = data["data"][0].get("b64_json")
            if b64:
                img_data = base64.b64decode(b64)
                final_path = base_image_path.replace(".png", "_edited.png")
                with open(final_path, "wb") as f:
                    f.write(img_data)
                return {"image_path": final_path, "image_model": model, "edited": True}
        return {"image_error": "Unexpected response from Venice Edit"}

    except Exception as e:
        logger.error(f"Image edit failed: {e}")
        return {"image_error": str(e)}
