"""In-memory job table for the Studio API's long-running actions.

`process-take` (VO normalize + transcribe) and `render-beat` (compile ->
render one beat) can each take from seconds to minutes, far longer than an
HTTP request should block. Both are submitted here: the endpoint gets a job
id back immediately and the browser polls `GET /api/jobs/{id}`.

Deliberately minimal and process-local: a dict guarded by a lock plus a
ThreadPoolExecutor. This is a single-user localhost studio (the server binds
127.0.0.1 only), so there is no need for a persistent queue or cross-process
broker — a restart simply drops in-flight jobs, which the UI re-issues.

No cancellation: there is no `cancel(job_id)`. A submitted job runs to
completion (or error); the UI simply stops polling a job it no longer cares
about (via an AbortController on its side). Finished jobs are evicted lazily
on each `submit` — by age (older than `ttl_seconds`) and by count (keeping at
most `max_jobs`) — so the table cannot grow without bound across a long
session. Running jobs are never evicted.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


class JobManager:
    """Submit callables, track their status/result/error by job id."""

    def __init__(
        self,
        max_workers: int = 4,
        *,
        max_jobs: int = 100,
        ttl_seconds: float = 3600.0,
    ) -> None:
        self._exec = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="dlstudio-job"
        )
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._max_jobs = max_jobs
        self._ttl = ttl_seconds

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        """Run `fn(*args, **kwargs)` on the executor. Returns a fresh job id;
        the job starts as `running` and transitions to `done`/`error`.

        Evicts stale/overflow finished jobs first (see `_evict_locked`)."""
        job_id = uuid.uuid4().hex
        with self._lock:
            self._evict_locked()
            self._jobs[job_id] = {
                "status": "running", "result": None, "error": None,
                "created_at": time.time(), "finished_at": None,
            }
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
            job = self._jobs.get(job_id)
            if job is None:  # already evicted (e.g. never polled) — drop the result
                return
            job.update(fields)
            if fields.get("status") in ("done", "error"):
                job["finished_at"] = time.time()

    def _evict_locked(self) -> None:
        """Drop finished jobs older than `ttl_seconds`, then, if still over
        `max_jobs`, drop the oldest-finished until back under the cap. Running
        jobs are always retained. Caller must hold `self._lock`."""
        now = time.time()
        stale = [
            jid for jid, j in self._jobs.items()
            if j["finished_at"] is not None and now - j["finished_at"] > self._ttl
        ]
        for jid in stale:
            del self._jobs[jid]
        if len(self._jobs) > self._max_jobs:
            finished = sorted(
                (jid for jid, j in self._jobs.items() if j["finished_at"] is not None),
                key=lambda jid: self._jobs[jid]["finished_at"],
            )
            for jid in finished[: len(self._jobs) - self._max_jobs]:
                del self._jobs[jid]

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Public snapshot of the job's state (status/result/error), or None
        if the id is unknown. Internal bookkeeping (timestamps) is not
        exposed, keeping the `GET /api/jobs/{id}` contract stable."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {"status": job["status"], "result": job["result"], "error": job["error"]}

    def shutdown(self) -> None:
        self._exec.shutdown(wait=False, cancel_futures=True)
