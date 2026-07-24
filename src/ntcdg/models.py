"""Card data model for NTCDG."""

from dataclasses import dataclass, field, fields as dataclass_fields
from typing import Dict, List, Any, Optional, Union


@dataclass
class Card:
    """Represents a single tarot card with all generation metadata."""

    # Core identity
    position: int = 0
    title: str = ""
    card_type: str = ""  # "Major Arcana" or "Minor Arcana"
    suit: Optional[str] = None
    rank: Optional[Union[int, str]] = None
    arcana_number: Optional[int] = None

    # Generation metadata
    symbols: List[str] = field(default_factory=list)
    layout: str = ""
    deck_vibe: str = ""
    deck_prompt: str = ""
    prompt: str = ""
    is_first: bool = False
    is_last: bool = False
    generated_at: str = ""

    # Venice text analysis results
    venice_title: Optional[str] = None
    new_title: Optional[str] = None
    description: Optional[str] = None
    serial: Optional[str] = None
    upright_interpretation: Optional[str] = None
    reversed_interpretation: Optional[str] = None
    venice_text_model: Optional[str] = None
    venice_error: Optional[str] = None

    # Image generation results
    image_path: Optional[str] = None
    image_model: Optional[str] = None
    image_size: Optional[str] = None
    image_error: Optional[str] = None
    symbol_mode: Optional[str] = None
    used_symbol_images: Optional[List[str]] = None
    edited: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
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
    def from_dict(cls, data: Dict[str, Any]) -> "Card":
        """Create a Card from a dict, mapping keys and ignoring unknowns."""
        valid_fields = {f.name for f in dataclass_fields(cls)}
        mapped = {}
        for k, v in data.items():
            attr = "card_type" if k == "type" else k
            if attr in valid_fields:
                mapped[attr] = v
        return cls(**mapped)

    def update(self, data: Dict[str, Any]):
        """Update card fields from a dict (e.g., Venice API response)."""
        for k, v in data.items():
            attr = "card_type" if k == "type" else k
            if hasattr(self, attr):
                setattr(self, attr, v)

    def display_title(self) -> str:
        """Return the best available title for display."""
        return self.venice_title or self.new_title or self.title
