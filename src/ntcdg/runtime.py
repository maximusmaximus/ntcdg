"""Runtime helpers that make NTCDG safe to drive from concurrent callers.

Two process-global assumptions in the original code break as soon as more
than one deck is generated at a time (e.g. from the web app or a busy MCP
server):

1. ``contextlib.redirect_stdout`` swaps ``sys.stdout`` for the *whole
   process*, so two concurrent captures interleave or steal each other's
   output.  :func:`capture_output` routes writes per-thread instead.
2. The Venice API key was only read from the ``VENICE_API_KEY`` environment
   variable.  :func:`venice_key_scope` lets a caller (e.g. a web job running
   on behalf of one user) bind a key for the current context only.
"""

from __future__ import annotations

import contextlib
import contextvars
import io
import os
import sys
import threading
from collections.abc import Callable, Iterator
from typing import Any

# ==================== PER-THREAD STDOUT CAPTURE ====================

_local = threading.local()
_install_lock = threading.Lock()


class _ThreadRoutingStdout(io.TextIOBase):
    """A ``sys.stdout`` proxy that sends writes to a per-thread buffer when one
    is active, and to the real stream otherwise."""

    def __init__(self, real: Any):
        super().__init__()
        self._real = real

    def _target(self):
        stack = getattr(_local, "buffers", None)
        return stack[-1] if stack else self._real

    def write(self, s: str) -> int:  # type: ignore[override]
        return self._target().write(s)

    def flush(self) -> None:
        target = self._target()
        if hasattr(target, "flush"):
            target.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._real, "isatty", lambda: False)())

    @property
    def encoding(self):  # type: ignore[override]
        return getattr(self._real, "encoding", "utf-8")

    def fileno(self) -> int:
        return self._real.fileno()


def _ensure_installed() -> None:
    if isinstance(sys.stdout, _ThreadRoutingStdout):
        return
    with _install_lock:
        if not isinstance(sys.stdout, _ThreadRoutingStdout):
            sys.stdout = _ThreadRoutingStdout(sys.stdout)


@contextlib.contextmanager
def capture_stdout_to(stream: Any) -> Iterator[Any]:
    """Send ``print`` output from the *current thread only* to ``stream``.

    ``stream`` only needs a ``write(str)`` method; a web job uses this to
    expose live console output while a long tool is still running.
    """
    _ensure_installed()
    stack = getattr(_local, "buffers", None)
    if stack is None:
        stack = []
        _local.buffers = stack
    stack.append(stream)
    try:
        yield stream
    finally:
        stack.pop()


@contextlib.contextmanager
def capture_stdout() -> Iterator[io.StringIO]:
    """Capture ``print`` output from the *current thread only*."""
    with capture_stdout_to(io.StringIO()) as buf:
        yield buf


def capture_output(func: Callable[..., Any], *args, **kwargs) -> tuple[Any, str]:
    """Run ``func`` capturing its stdout. Returns ``(result, output)``."""
    with capture_stdout() as buf:
        result = func(*args, **kwargs)
    return result, buf.getvalue().strip()


# ==================== SCOPED VENICE API KEY ====================

_venice_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "ntcdg_venice_key", default=None,
)
_allow_env_fallback: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "ntcdg_allow_env_fallback", default=True,
)


@contextlib.contextmanager
def venice_key_scope(key: str | None, allow_env_fallback: bool = True) -> Iterator[None]:
    """Bind a Venice API key for the current context (thread/task).

    With ``allow_env_fallback=False`` (used by the multi-user web app) an
    empty/missing key is an error instead of silently using the server's own
    ``VENICE_API_KEY`` -- one user must never spend the operator's credits.
    """
    token = _venice_key.set(key or None)
    fallback_token = _allow_env_fallback.set(bool(allow_env_fallback))
    try:
        yield
    finally:
        _allow_env_fallback.reset(fallback_token)
        _venice_key.reset(token)


def get_venice_key(required: bool = True) -> str:
    """Return the scoped key if bound, else ``VENICE_API_KEY`` from the env.

    Inside ``venice_key_scope(..., allow_env_fallback=False)`` the environment
    is never consulted.
    """
    key = _venice_key.get() or ""
    if not key and _allow_env_fallback.get():
        key = os.getenv("VENICE_API_KEY", "")
    if not key and required:
        if not _allow_env_fallback.get():
            raise ValueError(
                "No Venice API key is set for your account. Add your own key "
                "on your profile page to generate art and text."
            )
        raise ValueError(
            "VENICE_API_KEY is not set. Set the environment variable or "
            "provide a key for this request."
        )
    return key


# ==================== SCOPED EVENT SINK ====================

_event_sink: contextvars.ContextVar[Callable[[dict[str, Any]], None] | None] = (
    contextvars.ContextVar("ntcdg_event_sink", default=None)
)


@contextlib.contextmanager
def event_sink_scope(sink: Callable[[dict[str, Any]], None] | None) -> Iterator[None]:
    """Route progress events (e.g. from ``generate_deck``) to ``sink`` for this context.

    Lets a caller such as a web job observe per-card progress of MCP tools
    without adding non-serialisable callback parameters to the tools.
    """
    token = _event_sink.set(sink)
    try:
        yield
    finally:
        _event_sink.reset(token)


def current_event_sink() -> Callable[[dict[str, Any]], None] | None:
    return _event_sink.get()
