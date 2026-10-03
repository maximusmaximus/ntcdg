"""Tests for the thread-safe runtime helpers (stdout capture + scoped API key)."""

from __future__ import annotations

import threading

import pytest

from ntcdg.runtime import capture_output, capture_stdout, get_venice_key, venice_key_scope


def test_capture_output_returns_result_and_text():
    def work(x):
        print("hello", x)
        return x * 2

    result, out = capture_output(work, 21)
    assert result == 42
    assert out == "hello 21"


def test_nested_capture_is_isolated():
    with capture_stdout() as outer:
        print("outer-1")
        with capture_stdout() as inner:
            print("inner")
        print("outer-2")
    assert inner.getvalue().strip() == "inner"
    assert "inner" not in outer.getvalue()
    assert "outer-1" in outer.getvalue() and "outer-2" in outer.getvalue()


def test_concurrent_captures_do_not_interleave():
    """redirect_stdout is process-global; our capture must be per-thread."""
    barrier = threading.Barrier(4)
    results: dict[str, str] = {}

    def worker(tag: str):
        def noisy():
            barrier.wait()
            for _ in range(200):
                print(tag)
        _, out = capture_output(noisy)
        results[tag] = out

    threads = [threading.Thread(target=worker, args=(f"T{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for tag, out in results.items():
        lines = out.splitlines()
        assert len(lines) == 200
        assert set(lines) == {tag}


def test_capture_survives_exceptions():
    def boom():
        print("before")
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        capture_output(boom)
    # A subsequent capture still works and is empty of the old text
    _, out = capture_output(lambda: print("after"))
    assert out == "after"


def test_venice_key_scope_overrides_env(monkeypatch):
    monkeypatch.setenv("VENICE_API_KEY", "env-key")
    assert get_venice_key() == "env-key"
    with venice_key_scope("user-key"):
        assert get_venice_key() == "user-key"
    assert get_venice_key() == "env-key"


def test_venice_key_required_raises(monkeypatch):
    monkeypatch.delenv("VENICE_API_KEY", raising=False)
    with pytest.raises(ValueError):
        get_venice_key()
    assert get_venice_key(required=False) == ""


def test_venice_key_scope_is_per_thread(monkeypatch):
    monkeypatch.delenv("VENICE_API_KEY", raising=False)
    barrier = threading.Barrier(2)
    seen: dict[str, str] = {}

    def worker(key: str):
        with venice_key_scope(key):
            barrier.wait()
            seen[key] = get_venice_key()

    threads = [threading.Thread(target=worker, args=(k,)) for k in ("alice", "bob")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == {"alice": "alice", "bob": "bob"}
