"""Regression tests for PR 3: web hardening, SSE cursor log, cancellation, EXIF & decks.grok.me."""

from __future__ import annotations

import io
import os
import threading
import time

import pytest
from PIL import Image

pytest.importorskip("fastapi")

from ntcdg import public
from ntcdg.duplex import create_calibration_pdf
from ntcdg.runtime import check_cancelled
from ntcdg.web.auth import LoginRateLimiter
from ntcdg.web.files import CALIBRATION_RE
from ntcdg.web.jobs import LiveLog
from tests.web_support import (
    app_and_client,
    new_client,
    png_bytes,
    run_tool,
    set_key,
    setup_out,
    signup,
)


@pytest.fixture
def out(tmp_path, monkeypatch):
    return setup_out(tmp_path, monkeypatch)


class TestLiveLogCursorAndSanitizer:
    """Ensure LiveLog cursor stays monotonic across buffer rollover."""

    def test_livelog_monotonic_cursor_survives_truncation(self):
        log = LiveLog(cap=50, transform=lambda s: s.replace("SECRET", "[redacted]"))
        log.write("chunk1-SECRET-" * 2)  # 36 chars after transform
        part1, cur1 = log.slice_from(0)
        assert "[redacted]" in part1 and "SECRET" not in part1
        assert log.slice_from(cur1) == ("", cur1)

        # Write enough chunks to exceed cap=50 and evict chunk 1
        log.write("chunk2-" + "A" * 30)
        log.write("chunk3-" + "B" * 30)

        delta, cur2 = log.slice_from(cur1)
        assert cur2 > cur1
        # Even though chunk1 was evicted, cur1 (>= _start_offset or handled cleanly) must include chunk3!
        assert "chunk3-" in delta
        assert log.slice_from(cur2) == ("", cur2)


class TestCooperativeJobCancellation:
    """Verify running jobs can be cooperatively cancelled via POST /jobs/{id}/cancel."""

    def test_cancel_running_generation_job(self, out, tmp_path, monkeypatch):
        started = threading.Event()

        def cancellable_gen(name, num_cards, **kw):
            started.set()
            for _ in range(100):
                check_cancelled()
                time.sleep(0.02)
            return []

        monkeypatch.setattr("ntcdg.generator.generate_deck", cancellable_gen)

        with app_and_client(tmp_path) as (app, c):
            token = signup(c, "alice")
            set_key(app, "alice", "alice-venice-key-1234")

            r = run_tool(c, "create_deck", {"name": "abortme", "cards": 5}, token)
            assert r.status_code == 202
            job_id = r.json()["job_id"]
            assert started.wait(5)

            # Without CSRF -> 403
            assert c.post(f"/jobs/{job_id}/cancel").status_code == 403

            # Other user -> 404
            bob = new_client(app)
            b_tok = signup(bob, "bob")
            assert bob.post(f"/jobs/{job_id}/cancel", headers={"X-CSRF-Token": b_tok}).status_code == 404

            # Owner cancel -> 200 and job transitions to 'cancelled'
            cancel_resp = c.post(f"/jobs/{job_id}/cancel", headers={"X-CSRF-Token": token})
            assert cancel_resp.status_code == 200
            final_status = app.state.ntcdg.jobs.wait(job_id, timeout=10)
            assert final_status == "cancelled"

            view = c.get(f"/jobs/{job_id}").json()
            assert view["status"] == "cancelled"
            assert "Cancelled" in view["error"]


class TestRateLimitersAndExifStripping:
    """Verify bounded rate limiting, EXIF stripping, register_symbols key logic & calibration."""

    def test_login_rate_limiter_evicts_expired_and_enforces_ip_cap(self):
        lim = LoginRateLimiter(max_failures=3, window_seconds=1, ip_max_failures=4)
        for i in range(4):
            lim.record_failure(f"user_{i}", "198.51.100.9")
        # Individual user_99 has 0 failures, but IP hit ip_max_failures=4
        assert lim.retry_after("user_99", "198.51.100.9") >= 1

        time.sleep(1.05)
        assert lim.retry_after("user_0", "198.51.100.9") == 0
        assert lim.retry_after("user_99", "198.51.100.9") == 0
        # Pruned keys are removed from dict
        for i in range(4):
            lim.retry_after(f"user_{i}", "198.51.100.9")
        assert len(lim._failures) == 0

    def test_signup_rate_limit_blocks_flood(self, out, tmp_path):
        with app_and_client(tmp_path) as (app, c):
            app.state.ntcdg.signup_limiter = LoginRateLimiter(max_failures=2, window_seconds=300)
            # Prime session + CSRF
            page = c.get("/signup").text
            import re
            m = re.search(r'name="csrf_token" value="([^"]+)"', page)
            assert m
            csrf = m.group(1)

            for _ in range(2):
                r = c.post(
                    "/signup",
                    data={
                        "username": "x",  # invalid (too short) -> records attempt
                        "password": "short",
                        "password2": "short",
                        "csrf_token": csrf,
                    },
                )
                assert r.status_code == 400

            blocked = c.post(
                "/signup",
                data={
                    "username": "validuser",
                    "password": "goodpassword123",
                    "password2": "goodpassword123",
                    "csrf_token": csrf,
                },
            )
            assert blocked.status_code == 429
            assert "Retry-After" in blocked.headers

    def test_upload_strips_exif_and_transposes_orientation(self, out, tmp_path):
        # Build a 40x80 JPEG with EXIF Orientation=6 (rotate 90 CW -> should become 80x40)
        im = Image.new("RGB", (40, 80), (180, 60, 40))
        exif = im.getexif()
        exif[0x0112] = 6  # Orientation: Rotate 90 CW
        exif[0x010E] = "Sensitive Camera Note"  # ImageDescription
        buf = io.BytesIO()
        im.save(buf, format="JPEG", exif=exif.tobytes())

        with app_and_client(tmp_path) as (_app, c):
            token = signup(c, "alice")
            resp = c.post(
                "/uploads",
                data={"kind": "image"},
                files=[("file", ("phone.jpg", buf.getvalue(), "image/jpeg"))],
                headers={"X-CSRF-Token": token},
            )
            assert resp.status_code == 200
            up = resp.json()["uploads"][0]
            fetched = c.get(up["url"])
            assert fetched.status_code == 200
            with Image.open(io.BytesIO(fetched.content)) as saved:
                assert saved.size == (80, 40)
                saved_exif = saved.getexif()
                assert 0x010E not in saved_exif

    def test_register_symbols_key_requirement_respects_auto_describe(self, out, tmp_path):
        with app_and_client(tmp_path) as (app, c):
            token = signup(c, "alice")
            up = c.post(
                "/uploads",
                data={"kind": "image"},
                files=[("file", ("moon.png", png_bytes(), "image/png"))],
                headers={"X-CSRF-Token": token},
            ).json()["uploads"][0]

            # auto_describe=True with blank description and NO Venice key -> 400 needs_key=True
            r_need = run_tool(
                c,
                "register_symbols",
                {
                    "deck_name": "lunar",
                    "auto_describe": True,
                    "symbols": [{"name": "Moon", "image_path": up["ref"], "description": ""}],
                },
                token,
            )
            assert r_need.status_code == 400
            assert r_need.json().get("needs_key") is True

            # auto_describe=False without a Venice key -> 202 job succeeds!
            r_ok = run_tool(
                c,
                "register_symbols",
                {
                    "deck_name": "lunar",
                    "auto_describe": False,
                    "symbols": [{"name": "Moon", "image_path": up["ref"], "description": ""}],
                },
                token,
            )
            assert r_ok.status_code == 202
            assert app.state.ntcdg.jobs.wait(r_ok.json()["job_id"]) == "done"

    def test_calibration_atomic_write_and_decks_grok_me(self, out):
        results: list[str] = []
        errors: list[Exception] = []

        def worker(offset: tuple[float, float]) -> None:
            try:
                results.append(create_calibration_pdf("letter", "long_edge", offset))
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=((0.0, 0.0),)),
            threading.Thread(target=worker, args=((1.5, -0.5),)),
            threading.Thread(target=worker, args=((-0.8, 0.4),)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 3
        for p in results:
            assert os.path.basename(p) == "CALIBRATION_letter_long_edge.pdf"
            assert CALIBRATION_RE.match(os.path.basename(p))
            with open(p, "rb") as f:
                data = f.read()
            assert data.startswith(b"%PDF-")
            assert b"%%EOF" in data[-64:]
        assert not [n for n in os.listdir(out) if n.startswith(".tmp_cal_")]

        # Verify production domain decks.grok.me works in both path and subdomain modes
        base_path = public.validate_base_url("https://decks.grok.me")
        assert public.build_card_url(base_path, "arcana-x9k2m4", "01-the-fool") == (
            "https://decks.grok.me/c/arcana-x9k2m4/01-the-fool"
        )
        base_sub = public.validate_base_url("https://{deck}.decks.grok.me")
        assert public.build_card_url(base_sub, "arcana-x9k2m4", "01-the-fool") == (
            "https://arcana-x9k2m4.decks.grok.me/c/01-the-fool"
        )
