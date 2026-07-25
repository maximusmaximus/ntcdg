"""Usage tracking and cost estimation for Venice API calls.

Tracks all API calls made during deck generation and persists
the stats in the deck index for later review.
"""

import time
from dataclasses import dataclass, field
from typing import Any

# Venice pricing estimates (USD) — updated 2026
# These are approximations; actual pricing may vary.
PRICING = {
    "text": {
        "deepseek-v3.2": {"input": 0.0014, "output": 0.0028},  # per 1K tokens
        "qwen2.5-vl": {"input": 0.0020, "output": 0.0040},
        "_default": {"input": 0.0015, "output": 0.0030},
    },
    "image": {
        "flux-2-pro": 0.030,      # per image
        "flux-2-max-edit": 0.040,  # per image
        "_default": 0.035,
    },
}


@dataclass
class UsageTracker:
    """Accumulates API usage stats during deck generation."""

    # Text API
    text_calls: int = 0
    text_calls_failed: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    text_model: str = ""

    # Image API
    image_calls: int = 0
    image_calls_failed: int = 0
    image_model: str = ""
    image_size: str = ""

    # Style extraction
    style_calls: int = 0
    style_prompt: str = ""

    # Symbols
    symbol_mode: str = ""  # "generate" or "provide"
    symbol_names: list[str] = field(default_factory=list)
    symbols_file: str = ""

    # Preview
    preview_image_calls: int = 0

    # Timing
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0

    # Per-call log for detailed breakdown
    call_log: list[dict[str, Any]] = field(default_factory=list)

    def record_text_call(
        self, model: str, prompt_tokens: int = 0,
        completion_tokens: int = 0, success: bool = True,
        purpose: str = "analysis",
    ):
        """Record a text API call."""
        self.text_calls += 1
        if not success:
            self.text_calls_failed += 1
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.text_model = model
        self.call_log.append({
            "type": "text", "model": model, "purpose": purpose,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "success": success,
        })

    def record_image_call(
        self, model: str, size: str = "",
        success: bool = True, purpose: str = "card",
    ):
        """Record an image API call."""
        self.image_calls += 1
        if not success:
            self.image_calls_failed += 1
        self.image_model = model
        if size:
            self.image_size = size
        if purpose == "preview":
            self.preview_image_calls += 1
        self.call_log.append({
            "type": "image", "model": model, "purpose": purpose,
            "size": size, "success": success,
        })

    def record_style_call(self, style_prompt: str):
        """Record style extraction."""
        self.style_calls += 1
        self.style_prompt = style_prompt

    def finalize(self):
        """Mark generation as complete."""
        self.end_time = time.time()

    @property
    def elapsed_seconds(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def estimate_cost(self) -> dict[str, float]:
        """Estimate total cost in USD."""
        # Text cost
        text_pricing = PRICING["text"].get(
            self.text_model, PRICING["text"]["_default"],
        )
        text_cost = (
            (self.prompt_tokens / 1000) * text_pricing["input"]
            + (self.completion_tokens / 1000) * text_pricing["output"]
        )

        # Image cost
        img_price = PRICING["image"].get(
            self.image_model, PRICING["image"]["_default"],
        )
        image_cost = self.image_calls * img_price

        return {
            "text": round(text_cost, 4),
            "image": round(image_cost, 4),
            "total": round(text_cost + image_cost, 4),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage in deck index."""
        costs = self.estimate_cost()
        return {
            "text_calls": self.text_calls,
            "text_calls_failed": self.text_calls_failed,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "text_model": self.text_model,
            "image_calls": self.image_calls,
            "image_calls_failed": self.image_calls_failed,
            "image_model": self.image_model,
            "image_size": self.image_size,
            "preview_image_calls": self.preview_image_calls,
            "style_calls": self.style_calls,
            "style_prompt": self.style_prompt[:500],
            "symbol_mode": self.symbol_mode,
            "symbol_names": self.symbol_names[:20],
            "symbols_file": self.symbols_file,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "estimated_cost_usd": costs,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UsageTracker":
        """Reconstruct from stored dict."""
        tracker = cls()
        tracker.text_calls = data.get("text_calls", 0)
        tracker.text_calls_failed = data.get("text_calls_failed", 0)
        tracker.prompt_tokens = data.get("prompt_tokens", 0)
        tracker.completion_tokens = data.get("completion_tokens", 0)
        tracker.text_model = data.get("text_model", "")
        tracker.image_calls = data.get("image_calls", 0)
        tracker.image_calls_failed = data.get("image_calls_failed", 0)
        tracker.image_model = data.get("image_model", "")
        tracker.image_size = data.get("image_size", "")
        tracker.preview_image_calls = data.get("preview_image_calls", 0)
        tracker.style_calls = data.get("style_calls", 0)
        tracker.style_prompt = data.get("style_prompt", "")
        tracker.symbol_mode = data.get("symbol_mode", "")
        tracker.symbol_names = data.get("symbol_names", [])
        tracker.symbols_file = data.get("symbols_file", "")
        return tracker


def display_deck_stats(deck_name: str):
    """Display comprehensive usage stats for a deck."""
    from .storage import load_decks_index

    index = load_decks_index()
    meta = index.get(deck_name, {})
    if not meta:
        print(f"Deck '{deck_name}' not found.")
        return

    usage = meta.get("usage", {})
    if not usage:
        print(f"\nNo usage stats recorded for '{deck_name}'.")
        print("Stats are recorded during generation (--deck or --new).")
        return

    costs = usage.get("estimated_cost_usd", {})
    elapsed = usage.get("elapsed_seconds", 0)

    print(f"\n{'=' * 60}")
    print(f"  USAGE STATS: {deck_name}")
    print(f"{'=' * 60}")

    # --- API Calls ---
    print("\nAPI Calls:")
    text_ok = usage.get("text_calls", 0) - usage.get("text_calls_failed", 0)
    img_ok = usage.get("image_calls", 0) - usage.get("image_calls_failed", 0)
    print(f"  Text:     {text_ok} success / {usage.get('text_calls_failed', 0)} failed")
    print(f"  Image:    {img_ok} success / {usage.get('image_calls_failed', 0)} failed")
    previews = usage.get("preview_image_calls", 0)
    if previews:
        print(f"  Previews: {previews} (included in image count)")
    style_calls = usage.get("style_calls", 0)
    if style_calls:
        print(f"  Style:    {style_calls} extraction call(s)")

    # --- Tokens ---
    print("\nTokens:")
    print(f"  Prompt:     {usage.get('prompt_tokens', 0):,}")
    print(f"  Completion: {usage.get('completion_tokens', 0):,}")
    print(f"  Total:      {usage.get('total_tokens', 0):,}")

    # --- Models ---
    print("\nModels:")
    print(f"  Text:  {usage.get('text_model', 'N/A')}")
    print(f"  Image: {usage.get('image_model', 'N/A')}")
    print(f"  Size:  {usage.get('image_size', 'N/A')}")

    # --- Symbols ---
    sym_mode = usage.get("symbol_mode", "")
    if sym_mode:
        mode_label = "User-provided artwork" if sym_mode == "provide" else "AI-generated"
        print("\nSymbols:")
        print(f"  Mode:  {mode_label}")
        sym_names = usage.get("symbol_names", [])
        if sym_names:
            print(f"  Names: {', '.join(sym_names)}")
        sym_file = usage.get("symbols_file", "")
        if sym_file:
            print(f"  File:  {sym_file}")
    # --- Cost ---
    print("\nEstimated Cost (USD):")
    print(f"  Text inference:  ${costs.get('text', 0):.4f}")
    print(f"  Image generation: ${costs.get('image', 0):.4f}")
    print(f"  Total:            ${costs.get('total', 0):.4f}")

    # --- Timing ---
    if elapsed:
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        print(f"\nGeneration Time: {mins}m {secs}s")

    # --- Style Prompt ---
    style = usage.get("style_prompt", "")
    if style:
        print("\nDeck Style Prompt:")
        # Word-wrap at 70 chars
        words = style.split()
        line = "  "
        for word in words:
            if len(line) + len(word) + 1 > 72:
                print(line)
                line = "  " + word
            else:
                line += " " + word if line.strip() else "  " + word
        if line.strip():
            print(line)

    print(f"\n{'=' * 60}")
