"""HTML pages: landing/about, accounts & profile, dashboard, deck pages, workbench."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from .. import mcp_server, public
from ..storage import load_deck, load_decks_index
from . import auth, tools
from . import files as webfiles
from . import namespace as ns
from .deps import (
    current_user,
    render,
    require_user,
    safe_next,
    state,
)
from .public_views import deck_page, subdomain_slug

router = APIRouter()


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ==================== PUBLIC PAGES ====================

@router.get("/")
def home(request: Request):
    sub = subdomain_slug(request)
    if sub:
        return deck_page(request, sub, on_subdomain=True)
    return render(request, "index.html")


@router.get("/about")
def about(request: Request):
    return render(request, "about.html")


@router.get("/healthz")
def healthz():
    return {"ok": True}


# ==================== ACCOUNTS ====================

@router.get("/signup")
def signup_form(request: Request):
    if current_user(request):
        return _redirect("/dashboard")
    return render(request, "signup.html", form={})


@router.post("/signup")
async def signup(request: Request):
    form = await auth.check_csrf_form(request)
    st = state(request)
    username = str(form.get("username") or "").strip().lower()
    display_name = str(form.get("display_name") or "").strip()[:80]
    password = str(form.get("password") or "")
    password2 = str(form.get("password2") or "")
    error = ""
    try:
        username = ns.validate_username(username)
        auth.validate_password(password)
        if password != password2:
            raise ValueError("The two passwords do not match.")
    except ValueError as e:
        error = str(e)
    if not error and st.db.get_user_by_username(username):
        error = "That username is taken."
    if error:
        return render(request, "signup.html", status_code=400, error=error,
                      form={"username": username, "display_name": display_name})
    try:
        uid = st.db.create_user(username, auth.hash_password(password), display_name)
    except Exception:  # unique race
        return render(request, "signup.html", status_code=400, error="That username is taken.",
                      form={"username": username, "display_name": display_name})
    auth.login_session(request, st.db.get_user(uid))
    auth.flash(request, "Welcome! Add your Venice API key on your profile to start generating.", "ok")
    return _redirect("/dashboard")


@router.get("/login")
def login_form(request: Request, next: str = ""):
    if current_user(request):
        return _redirect(safe_next(next))
    return render(request, "login.html", next=safe_next(next) if next else "", form={})


@router.post("/login")
async def login(request: Request):
    form = await auth.check_csrf_form(request)
    st = state(request)
    username = str(form.get("username") or "").strip().lower()[:64]
    password = str(form.get("password") or "")
    nxt = safe_next(str(form.get("next") or ""))
    ip = _client_ip(request)
    wait = st.limiter.retry_after(username, ip)
    if wait:
        resp = render(request, "login.html", status_code=429, next=nxt, form={"username": username},
                      error=f"Too many failed attempts. Try again in {wait} seconds.")
        resp.headers["Retry-After"] = str(wait)
        return resp
    user = st.db.get_user_by_username(username) if username else None
    if not auth.verify_password_or_dummy(password, user["password_hash"] if user else None):
        st.limiter.record_failure(username, ip)
        return render(request, "login.html", status_code=401, next=nxt, form={"username": username},
                      error="Invalid username or password.")
    st.limiter.reset(username, ip)
    auth.login_session(request, user)
    return _redirect(nxt)


@router.post("/logout")
async def logout(request: Request):
    await auth.check_csrf_form(request)
    auth.logout_session(request)
    return _redirect("/")


# ==================== PROFILE ====================

@router.get("/profile")
def profile(request: Request):
    user = require_user(request)
    st = state(request)
    key_state = "none"
    if user.get("venice_key_enc"):
        key_state = "ok" if st.keybox.decrypt(user["venice_key_enc"]) else "undecryptable"
    return render(request, "profile.html", key_state=key_state,
                  key_last4=user.get("venice_key_last4") or "")


@router.post("/profile")
async def profile_update(request: Request):
    form = await auth.check_csrf_form(request)
    user = require_user(request)
    display_name = str(form.get("display_name") or "").strip()[:80] or user["username"]
    bio = str(form.get("bio") or "").strip()[:2000]
    state(request).db.update_profile(user["id"], display_name, bio)
    auth.flash(request, "Profile saved.", "ok")
    return _redirect("/profile")


@router.post("/profile/key")
async def profile_set_key(request: Request):
    form = await auth.check_csrf_form(request)
    user = require_user(request)
    st = state(request)
    try:
        key = auth.validate_venice_key(str(form.get("venice_key") or ""))
    except ValueError as e:
        auth.flash(request, str(e), "error")
        return _redirect("/profile")
    st.db.set_venice_key(user["id"], st.keybox.encrypt(key), key[-4:])
    auth.flash(request, "Venice API key saved (encrypted).", "ok")
    return _redirect("/profile")


@router.post("/profile/key/delete")
async def profile_delete_key(request: Request):
    await auth.check_csrf_form(request)
    user = require_user(request)
    state(request).db.set_venice_key(user["id"], "", "")
    auth.flash(request, "Venice API key removed.", "ok")
    return _redirect("/profile")


@router.post("/profile/password")
async def profile_password(request: Request):
    form = await auth.check_csrf_form(request)
    user = require_user(request)
    st = state(request)
    current = str(form.get("current_password") or "")
    new = str(form.get("new_password") or "")
    new2 = str(form.get("new_password2") or "")
    if not auth.verify_password(current, user["password_hash"]):
        auth.flash(request, "Current password is incorrect.", "error")
        return _redirect("/profile")
    try:
        auth.validate_password(new)
        if new != new2:
            raise ValueError("The two new passwords do not match.")
    except ValueError as e:
        auth.flash(request, str(e), "error")
        return _redirect("/profile")
    st.db.set_password(user["id"], auth.hash_password(new))
    auth.login_session(request, st.db.get_user(user["id"]))
    auth.flash(request, "Password changed. Other sessions were signed out.", "ok")
    return _redirect("/profile")


def delete_user_data(st: Any, user: dict[str, Any]) -> int:
    """Delete every deck, symbol folder, preview and upload owned by ``user``."""
    import shutil

    from ..storage import delete_deck

    count = 0
    for _short, internal, _meta in ns.user_decks(user["username"]):
        if delete_deck(internal, confirm=False):
            count += 1
    pre = ns.prefix(user["username"])
    # Index entries without a deck JSON (e.g. half-created decks)
    from ..storage import _INDEX_LOCK, save_decks_index
    with _INDEX_LOCK:
        index = load_decks_index()
        stale = [k for k in index if ns.owns(user["username"], k)]
        if stale:
            for k in stale:
                index.pop(k, None)
            save_decks_index(index)
    sroot = webfiles.symbols_root()
    if os.path.isdir(sroot):
        for entry in os.listdir(sroot):
            if ns.owns(user["username"], entry):
                shutil.rmtree(os.path.join(sroot, entry), ignore_errors=True)
    pdir = webfiles.previews_dir()
    if os.path.isdir(pdir):
        for fname in os.listdir(pdir):
            full = os.path.join(pdir, fname)
            if fname.startswith(pre) and os.path.isfile(full):
                os.remove(full)
        raw = os.path.join(pdir, "_raw")
        if os.path.isdir(raw):
            for entry in os.listdir(raw):
                if ns.owns(user["username"], entry):
                    shutil.rmtree(os.path.join(raw, entry), ignore_errors=True)
    shutil.rmtree(webfiles.uploads_dir(user["id"]), ignore_errors=True)
    return count


@router.post("/profile/delete")
async def profile_delete(request: Request):
    form = await auth.check_csrf_form(request)
    user = require_user(request)
    st = state(request)
    if str(form.get("confirm_username") or "") != user["username"] or not auth.verify_password(
        str(form.get("password") or ""), user["password_hash"],
    ):
        auth.flash(request, "To delete your account, type your username and current password.", "error")
        return _redirect("/profile")
    if st.jobs.active_jobs(user["id"]):
        auth.flash(request, "Wait for your running jobs to finish before deleting your account.", "error")
        return _redirect("/profile")
    delete_user_data(st, user)
    st.db.delete_user(user["id"])
    auth.logout_session(request)
    auth.flash(request, "Your account and all of your decks were deleted.", "ok")
    return _redirect("/")


# ==================== DASHBOARD & DECKS ====================

def deck_cards(username: str, short: str, internal: str) -> list[dict[str, Any]]:
    cards = []
    for c in sorted(load_deck(internal), key=lambda c: c.position or 0):
        has_img = bool(c.image_path and os.path.exists(str(c.image_path)))
        cards.append({
            "position": c.position, "title": c.display_title(), "original_title": c.title,
            "card_type": c.card_type or "", "suit": c.suit or "",
            "has_image": has_img,
            "image_url": f"/files/{short}/card/{c.position}" if has_img else "",
            "has_analysis": bool(c.description and not c.venice_error),
            "has_meanings": bool(c.upright_interpretation and c.reversed_interpretation),
            "error": c.venice_error or c.image_error or "",
        })
    return cards


@router.get("/dashboard")
def dashboard(request: Request):
    user = require_user(request)
    st = state(request)
    decks = []
    for short, internal, meta in ns.user_decks(user["username"]):
        cards = deck_cards(user["username"], short, internal)
        cover = next((c["image_url"] for c in cards if c["has_image"]), "")
        decks.append({
            "name": short, "cards": len(cards), "cover": cover,
            "images": sum(1 for c in cards if c["has_image"]),
            "vibe": meta.get("vibe", ""), "published": bool(meta.get("published")),
            "last_modified": (meta.get("last_modified") or "")[:16].replace("T", " "),
        })
    jobs = st.jobs.list_jobs(user["id"], limit=10)
    return render(request, "dashboard.html", decks=decks, jobs=jobs)


def form_ctx(st: Any, user: dict[str, Any]) -> dict[str, Any]:
    """Context every page with tool forms needs (decks, uploads, symbol manifests)."""
    return {
        "decks": [d[0] for d in ns.user_decks(user["username"])],
        "uploads": st.db.list_uploads(user["id"], "image"),
        "json_uploads": st.db.list_uploads(user["id"], "symbols_json"),
        "manifests": webfiles.list_symbol_manifests(user["username"]),
    }


@router.get("/decks/new")
def deck_new(request: Request):
    user = require_user(request)
    st = state(request)
    return render(request, "deck_new.html", **form_ctx(st, user))


def _owned_or_404(user: dict[str, Any], short: str) -> str:
    try:
        return ns.owned_deck(user["username"], short)
    except ns.NamespaceError:
        raise HTTPException(status_code=404, detail="Deck not found") from None


@router.get("/decks/{short}")
def deck_detail(request: Request, short: str):
    user = require_user(request)
    st = state(request)
    internal = _owned_or_404(user, short)
    sanitizer = webfiles.Sanitizer(st.db, user)
    meta = load_decks_index().get(internal, {})
    summary = sanitizer.value(mcp_server._deck_summary(internal))
    cards = deck_cards(user["username"], short, internal)
    usage = sanitizer.scrub(meta.get("usage") or {})
    busy = st.jobs.deck_busy(user["id"], internal)
    back_url = "/files/" + short + "/back/back.png" if meta.get("back_image") and os.path.exists(
        str(meta.get("back_image"))) else ""
    links = public.public_links(internal)
    return render(
        request, "deck.html", deck=short, summary=summary, cards=cards, meta=meta, usage=usage,
        busy=busy.summary() if busy else None, back_url=back_url, links=links, **form_ctx(st, user),
    )


@router.get("/decks/{short}/cards/{position}")
def card_detail(request: Request, short: str, position: int):
    user = require_user(request)
    st = state(request)
    internal = _owned_or_404(user, short)
    details = mcp_server.get_card_details(internal, position)
    if "error" in details:
        raise HTTPException(status_code=404, detail="Card not found")
    sanitizer = webfiles.Sanitizer(st.db, user)
    details = sanitizer.value(details)
    details["image_url"] = f"/files/{short}/card/{position}" if details.get("has_image") else ""
    details.pop("image_path", None)
    positions = [c.position for c in sorted(load_deck(internal), key=lambda c: c.position or 0)]
    idx = positions.index(position) if position in positions else 0
    prev_pos = positions[idx - 1] if positions else None
    next_pos = positions[(idx + 1) % len(positions)] if positions else None
    links = public.public_links(internal)
    public_url = ""
    if links.get("enabled"):
        public_url = next((c["url"] for c in links["cards"] if c["position"] == position), "")
    return render(request, "card_edit.html", deck=short, card=details, prev_pos=prev_pos,
                  next_pos=next_pos, public_url=public_url, **form_ctx(st, user))


@router.get("/decks/{short}/print")
def deck_print(request: Request, short: str):
    user = require_user(request)
    st = state(request)
    internal = _owned_or_404(user, short)
    from ..storage import deck_artifact_files

    artifacts = []
    for path in deck_artifact_files(internal, include_bundle=True):
        suffix = os.path.basename(path)[len(internal) + 1:]
        kind = suffix.split("_", 1)[0].split(".", 1)[0]
        artifacts.append({
            "name": f"{short}_{suffix}", "kind": kind, "url": f"/files/{short}/artifact/{suffix}",
            "size_kb": max(1, os.path.getsize(path) // 1024),
        })
    links = public.public_links(internal)
    sanitizer = webfiles.Sanitizer(st.db, user)
    return render(request, "print.html", deck=short, artifacts=artifacts, links=links,
                  summary=sanitizer.value(mcp_server._deck_summary(internal)), **form_ctx(st, user))


@router.get("/decks/{short}/qr/{position}.svg")
def deck_qr(request: Request, short: str, position: int):
    user = require_user(request)
    internal = _owned_or_404(user, short)
    links = public.public_links(internal)
    url = next((c["url"] for c in links.get("cards", []) if c["position"] == position), "") \
        if links.get("enabled") else ""
    if not url:
        raise HTTPException(status_code=404, detail="Deck has no public links yet")
    return Response(webfiles.qr_svg(url), media_type="image/svg+xml",
                    headers={"Cache-Control": "private, max-age=300"})


@router.post("/decks/{short}/delete")
async def deck_delete(request: Request, short: str):
    form = await auth.check_csrf_form(request)
    user = require_user(request)
    st = state(request)
    internal = _owned_or_404(user, short)
    if str(form.get("confirm") or "") != short:
        auth.flash(request, "Type the deck name exactly to confirm deletion.", "error")
        return _redirect(f"/decks/{short}")
    if st.jobs.deck_busy(user["id"], internal):
        auth.flash(request, "This deck is busy with a running job.", "error")
        return _redirect(f"/decks/{short}")
    mcp_server.delete_deck(internal)
    auth.flash(request, f"Deck '{short}' deleted.", "ok")
    return _redirect("/dashboard")


# ==================== WORKBENCH & JOBS ====================

@router.get("/workbench")
def workbench(request: Request):
    user = require_user(request)
    st = state(request)
    return render(
        request, "workbench.html",
        groups=tools.registry_by_category(),
        decks=[d[0] for d in ns.user_decks(user["username"])],
        uploads=st.db.list_uploads(user["id"], "image"),
        json_uploads=st.db.list_uploads(user["id"], "symbols_json"),
        manifests=webfiles.list_symbol_manifests(user["username"]),
        excluded=tools.EXCLUDED_TOOLS,
    )


@router.get("/jobs")
def jobs_page(request: Request):
    user = require_user(request)
    return render(request, "jobs.html", jobs=state(request).jobs.list_jobs(user["id"], limit=100))


@router.get("/jobs/{job_id}/view")
def job_page(request: Request, job_id: str):
    user = require_user(request)
    job = state(request).jobs.view(job_id, user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return render(request, "job.html", job=job)
