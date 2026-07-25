"""User configuration file support for NTCDG.

Loads defaults from ~/.ntcdgrc (YAML) so users don't need to
repeat common arguments like API key, vibe, and model preferences.

File format (~/.ntcdgrc):
    venice_api_key: sk-xxx
    default_vibe: "cosmic horror meets art nouveau"
    default_image_model: flux-2-pro
    default_text_model: deepseek-v3.2
    default_image_size: 1024x1792
    default_font: /path/to/font.ttf
    default_negative_prompt: "text, ugly, blurry"
    rate_limit: 1.5
"""

import os
from typing import Any

from .config import logger

RC_PATHS = [
    os.path.expanduser("~/.ntcdgrc"),
    ".ntcdgrc",  # project-local override
]


def _parse_rc_file(path: str) -> dict[str, str]:
    """Parse a simple key: value config file (YAML-lite).

    Supports both ':' and '=' as delimiters:
        venice_api_key: sk-xxx
        venice_api_key = sk-xxx
    """
    config: dict[str, str] = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Support both : and = as delimiters
                if "=" in line and ":" not in line:
                    key, _, value = line.partition("=")
                elif ":" in line:
                    key, _, value = line.partition(":")
                else:
                    continue
                key = key.strip()
                value = value.strip()
                # Strip surrounding quotes
                if (
                    len(value) >= 2
                    and value[0] in ('"', "'")
                    and value[-1] == value[0]
                ):
                    value = value[1:-1]
                config[key] = value
    except Exception as e:
        logger.debug(f"Could not read config {path}: {e}")
    return config


def load_user_config() -> dict[str, Any]:
    """Load user configuration from ~/.ntcdgrc and ./.ntcdgrc.

    Project-local .ntcdgrc values override global ~/.ntcdgrc values.
    Returns a dict of config values.
    """
    merged: dict[str, str] = {}
    for path in RC_PATHS:
        if os.path.exists(path):
            logger.debug(f"Loading config from {path}")
            merged.update(_parse_rc_file(path))
    return merged


def apply_config_defaults(args, config: dict[str, Any]):
    """Apply config file defaults to argparse args (without overriding explicit CLI values).

    Only fills in values that the user did NOT specify on the command line.
    """
    # Map config keys to argparse attribute names and their CLI defaults
    mappings = {
        "venice_api_key": ("venice_key", None),
        "default_vibe": ("vibe", None),
        "default_image_model": ("venice_image_model", None),
        "default_text_model": ("venice_text_model", None),
        "default_image_size": ("image_size", None),
        "default_font": ("font", None),
        "default_negative_prompt": ("negative_prompt", ""),
        "rate_limit": ("rate_limit", None),
        "default_deck_prompt": ("deck_prompt", ""),
    }

    applied = []
    for config_key, (attr_name, cli_default) in mappings.items():
        if config_key not in config:
            continue
        current = getattr(args, attr_name, cli_default)
        # Only apply if the arg is at its default (user didn't specify it)
        if current is None or current == cli_default or current == "":
            config_val = config[config_key]
            # Handle numeric types
            if attr_name == "rate_limit":
                try:
                    config_val = float(config_val)
                except ValueError:
                    continue
            setattr(args, attr_name, config_val)
            applied.append(config_key)

    if applied:
        logger.debug(f"Applied config defaults: {', '.join(applied)}")


def create_sample_config():
    """Create a sample ~/.ntcdgrc file."""
    path = os.path.expanduser("~/.ntcdgrc")
    if os.path.exists(path):
        print(f"Config file already exists: {path}")
        return

    sample = """# NTCDG Configuration
# Uncomment and edit the settings you want as defaults.

# Venice API key (or set VENICE_API_KEY environment variable)
# venice_api_key: sk-your-key-here

# Default deck style/vibe
# default_vibe: "cosmic horror meets art nouveau"

# Default theme/prompt
# default_deck_prompt: ""

# Model preferences
# default_text_model: deepseek-v3.2
# default_image_model: flux-2-pro
# default_image_size: 1024x1792

# Font for card overlay
# default_font: /path/to/font.ttf

# Default negative prompt (appended to all image generations)
# default_negative_prompt: "text, letters, blurry, low quality"

# API rate limit (seconds between calls)
# rate_limit: 1.5
"""
    with open(path, "w") as f:
        f.write(sample)
    print(f"Created sample config: {path}")
    print("Edit it to set your defaults.")
