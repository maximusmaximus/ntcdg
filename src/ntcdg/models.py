"""Card data model for NTCDG."""

from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from typing import Any


@dataclass
class Card:
    """Represents a single tarot card with all generation metadata."""

    # Core identity
    position: int = 0
    title: str = ""
    card_type: str = ""  # "Major Arcana" or "Minor Arcana"
    suit: str | None = None
    rank: int | str | None = None
    arcana_number: int | None = None

    # Generation metadata
    symbols: list[str] = field(default_factory=list)
    layout: str = ""
    deck_vibe: str = ""
    deck_prompt: str = ""
    prompt: str = ""
    is_first: bool = False
    is_last: bool = False
    generated_at: str = ""

    # Venice text analysis results
    venice_title: str | None = None
    new_title: str | None = None
    description: str | None = None
    serial: str | None = None
    upright_interpretation: str | None = None
    reversed_interpretation: str | None = None
    venice_text_model: str | None = None
    venice_error: str | None = None

    # Image generation results
    image_path: str | None = None
    image_model: str | None = None
    image_size: str | None = None
    image_error: str | None = None
    symbol_mode: str | None = None
    used_symbol_images: list[str] | None = None
    edited: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization, omitting None values."""
        result = {}
        for f in dataclass_fields(self):
            val = getattr(self, f.name)
            if val is None:
                continue
            # Map dataclass field names to JSON keys
            key = "type" if f.name == "card_type" else f.name
            result[key] = val
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Card":
        """Create a Card from a dict, mapping keys and ignoring unknowns."""
        valid_fields = {f.name for f in dataclass_fields(cls)}
        mapped = {}
        for k, v in data.items():
            attr = "card_type" if k == "type" else k
            if attr in valid_fields:
                mapped[attr] = v
        return cls(**mapped)

    def update(self, data: dict[str, Any]):
        """Update card fields from a dict (e.g., Venice API response)."""
        for k, v in data.items():
            attr = "card_type" if k == "type" else k
            if hasattr(self, attr):
                setattr(self, attr, v)

    def display_title(self) -> str:
        """Return the best available title for display."""
        return self.venice_title or self.new_title or self.title
