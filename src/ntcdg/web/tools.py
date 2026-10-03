"""Workbench registry: every MCP tool described from its signature + docstring,
plus the per-user input mapping and output post-processing used by the web app.

Every ``@mcp.tool()`` function in :mod:`ntcdg.mcp_server` must appear in
:data:`REGISTRY` or in :data:`EXCLUDED_TOOLS` (with a reason); a test enforces
this so new tools cannot be silently missed.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .. import mcp_server
from ..config import Config
from ..runtime import capture_stdout_to, venice_key_scope
from . import files as webfiles
from . import namespace as ns

# ==================== TOOL CLASSIFICATION ====================

#: Tools that run as background jobs (slow: Venice calls or PDF rendering).
JOB_TOOLS = frozenset({
    "create_deck", "retry_failed", "generate_back", "generate_single_card", "complete_symbols",
    "preview_style", "finalize_deck", "export_bundle", "describe_symbols", "register_symbols",
    "suggest_deck",
})
#: Image/deck generation jobs: at most one active per user.
GENERATION_TOOLS = frozenset({
    "create_deck", "retry_failed", "generate_back", "generate_single_card", "complete_symbols",
    "preview_style",
})
#: Tools that spend Venice credits (need the user's own key).
KEY_TOOLS = GENERATION_TOOLS | {"describe_symbols", "suggest_deck", "register_symbols"}

CATEGORIES: dict[str, str] = {
    "suggest_deck": "1 · Plan", "estimate_cost": "1 · Plan", "get_traditional_symbols": "1 · Plan",
    "register_symbols": "2 · Symbols", "describe_symbols": "2 · Symbols",
    "match_symbols": "2 · Symbols", "complete_symbols": "2 · Symbols",
    "preview_style": "3 · Generate", "create_deck": "3 · Generate", "retry_failed": "3 · Generate",
    "generate_single_card": "3 · Generate", "generate_back": "3 · Generate",
    "deck_progress": "3 · Generate",
    "list_decks": "4 · Decks", "deck_info": "4 · Decks", "deck_stats": "4 · Decks",
    "list_cards": "4 · Decks", "get_card_details": "4 · Decks", "get_card_image": "4 · Decks",
    "get_all_images": "4 · Decks", "edit_card": "4 · Decks", "clone_deck": "4 · Decks",
    "delete_deck": "4 · Decks", "get_deck_traditional_coverage": "4 · Decks",
    "finalize_deck": "5 · Print & share", "duplex_calibration": "5 · Print & share",
    "get_public_links": "5 · Print & share", "get_card_by_slug": "5 · Print & share",
    "export_bundle": "5 · Print & share",
}

#: Tools deliberately not offered in the web workbench (name -> reason).
#: Currently every tool is offered; tools that take server paths are *adapted*
#: (see WEB_NOTES) rather than excluded.
EXCLUDED_TOOLS: dict[str, str] = {}

#: How the web app adapts a tool for multi-user use (shown in the workbench).
WEB_NOTES: dict[str, str] = {
    "create_deck": "symbols_file accepts only your own symbol manifests/uploads.",
    "list_decks": "Only your own decks are listed.",
    "register_symbols": "Each symbol's image_path must be one of your uploads (upload:<id>).",
    "describe_symbols": "Pick from your uploaded images; server paths are not accepted.",
    "match_symbols": "symbols_file accepts only your own symbol manifests/uploads.",
    "complete_symbols": "symbols_file accepts only your own symbol manifests/uploads.",
    "preview_style": "symbols_file accepts only your own symbol manifests/uploads.",
    "finalize_deck": (
        "QR codes always use this server's configured public URL "
        "(public_base_url / rebase_url are fixed by the server)."
    ),
    "delete_deck": "Type the deck name again to confirm.",
    "get_card_by_slug": "Public lookup: resolves any published deck, exactly like a scanned QR code.",
    "duplex_calibration": "The calibration sheet contains no deck data and is shared by everyone.",
}

_CHOICES: dict[str, list[str]] = {
    "symbol_mode": ["generate", "provide"],
    "sheet_size": ["letter", "tabloid", "a4", "a3"],
    "color_mode": ["color", "bw"],
    "duplex_flip": ["long_edge", "short_edge"],
    "target_scope": ["full", "major", "suits"],
    "arcana_type": ["all", "major", "suit", "court"],
    "suit": ["", "Wands", "Cups", "Swords", "Pentacles"],
    "field": ["title", "venice_title", "new_title", "description",
              "upright_interpretation", "reversed_interpretation"],
    "image_model": ["", *Config.SUPPORTED_IMAGE_MODELS],
}
_TEXTAREAS = frozenset({"deck_prompt", "prompt", "value", "user_description", "style_prompt"})
_BOUNDS: dict[str, tuple[float, float]] = {
    "cards": (1, mcp_server.MAX_CARDS),
    "card_num": (0, 999),
    "previews": (0, 10),
    "max_generate": (0, 100),
    "back_offset_x_mm": (-20, 20),
    "back_offset_y_mm": (-20, 20),
}
_KIND_OVERRIDES: dict[tuple[str, str], str] = {
    ("create_deck", "name"): "new_deck",
    ("clone_deck", "source"): "deck",
    ("clone_deck", "new_name"): "new_deck",
    ("preview_style", "name"): "label_deck",
    ("register_symbols", "deck_name"): "label_deck",
    ("complete_symbols", "deck_name"): "label_deck",
    ("register_symbols", "symbols"): "symbol_defs",
    ("match_symbols", "symbols"): "json_list",
    ("describe_symbols", "image_paths"): "upload_images",
    ("finalize_deck", "public_base_url"): "hidden",
    ("finalize_deck", "rebase_url"): "hidden",
}
MAX_STR = 8000
MAX_LIST = 200


# ==================== SPECS ====================

@dataclass
class ParamSpec:
    name: str
    kind: str
    annotation: str
    default: Any = None
    required: bool = False
    description: str = ""
    choices: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    web_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "kind": self.kind, "annotation": self.annotation,
            "default": self.default, "required": self.required,
            "description": self.description, "choices": self.choices,
            "minimum": self.minimum, "maximum": self.maximum, "web_only": self.web_only,
        }


@dataclass
class ToolSpec:
    name: str
    summary: str
    doc: str
    params: list[ParamSpec]
    mode: str
    generation: bool
    needs_key: bool
    category: str
    note: str = ""
    func: Callable[..., Any] | None = field(default=None, repr=False)

    @property
    def visible_params(self) -> list[ParamSpec]:
        return [p for p in self.params if p.kind != "hidden"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "summary": self.summary, "doc": self.doc,
            "params": [p.to_dict() for p in self.visible_params], "mode": self.mode,
            "generation": self.generation, "needs_key": self.needs_key,
            "category": self.category, "note": self.note,
        }


def discover_mcp_tools() -> list[str]:
    """Names of every function decorated with ``@mcp.tool()`` in mcp_server (source order)."""
    source = inspect.getsource(mcp_server)
    names = []
    for node in ast.parse(source).body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if (isinstance(target, ast.Attribute) and target.attr == "tool"
                    and isinstance(target.value, ast.Name) and target.value.id == "mcp"):
                names.append(node.name)
    return names


def parse_docstring(doc: str | None) -> tuple[str, str, dict[str, str]]:
    """``(summary, body_without_args, {param: description})`` from a Google-style docstring."""
    lines = inspect.cleandoc(doc or "").splitlines()
    summary_lines: list[str] = []
    for line in lines:
        if not line.strip():
            break
        summary_lines.append(line.strip())
    args: dict[str, str] = {}
    body: list[str] = []
    in_args = False
    current: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped in ("Args:", "Arguments:", "Parameters:"):
            in_args, current = True, None
            continue
        if in_args:
            m = re.match(r"^ {2,6}(\w+)\s*(?:\([^)]*\))?:\s*(.*)$", line)
            if m and len(line) - len(line.lstrip()) <= 6:
                current = m.group(1)
                args[current] = m.group(2).strip()
                continue
            if stripped and line.startswith(" ") and current:
                args[current] = (args[current] + " " + stripped).strip()
                continue
            if not stripped:
                continue
            in_args, current = False, None
        body.append(line)
    return " ".join(summary_lines), "\n".join(body).strip(), args


def _annotation_str(ann: Any) -> str:
    if ann is inspect.Parameter.empty:
        return "str"
    if isinstance(ann, str):
        return ann
    if typing.get_origin(ann) is not None:
        return str(ann).replace("typing.", "")
    return getattr(ann, "__name__", None) or str(ann).replace("typing.", "")


def _infer_kind(tool: str, name: str, ann: str) -> str:
    if (tool, name) in _KIND_OVERRIDES:
        return _KIND_OVERRIDES[(tool, name)]
    if name == "deck_name":
        return "deck"
    if name == "symbols_file":
        return "symbols_file"
    if ann == "bool":
        return "bool"
    if ann == "int":
        return "int"
    if ann == "float":
        return "float"
    if ann.startswith("list"):
        return "json_list"
    if name in _CHOICES:
        return "choice"
    if name in _TEXTAREAS:
        return "text"
    return "str"


def build_spec(name: str) -> ToolSpec:
    func = getattr(mcp_server, name)
    try:
        hints = typing.get_type_hints(func)
    except Exception:  # pragma: no cover - fall back to raw annotations
        hints = {}
    summary, body, arg_docs = parse_docstring(func.__doc__)
    params: list[ParamSpec] = []
    for pname, p in inspect.signature(func).parameters.items():
        ann = hints.get(pname, p.annotation)
        ann_s = _annotation_str(ann)
        kind = _infer_kind(name, pname, ann_s)
        bounds = _BOUNDS.get(pname)
        default = None if p.default is inspect.Parameter.empty else p.default
        params.append(ParamSpec(
            name=pname, kind=kind, annotation=ann_s, default=default,
            required=p.default is inspect.Parameter.empty,
            description=arg_docs.get(pname, ""),
            choices=_CHOICES.get(pname) if kind == "choice" else None,
            minimum=bounds[0] if bounds else None, maximum=bounds[1] if bounds else None,
        ))
    if name == "delete_deck":
        params.append(ParamSpec(
            name="confirm", kind="confirm", annotation="str", required=True, web_only=True,
            description="Type the deck name again to confirm permanent deletion.",
        ))
    return ToolSpec(
        name=name, summary=summary, doc=body, params=params,
        mode="job" if name in JOB_TOOLS else "sync",
        generation=name in GENERATION_TOOLS, needs_key=name in KEY_TOOLS,
        category=CATEGORIES.get(name, "6 · Other"), note=WEB_NOTES.get(name, ""), func=func,
    )


def build_registry() -> dict[str, ToolSpec]:
    return {n: build_spec(n) for n in discover_mcp_tools() if n not in EXCLUDED_TOOLS}


REGISTRY: dict[str, ToolSpec] = build_registry()


def registry_by_category() -> list[tuple[str, list[ToolSpec]]]:
    groups: dict[str, list[ToolSpec]] = {}
    for spec in REGISTRY.values():
        groups.setdefault(spec.category, []).append(spec)
    return sorted(groups.items())


# ==================== INPUT MAPPING ====================

class ToolInputError(ValueError):
    """Invalid or forbidden tool input (shown to the user)."""


@dataclass
class ToolContext:
    db: Any
    user: dict[str, Any]
    settings: Any

    @property
    def username(self) -> str:
        return self.user["username"]


@dataclass
class PreparedCall:
    spec: ToolSpec
    display_input: dict[str, Any]
    kwargs: dict[str, Any]
    deck: str = ""
    internal_deck: str = ""


def _to_bool(v: Any, pname: str) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "1", "on", "yes"):
        return True
    if s in ("false", "0", "off", "no", ""):
        return False
    raise ToolInputError(f"{pname} must be true or false")


def _to_number(v: Any, p: ParamSpec) -> int | float:
    try:
        if isinstance(v, bool):
            raise ValueError
        num: int | float = int(v) if p.kind == "int" else float(v)
        if p.kind == "int" and isinstance(v, float) and not float(v).is_integer():
            raise ValueError
    except (TypeError, ValueError):
        raise ToolInputError(f"{p.name} must be a{'n integer' if p.kind == 'int' else ' number'}") from None
    if p.kind == "float" and num != num:  # NaN
        raise ToolInputError(f"{p.name} must be a number")
    if p.minimum is not None and num < p.minimum:
        raise ToolInputError(f"{p.name} must be at least {p.minimum:g}")
    if p.maximum is not None and num > p.maximum:
        raise ToolInputError(f"{p.name} must be at most {p.maximum:g}")
    return num


def _to_list(v: Any, pname: str) -> list[Any]:
    if v is None or v == "":
        return []
    if isinstance(v, str):
        text = v.strip()
        if text.startswith("["):
            try:
                v = json.loads(text)
            except ValueError:
                raise ToolInputError(f"{pname} is not valid JSON") from None
        else:
            v = [line.strip() for line in text.splitlines() if line.strip()]
    if not isinstance(v, list):
        raise ToolInputError(f"{pname} must be a list")
    if len(v) > MAX_LIST:
        raise ToolInputError(f"{pname} may contain at most {MAX_LIST} items")
    return v


def _str(v: Any, pname: str) -> str:
    if v is None:
        return ""
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise ToolInputError(f"{pname} must be text")
    s = str(v)
    if len(s) > MAX_STR:
        raise ToolInputError(f"{pname} is too long (max {MAX_STR} characters)")
    return s


def _symbol_dicts(items: list[Any], pname: str) -> list[dict[str, str]]:
    out = []
    for item in items:
        if not isinstance(item, dict):
            raise ToolInputError(f"Each entry of {pname} must be an object")
        clean = {}
        for k, val in item.items():
            if not isinstance(k, str) or len(k) > 50:
                raise ToolInputError(f"Bad key in {pname}")
            clean[k] = _str(val, f"{pname}.{k}")[:2000]
        out.append(clean)
    return out


def prepare_call(spec: ToolSpec, raw: dict[str, Any], ctx: ToolContext) -> PreparedCall:
    """Validate browser input and map it to safe tool kwargs for ``ctx.user``."""
    if not isinstance(raw, dict):
        raise ToolInputError("inputs must be an object")
    known = {p.name for p in spec.params if p.kind != "hidden"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ToolInputError(f"Unknown input(s) for {spec.name}: {', '.join(unknown)}")

    display: dict[str, Any] = {}
    kwargs: dict[str, Any] = {}
    deck_short = ""
    internal_deck = ""
    for p in spec.params:
        present = p.name in raw and raw[p.name] is not None
        value = raw.get(p.name) if present else p.default
        if p.kind == "hidden":
            continue
        if not present and p.required and p.kind not in ("bool",):
            raise ToolInputError(f"{p.name} is required")

        if p.kind in ("deck", "new_deck", "label_deck"):
            short = _str(value, p.name).strip()
            try:
                if p.kind == "deck":
                    internal = ns.owned_deck(ctx.username, short)
                else:
                    internal = ns.internal_name(ctx.username, short)
            except ns.NamespaceError as e:
                raise ToolInputError(str(e)) from None
            if p.kind == "new_deck" and spec.name == "clone_deck":
                from ..storage import deck_exists
                if deck_exists(internal):
                    raise ToolInputError(f"Deck '{short}' already exists")
            display[p.name] = short
            kwargs[p.name] = internal
            if not deck_short or p.name in ("deck_name", "name"):
                deck_short, internal_deck = short, internal
        elif p.kind == "bool":
            display[p.name] = kwargs[p.name] = _to_bool(value, p.name)
        elif p.kind in ("int", "float"):
            display[p.name] = kwargs[p.name] = _to_number(value, p)
        elif p.kind == "choice":
            s = _str(value, p.name)
            if p.choices is not None and s not in p.choices:
                allowed = ", ".join(c or "(empty)" for c in p.choices)
                raise ToolInputError(f"{p.name} must be one of: {allowed}")
            display[p.name] = kwargs[p.name] = s
        elif p.kind in ("str", "text"):
            display[p.name] = kwargs[p.name] = _str(value, p.name)
        elif p.kind == "symbols_file":
            ref = _str(value, p.name).strip()
            try:
                kwargs[p.name] = webfiles.resolve_symbols_ref(ctx.db, ctx.user, ref)
            except webfiles.FileInputError as e:
                raise ToolInputError(str(e)) from None
            display[p.name] = ref
        elif p.kind == "upload_images":
            refs = [_str(r, p.name).strip() for r in _to_list(value, p.name)]
            if len(refs) > 20:
                raise ToolInputError(f"{p.name}: at most 20 images at a time")
            try:
                kwargs[p.name] = [webfiles.resolve_upload(ctx.db, ctx.user, r, kind="image") for r in refs]
            except webfiles.FileInputError as e:
                raise ToolInputError(str(e)) from None
            display[p.name] = refs
        elif p.kind == "symbol_defs":
            items = _symbol_dicts(_to_list(value, p.name), p.name)
            mapped = []
            for item in items:
                ref = item.get("image_path") or item.get("image") or ""
                try:
                    path = webfiles.resolve_upload(ctx.db, ctx.user, ref, kind="image")
                except webfiles.FileInputError as e:
                    raise ToolInputError(f"{item.get('name') or 'symbol'}: {e}") from None
                mapped.append({"name": item.get("name", ""), "image_path": path,
                               "description": item.get("description", "")})
            display[p.name] = items
            kwargs[p.name] = mapped
        elif p.kind == "json_list":
            items = _symbol_dicts(_to_list(value, p.name), p.name)
            # Server paths are meaningless (and unsafe) here: drop them.
            cleaned = [{k: v for k, v in it.items() if k not in ("image", "image_path")} for it in items]
            display[p.name] = cleaned
            kwargs[p.name] = cleaned or None
        elif p.kind == "confirm":
            display[p.name] = _str(value, p.name)
        else:  # pragma: no cover - every kind is handled above
            raise ToolInputError(f"Unsupported parameter {p.name}")

    if spec.name == "delete_deck" and display.get("confirm") != display.get("deck_name"):
        raise ToolInputError("Confirmation does not match the deck name; nothing was deleted.")

    if spec.name == "finalize_deck":
        cfg = ctx.settings.public_config()
        kwargs["public_base_url"] = cfg["base_url"]
        kwargs["rebase_url"] = False

    return PreparedCall(spec, display, kwargs, deck_short, internal_deck)


# ==================== EXECUTION ====================

def _seed_public_slug(internal: str, short: str) -> None:
    """Give a deck its public slug from its *short* name (never the username)."""
    from .. import public
    from ..storage import load_decks_index, update_deck_meta

    index = load_decks_index()
    if index.get(internal, {}).get("public_slug"):
        return
    taken = {m.get("public_slug") for m in index.values() if m.get("public_slug")}
    update_deck_meta(internal, public_slug=public.new_deck_slug(short, taken))


def execute(call: PreparedCall, ctx: ToolContext, venice_key: str | None,
            stdout: Any = None) -> dict[str, Any]:
    """Run a prepared call with the user's key bound (never the server env key)."""
    import io

    stream = stdout if stdout is not None else io.StringIO()
    kwargs = dict(call.kwargs)
    with venice_key_scope(venice_key, allow_env_fallback=False), capture_stdout_to(stream):
        try:
            if call.spec.name == "finalize_deck":
                kwargs.pop("confirm", None)
                if kwargs.get("qr_codes", True) and kwargs.get("public_base_url"):
                    _seed_public_slug(call.internal_deck, call.deck)
                result = mcp_server._finalize_impl(
                    kwargs.pop("deck_name"), allow_local_url=bool(ctx.settings.allow_local_url),
                    **kwargs,
                )
            else:
                kwargs.pop("confirm", None)
                result = call.spec.func(**kwargs)
        except Exception as e:
            result = {"success": False, "error": str(e) or type(e).__name__}
    if not isinstance(result, dict):
        result = {"result": result}
    return postprocess(call, result, ctx)


def postprocess(call: PreparedCall, result: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if call.spec.name == "list_decks":
        decks = [d for d in result.get("decks", []) if ns.owns(ctx.username, str(d.get("name", "")))]
        result = {**result, "decks": decks, "count": len(decks)}
    return result


def run_sync(call: PreparedCall, ctx: ToolContext, venice_key: str | None) -> dict[str, Any]:
    """Run a quick tool inline; returns ``{tool, input, output, console}`` (sanitised)."""
    import io

    buf = io.StringIO()
    output = execute(call, ctx, venice_key, stdout=buf)
    sanitizer = webfiles.Sanitizer(ctx.db, ctx.user)
    return {
        "mode": "sync",
        "tool": call.spec.name,
        "input": call.display_input,
        "output": sanitizer.value(output),
        "console": sanitizer.text(buf.getvalue().strip()),
    }
