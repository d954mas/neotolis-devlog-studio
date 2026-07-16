"""In-memory job table for the Studio API's long-running actions.

`process-take` (VO normalize + transcribe) and `render-beat` (compile ->
render one beat) can each take from seconds to minutes, far longer than an
HTTP request should block. Both are submitted here: the endpoint gets a job
id back immediately and the browser polls `GET /api/jobs/{id}`.

Deliberately minimal and process-local: a dict guarded by a lock plus a
ThreadPoolExecutor. This is a single-user localhost studio (the server binds
127.0.0.1 only), so there is no need for a persistent queue or cross-process
broker — a restart simply drops in-flight jobs, which the UI re-issues.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


class JobManager:
    """Submit callables, track their status/result/error by job id."""

    def __init__(self, max_workers: int = 4) -> None:
        self._exec = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="dlstudio-job"
        )
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        """Run `fn(*args, **kwargs)` on the executor. Returns a fresh job id;
        the job starts as `running` and transitions to `done`/`error`."""
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {"status": "running", "result": None, "error": None}
        self._exec.submit(self._run, job_id, fn, args, kwargs)
        return job_id

    def _run(self, job_id: str, fn: Callable[..., Any], args: tuple, kwargs: dict) -> None:
        try:
            result = fn(*args, **kwargs)
            self._set(job_id, status="done", result=result, error=None)
        except Exception as e:  # noqa: BLE001 — surface any failure as job error
            self._set(job_id, status="error", result=None, error=f"{type(e).__name__}: {e}")

    def _set(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            self._jobs[job_id] = dict(fields)

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Snapshot of the job's state, or None if the id is unknown."""
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None

    def shutdown(self) -> None:
        self._exec.shutdown(wait=False, cancel_futures=True)
