"""Background jobs for long-running tools, with live events/log for the browser.

Each job runs in a worker thread with the owner's Venice key bound in strict
mode (no server-key fallback), its stdout and NTCDG log records captured into
a live log, and ``generate_deck`` progress events collected via the runtime
event sink. Job summaries are persisted in SQLite so history survives a
restart (jobs that were running at shutdown are marked "interrupted").
"""

from __future__ import annotations

import contextlib
import json
import logging
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from ..runtime import JobCancelledError, cancel_scope, event_sink_scope
from . import tools
from .db import now_iso
from .files import Sanitizer

ACTIVE = ("queued", "running")
TERMINAL = ("done", "error", "interrupted", "cancelled")
MAX_EVENTS = 5000
MAX_FINISHED_IN_MEMORY = 200


class JobLimitError(Exception):
    """The user already has too many (or a conflicting) active jobs."""


class LiveLog:
    """Thread-safe, size-capped text buffer with monotonic cursor slicing."""

    def __init__(
        self,
        cap: int = 400_000,
        transform: Callable[[str], str] | None = None,
        on_write: Callable[[], None] | None = None,
    ):
        self._chunks: deque[tuple[int, str]] = deque()
        self._size = 0
        self._cap = cap
        self._start_offset = 0
        self._total_written = 0
        self._transform = transform
        self._on_write = on_write
        self._lock = threading.Lock()

    @property
    def has_transform(self) -> bool:
        return self._transform is not None

    @property
    def total_written(self) -> int:
        with self._lock:
            return self._total_written

    def set_transform(self, transform: Callable[[str], str] | None) -> None:
        with self._lock:
            self._transform = transform
            if transform and self._chunks:
                rebuilt: deque[tuple[int, str]] = deque()
                offset = self._start_offset
                size = 0
                for _end, text in self._chunks:
                    clean = transform(text)
                    offset += len(clean)
                    size += len(clean)
                    rebuilt.append((offset, clean))
                self._chunks = rebuilt
                self._size = size
                self._total_written = offset

    def write(self, s: str) -> int:
        if not s:
            return 0
        orig_len = len(s)
        notify = None
        with self._lock:
            text = self._transform(s) if self._transform is not None else s
            if text:
                end = self._total_written + len(text)
                self._chunks.append((end, text))
                self._total_written = end
                self._size += len(text)
                while self._size > self._cap and len(self._chunks) > 1:
                    old_end, removed = self._chunks.popleft()
                    self._size -= len(removed)
                    self._start_offset = old_end
            notify = self._on_write
        if notify is not None:
            notify()
        return orig_len

    def flush(self) -> None:
        return None

    def slice_from(self, cursor: int = 0) -> tuple[str, int]:
        """Return ``(new_text, total_written)`` for monotonic ``cursor``."""
        cursor = max(0, int(cursor))
        with self._lock:
            if cursor >= self._total_written:
                return "", self._total_written
            parts: list[str] = []
            if cursor < self._start_offset:
                trimmed = self._start_offset - cursor
                prefix = "" if cursor == 0 else "\n"
                parts.append(f"{prefix}[... {trimmed} earlier characters trimmed ...]\n")
                parts.extend(chunk for _end, chunk in self._chunks)
                return "".join(parts), self._total_written
            for end, chunk in self._chunks:
                if end <= cursor:
                    continue
                chunk_start = end - len(chunk)
                if cursor > chunk_start:
                    parts.append(chunk[cursor - chunk_start :])
                else:
                    parts.append(chunk)
            return "".join(parts), self._total_written

    def getvalue(self) -> str:
        text, _ = self.slice_from(0)
        return text


class Job:
    def __init__(self, job_id: str, user: dict[str, Any], call: tools.PreparedCall):
        self.id = job_id
        self.user_id = int(user["id"])
        self.username = user["username"]
        self.tool = call.spec.name
        self.generation = call.spec.generation
        self.deck = call.deck
        self.internal_deck = call.internal_deck
        self.input = call.display_input
        self.status = "queued"
        self.events: list[dict[str, Any]] = []
        self.cond = threading.Condition()
        self.cancel_event = threading.Event()
        self._future: Future[Any] | None = None
        self.log = LiveLog(on_write=self._notify_log)
        self.output: Any = None
        self.error = ""
        self.created_at = now_iso()
        self.started_at = ""
        self.finished_at = ""

    def _notify_log(self) -> None:
        with self.cond:
            self.cond.notify_all()

    def add_event(self, event: dict[str, Any]) -> None:
        with self.cond:
            if len(self.events) < MAX_EVENTS:
                self.events.append(event)
            self.cond.notify_all()

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id, "tool": self.tool, "deck": self.deck, "status": self.status,
            "error": self.error, "created_at": self.created_at, "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class _JobLogHandler(logging.Handler):
    """Routes NTCDG log records emitted on a job's worker thread into that job's log."""

    def __init__(self, manager: JobManager):
        super().__init__(level=logging.INFO)
        self.manager = manager
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        job = self.manager._thread_jobs.get(record.thread or 0)
        if job is None:
            return
        with contextlib.suppress(Exception):  # logging must never raise
            job.log.write(self.format(record) + "\n")


def _output_failed(output: Any) -> str:
    """Error message if a tool's output reports failure, else ""."""
    if not isinstance(output, dict):
        return ""
    if output.get("success") is False:
        return str(output.get("error") or "Tool reported failure")
    if output.get("error") and output.get("success") is not True:
        return str(output["error"])
    return ""


class JobManager:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings
        self.executor = ThreadPoolExecutor(
            max_workers=settings.job_workers, thread_name_prefix="ntcdg-job",
        )
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._thread_jobs: dict[int, Job] = {}
        self._log_handler = _JobLogHandler(self)
        logging.getLogger("NTCDG").addHandler(self._log_handler)

    # ---------- lifecycle ----------

    def shutdown(self, wait: bool = False) -> None:
        logging.getLogger("NTCDG").removeHandler(self._log_handler)
        self.executor.shutdown(wait=wait, cancel_futures=True)

    # ---------- queries ----------

    def active_jobs(self, user_id: int) -> list[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.user_id == int(user_id) and j.status in ACTIVE]

    def deck_busy(self, user_id: int, internal_deck: str) -> Job | None:
        return next((j for j in self.active_jobs(user_id) if j.internal_deck == internal_deck), None)

    def _memory_job(self, job_id: str, user_id: int) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.user_id != int(user_id):
            return None
        return job

    def view(self, job_id: str, user_id: int, since_event: int = 0, since_log: int = 0,
             sanitizer: Sanitizer | None = None) -> dict[str, Any] | None:
        """Full job state for its owner (None for anyone else / unknown ids)."""
        job = self._memory_job(job_id, user_id)
        if job is not None:
            log_chunk, log_total = job.log.slice_from(since_log)
            if sanitizer is not None and not job.log.has_transform and log_chunk:
                log_chunk = sanitizer.text(log_chunk)
            with job.cond:
                events = list(job.events[since_event:])
                total_events = len(job.events)
            return {
                **job.summary(), "input": job.input, "events": events,
                "events_total": total_events, "log": log_chunk, "log_total": log_total,
                "output": job.output, "live": True,
            }
        row = self.db.get_job(job_id)
        if not row or int(row["user_id"]) != int(user_id):
            return None
        events = json.loads(row["events_json"] or "[]")
        log = row["log"] or ""
        return {
            "id": row["id"], "tool": row["tool"], "deck": row["deck"], "status": row["status"],
            "error": row["error"], "created_at": row["created_at"], "started_at": row["started_at"],
            "finished_at": row["finished_at"], "input": json.loads(row["input_json"] or "{}"),
            "events": events[since_event:], "events_total": len(events),
            "log": log[since_log:], "log_total": len(log),
            "output": json.loads(row["output_json"]) if row["output_json"] else None,
            "live": False,
        }

    def wait_for_change(
        self, job_id: str, user_id: int, since_event: int, since_log: int, timeout: float = 0.5,
    ) -> None:
        """Wait up to ``timeout`` seconds for new events, log lines, or completion."""
        job = self._memory_job(job_id, user_id)
        if job is None:
            return
        with job.cond:
            if (
                len(job.events) > since_event
                or job.log.total_written > since_log
                or (job.status in TERMINAL and job.finished_at)
            ):
                return
            job.cond.wait(timeout)

    def cancel(self, job_id: str, user_id: int) -> dict[str, Any] | None:
        """Request cooperative cancellation of an owned job."""
        job = self._memory_job(job_id, user_id)
        if job is None:
            row = self.db.get_job(job_id)
            if not row or int(row["user_id"]) != int(user_id):
                return None
            return {"id": job_id, "status": row["status"], "cancelled": False}

        job.cancel_event.set()
        with job.cond:
            if job.status in TERMINAL:
                return {"id": job.id, "status": job.status, "cancelled": False}
            if job.status == "queued" and job._future is not None and job._future.cancel():
                job.status = "cancelled"
                job.error = "Cancelled before starting"
                job.finished_at = now_iso()
                job.cond.notify_all()
                with contextlib.suppress(Exception):
                    self.db.update_job(
                        job.id, status=job.status, error=job.error, finished_at=job.finished_at,
                        events_json=json.dumps(job.events), log=job.log.getvalue(), output_json="",
                    )
                return {"id": job.id, "status": job.status, "cancelled": True}

        job.add_event({"type": "cancelling", "ts": now_iso()})
        return {"id": job.id, "status": job.status, "cancelling": True}

    def list_jobs(self, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
        rows = {r["id"]: r for r in self.db.list_jobs(user_id, limit)}
        for job in self.active_jobs(user_id):
            rows[job.id] = job.summary()
        return sorted(rows.values(), key=lambda r: r["created_at"], reverse=True)[:limit]

    # ---------- submission ----------

    def submit(self, call: tools.PreparedCall, ctx: tools.ToolContext, venice_key: str | None) -> Job:
        uid = int(ctx.user["id"])
        with self._lock:
            active = [j for j in self._jobs.values() if j.user_id == uid and j.status in ACTIVE]
            if call.spec.generation:
                running = next((j for j in active if j.generation), None)
                if running is not None:
                    raise JobLimitError(
                        f"You already have a generation running ({running.tool}"
                        f"{' on ' + running.deck if running.deck else ''}). "
                        "Please wait for it to finish before starting another."
                    )
            if call.internal_deck:
                busy = next((j for j in active if j.internal_deck == call.internal_deck), None)
                if busy is not None:
                    raise JobLimitError(
                        f"Deck '{call.deck}' is busy with {busy.tool}; try again when it finishes."
                    )
            if len(active) >= self.settings.max_active_jobs_per_user:
                raise JobLimitError("Too many jobs running at once; wait for one to finish.")
            job = Job(secrets.token_urlsafe(12), ctx.user, call)
            self._jobs[job.id] = job
            self._prune_locked()
        self.db.insert_job(job.id, uid, job.tool, job.deck, job.input, job.status, job.created_at)
        job._future = self.executor.submit(self._run, job, call, ctx, venice_key)
        return job

    def _prune_locked(self) -> None:
        finished = [j for j in self._jobs.values() if j.status in TERMINAL]
        if len(finished) <= MAX_FINISHED_IN_MEMORY:
            return
        finished.sort(key=lambda j: j.finished_at or j.created_at)
        for j in finished[: len(finished) - MAX_FINISHED_IN_MEMORY]:
            self._jobs.pop(j.id, None)

    # ---------- execution ----------

    @staticmethod
    def _clean_event(event: dict[str, Any], job: Job, sanitizer: Sanitizer) -> dict[str, Any]:
        ev = dict(event)
        stamp = int(time.time() * 1000)
        pos = ev.get("position")
        if "image_path" in ev:
            had = bool(ev.pop("image_path"))
            if had and job.deck and isinstance(pos, int):
                ev["image_url"] = f"/files/{job.deck}/card/{pos}?v={stamp}"
        card = ev.get("card")
        if isinstance(card, dict):
            card = dict(card)
            had = bool(card.pop("image_path", None))
            if had and job.deck and isinstance(card.get("position"), int):
                card["image_url"] = f"/files/{job.deck}/card/{card['position']}?v={stamp}"
            ev["card"] = card
        ev["ts"] = now_iso()
        return sanitizer.scrub(ev)

    def _run(self, job: Job, call: tools.PreparedCall, ctx: tools.ToolContext,
             venice_key: str | None) -> None:
        ident = threading.get_ident()
        sanitizer = Sanitizer(ctx.db, ctx.user)
        job.log.set_transform(sanitizer.text)
        with job.cond:
            if job.cancel_event.is_set():
                job.status = "cancelled"
                job.error = "Cancelled by user"
                job.finished_at = now_iso()
                job.cond.notify_all()
                with contextlib.suppress(Exception):
                    self.db.update_job(
                        job.id, status=job.status, error=job.error, finished_at=job.finished_at,
                    )
                return
            job.status = "running"
            job.started_at = now_iso()
            job.cond.notify_all()
        self.db.update_job(job.id, status="running", started_at=job.started_at)
        self._thread_jobs[ident] = job

        def sink(event: dict[str, Any]) -> None:
            job.add_event(self._clean_event(event, job, sanitizer))

        try:
            with event_sink_scope(sink), cancel_scope(job.cancel_event):
                output = tools.execute(call, ctx, venice_key, stdout=job.log)
            sanitizer.refresh()
            clean = sanitizer.value(output)
            failure = _output_failed(clean)
            with job.cond:
                job.output = clean
                job.error = failure
                job.status = "error" if failure else "done"
        except JobCancelledError:
            with job.cond:
                job.error = "Cancelled by user"
                job.status = "cancelled"
        except Exception as e:  # pragma: no cover - execute() already traps tool errors
            with job.cond:
                job.error = sanitizer.text(str(e) or type(e).__name__)
                job.status = "error"
        finally:
            self._thread_jobs.pop(ident, None)
            with job.cond:
                job.finished_at = now_iso()
                job.cond.notify_all()
            with contextlib.suppress(Exception):  # e.g. user deleted mid-job
                self.db.update_job(
                    job.id, status=job.status, error=job.error, finished_at=job.finished_at,
                    events_json=json.dumps(job.events), log=job.log.getvalue(),
                    output_json=json.dumps(job.output) if job.output is not None else "",
                )

    def wait(self, job_id: str, timeout: float = 30.0) -> str:
        """Block until a job finishes (tests / CLI). Returns the final status."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return ""
        deadline = time.monotonic() + timeout
        with job.cond:
            while job.status in ACTIVE or not job.finished_at:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                job.cond.wait(remaining)
        return job.status
