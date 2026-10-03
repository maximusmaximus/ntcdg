"""Web app: background jobs (mocked generation), SSE, limits, ownership and finalize."""

from __future__ import annotations

import json
import os
import threading

import pytest

pytest.importorskip("fastapi")

from tests.web_support import (
    BASE_URL,
    app_and_client,
    make_deck,
    new_client,
    run_tool,
    set_key,
    setup_out,
    signup,
)


@pytest.fixture
def out(tmp_path, monkeypatch):
    return setup_out(tmp_path, monkeypatch)


@pytest.fixture
def web(out, tmp_path):
    with app_and_client(tmp_path) as (app, client):
        token = signup(client, "alice")
        set_key(app, "alice", "alice-venice-key-0001")
        yield app, client, token


class FakeGenerator:
    """Stands in for ``ntcdg.generator.generate_deck``: no network, real files + events."""

    def __init__(self, gate: threading.Event | None = None):
        self.gate = gate
        self.calls: list[dict] = []

    def __call__(self, name, num_cards, venice_key=None, **kw):
        from PIL import Image

        from ntcdg.config import logger
        from ntcdg.models import Card
        from ntcdg.runtime import current_event_sink
        from ntcdg.storage import deck_images_dir, save_deck

        self.calls.append({"name": name, "num_cards": num_cards, "venice_key": venice_key})
        sink = current_event_sink() or (lambda e: None)
        print(f"Generating {name} with {num_cards} cards")
        logger.info("fake generator log line for %s", name)
        if self.gate is not None:
            assert self.gate.wait(10), "test gate never opened"
        sink({"type": "deck_started", "deck": name, "num_cards": num_cards})
        folder = deck_images_dir(name)
        os.makedirs(folder, exist_ok=True)
        cards = []
        for pos in range(1, num_cards + 1):
            sink({"type": "card_started", "position": pos, "total": num_cards, "title": f"Card {pos}"})
            path = os.path.join(folder, f"{pos:03d}.png")
            Image.new("RGB", (60, 100), (90, 40, pos * 30 % 255)).save(path)
            card = Card(position=pos, title=f"Card {pos}", card_type="Major Arcana", image_path=path,
                        description="d", upright_interpretation="u", reversed_interpretation="r")
            cards.append(card)
            sink({"type": "card_image", "position": pos, "image_path": path})
            sink({"type": "card_done", "position": pos, "card": card.to_dict()})
        save_deck(cards, name)
        sink({"type": "deck_done", "deck": name, "num_cards": num_cards})
        return cards


def _wait(app, job_id, timeout=30):
    return app.state.ntcdg.jobs.wait(job_id, timeout)


class TestJobLifecycle:
    def test_create_deck_job_events_log_and_output(self, web, monkeypatch):
        app, c, token = web
        fake = FakeGenerator()
        monkeypatch.setattr("ntcdg.generator.generate_deck", fake)
        r = run_tool(c, "create_deck", {"name": "stars", "cards": 3, "vibe": "night sky"}, token)
        assert r.status_code == 202, r.text
        data = r.json()
        assert data["mode"] == "job" and data["input"]["name"] == "stars"
        assert _wait(app, data["job_id"]) == "done"

        # The tool got the user's key and the namespaced deck name.
        assert fake.calls == [{"name": "alice__stars", "num_cards": 3, "venice_key": "alice-venice-key-0001"}]

        view = c.get(data["poll_url"]).json()
        assert view["status"] == "done" and view["tool"] == "create_deck" and view["deck"] == "stars"
        types = [e["type"] for e in view["events"]]
        assert types[0] == "deck_started" and types[-1] == "deck_done" and types.count("card_done") == 3
        img_events = [e for e in view["events"] if e["type"] == "card_image"]
        assert img_events[0]["image_url"].startswith("/files/stars/card/1")
        assert "image_path" not in img_events[0]
        assert "Generating stars with 3 cards" in view["log"]
        assert "fake generator log line" in view["log"]
        assert view["output"]["name"] == "stars" and view["output"]["total_cards"] == 3
        body = json.dumps(view)
        assert "alice__" not in body and str(app.state.ntcdg.settings.db_path) not in body
        assert c.get(img_events[0]["image_url"]).status_code == 200

        # incremental polling
        later = c.get(f"{data['poll_url']}?since_event={view['events_total']}&since_log={view['log_total']}")
        assert later.json()["events"] == [] and later.json()["log"] == ""

        # deck pages now work
        assert c.get("/decks/stars").status_code == 200
        assert c.get("/decks/stars/cards/2").status_code == 200
        assert "stars" in c.get("/dashboard").text
        assert c.get(f"/jobs/{data['job_id']}/view").status_code == 200

    def test_sse_stream_delivers_updates_and_done(self, web, monkeypatch):
        app, c, token = web
        monkeypatch.setattr("ntcdg.generator.generate_deck", FakeGenerator())
        data = run_tool(c, "create_deck", {"name": "sse", "cards": 2}, token).json()
        _wait(app, data["job_id"])
        with c.stream("GET", data["events_url"]) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            text = "".join(resp.iter_text())
        assert "event: update" in text and "event: done" in text
        frames = [json.loads(line[len("data: "):]) for line in text.splitlines()
                  if line.startswith("data: ") and line != "data: {}"]
        assert frames[-1]["status"] == "done" and frames[-1]["output"]["total_cards"] == 2
        assert any(e["type"] == "card_done" for f in frames for e in f["events"])

    def test_one_active_generation_per_user(self, web, monkeypatch):
        app, c, token = web
        gate = threading.Event()
        monkeypatch.setattr("ntcdg.generator.generate_deck", FakeGenerator(gate))
        first = run_tool(c, "create_deck", {"name": "one", "cards": 1}, token)
        assert first.status_code == 202
        try:
            second = run_tool(c, "create_deck", {"name": "two", "cards": 1}, token)
            assert second.status_code == 409 and "already have a generation" in second.json()["error"]
            # Quick sync tools still work meanwhile.
            assert run_tool(c, "estimate_cost", {"cards": 3}, token).status_code == 200
            jobs_page = c.get("/jobs").text
            assert "create_deck" in jobs_page
        finally:
            gate.set()
        assert _wait(app, first.json()["job_id"]) == "done"
        third = run_tool(c, "create_deck", {"name": "two", "cards": 1}, token)
        assert third.status_code == 202
        _wait(app, third.json()["job_id"])

    def test_busy_deck_blocks_edits(self, web, monkeypatch):
        from ntcdg.web import tools

        app, c, token = web
        make_deck("alice__busy", 2)
        gate = threading.Event()

        def slow_export(deck_name):
            assert gate.wait(10)
            return {"success": True, "deck": deck_name}

        monkeypatch.setattr(tools.REGISTRY["export_bundle"], "func", slow_export)
        job = run_tool(c, "export_bundle", {"deck_name": "busy"}, token)
        try:
            assert job.status_code == 202, job.text
            r = run_tool(c, "edit_card", {"deck_name": "busy", "card_num": 1, "field": "new_title",
                                          "value": "x"}, token)
            assert r.status_code == 409
            again = run_tool(c, "export_bundle", {"deck_name": "busy"}, token)
            assert again.status_code == 409
            assert "data-busy" in c.get("/decks/busy").text
        finally:
            gate.set()
        assert _wait(app, job.json()["job_id"]) == "done"
        assert run_tool(c, "edit_card", {"deck_name": "busy", "card_num": 1, "field": "new_title",
                                         "value": "x"}, token).status_code == 200

    def test_jobs_are_owner_only(self, web, monkeypatch):
        app, c, token = web
        monkeypatch.setattr("ntcdg.generator.generate_deck", FakeGenerator())
        data = run_tool(c, "create_deck", {"name": "private", "cards": 1}, token).json()
        _wait(app, data["job_id"])
        bob = new_client(app)
        signup(bob, "bob")
        assert bob.get(data["poll_url"]).status_code == 404
        assert bob.get(data["events_url"]).status_code == 404
        assert bob.get(f"/jobs/{data['job_id']}/view").status_code == 404
        assert "private" not in bob.get("/jobs").text

    def test_failed_tool_marks_job_error(self, web, monkeypatch):
        app, c, token = web

        def boom(**kw):
            raise RuntimeError("Venice exploded")

        monkeypatch.setattr("ntcdg.generator.generate_deck", boom)
        data = run_tool(c, "create_deck", {"name": "bad", "cards": 1}, token).json()
        assert _wait(app, data["job_id"]) == "error"
        view = c.get(data["poll_url"]).json()
        assert "Venice exploded" in view["error"]

    def test_running_jobs_marked_interrupted_on_restart(self, out, tmp_path):
        from tests.web_support import login

        with app_and_client(tmp_path) as (app, c):
            signup(c, "alice")
            db = app.state.ntcdg.db
            user = db.get_user_by_username("alice")
            db.insert_job("stuckjob123", user["id"], "create_deck", "x", {}, "running", "2020")
        with app_and_client(tmp_path) as (_app2, c2):
            login(c2, "alice")
            view = c2.get("/jobs/stuckjob123").json()
            assert view["status"] == "interrupted" and "restarted" in view["error"]
            assert c2.get("/jobs/stuckjob123/view").status_code == 200
            with c2.stream("GET", "/jobs/stuckjob123/events") as resp:
                assert "event: done" in "".join(resp.iter_text())


class TestFinalizeViaWeb:
    def test_finalize_produces_duplex_pdf_and_public_links(self, web):
        from ntcdg.storage import load_decks_index

        app, c, token = web
        make_deck("alice__fin", 3)
        r = run_tool(c, "finalize_deck", {"deck_name": "fin"}, token)
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        assert _wait(app, job_id, timeout=120) == "done", c.get(f"/jobs/{job_id}").json()
        view = c.get(f"/jobs/{job_id}").json()
        output = view["output"]
        assert output["success"] is True
        assert output["duplex_pdf"].startswith("/files/fin/artifact/DUPLEX_")
        pdf = c.get(output["duplex_pdf"])
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        assert "attachment" in pdf.headers["content-disposition"]

        meta = load_decks_index()["alice__fin"]
        assert meta["published"] is True and meta["public_base_url"] == BASE_URL
        assert "alice" not in meta["public_slug"] and meta["public_slug"].startswith("fin-")

        links = run_tool(c, "get_public_links", {"deck_name": "fin"}, token).json()["output"]
        assert links["deck_url"] == f"{BASE_URL}/c/{meta['public_slug']}"
        assert links["cards"][0]["url"] == f"{BASE_URL}/c/{meta['public_slug']}/01-card-1"

        page = c.get("/decks/fin/print").text
        assert "DUPLEX_" in page and links["cards"][0]["url"] in page
        qr = c.get("/decks/fin/qr/1.svg")
        assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg")

        public = c.get(f"/c/{meta['public_slug']}/01-card-1")
        assert public.status_code == 200 and "Upright 1" in public.text

    def test_finalize_uses_configured_url_not_request_host(self, web):
        from ntcdg.storage import load_decks_index

        app, c, token = web
        make_deck("alice__host", 1)
        hostile = {"X-CSRF-Token": token, "Host": "attacker.example", "X-Forwarded-Host": "evil.example"}
        r = c.post("/api/tools/finalize_deck", json={"inputs": {"deck_name": "host"}}, headers=hostile)
        assert r.status_code == 202, r.text
        _wait(app, r.json()["job_id"], timeout=120)
        assert load_decks_index()["alice__host"]["public_base_url"] == BASE_URL

    def test_finalize_without_public_url_still_prints(self, out, tmp_path):
        with app_and_client(tmp_path, public_base_url="") as (app, c):
            token = signup(c, "alice")
            make_deck("alice__plain", 2)
            assert "NTCDG_PUBLIC_BASE_URL" in c.get("/decks/plain/print").text
            r = run_tool(c, "finalize_deck", {"deck_name": "plain"}, token)
            assert _wait(app, r.json()["job_id"], timeout=120) == "done"
            out_json = c.get(f"/jobs/{r.json()['job_id']}").json()["output"]
            assert out_json["success"] and out_json["qr"]["enabled"] is False
