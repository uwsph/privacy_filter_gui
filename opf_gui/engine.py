"""Background execution for the Privacy Filter GUI.

Model loading and inference are slow (seconds to minutes), so they never run on
the Tk main thread. ``EngineController`` owns a single worker thread plus a
result queue that the UI drains with ``after()``. Tk objects are never touched
from the worker.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
from typing import Any, Callable, Sequence

from .backends import Backend, BackendError, create_backend
from .models import Settings

POLL_INTERVAL_MS = 60

JOB_LOAD = "load"
JOB_WARMUP = "warmup"
JOB_REDACT = "redact"
JOB_BATCH = "batch"
JOB_UNLOAD = "unload"

# message kinds emitted to the UI callback
MSG_LOG = "log"
MSG_STATUS = "status"
MSG_PROGRESS = "progress"
MSG_RESULT = "result"
MSG_BATCH_ITEM = "batch_item"
MSG_ERROR = "error"
MSG_DONE = "done"
MSG_STATE = "state"


class EngineController:
    """Queue-backed single-worker executor around a redaction backend."""

    def __init__(
        self,
        *,
        settings: Settings,
        host: Any = None,
        on_message: Callable[[str, Any], None],
        inline: bool = False,
    ) -> None:
        self.settings = settings
        self.host = host
        self.on_message = on_message
        self.inline = inline
        self.backend: Backend = create_backend(settings, log=self._log)
        self._jobs: "queue.Queue[tuple[str, Any] | None]" = queue.Queue()
        self._messages: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()
        self._rebuild = threading.Event()
        self._busy = 0
        self._stop = False
        #: A model pass has run since the backend was (re)built - the UI uses this
        #: to tell a cold model from a warm one (warm-up button colour).
        self._warm = False

    # ------------------------------------------------------------------ #
    # plumbing
    # ------------------------------------------------------------------ #
    def _log(self, message: str) -> None:
        if self.inline:
            self.on_message(MSG_LOG, message)
        else:
            self._messages.put((MSG_LOG, message))

    @property
    def busy(self) -> bool:
        return self._busy > 0 or not self._jobs.empty()

    def start(self) -> None:
        """Start the worker thread and the UI poll loop."""
        if self.inline:
            return
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(
                target=self._run, name="opf-worker", daemon=True
            )
            self._worker.start()
        self._schedule_poll()

    def shutdown(self) -> None:
        self._stop = True
        self._jobs.put(None)
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=1.5)

    def _schedule_poll(self) -> None:
        if self.inline or self.host is None:
            return
        self.host.after(POLL_INTERVAL_MS, self._poll)

    def _poll(self) -> None:
        """Drain worker messages on the Tk thread, then reschedule."""
        drained = 0
        while drained < 50:
            try:
                kind, payload = self._messages.get_nowait()
            except queue.Empty:
                break
            drained += 1
            self.on_message(kind, payload)
            if kind == MSG_DONE:
                self._busy = max(0, self._busy - 1)
        self._schedule_poll()

    # ------------------------------------------------------------------ #
    # submission
    # ------------------------------------------------------------------ #
    def _submit(self, kind: str, payload: Any = None) -> None:
        self._cancel.clear()
        self._busy += 1
        if self.inline:
            self._execute((kind, payload))
            self.on_message(MSG_DONE, kind)
            self._busy = max(0, self._busy - 1)
            return
        self._jobs.put((kind, payload))

    def load(self) -> None:
        self._submit(JOB_LOAD)

    def warmup(self) -> None:
        self._submit(JOB_WARMUP)

    def redact(self, text: str, source: str | None = None) -> None:
        self._submit(JOB_REDACT, {"text": text, "source": source})

    def batch(self, items: Sequence[tuple[str, str]]) -> None:
        """``items`` is a sequence of ``(source_name, text)`` pairs."""
        self._submit(JOB_BATCH, list(items))

    def unload(self) -> None:
        self._submit(JOB_UNLOAD)

    def request_backend_rebuild(self) -> None:
        """Called by the UI when the engine choice changed."""
        self._rebuild.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._log("Cancellation requested - finishing current item...")

    # ------------------------------------------------------------------ #
    # execution
    # ------------------------------------------------------------------ #
    def _emit(self, kind: str, payload: Any = None) -> None:
        if self.inline:
            self.on_message(kind, payload)
        else:
            self._messages.put((kind, payload))

    def _run(self) -> None:
        while not self._stop:
            try:
                job = self._jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            if job is None:
                break
            self._execute(job)
            self._emit(MSG_DONE, job[0])

    def _ensure_backend(self) -> None:
        if self._rebuild.is_set():
            self._rebuild.clear()
            try:
                self.backend.close()
            except Exception:  # noqa: BLE001 - best effort
                pass
            self.backend = create_backend(self.settings, log=self._log)
            self._warm = False  # fresh backend: nothing has been inferred yet
            self._emit(MSG_STATE, {"backend": self.backend.name})

    def _execute(self, job: "tuple[str, Any]") -> None:
        kind, payload = job
        try:
            self._ensure_backend()
            self._emit(MSG_STATUS, _busy_status(kind, payload))
            if kind == JOB_LOAD:
                self._do_load()
            elif kind == JOB_WARMUP:
                self.backend.warmup()
                self._warm = True
            elif kind == JOB_REDACT:
                self._do_redact(str(payload["text"]), payload.get("source"))
                self._warm = self._weights_loaded()  # a finished model pass means warm
            elif kind == JOB_BATCH:
                self._do_batch(list(payload))
                self._warm = self._weights_loaded()
            elif kind == JOB_UNLOAD:
                self.backend.close()
                self._warm = False
                self._emit(MSG_STATUS, "Model unloaded")
            else:
                raise BackendError(f"Unknown job type: {kind}")
        except BackendError as exc:
            self._emit(MSG_ERROR, str(exc))
        except Exception as exc:  # noqa: BLE001 - never let the worker die silently
            self._emit(MSG_ERROR, f"{type(exc).__name__}: {exc}")
            self._log(traceback.format_exc(limit=4))
        finally:
            # Tell the UI how much is really resident now: warm-up and the first
            # redaction load weights implicitly, a failed load loads nothing.
            self._emit(MSG_STATE, {
                "loaded": self._weights_loaded(),
                "warm": self._warm,
                "backend": self.backend.name,
            })

    def _weights_loaded(self) -> bool:
        """Ask the live backend whether it holds weights (demo backends say no)."""
        try:
            return bool(getattr(self.backend, "loaded", False))
        except Exception:  # noqa: BLE001 - reporting must never break a job
            return False

    def _do_load(self) -> None:
        """Load the weights (or warm up backends without an explicit load hook)."""
        load = getattr(self.backend, "load", None)
        if callable(load):
            load()
        else:
            self.backend.warmup()
        self._emit(MSG_STATUS, "Model ready")
        self._emit(MSG_STATE, {"loaded": True, "backend": self.backend.name})

    def _do_redact(self, text: str, source: str | None) -> None:
        started = time.perf_counter()
        outcome = self.backend.redact(text)
        if source and not outcome.source:
            outcome.source = source
        if not outcome.latency_ms:
            outcome.latency_ms = (time.perf_counter() - started) * 1000.0
        self._emit(MSG_RESULT, outcome)

    def _do_batch(self, items: list[tuple[str, str]]) -> None:
        total = len(items)
        for index, (source, text) in enumerate(items, start=1):
            if self._cancel.is_set():
                self._emit(MSG_STATUS, f"Batch cancelled after {index - 1}/{total} files")
                return
            self._emit(MSG_PROGRESS, (index - 1, total))
            try:
                outcome = self.backend.redact(text)
            except BackendError as exc:
                self._emit(MSG_ERROR, f"{source}: {exc}")
                continue
            outcome.source = outcome.source or source
            self._emit(MSG_BATCH_ITEM, outcome)
        self._emit(MSG_PROGRESS, (total, total))


def _busy_status(kind: str, payload: Any) -> str:
    if kind == JOB_LOAD:
        return "Loading model..."
    if kind == JOB_WARMUP:
        return "Warming up..."
    if kind == JOB_BATCH:
        count = len(payload) if payload else 0
        return f"Batch redaction of {count} file(s)..."
    if kind == JOB_UNLOAD:
        return "Unloading model..."
    return "Redacting..."
