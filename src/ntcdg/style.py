"""Deck style extraction, prompt refinement, and visual consistency.

When the user provides symbol artwork, those images define the artistic
DNA of the entire deck. We analyze them to extract a "meta style prompt"
that drives all subsequent card image generation.

When no artwork is provided, the style is synthesized from the deck's
vibe, theme, and symbol descriptions via the text model.
"""

import base64
import os
from typing import Any

from .config import Config, logger, requests
from .models import Card
from .venice import _extract_text_content


# ==================== STYLE EXTRACTION ====================
def extract_style_from_images(
    image_paths: list[str],
    api_key: str,
    model: str | None = None,
) -> str:
    """Analyze provided artwork images to extract a unified style description.

    Sends up to 4 images to a vision-capable model and asks it to
    describe the artistic style in detail. This description becomes
    the "meta prompt" that defines the deck's visual identity.
    """
    if not requests or not api_key:
        return ""

    vision_model = model or Config.DEFAULT_VISION_MODEL

    # Encode images as base64 data URIs
    content: list[dict[str, Any]] = []
    for path in image_paths[:4]:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = os.path.splitext(path)[1].lstrip(".") or "png"
            mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
        except Exception as e:
            logger.warning(f"Could not read image {path}: {e}")

    if not content:
        return ""

    content.append({
        "type": "text",
        "text": (
            "You are an expert art director analyzing reference artwork for "
            "a tarot card deck. Study these images carefully and write a "
            "comprehensive style description covering:\n\n"
            "1. MEDIUM & TECHNIQUE: What artistic medium do these resemble? "
            "(oil painting, watercolor, digital illustration, woodcut, etc.)\n"
            "2. COLOR PALETTE: Describe the exact colors, their warmth/coolness, "
            "saturation, and how they interact.\n"
            "3. TEXTURE & SURFACE: Is it smooth, textured, grainy, glossy?\n"
            "4. LIGHTING & MOOD: How is light used? What emotional tone?\n"
            "5. LINE WORK & DETAIL: Thick/thin lines, level of detail, "
            "stylization vs realism.\n"
            "6. COMPOSITION STYLE: How are elements arranged? Symmetric, "
            "dynamic, centered?\n\n"
            "Write this as a single dense paragraph that could be prepended "
            "to an image generation prompt to recreate this exact style. "
            "Be extremely specific — mention exact color values, techniques, "
            "and visual qualities. Do NOT mention specific subjects or "
            "symbols, only the style itself."
        ),
    })

    try:
        resp = requests.post(
            Config.VENICE_TEXT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": vision_model,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 4000,
                "temperature": 0.3,
            },
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        style = _extract_text_content(data)
        logger.info(f"Extracted visual style from {len(content) - 1} images")
        return style
    except Exception as e:
        logger.warning(f"Vision style extraction failed: {e}")
        return ""


def generate_style_from_text(
    vibe: str,
    deck_prompt: str,
    symbol_descriptions: list[str],
    api_key: str,
    model: str | None = None,
) -> str:
    """Synthesize a deck style description from text inputs.

    Fallback when no reference artwork is available. Uses the deck's
    vibe, theme prompt, and symbol descriptions to craft a cohesive
    visual style.
    """
    if not requests or not api_key:
        return ""

    text_model = model or Config.DEFAULT_TEXT_MODEL

    symbols_text = ", ".join(symbol_descriptions[:10]) if symbol_descriptions else "none"

    try:
        resp = requests.post(
            Config.VENICE_TEXT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": text_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an expert art director designing the visual "
                            "identity for a tarot card deck. You specialize in "
                            "creating cohesive, distinctive visual styles."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Design a comprehensive visual style for a tarot "
                            f"deck with this vibe: '{vibe}'\n"
                            f"Theme: {deck_prompt or 'not specified'}\n"
                            f"Key symbols: {symbols_text}\n\n"
                            "Write a single dense paragraph describing the "
                            "exact artistic style covering: medium/technique, "
                            "specific color palette (name exact hues), texture, "
                            "lighting, line work, level of detail, and mood.\n\n"
                            "This will be prepended to every image prompt, so "
                            "be very specific and actionable. Do NOT mention "
                            "specific card subjects — only the style itself."
                        ),
                    },
                ],
                "max_tokens": 4000,
                "temperature": 0.7,
            },
            timeout=90,
        )
        resp.raise_for_status()
        style = _extract_text_content(resp.json())
        logger.info("Generated deck style from text description")
        return style
    except Exception as e:
        logger.warning(f"Text style generation failed: {e}")
        return ""


def extract_deck_style(
    symbol_images: dict[str, str],
    symbol_descriptions: list[str],
    vibe: str,
    deck_prompt: str,
    api_key: str,
    text_model: str | None = None,
) -> str:
    """Extract or generate a deck style — the meta prompt for all artwork.

    If the user provided symbol artwork, those images define the style.
    Otherwise, the style is synthesized from text inputs.
    """
    # Try vision-based extraction from provided artwork first
    if symbol_images:
        image_paths = [p for p in symbol_images.values() if os.path.exists(p)]
        if image_paths:
            logger.info(
                f"Extracting deck style from {len(image_paths)} "
                f"provided artwork images..."
            )
            style = extract_style_from_images(image_paths, api_key)
            if style:
                return style
            logger.info("Vision extraction failed, falling back to text")

    # Fallback: text-based style generation
    return generate_style_from_text(
        vibe, deck_prompt, symbol_descriptions, api_key, text_model,
    )


# ==================== PROMPT REFINEMENT ====================
def refine_card_prompt(
    card: Card,
    deck_style: str,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    """Write an art-director-quality image prompt for a specific card.

    Combines the locked deck style with card-specific content.
    If API is unavailable, falls back to a template-based prompt.
    """
    # Always start with the deck style as foundation
    style_prefix = deck_style or ""

    # If no API, use template fallback
    if not api_key or not requests:
        return _build_fallback_prompt(card, style_prefix)

    text_model = model or Config.DEFAULT_TEXT_MODEL

    try:
        resp = requests.post(
            Config.VENICE_TEXT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": text_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an expert art director writing image "
                            "generation prompts for a tarot card deck. Every "
                            "card must match the established deck style exactly."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"DECK STYLE (must be followed precisely):\n"
                            f"{style_prefix}\n\n"
                            f"CARD TO ILLUSTRATE:\n"
                            f"Title: {card.title}\n"
                            f"Type: {card.card_type}\n"
                            f"Symbols: {', '.join(card.symbols)}\n"
                            f"Composition: {card.layout}\n"
                            f"{'First card of deck — origins/beginnings. ' if card.is_first else ''}"
                            f"{'Final card of deck — culmination/synthesis. ' if card.is_last else ''}"
                            f"\nWrite a single image generation prompt (max "
                            f"150 words) that:\n"
                            f"1. Opens with the deck style description\n"
                            f"2. Describes this specific card's scene, "
                            f"composition, and symbolic elements\n"
                            f"3. Specifies portrait orientation\n"
                            f"4. Ends with technical quality terms\n"
                            f"Do NOT include any text, titles, numbers, or "
                            f"lettering in the prompt. Output ONLY the "
                            f"prompt text, no preamble."
                        ),
                    },
                ],
                "max_tokens": 4000,
                "temperature": 0.6,
            },
            timeout=90,
        )
        resp.raise_for_status()
        prompt = _extract_text_content(resp.json())

        # Strip any markdown quotes the model might add
        if prompt.startswith('"') and prompt.endswith('"'):
            prompt = prompt[1:-1]

        logger.debug(f"Refined prompt for '{card.title}' ({len(prompt)} chars)")
        return prompt
    except Exception as e:
        logger.warning(f"Prompt refinement failed for '{card.title}': {e}")
        return _build_fallback_prompt(card, style_prefix)


def _build_fallback_prompt(card: Card, style_prefix: str) -> str:
    """Template-based prompt when LLM refinement is unavailable."""
    parts = []
    if style_prefix:
        parts.append(style_prefix)

    parts.append(
        f"Tarot card artwork in portrait orientation. "
        f"{card.card_type}: '{card.title}'. "
        f"Visual elements: {', '.join(card.symbols)}. "
        f"Composition: {card.layout}."
    )

    if card.is_first:
        parts.append("Origins and new beginnings.")
    if card.is_last:
        parts.append("Culmination and full synthesis.")
    if card.deck_prompt:
        parts.append(f"Theme: {card.deck_prompt}.")

    parts.append(
        "Highly detailed, dramatic cinematic lighting, "
        "rich symbolic density, professional quality. "
        "No text, no letters, no numbers, no titles."
    )
    return " ".join(parts)
