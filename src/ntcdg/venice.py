"""Venice.ai API integration: text analysis, image generation, and image editing."""

import base64
import contextlib
import os
import re
import time
from typing import Any

from .config import Config, logger, requests, retry_on_failure
from .models import Card


def _parse_image_size(image_size: str) -> tuple[int, int]:
    """Parse 'WIDTHxHEIGHT' string into (width, height) integers."""
    parts = image_size.lower().split("x")
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    return 1024, 1024


def _build_image_request(model: str, prompt: str, image_size: str,
                         negative_prompt: str = "") -> dict[str, Any]:
    """Build the Venice /image/generate request body.

    Venice enforces a max of 1280 for both width and height.
    Dimensions are clamped down while preserving aspect ratio.
    """
    width, height = _parse_image_size(image_size)
    max_dim = 1280
    if width > max_dim or height > max_dim:
        scale = max_dim / max(width, height)
        old_w, old_h = width, height
        width = int(width * scale) // 8 * 8   # round to multiple of 8
        height = int(height * scale) // 8 * 8
        logger.warning(
            f"Image size {old_w}x{old_h} exceeds Venice max ({max_dim}). "
            f"Clamped to {width}x{height}."
        )
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
    }
    if negative_prompt:
        body["negative_prompt"] = negative_prompt
    body["width"] = width
    body["height"] = height
    return body


def _extract_image_b64(data: dict) -> str | None:
    """Extract base64 image data from Venice response."""
    # Venice native format: {"images": ["base64..."]}
    if data.get("images") and len(data["images"]) > 0:
        return data["images"][0]
    # OpenAI-compat fallback: {"data": [{"b64_json": "..."}]}
    if data.get("data") and len(data["data"]) > 0:
        return data["data"][0].get("b64_json")
    return None


# ==================== TEXT ANALYSIS ====================
@retry_on_failure(max_retries=2, delay=1.5)
def analyze_with_venice(
    card: Card, api_key: str, model: str, tracker=None,
) -> dict[str, Any]:
    """Analyze a card with Venice text model, returning enrichment fields."""
    if not api_key:
        return {"venice_error": "Venice API key not provided"}
    if not requests:
        return {"venice_error": "Missing requests library"}

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
        resp_json = resp.json()
        raw = resp_json["choices"][0]["message"]["content"].strip()

        # Track usage
        if tracker:
            usage = resp_json.get("usage", {})
            tracker.record_text_call(
                model=model,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                success=True,
                purpose="analysis",
            )

        # response_format should give clean JSON, but strip fences as fallback
        match = re.search(r'```(?:json)?\s*(.*?)```', raw, re.DOTALL)
        content = match.group(1).strip() if match else raw
        import json
        analysis = json.loads(content)
        analysis["venice_text_model"] = model
        return analysis
    except Exception as e:
        logger.error(f"Venice text analysis failed for card {card.position}: {e}")
        if tracker:
            tracker.record_text_call(model=model, success=False, purpose="analysis")
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
    tracker=None,
) -> dict[str, Any]:
    """Generate a card image via Venice. Returns a dict of result fields."""
    if not api_key:
        return {"image_error": "Venice API key not provided"}
    if not requests:
        return {"image_error": "Missing requests library"}

    time.sleep(rate_limit_delay)

    full_prompt = card.prompt
    neg_prompt = negative_prompt or Config.DEFAULT_NEGATIVE_PROMPT

    try:
        # === GENERATE MODE (default) ===
        if symbol_mode == "generate" or not symbol_images:
            resp = requests.post(
                Config.VENICE_IMAGE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json=_build_image_request(
                    model, full_prompt, image_size, neg_prompt,
                ),
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()

            b64 = _extract_image_b64(data)
            if b64:
                img_data = base64.b64decode(b64)
                safe_title = str(card.title).replace(" ", "_")[:40]
                filename = f"{card.position:03d}_{safe_title}.png"
                filepath = os.path.join(Config.IMAGES_DIR, filename)
                with open(filepath, "wb") as f:
                    f.write(img_data)
                    if tracker:
                        tracker.record_image_call(
                            model, image_size, success=True,
                        )
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
                json=_build_image_request(
                    model, full_prompt, image_size, neg_prompt,
                ),
                timeout=180,
            )
            base_resp.raise_for_status()
            base_data = base_resp.json()

            b64 = _extract_image_b64(base_data)
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
                    if tracker:
                        tracker.record_image_call(
                            model, image_size, success=True,
                        )
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
        if tracker:
            tracker.record_image_call(model, image_size, success=False)
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

# ==================== CARD BACK GENERATION ====================
@retry_on_failure(max_retries=2, delay=2.0)
def generate_card_back(
    prompt: str,
    api_key: str,
    model: str,
    deck_name: str,
    image_size: str = "1024x1536",
    negative_prompt: str = "",
    rate_limit_delay: float = 1.5,
) -> str:
    """
    Generate a single card back design image via Venice.

    The back is a single design used for all cards in the deck.
    Returns the path to the saved image, or "" on failure.
    """
    if not api_key or not requests:
        logger.error("Missing API key or requests library")
        return ""

    time.sleep(rate_limit_delay)
    neg = negative_prompt or Config.DEFAULT_NEGATIVE_PROMPT

    try:
        resp = requests.post(
            Config.VENICE_IMAGE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=_build_image_request(
                model, prompt, image_size, neg,
            ),
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()

        b64 = _extract_image_b64(data)
        if b64:
            os.makedirs(Config.IMAGES_DIR, exist_ok=True)
            filename = f"{deck_name}_BACK.png"
            filepath = os.path.join(Config.IMAGES_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(b64))
            logger.info(f"Card back saved: {filepath}")
            return filepath

        logger.error("No image data in Venice response for card back")
        return ""
    except Exception as e:
        logger.error(f"Card back generation failed: {e}")
        return ""
