"""Web app: accounts, sessions, CSRF, rate limiting, profile and encrypted Venice keys."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from tests.web_support import (
    PASSWORD,
    app_and_client,
    csrf,
    login,
    make_deck,
    new_client,
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
        yield app, client


class TestPublicPages:
    def test_home_and_about(self, web):
        _app, c = web
        home = c.get("/")
        assert home.status_code == 200
        assert "give it away" in home.text
        about = c.get("/about")
        assert about.status_code == 200
        # The give-away philosophy is explained on the about page.
        assert "made to be given away" in about.text
        assert "energy" in about.text and "just for" in about.text

    def test_security_headers(self, web):
        _app, c = web
        r = c.get("/")
        assert "default-src 'self'" in r.headers["content-security-policy"]
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["cache-control"] == "no-store"

    def test_private_pages_redirect_to_login(self, web):
        _app, c = web
        for path in ("/dashboard", "/profile", "/workbench", "/decks/new", "/jobs"):
            r = c.get(path, follow_redirects=False)
            assert r.status_code == 303
            assert r.headers["location"].startswith("/login?next=")

    def test_api_requires_login(self, web):
        _app, c = web
        r = c.post("/api/tools/list_decks", json={"inputs": {}})
        assert r.status_code == 401
        assert r.json()["error"]


class TestSignupLogin:
    def test_signup_login_logout(self, web):
        _app, c = web
        token = signup(c, "alice")
        assert "alice" in c.get("/dashboard").text
        r = c.post("/logout", data={"csrf_token": token}, follow_redirects=False)
        assert r.status_code == 303
        assert c.get("/dashboard", follow_redirects=False).status_code == 303
        r = login(c, "alice")
        assert r.status_code == 303 and r.headers["location"] == "/dashboard"
        assert c.get("/dashboard").status_code == 200

    def test_login_next_is_local_only(self, web):
        _app, c = web
        signup(c, "alice")
        c.cookies.clear()
        token = csrf(c, "/login")
        r = c.post("/login", data={"username": "alice", "password": PASSWORD, "csrf_token": token,
                                   "next": "//evil.example.com/x"}, follow_redirects=False)
        assert r.headers["location"] == "/dashboard"

    def test_duplicate_username(self, web):
        app, c = web
        signup(c, "alice")
        other = new_client(app)
        token = csrf(other, "/signup")
        r = other.post("/signup", data={"username": "Alice", "password": PASSWORD, "password2": PASSWORD,
                                        "csrf_token": token})
        assert r.status_code == 400
        assert "taken" in r.text

    @pytest.mark.parametrize("username", ["a", "admin", "bad name", "x__y", "trailing_", "UPPER!"])
    def test_invalid_usernames(self, web, username):
        _app, c = web
        token = csrf(c, "/signup")
        r = c.post("/signup", data={"username": username, "password": PASSWORD, "password2": PASSWORD,
                                    "csrf_token": token})
        assert r.status_code == 400

    def test_short_and_mismatched_passwords(self, web):
        _app, c = web
        token = csrf(c, "/signup")
        r = c.post("/signup", data={"username": "bob", "password": "short", "password2": "short",
                                    "csrf_token": token})
        assert r.status_code == 400 and "at least" in r.text
        r = c.post("/signup", data={"username": "bob", "password": PASSWORD, "password2": PASSWORD + "x",
                                    "csrf_token": token})
        assert r.status_code == 400 and "do not match" in r.text

    def test_bad_password(self, web):
        _app, c = web
        signup(c, "alice")
        c.cookies.clear()
        r = login(c, "alice", "wrong password!")
        assert r.status_code == 401
        assert "Invalid username or password" in r.text
        r = login(c, "nobody", "wrong password!")
        assert r.status_code == 401

    def test_password_is_hashed(self, web):
        app, c = web
        signup(c, "alice")
        row = app.state.ntcdg.db.get_user_by_username("alice")
        assert row["password_hash"].startswith("scrypt$")
        assert PASSWORD not in row["password_hash"]


class TestCsrf:
    def test_form_without_token_rejected(self, web):
        _app, c = web
        csrf(c, "/signup")
        r = c.post("/signup", data={"username": "eve", "password": PASSWORD, "password2": PASSWORD})
        assert r.status_code == 403

    def test_api_without_or_with_wrong_header_rejected(self, web):
        _app, c = web
        signup(c, "alice")
        r = c.post("/api/tools/list_decks", json={"inputs": {}})
        assert r.status_code == 403
        r = c.post("/api/tools/list_decks", json={"inputs": {}}, headers={"X-CSRF-Token": "nope"})
        assert r.status_code == 403

    def test_logout_requires_token(self, web):
        _app, c = web
        signup(c, "alice")
        assert c.post("/logout", data={}).status_code == 403
        assert c.get("/dashboard", follow_redirects=False).status_code == 200


class TestRateLimit:
    def test_login_rate_limited_after_failures(self, out, tmp_path):
        with app_and_client(tmp_path, login_max_failures=3) as (_app, c):
            signup(c, "alice")
            c.cookies.clear()
            for _ in range(3):
                assert login(c, "alice", "wrong password!").status_code == 401
            r = login(c, "alice", PASSWORD)  # even the right password is refused now
            assert r.status_code == 429
            assert int(r.headers["retry-after"]) > 0


class TestProfile:
    def test_edit_profile(self, web):
        _app, c = web
        token = signup(c, "alice")
        r = c.post("/profile", data={"display_name": "Alice Moon", "bio": "I draw cats",
                                     "csrf_token": token}, follow_redirects=True)
        assert r.status_code == 200
        assert "Alice Moon" in r.text and "I draw cats" in r.text

    def test_key_encrypted_masked_removed(self, web):
        app, c = web
        token = signup(c, "alice")
        secret_key = "vk-SUPERSECRET-abcd9876"
        r = c.post("/profile/key", data={"venice_key": secret_key, "csrf_token": token},
                   follow_redirects=True)
        assert r.status_code == 200
        row = app.state.ntcdg.db.get_user_by_username("alice")
        assert row["venice_key_enc"] and secret_key not in row["venice_key_enc"]
        assert row["venice_key_last4"] == "9876"
        assert app.state.ntcdg.keybox.decrypt(row["venice_key_enc"]) == secret_key
        page = c.get("/profile").text
        assert "9876" in page and secret_key not in page and "SUPERSECRET" not in page
        # Removing the key
        token = csrf(c, "/profile")
        c.post("/profile/key/delete", data={"csrf_token": token})
        row = app.state.ntcdg.db.get_user_by_username("alice")
        assert not row["venice_key_enc"] and not row["venice_key_last4"]

    def test_key_from_other_secret_is_undecryptable(self, out, tmp_path):
        with app_and_client(tmp_path) as (app, c):
            signup(c, "alice")
            set_key(app, "alice")
        with app_and_client(tmp_path, secret="t" * 32) as (app2, c2):
            assert login(c2, "alice").status_code == 303
            assert "can no longer be decrypted" in c2.get("/profile").text
            row = app2.state.ntcdg.db.get_user_by_username("alice")
            assert app2.state.ntcdg.keybox.decrypt(row["venice_key_enc"]) is None

    def test_change_password_signs_out_other_sessions(self, web):
        app, c = web
        token = signup(c, "alice")
        other = new_client(app)
        assert login(other, "alice").status_code == 303
        new_pw = "a brand new passphrase"
        r = c.post("/profile/password", data={"current_password": PASSWORD, "new_password": new_pw,
                                              "new_password2": new_pw, "csrf_token": token},
                   follow_redirects=False)
        assert r.status_code == 303
        assert c.get("/dashboard", follow_redirects=False).status_code == 200
        assert other.get("/dashboard", follow_redirects=False).status_code == 303
        c.cookies.clear()
        assert login(c, "alice", PASSWORD).status_code == 401
        assert login(c, "alice", new_pw).status_code == 303

    def test_delete_account_removes_decks(self, web):
        from ntcdg.storage import deck_exists

        app, c = web
        token = signup(c, "alice")
        make_deck("alice__mine", 2)
        bob = new_client(app)
        signup(bob, "bob")
        make_deck("bob__his", 2)
        # wrong confirmation keeps everything
        c.post("/profile/delete", data={"confirm_username": "alice", "password": "nope nope",
                                        "csrf_token": token})
        assert deck_exists("alice__mine")
        token = csrf(c, "/profile")
        r = c.post("/profile/delete", data={"confirm_username": "alice", "password": PASSWORD,
                                            "csrf_token": token}, follow_redirects=False)
        assert r.status_code == 303
        assert not deck_exists("alice__mine")
        assert deck_exists("bob__his")
        assert app.state.ntcdg.db.get_user_by_username("alice") is None
        assert c.get("/dashboard", follow_redirects=False).status_code == 303
