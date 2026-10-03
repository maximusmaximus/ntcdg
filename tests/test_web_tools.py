"""Web app: tool registry, input/output, per-user isolation, path safety, uploads and keys."""

from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("fastapi")

from tests.web_support import (
    app_and_client,
    make_deck,
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


@pytest.fixture
def web(out, tmp_path):
    with app_and_client(tmp_path) as (app, client):
        token = signup(client, "alice")
        yield app, client, token


def _upload(client, token, data, name="art.png", kind="image"):
    files = [("file", (name, data, "application/octet-stream"))]
    return client.post("/uploads", data={"kind": kind}, files=files, headers={"X-CSRF-Token": token})


# ==================== REGISTRY ====================

class TestRegistry:
    def test_every_mcp_tool_is_offered_or_excluded_with_reason(self):
        from ntcdg.web import tools

        discovered = tools.discover_mcp_tools()
        assert len(discovered) >= 25
        for name in discovered:
            assert name in tools.REGISTRY or name in tools.EXCLUDED_TOOLS, f"{name} missing from web registry"
        for name, why in tools.EXCLUDED_TOOLS.items():
            assert name in discovered and why.strip(), name
        assert set(tools.REGISTRY) <= set(discovered)

    def test_classification_sets_reference_real_tools(self):
        from ntcdg.web import tools

        for group in (tools.JOB_TOOLS, tools.GENERATION_TOOLS, tools.KEY_TOOLS, set(tools.WEB_NOTES)):
            assert set(group) <= set(tools.REGISTRY), group - set(tools.REGISTRY)
        assert tools.GENERATION_TOOLS <= tools.JOB_TOOLS

    def test_specs_describe_params(self):
        from ntcdg.web import tools

        spec = tools.REGISTRY["create_deck"]
        kinds = {p.name: p.kind for p in spec.params}
        assert kinds["name"] == "new_deck" and kinds["cards"] == "int"
        assert kinds["symbols_file"] == "symbols_file"
        assert spec.mode == "job" and spec.needs_key
        fin = {p.name: p.kind for p in tools.REGISTRY["finalize_deck"].params}
        assert fin["public_base_url"] == "hidden" and fin["rebase_url"] == "hidden"
        assert tools.REGISTRY["delete_deck"].params[-1].name == "confirm"

    def test_workbench_renders_every_tool(self, web):
        from ntcdg.web import tools

        _app, c, _ = web
        page = c.get("/workbench").text
        for name in tools.REGISTRY:
            assert f'data-tool="{name}"' in page, name

    def test_api_tools_listing(self, web):
        _app, c, _ = web
        data = c.get("/api/tools").json()
        names = {t["name"] for t in data["tools"]}
        assert {"create_deck", "finalize_deck", "get_card_by_slug"} <= names
        fin = next(t for t in data["tools"] if t["name"] == "finalize_deck")
        assert "public_base_url" not in {p["name"] for p in fin["params"]}


# ==================== SYNC TOOL CALLS ====================

class TestSyncCalls:
    def test_sync_call_returns_input_and_output(self, web):
        _app, c, token = web
        r = run_tool(c, "estimate_cost", {"cards": 22, "previews": 0}, token)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["mode"] == "sync" and data["tool"] == "estimate_cost"
        assert data["input"]["cards"] == 22 and data["input"]["previews"] == 0
        assert isinstance(data["output"], dict) and data["output"]
        assert "console" in data

    def test_unknown_tool_and_unknown_input(self, web):
        _app, c, token = web
        assert run_tool(c, "rm_rf", {}, token).status_code == 404
        r = run_tool(c, "estimate_cost", {"cards": 3, "surprise": 1}, token)
        assert r.status_code == 400 and "surprise" in r.json()["error"]

    def test_input_validation(self, web):
        _app, c, token = web
        r = run_tool(c, "estimate_cost", {"cards": 100000}, token)
        assert r.status_code == 400 and "at most" in r.json()["error"]
        r = run_tool(c, "estimate_cost", {"cards": "many"}, token)
        assert r.status_code == 400
        r = run_tool(c, "finalize_deck", {"deck_name": "x", "sheet_size": "napkin"}, token)
        assert r.status_code == 400

    def test_server_forced_params_cannot_be_supplied(self, web):
        _app, c, token = web
        make_deck("alice__fin", 1)
        evil = {"deck_name": "fin", "public_base_url": "https://evil.example"}
        r = run_tool(c, "finalize_deck", evil, token)
        assert r.status_code == 400 and "public_base_url" in r.json()["error"]

    def test_deck_tool_output_uses_short_names_and_urls(self, web):
        _app, c, token = web
        make_deck("alice__moon", 2)
        r = run_tool(c, "get_card_details", {"deck_name": "moon", "card_num": 1}, token)
        assert r.status_code == 200, r.text
        out = r.json()["output"]
        assert out["title"] == "Card 1"
        assert out["image_path"] == "/files/moon/card/1"
        body = json.dumps(r.json())
        assert "alice__" not in body
        assert os.path.abspath(".") not in body

    def test_edit_and_delete_via_tools(self, web):
        from ntcdg.storage import deck_exists, load_deck

        _app, c, token = web
        make_deck("alice__ed", 2)
        r = run_tool(c, "edit_card", {"deck_name": "ed", "card_num": 2, "field": "new_title",
                                      "value": "The Lantern"}, token)
        assert r.status_code == 200 and r.json()["output"]["success"], r.text
        assert any(card.display_title() == "The Lantern" for card in load_deck("alice__ed"))
        r = run_tool(c, "delete_deck", {"deck_name": "ed", "confirm": "nope"}, token)
        assert r.status_code == 400 and deck_exists("alice__ed")
        r = run_tool(c, "delete_deck", {"deck_name": "ed", "confirm": "ed"}, token)
        assert r.status_code == 200 and not deck_exists("alice__ed")


# ==================== NAMESPACING / ISOLATION ====================

class TestIsolation:
    def test_decks_are_namespaced_and_isolated(self, web):
        app, alice, a_token = web
        bob = new_client(app)
        b_token = signup(bob, "bob")
        make_deck("alice__shared-name", 2)
        make_deck("bob__shared-name", 3)

        a = run_tool(alice, "list_decks", {}, a_token).json()["output"]
        b = run_tool(bob, "list_decks", {}, b_token).json()["output"]
        assert a["count"] == 1 and b["count"] == 1
        assert "bob" not in json.dumps(a) and "alice" not in json.dumps(b)

        info = run_tool(bob, "deck_info", {"deck_name": "shared-name"}, b_token).json()["output"]
        assert info["total_cards"] == 3

    def test_cross_user_access_is_denied(self, web):
        app, alice, _a_token = web
        bob = new_client(app)
        b_token = signup(bob, "bob")
        make_deck("alice__secret", 2)
        # tools
        r = run_tool(bob, "deck_info", {"deck_name": "secret"}, b_token)
        assert r.status_code == 400 and "not found" in r.json()["error"]
        r = run_tool(bob, "deck_info", {"deck_name": "alice__secret"}, b_token)
        assert r.status_code == 400
        r = run_tool(bob, "delete_deck", {"deck_name": "secret", "confirm": "secret"}, b_token)
        assert r.status_code == 400
        r = run_tool(bob, "clone_deck", {"source": "secret", "new_name": "mine"}, b_token)
        assert r.status_code == 400
        # pages and files
        assert bob.get("/decks/secret").status_code == 404
        assert bob.get("/decks/secret/print").status_code == 404
        assert bob.get("/files/secret/card/1").status_code == 404
        assert alice.get("/files/secret/card/1").status_code == 200
        r = bob.post("/decks/secret/delete", data={"confirm": "secret", "csrf_token": b_token})
        assert r.status_code == 404

    def test_uploads_are_private(self, web):
        app, alice, a_token = web
        up = _upload(alice, a_token, png_bytes()).json()["uploads"][0]
        assert alice.get(up["url"]).status_code == 200
        bob = new_client(app)
        b_token = signup(bob, "bob")
        assert bob.get(up["url"]).status_code == 404
        r = run_tool(bob, "describe_symbols", {"image_paths": [up["ref"]]}, b_token)
        assert r.status_code == 400  # not bob's upload (or no key) -- never reaches Venice

    def test_reserved_usernames_cannot_collide_with_internal_folders(self):
        from ntcdg.web import namespace as ns

        for bad in ("admin", "files", "a__b", "x_"):
            with pytest.raises(ns.NamespaceError):
                ns.validate_username(bad)
        assert ns.owns("al", "al__deck") and not ns.owns("al", "al_x__deck")


# ==================== PATH SAFETY ====================

class TestPathSafety:
    @pytest.mark.parametrize("ref", [
        "/etc/passwd", "../../etc/passwd", "..\\..\\windows\\win.ini", "C:\\Windows\\win.ini",
        "upload:../../etc/passwd", "upload:" + "a" * 50, "symbols:../../x", "symbols:nope",
    ])
    def test_symbols_file_rejects_server_paths(self, web, ref):
        app, c, token = web
        set_key(app, "alice")
        r = run_tool(c, "match_symbols", {"symbols_file": ref}, token)
        assert r.status_code == 400, r.text
        assert "passwd" not in json.dumps(r.json().get("output", ""))

    @pytest.mark.parametrize("ref", ["/etc/passwd", "../x.png", "upload:zzzzzzzzzzzz"])
    def test_symbol_image_paths_must_be_own_uploads(self, web, ref):
        _app, c, token = web
        r = run_tool(c, "register_symbols", {"deck_name": "mine", "auto_describe": False,
                                             "symbols": [{"name": "Moon", "image_path": ref}]}, token)
        assert r.status_code == 400

    @pytest.mark.parametrize("name", ["../../etc/passwd", "..", "a/b", "x__y", ""])
    def test_deck_names_validated(self, web, name):
        _app, c, token = web
        r = run_tool(c, "deck_info", {"deck_name": name}, token)
        assert r.status_code == 400

    @pytest.mark.parametrize("path", [
        "/files/..%2F..%2Fetc/passwd", "/files/_previews/..%2Fsecret.png", "/files/_calibration/passwd",
        "/files/_symbols/x/..%2F..%2Fweb.sqlite3", "/files/x/artifact/..%2F..%2Fweb.sqlite3",
        "/files/x/card/abc", "/uploads/..%2F..%2Fetc%2Fpasswd",
    ])
    def test_file_routes_reject_traversal(self, web, path):
        _app, c, _ = web
        make_deck("alice__x", 1)
        assert c.get(path).status_code == 404

    def test_upload_validation(self, web):
        _app, c, token = web
        assert _upload(c, token, b"not an image at all", "evil.png").status_code == 400
        assert _upload(c, token, b"").status_code == 400
        ok = _upload(c, token, png_bytes(fmt="JPEG"), "photo.jpg")
        assert ok.status_code == 200 and ok.json()["uploads"][0]["ref"].startswith("upload:")
        # symbols.json: only own uploads survive as image references
        img = _upload(c, token, png_bytes()).json()["uploads"][0]
        manifest = {"symbols": [{"name": "Sun", "image": img["ref"]},
                                {"name": "Key", "image": "/etc/passwd"}]}
        r = _upload(c, token, json.dumps(manifest).encode(), "symbols.json", kind="symbols_json")
        assert r.status_code == 200
        res = r.json()["uploads"][0]
        assert res["symbols"] == 2 and res["dropped_image_refs"] == 1
        # an upload without CSRF is refused
        r = c.post("/uploads", data={"kind": "image"}, files=[("file", ("a.png", png_bytes(), "image/png"))])
        assert r.status_code == 403

    def test_upload_size_limit(self, out, tmp_path):
        with app_and_client(tmp_path, max_upload_mb=1) as (_app, c):
            token = signup(c, "alice")
            big = b"\x89PNG" + b"0" * (1024 * 1024 + 10)
            r = _upload(c, token, big)
            assert r.status_code == 400 and "too large" in json.dumps(r.json())


# ==================== VENICE KEYS ====================

class TestVeniceKeys:
    def test_keyless_user_cannot_use_server_env_key(self, web, monkeypatch):
        _app, c, token = web
        monkeypatch.setenv("VENICE_API_KEY", "SERVER-OWNER-KEY")
        called = []
        monkeypatch.setattr("ntcdg.generator.generate_deck", lambda **kw: called.append(kw))
        for tool, inputs in [
            ("create_deck", {"name": "freebie", "cards": 1}),
            ("suggest_deck", {"user_description": "cats"}),
            ("preview_style", {"name": "freebie"}),
        ]:
            r = run_tool(c, tool, inputs, token)
            assert r.status_code == 400, (tool, r.text)
            assert r.json()["needs_key"] is True
        assert called == []

    def test_strict_scope_blocks_env_fallback_inside_tools(self, web, monkeypatch):
        """Even if a tool slipped past the API check, the runtime refuses the env key."""
        from ntcdg.web import tools

        app, _c, _token = web
        monkeypatch.setenv("VENICE_API_KEY", "SERVER-OWNER-KEY")
        called = []
        monkeypatch.setattr("ntcdg.generator.generate_deck", lambda **kw: called.append(kw))
        st = app.state.ntcdg
        user = st.db.get_user_by_username("alice")
        ctx = tools.ToolContext(db=st.db, user=user, settings=st.settings)
        call = tools.prepare_call(tools.REGISTRY["create_deck"], {"name": "sneaky", "cards": 1}, ctx)
        result = tools.execute(call, ctx, None)
        assert result["success"] is False and "No Venice API key" in result["error"]
        assert called == []

    def test_users_key_is_used(self, web, monkeypatch):
        from ntcdg.runtime import get_venice_key
        from ntcdg.web import tools

        app, _c, _token = web
        monkeypatch.setenv("VENICE_API_KEY", "SERVER-OWNER-KEY")
        st = app.state.ntcdg
        user = st.db.get_user_by_username("alice")
        ctx = tools.ToolContext(db=st.db, user=user, settings=st.settings)
        seen = []
        monkeypatch.setattr("ntcdg.generator.generate_deck", lambda **kw: seen.append(get_venice_key()))
        call = tools.prepare_call(tools.REGISTRY["create_deck"], {"name": "mine", "cards": 1}, ctx)
        tools.execute(call, ctx, "user-own-key-5678")
        assert seen == ["user-own-key-5678"]
