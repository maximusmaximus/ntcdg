"""Venice.ai API integration: text analysis, image generation, and image editing."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import threading
import time
from typing import Any

from .config import RETRYABLE_STATUS_CODES, Config, _requests, logger, requests
from .models import Card
from .runtime import current_usage_tracker

_SESSION_LOCAL = threading.local()


def _http_post_callable():
    """Return a thread-local ``requests.Session().post`` or a test-patched ``requests.post``."""
    if requests is None:
        return None
    if _requests is not None and requests is _requests:
        sess = getattr(_SESSION_LOCAL, "session", None)
        if sess is None:
            sess = _requests.Session()
            _SESSION_LOCAL.session = sess
        return sess.post
    return requests.post


def venice_post(
    url: str,
    api_key: str,
    json_payload: dict[str, Any],
    *,
    timeout: float = 90,
    max_retries: int = 2,
    initial_delay: float = 1.5,
    backoff: float = 2.0,
):
    """POST to a Venice endpoint with connection pooling, 429 Retry-After, and 5xx retries.

    Permanent client errors (400/401/402/403/404/422) fail immediately without retrying.
    """
    post_fn = _http_post_callable()
    if post_fn is None:
        raise RuntimeError("Missing requests library")

    headers = {"Authorization": f"Bearer {api_key}"}
    current_delay = initial_delay
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            resp = post_fn(url, headers=headers, json=json_payload, timeout=timeout)
            raw_status = getattr(resp, "status_code", 200)
            status = raw_status if isinstance(raw_status, int) else 200
            if status in RETRYABLE_STATUS_CODES and attempt < max_retries:
                if status == 429:
                    retry_after = getattr(resp, "headers", {}).get("Retry-After")
                    if retry_after:
                        with contextlib.suppress(ValueError, TypeError):
                            current_delay = max(float(retry_after), current_delay)
                logger.warning(
                    f"Venice HTTP {status} on {url} (attempt {attempt + 1}/{max_retries + 1}); "
                    f"retrying in {current_delay:.1f}s..."
                )
                time.sleep(current_delay)
                current_delay *= backoff
                continue
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_exc = e
            err_resp = getattr(e, "response", None)
            raw_err_status = getattr(err_resp, "status_code", 0) if err_resp is not None else 0
            err_status = raw_err_status if isinstance(raw_err_status, int) else 0
            if 400 <= err_status < 500 and err_status not in RETRYABLE_STATUS_CODES:
                raise
            if err_status == 429 and err_resp is not None:
                retry_after = getattr(err_resp, "headers", {}).get("Retry-After")
                if retry_after:
                    with contextlib.suppress(ValueError, TypeError):
                        current_delay = max(float(retry_after), current_delay)
            if attempt < max_retries:
                logger.warning(
                    f"Venice request failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                    f"Retrying in {current_delay:.1f}s..."
                )
                time.sleep(current_delay)
                current_delay *= backoff
                continue
            raise
    assert last_exc is not None
    raise last_exc


def parse_json_response(raw: str) -> dict[str, Any]:
    """Extract and parse a JSON object from an LLM text response (stripping code fences)."""
    match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    candidate = match.group(1).strip() if match else raw.strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end > start:
            parsed = json.loads(candidate[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        raise
    raise ValueError("Expected a JSON object from Venice model")


def _parse_image_size(image_size: str) -> tuple[int, int]:
    """Parse 'WIDTHxHEIGHT' string into (width, height) integers."""
    parts = image_size.lower().split("x")
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    return 1024, 1024


def _clamp_dimensions(width: int, height: int, max_dim: int = 1280) -> tuple[int, int]:
    """Clamp (width, height) to ``max_dim`` (multiples of 8) while preserving aspect ratio."""
    if width > max_dim or height > max_dim:
        scale = max_dim / max(width, height)
        old_w, old_h = width, height
        width = max(8, int(width * scale) // 8 * 8)
        height = max(8, int(height * scale) // 8 * 8)
        logger.warning(
            f"Image size {old_w}x{old_h} exceeds Venice max ({max_dim}). "
            f"Clamped to {width}x{height}."
        )
    return width, height


def _detect_image_mime(raw: bytes, path: str) -> str:
    """Detect image MIME type from magic bytes with file-extension fallback."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if raw.startswith(b"BM"):
        return "image/bmp"
    ext = os.path.splitext(path)[1].lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext, "image/png")


def _encode_image_data_uri(path: str) -> str:
    """Encode an image file on disk as a base64 ``data:image/...;base64,...`` URI."""
    with open(path, "rb") as f:
        raw = f.read()
    mime = _detect_image_mime(raw, path)
    return f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"


def _build_image_request(model: str, prompt: str, image_size: str,
                         negative_prompt: str = "") -> dict[str, Any]:
    """Build the Venice /image/generate request body.

    Venice enforces a max of 1280 for both width and height.
    Dimensions are clamped down while preserving aspect ratio.
    """
    width, height = _clamp_dimensions(*_parse_image_size(image_size))
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


def _extract_text_content(resp_json: dict) -> str:
    """Extract text content from Venice chat completion response.

    DeepSeek v3.2+ models put reasoning in 'reasoning_content' and may
    leave 'content' empty if max_tokens is too low. This handles both cases.
    """
    msg = resp_json["choices"][0]["message"]
    raw = (msg.get("content") or "").strip()
    if raw:
        return raw
    # Fallback: try reasoning_content
    reasoning = (msg.get("reasoning_content") or "").strip()
    if reasoning:
        logger.warning("Content empty, checking reasoning_content for output")
        return reasoning
    return ""


# ==================== TEXT ANALYSIS ====================
def analyze_with_venice(
    card: Card, api_key: str, model: str, tracker=None,
) -> dict[str, Any]:
    """Analyze a card with Venice text model, returning enrichment fields."""
    if not api_key:
        return {"venice_error": "Venice API key not provided"}
    if not requests:
        return {"venice_error": "Missing requests library"}
    tracker = tracker or current_usage_tracker()

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
            "max_tokens": 4000,
        }
        resp = venice_post(Config.VENICE_TEXT_URL, api_key, payload, timeout=90)
        resp_json = resp.json()
        raw = _extract_text_content(resp_json)

        if not raw:
            return {"venice_error": "Empty response from Venice text model"}

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

        analysis = parse_json_response(raw)
        analysis["venice_text_model"] = model
        return analysis
    except Exception as e:
        logger.error(f"Venice text analysis failed for card {card.position}: {e}")
        if tracker:
            tracker.record_text_call(model=model, success=False, purpose="analysis")
        return {"venice_error": str(e)}


_SYMBOL_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "into", "over", "under",
    "this", "that", "card", "tarot", "of", "in", "on", "to", "a", "an",
})


def _match_card_symbol_images(
    card: Card, symbol_images: dict[str, str],
) -> list[tuple[str, str]]:
    """Return ``[(symbol_name, path), ...]`` matching this card's symbols or prompt."""
    card_syms_lower = [str(s).lower() for s in (card.symbols or [])]
    prompt_lower = (card.prompt or "").lower()
    title_lower = (card.title or "").lower()

    explicit_matches: list[tuple[str, str]] = []
    prompt_matches: list[tuple[str, str]] = []

    for sym_name, sym_path in (symbol_images or {}).items():
        if not sym_path or not os.path.isfile(str(sym_path)):
            continue
        norm_name = str(sym_name).strip().lower()
        if not norm_name:
            continue
        tokens = [
            tok for tok in re.split(r"[^a-z0-9]+", norm_name)
            if len(tok) >= 3 and tok not in _SYMBOL_STOPWORDS
        ]
        if any(norm_name in cs or cs in norm_name for cs in card_syms_lower) or (
            tokens and any(any(tok in cs for cs in card_syms_lower) for tok in tokens)
        ):
            explicit_matches.append((sym_name, str(sym_path)))
            continue

        if norm_name in prompt_lower or norm_name in title_lower or (
            tokens and any(re.search(rf"\b{re.escape(tok)}\b", prompt_lower) for tok in tokens)
        ):
            prompt_matches.append((sym_name, str(sym_path)))

    return explicit_matches + prompt_matches


# ==================== IMAGE GENERATION ====================
def generate_image_with_venice(
    card: Card,
    api_key: str,
    model: str,
    image_size: str = Config.DEFAULT_IMAGE_SIZE,
    negative_prompt: str = "",
    rate_limit_delay: float = 1.5,
    symbol_mode: str = "generate",
    symbol_images: dict[str, str] | None = None,
    tracker=None,
    output_dir: str | None = None,
    edit_model: str | None = None,
) -> dict[str, Any]:
    """Generate a card image via Venice. Returns a dict of result fields.

    ``output_dir`` -- where to save the image (default ``Config.IMAGES_DIR``);
    pass the deck's own folder so decks never overwrite each other's files.
    """
    if not api_key:
        return {"image_error": "Venice API key not provided"}
    if not requests:
        return {"image_error": "Missing requests library"}
    tracker = tracker or current_usage_tracker()

    time.sleep(rate_limit_delay)

    images_dir = output_dir or Config.IMAGES_DIR
    os.makedirs(images_dir, exist_ok=True)
    full_prompt = card.prompt
    neg_prompt = negative_prompt or Config.DEFAULT_NEGATIVE_PROMPT
    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", str(card.title or "Card")).strip("_")[:40] or "Card"
    final_card_path = os.path.join(images_dir, f"{card.position:03d}_{safe_title}.png")
    temp_path: str | None = None

    try:
        # === GENERATE MODE (default) ===
        if symbol_mode == "generate" or not symbol_images:
            resp = venice_post(
                Config.VENICE_IMAGE_URL,
                api_key,
                _build_image_request(model, full_prompt, image_size, neg_prompt),
                timeout=180,
                initial_delay=2.0,
            )
            data = resp.json()

            b64 = _extract_image_b64(data)
            if b64:
                img_data = base64.b64decode(b64)
                with open(final_card_path, "wb") as f:
                    f.write(img_data)
                if tracker:
                    tracker.record_image_call(
                        model, image_size, success=True,
                    )
                return {
                    "image_path": final_card_path,
                    "image_model": model,
                    "image_size": image_size,
                    "symbol_mode": "generate",
                }

        # === PROVIDE MODE (Two-Pass Base Generation + Multi-Reference Artist Refinement) ===
        else:
            base_resp = venice_post(
                Config.VENICE_IMAGE_URL,
                api_key,
                _build_image_request(model, full_prompt, image_size, neg_prompt),
                timeout=180,
                initial_delay=2.0,
            )
            base_data = base_resp.json()

            b64 = _extract_image_b64(base_data)
            if not b64:
                if tracker:
                    tracker.record_image_call(model, image_size, success=False, purpose="card_base")
                return {"image_error": "No base image data"}

            if tracker:
                tracker.record_image_call(model, image_size, success=True, purpose="card_base")

            temp_path = os.path.join(images_dir, f".tmp_pass1_{card.position:03d}_{safe_title}.png")
            with open(temp_path, "wb") as f:
                f.write(base64.b64decode(b64))

            matched = _match_card_symbol_images(card, symbol_images)
            if matched:
                style_desc = (
                    (card.deck_vibe or "").strip()
                    or (card.deck_prompt or "").strip()
                    or "cohesive illustrated tarot"
                )
                ref_pairs = matched[:2]  # Venice multi-edit supports up to 3 total layers (1 base + 2 refs)
                edit_parts = [
                    f"Preserve the overall {style_desc} aesthetic, palette, lighting, and scene "
                    f"composition of image 1 (the tarot card '{card.title}')."
                ]
                for ref_idx, (sym_name, _sym_path) in enumerate(ref_pairs, start=2):
                    edit_parts.append(
                        f"Refine and integrate the '{sym_name}' element so its visual form, "
                        f"linework, and texture faithfully match reference image {ref_idx}."
                    )
                for extra_name, _ in matched[2:]:
                    edit_parts.append(
                        f"Ensure the '{extra_name}' motif harmonizes seamlessly with the artist's style."
                    )
                edit_parts.append(
                    "Do not add any text, letters, numbers, watermarks, or card borders."
                )
                edit_prompt = " ".join(edit_parts)

                ref_layers = [temp_path, *[p for _, p in ref_pairs]]
                edit_result = multi_edit_image_with_venice(
                    ref_layers,
                    edit_prompt,
                    api_key,
                    model=edit_model,
                    image_size=image_size,
                    output_path=final_card_path,
                    rate_limit_delay=rate_limit_delay,
                    tracker=tracker,
                )
                if edit_result.get("image_path"):
                    with contextlib.suppress(OSError):
                        os.remove(temp_path)
                    return {
                        "image_path": edit_result["image_path"],
                        "image_model": model,
                        "image_size": image_size,
                        "symbol_mode": "provide",
                        "used_symbol_images": [name for name, _ in matched],
                        "edited": True,
                    }

            # Fallback to Pass 1 base artwork with clean card filename if no symbols matched or edit failed
            os.replace(temp_path, final_card_path)
            return {
                "image_path": final_card_path,
                "image_model": model,
                "image_size": image_size,
                "symbol_mode": "provide_fallback",
            }

        return {"image_error": "Unexpected response from Venice"}

    except Exception as e:
        if temp_path and os.path.exists(temp_path):
            with contextlib.suppress(OSError):
                os.remove(temp_path)
        logger.error(f"Image generation failed for card {card.position}: {e}")
        if tracker:
            tracker.record_image_call(model, image_size, success=False)
        return {"image_error": str(e)}


# ==================== IMAGE EDITING ====================
def _save_edit_response(resp, final_path: str, model: str) -> dict[str, Any]:
    """Decode binary or base64 JSON image payload from a Venice edit response."""
    os.makedirs(os.path.dirname(final_path) or ".", exist_ok=True)
    content_type = (getattr(resp, "headers", {}) or {}).get("content-type", "").lower()
    raw = getattr(resp, "content", b"") or b""
    if (
        "image/" in content_type
        or "octet-stream" in content_type
        or raw.startswith(b"\x89PNG")
        or raw.startswith(b"\xff\xd8\xff")
        or (len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")
    ):
        with open(final_path, "wb") as f:
            f.write(raw)
        return {"image_path": final_path, "image_model": model, "edited": True}

    data = resp.json()
    b64 = _extract_image_b64(data)
    if b64:
        with open(final_path, "wb") as f:
            f.write(base64.b64decode(b64))
        return {"image_path": final_path, "image_model": model, "edited": True}

    return {"image_error": "Unexpected response from Venice Edit"}


def edit_image_with_venice(
    base_image_path: str,
    edit_prompt: str,
    api_key: str,
    model: str | None = None,
    image_size: str = Config.DEFAULT_IMAGE_SIZE,
    enhance_prompt: bool = True,
    rate_limit_delay: float = 2.0,
    output_path: str | None = None,
    tracker=None,
) -> dict[str, Any]:
    """
    Use Venice's /image/edit endpoint to modify an existing image
    based on text instructions.

    Clamps dimensions to Venice's 1280px ceiling, detects true input MIME type,
    never overwrites non-PNG source files unless ``output_path`` is explicit,
    and handles both raw binary image responses and JSON base64 payloads.
    """
    if not api_key or not requests:
        return {"image_error": "Missing API key or requests"}
    tracker = tracker or current_usage_tracker()

    used_model = model or Config.DEFAULT_EDIT_MODEL
    if rate_limit_delay > 0:
        time.sleep(rate_limit_delay)

    try:
        data_uri = _encode_image_data_uri(base_image_path)
        width, height = _clamp_dimensions(*_parse_image_size(image_size))
        payload = {
            "model": used_model,
            "prompt": edit_prompt,
            "image": data_uri,
            "width": width,
            "height": height,
            "enhance_prompt": enhance_prompt,
        }

        resp = venice_post(
            Config.VENICE_EDIT_URL,
            api_key,
            payload,
            timeout=180,
            initial_delay=2.0,
        )

        stem, _ext = os.path.splitext(base_image_path)
        final_path = output_path or f"{stem}_edited.png"
        result = _save_edit_response(resp, final_path, used_model)
        if tracker:
            tracker.record_image_call(
                used_model, f"{width}x{height}",
                success="image_path" in result, purpose="edit",
            )
        return result

    except Exception as e:
        logger.error(f"Image edit failed: {e}")
        if tracker:
            tracker.record_image_call(used_model, image_size, success=False, purpose="edit")
        return {"image_error": str(e)}


def multi_edit_image_with_venice(
    image_paths: list[str],
    edit_prompt: str,
    api_key: str,
    model: str | None = None,
    image_size: str = Config.DEFAULT_IMAGE_SIZE,
    enhance_prompt: bool = True,
    rate_limit_delay: float = 1.5,
    output_path: str | None = None,
    tracker=None,
) -> dict[str, Any]:
    """Use Venice's ``/image/multi-edit`` endpoint with reference artwork layers.

    ``image_paths[0]`` is the base card image; ``image_paths[1:3]`` are artist
    reference symbol images. Automatically falls back to single-image
    ``edit_image_with_venice`` if ``/image/multi-edit`` rejects the model/request
    with HTTP 400/404/422.
    """
    if not api_key or not requests:
        return {"image_error": "Missing API key or requests"}
    tracker = tracker or current_usage_tracker()
    valid_paths = [p for p in (image_paths or []) if p and os.path.isfile(p)]
    if not valid_paths:
        return {"image_error": "No valid input images for multi-edit"}

    base_path = valid_paths[0]
    stem, _ext = os.path.splitext(base_path)
    final_path = output_path or f"{stem}_edited.png"

    # Single image only -> delegate directly to /image/edit
    if len(valid_paths) == 1:
        return edit_image_with_venice(
            base_path,
            edit_prompt,
            api_key,
            model=model or Config.DEFAULT_EDIT_MODEL,
            image_size=image_size,
            enhance_prompt=enhance_prompt,
            rate_limit_delay=rate_limit_delay,
            output_path=final_path,
            tracker=tracker,
        )

    used_model = model or Config.DEFAULT_MULTI_EDIT_MODEL
    if rate_limit_delay > 0:
        time.sleep(rate_limit_delay)

    try:
        capped_paths = valid_paths[:3]  # Venice multi-edit supports max 3 layered images
        payload = {
            "model": used_model,
            "prompt": edit_prompt,
            "images": [_encode_image_data_uri(p) for p in capped_paths],
            "aspect_ratio": "auto",
            "output_format": "png",
            "enhance_prompt": enhance_prompt,
        }
        resp = venice_post(
            Config.VENICE_MULTI_EDIT_URL,
            api_key,
            payload,
            timeout=180,
            initial_delay=2.0,
        )
        result = _save_edit_response(resp, final_path, used_model)
        if tracker:
            tracker.record_image_call(
                used_model, image_size,
                success="image_path" in result, purpose="edit",
            )
        return result
    except Exception as e:
        err_resp = getattr(e, "response", None)
        raw_status = getattr(err_resp, "status_code", 0) if err_resp is not None else 0
        status = raw_status if isinstance(raw_status, int) else 0
        if status in (400, 404, 422):
            logger.warning(
                f"Venice multi-edit returned HTTP {status} ({e}); falling back to /image/edit."
            )
            return edit_image_with_venice(
                base_path,
                edit_prompt,
                api_key,
                model=Config.DEFAULT_EDIT_MODEL,
                image_size=image_size,
                enhance_prompt=enhance_prompt,
                rate_limit_delay=0,
                output_path=final_path,
                tracker=tracker,
            )
        logger.error(f"Multi-image edit failed: {e}")
        if tracker:
            tracker.record_image_call(used_model, image_size, success=False, purpose="edit")
        return {"image_error": str(e)}


# ==================== CARD BACK GENERATION ====================
def generate_card_back(
    prompt: str,
    api_key: str,
    model: str,
    deck_name: str,
    image_size: str = Config.DEFAULT_IMAGE_SIZE,
    negative_prompt: str = "",
    rate_limit_delay: float = 1.5,
    tracker=None,
) -> str:
    """
    Generate a single card back design image via Venice.

    The back is saved inside ``deck_images_dir(deck_name)`` so each deck remains
    self-contained. Returns the path to the saved image, or "" on failure.
    """
    if not api_key or not requests:
        logger.error("Missing API key or requests library")
        return ""
    tracker = tracker or current_usage_tracker()

    time.sleep(rate_limit_delay)
    neg = negative_prompt or Config.DEFAULT_NEGATIVE_PROMPT

    try:
        resp = venice_post(
            Config.VENICE_IMAGE_URL,
            api_key,
            _build_image_request(model, prompt, image_size, neg),
            timeout=180,
            initial_delay=2.0,
        )
        data = resp.json()

        b64 = _extract_image_b64(data)
        if b64:
            from .storage import deck_images_dir

            target_dir = deck_images_dir(deck_name)
            os.makedirs(target_dir, exist_ok=True)
            filename = f"{deck_name}_BACK.png"
            filepath = os.path.join(target_dir, filename)
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(b64))
            if tracker:
                tracker.record_image_call(model, image_size, success=True, purpose="card_back")
            logger.info(f"Card back saved: {filepath}")
            return filepath

        if tracker:
            tracker.record_image_call(model, image_size, success=False, purpose="card_back")
        logger.error("No image data in Venice response for card back")
        return ""
    except Exception as e:
        if tracker:
            tracker.record_image_call(model, image_size, success=False, purpose="card_back")
        logger.error(f"Card back generation failed: {e}")
        return ""
