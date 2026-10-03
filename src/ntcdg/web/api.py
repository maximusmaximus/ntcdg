"""JSON/SSE endpoints: tool invocation, jobs, uploads and owned-file downloads."""

from __future__ import annotations

import asyncio
import json
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from . import auth, tools
from . import files as webfiles
from .deps import require_api_user, require_user, state, user_venice_key
from .jobs import TERMINAL, JobLimitError

router = APIRouter()

#: Sync tools that modify a deck -- refused while a job is working on it.
_SYNC_WRITERS = frozenset({"edit_card", "delete_deck"})


def _error(message: str, status: int = 400, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


# ==================== TOOLS ====================

@router.get("/api/tools")
def api_tools(request: Request):
    require_api_user(request)
    return {
        "tools": [spec.to_dict() for spec in tools.REGISTRY.values()],
        "excluded": tools.EXCLUDED_TOOLS,
    }


@router.post("/api/tools/{tool_name}")
async def api_run_tool(request: Request, tool_name: str):
    user = require_api_user(request)
    auth.check_csrf(request)
    st = state(request)
    spec = tools.REGISTRY.get(tool_name)
    if spec is None:
        return _error(f"Unknown tool '{tool_name}'", 404)
    try:
        body = await request.json()
    except ValueError:
        return _error("Request body must be JSON: {\"inputs\": {...}}")
    raw = body.get("inputs", {}) if isinstance(body, dict) else None
    if not isinstance(raw, dict):
        return _error("Request body must be JSON: {\"inputs\": {...}}")

    ctx = tools.ToolContext(db=st.db, user=user, settings=st.settings)
    try:
        call = tools.prepare_call(spec, raw, ctx)
    except tools.ToolInputError as e:
        return _error(str(e), 400, tool=tool_name, input=raw)

    key = user_venice_key(request, user)
    if spec.name in tools.GENERATION_TOOLS | {"describe_symbols", "suggest_deck"} and not key:
        return _error(
            "This tool uses Venice AI and needs your own Venice API key. "
            "Add it on your profile page (it is stored encrypted).",
            400, tool=tool_name, input=call.display_input, needs_key=True,
        )
    if spec.name in _SYNC_WRITERS and call.internal_deck:
        busy = st.jobs.deck_busy(user["id"], call.internal_deck)
        if busy is not None:
            return _error(f"Deck '{call.deck}' is busy with {busy.tool}; try again when it finishes.", 409)

    if spec.mode == "job":
        try:
            job = st.jobs.submit(call, ctx, key)
        except JobLimitError as e:
            return _error(str(e), 409, tool=tool_name, input=call.display_input)
        return JSONResponse({
            "mode": "job", "tool": tool_name, "input": call.display_input, "job_id": job.id,
            "status": job.status, "view_url": f"/jobs/{job.id}/view",
            "events_url": f"/jobs/{job.id}/events", "poll_url": f"/jobs/{job.id}",
        }, status_code=202)

    result = await asyncio.to_thread(tools.run_sync, call, ctx, key)
    return JSONResponse(result)


# ==================== JOBS ====================

@router.get("/jobs/{job_id}")
def job_json(request: Request, job_id: str, since_event: int = 0, since_log: int = 0):
    user = require_api_user(request)
    st = state(request)
    view = st.jobs.view(job_id, user["id"], max(0, since_event), max(0, since_log),
                        sanitizer=webfiles.Sanitizer(st.db, user))
    if view is None:
        return _error("Job not found", 404)
    return view


@router.get("/jobs/{job_id}/events")
async def job_events(request: Request, job_id: str):
    """Server-Sent Events: incremental events/log/status until the job finishes."""
    user = require_api_user(request)
    st = state(request)
    sanitizer = webfiles.Sanitizer(st.db, user)
    if st.jobs.view(job_id, user["id"]) is None:
        return _error("Job not found", 404)

    async def stream():
        since_event = 0
        since_log = 0
        while True:
            view = st.jobs.view(job_id, user["id"], since_event, since_log, sanitizer=sanitizer)
            if view is None:
                break
            since_event = view["events_total"]
            since_log = view["log_total"]
            done = view["status"] in TERMINAL and (not view["live"] or view["finished_at"])
            payload = {
                "status": view["status"], "error": view["error"], "events": view["events"],
                "log": view["log"], "output": view["output"] if done else None,
            }
            yield f"event: update\ndata: {json.dumps(payload)}\n\n"
            if done:
                yield "event: done\ndata: {}\n\n"
                break
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ==================== UPLOADS ====================

@router.get("/uploads")
def uploads_list(request: Request):
    user = require_api_user(request)
    rows = state(request).db.list_uploads(user["id"])
    return {"uploads": [
        {"id": r["id"], "kind": r["kind"], "name": r["original_name"], "size": r["size"],
         "ref": f"upload:{r['id']}", "url": f"/uploads/{r['id']}" if r["kind"] == "image" else "",
         "created_at": r["created_at"]}
        for r in rows
    ]}


@router.post("/uploads")
async def uploads_create(request: Request):
    user = require_api_user(request)
    st = state(request)
    form = await request.form()
    auth.check_csrf(request, form.get(auth.CSRF_FIELD))
    kind = str(form.get("kind") or "image")
    files = [f for f in form.getlist("file") if hasattr(f, "read")]
    if not files:
        return _error("Choose at least one file to upload.")
    if len(files) > 30:
        return _error("At most 30 files per upload.")
    results, errors = [], []
    for f in files:
        data = await f.read(st.settings.max_upload_bytes + 1)
        try:
            if kind == "symbols_json":
                results.append(webfiles.save_symbols_json_upload(
                    st.db, user, f.filename or "", data, st.settings.max_upload_bytes))
            elif kind == "image":
                results.append(webfiles.save_image_upload(
                    st.db, user, f.filename or "", data, st.settings.max_upload_bytes))
            else:
                return _error("kind must be 'image' or 'symbols_json'")
        except webfiles.FileInputError as e:
            errors.append({"name": f.filename or "", "error": str(e)})
    status = 200 if results else 400
    return JSONResponse({"uploads": results, "errors": errors}, status_code=status)


@router.get("/uploads/{upload_id}")
def upload_get(request: Request, upload_id: str):
    user = require_user(request)
    st = state(request)
    if not webfiles.UPLOAD_ID_RE.match(upload_id):
        raise HTTPException(status_code=404, detail="Not found")
    row = st.db.get_upload(user["id"], upload_id)
    if not row or row["kind"] != "image":
        raise HTTPException(status_code=404, detail="Not found")
    path = webfiles.upload_path(user, row)
    if not webfiles.is_within(path, webfiles.data_roots()) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


@router.post("/uploads/{upload_id}/delete")
async def upload_delete(request: Request, upload_id: str):
    user = require_api_user(request)
    form = await request.form()
    auth.check_csrf(request, form.get(auth.CSRF_FIELD))
    if not webfiles.delete_upload(state(request).db, user, upload_id):
        return _error("Upload not found", 404)
    return {"deleted": upload_id}


# ==================== OWNED FILES ====================

def _serve(request: Request, deck: str, kind: str, name: str):
    user = require_user(request)
    found = webfiles.resolve_owned_file(user, deck, kind, name)
    if not found:
        raise HTTPException(status_code=404, detail="File not found")
    path, download = found
    is_attachment = download.lower().endswith((".pdf", ".zip", ".xlsx"))
    return FileResponse(
        path, filename=download if is_attachment else None,
        content_disposition_type="attachment" if is_attachment else "inline",
        headers={"Cache-Control": "private, no-cache"},
    )


@router.get("/files/{deck}/{kind}")
def file_two(request: Request, deck: str, kind: str):
    return _serve(request, deck, kind, "")


@router.get("/files/{deck}/{kind}/{name}")
def file_three(request: Request, deck: str, kind: str, name: str):
    return _serve(request, deck, kind, name)
