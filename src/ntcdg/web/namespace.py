"""Per-user deck namespacing.

Every web user's decks are stored under internal names ``{username}__{deck}``
so they share the normal NTCDG storage without ever colliding. Usernames may
not contain ``__`` nor end in ``_``; that makes ``internal.startswith(username
+ "__")`` an exact ownership test (no other username can produce that prefix).
"""

from __future__ import annotations

import re
from typing import Any

from ..storage import DECK_NAME_RE, deck_exists, load_decks_index

SEP = "__"
USERNAME_RE = re.compile(r"^(?!.*__)[a-z0-9][a-z0-9_-]{1,30}[a-z0-9]$")
SHORT_DECK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$")
RESERVED_USERNAMES = frozenset({
    "admin", "root", "system", "ntcdg", "api", "static", "files", "uploads", "public",
})


class NamespaceError(ValueError):
    """Bad or foreign deck/user name."""


def validate_username(username: str) -> str:
    name = (username or "").strip().lower()
    if not USERNAME_RE.match(name):
        raise NamespaceError(
            "Usernames are 3-32 characters: lowercase letters, numbers, '-' and single '_', "
            "starting and ending with a letter or number."
        )
    if name in RESERVED_USERNAMES:
        raise NamespaceError("That username is reserved.")
    return name


def validate_short_deck(name: str) -> str:
    deck = (name or "").strip()
    if not SHORT_DECK_RE.match(deck):
        raise NamespaceError(
            "Deck names are 1-60 characters: letters, numbers, '-' and '_', starting with a "
            "letter or number."
        )
    return deck


def prefix(username: str) -> str:
    return f"{username}{SEP}"


def internal_name(username: str, short: str) -> str:
    name = f"{prefix(username)}{validate_short_deck(short)}"
    if not DECK_NAME_RE.match(name):  # pragma: no cover - guaranteed by the regexes
        raise NamespaceError("Deck name too long")
    return name


def short_name(username: str, internal: str) -> str | None:
    """Short deck name if ``internal`` belongs to ``username``, else None."""
    pre = prefix(username)
    if isinstance(internal, str) and internal.startswith(pre) and len(internal) > len(pre):
        return internal[len(pre):]
    return None


def owns(username: str, internal: str) -> bool:
    return short_name(username, internal) is not None


def user_decks(username: str) -> list[tuple[str, str, dict[str, Any]]]:
    """``[(short, internal, meta)]`` for every saved deck of ``username``."""
    found = []
    for internal, meta in sorted(load_decks_index().items()):
        short = short_name(username, internal)
        if short is None or not SHORT_DECK_RE.match(short):
            continue
        if not deck_exists(internal):
            continue
        found.append((short, internal, meta))
    return found


def owned_deck(username: str, short: str) -> str:
    """Internal name of the user's existing deck ``short`` or raise NamespaceError."""
    try:
        internal = internal_name(username, short)
    except NamespaceError:
        raise NamespaceError(f"Deck '{short}' not found") from None
    if not deck_exists(internal):
        raise NamespaceError(f"Deck '{short}' not found")
    return internal
