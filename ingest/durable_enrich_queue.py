"""Durable enrichment queue backed by SQLite on the persistent runtime volume.

Replaces the in-memory ``_EnrichmentQueue`` so accepted enrichment work survives
container restart, retries rate limits with backoff, dedupes by event name, and
tracks attempts / next-retry / lease / completion / terminal failure.

Durability rule: ``enqueue`` commits to SQLite *before* returning; a job is only
acknowledged (``done``) after ``enrich_event`` reports success. Restart recovery
re-queues ``queued``/``leased``/``retry`` rows — nothing accepted is lost.

The runner is synchronous per job (worker thread drives ``enrich_event``); the
HTTP path stays non-blocking because ``enqueue`` is a fast SQLite insert.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS enrich_jobs (
    name          TEXT PRIMARY KEY,
    fetch_lc      INTEGER NOT NULL DEFAULT 1,
    fetch_spec    INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'queued',  -- queued|leased|retry|done|failed
    attempts      INTEGER NOT NULL DEFAULT 0,
    max_attempts  INTEGER NOT NULL DEFAULT 3,
    not_before    REAL NOT NULL DEFAULT 0,
    lease_until   REAL NOT NULL DEFAULT 0,
    enqueued_at   REAL NOT NULL,
    updated_at    REAL NOT NULL,
    last_error    TEXT
);
CREATE INDEX IF NOT EXISTS idx_enrich_status_nb ON enrich_jobs(status, not_before);
"""


def _db_path() -> Path:
    try:
        from serve import data_paths

        d = data_paths.resolve_runtime_dir()
    except Exception:
        env = (os.environ.get("SNE_RUNTIME_DIR") or "").strip()
        d = Path(env) if env else Path(__file__).resolve().parent.parent / "serve" / "www" / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d / "enrich_queue.db"


class DurableEnrichmentQueue:
    """SQLite-backed, restart-safe, dedup'd enrichment job queue."""

    def __init__(
        self,
        *,
        db: Optional[Path] = None,
        max_attempts: int = 3,
        job_timeout: float = 45.0,
        base_backoff: float = 30.0,
        backoff_cap: float = 900.0,
        rate_limit_cooldown: float = 120.0,
        lease_seconds: float = 90.0,
    ) -> None:
        self.db = db or _db_path()
        self.max_attempts = max_attempts
        self.job_timeout = job_timeout
        self.base_backoff = base_backoff
        self.backoff_cap = backoff_cap
        self.rate_limit_cooldown = rate_limit_cooldown
        self.lease_seconds = lease_seconds
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db), timeout=60.0, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._conn:
            self._conn.executescript(_SCHEMA)
        self._started = False
        self._wake = threading.Condition(self._lock)
        # process-level counters (persisted counters live in the table)
        self.enqueued = 0
        self.deduped = 0
        self.completed = 0
        self.failed = 0
        self.rate_limited = 0

    # -- durability ------------------------------------------------------

    def enqueue(self, name: str, fetch_lightcurve: bool = True, fetch_spectra: bool = True) -> bool:
        """Durably record a job. False when already queued/leased (deduped)."""
        if not name:
            return False
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM enrich_jobs WHERE name = ?", (name,)
            ).fetchone()
            if row is not None and row[0] in ("queued", "leased", "retry"):
                self.deduped += 1
                return False
            with self._conn:
                self._conn.execute(
                    "INSERT INTO enrich_jobs(name, fetch_lc, fetch_spec, status, attempts, "
                    "max_attempts, not_before, enqueued_at, updated_at, last_error) "
                    "VALUES(?,?,?,?,0,?,0,?,?,NULL) "
                    "ON CONFLICT(name) DO UPDATE SET status='queued', not_before=0, "
                    "attempts=0, updated_at=excluded.updated_at, last_error=NULL",
                    (name, int(fetch_lightcurve), int(fetch_spectra), "queued", self.max_attempts, now, now),
                )
            self.enqueued += 1
            self._wake.notify()
            return True

    def _claim(self) -> Optional[tuple[str, bool, bool]]:
        """Lease the next due job. Restart recovery: expired leases are reclaimable."""
        now = time.time()
        with self._lock:
            # Requeue leased jobs whose lease expired (worker died mid-job).
            with self._conn:
                self._conn.execute(
                    "UPDATE enrich_jobs SET status='queued', updated_at=? "
                    "WHERE status='leased' AND lease_until < ?",
                    (now, now),
                )
            row = self._conn.execute(
                "SELECT name, fetch_lc, fetch_spec FROM enrich_jobs "
                "WHERE status IN ('queued','retry') AND not_before <= ? "
                "ORDER BY enqueued_at LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                return None
            name, lc, sp = row[0], bool(row[1]), bool(row[2])
            with self._conn:
                self._conn.execute(
                    "UPDATE enrich_jobs SET status='leased', lease_until=?, updated_at=? "
                    "WHERE name=?",
                    (now + self.lease_seconds, now, name),
                )
            return name, lc, sp

    def _finish_ok(self, name: str) -> None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE enrich_jobs SET status='done', updated_at=?, last_error=NULL WHERE name=?",
                (now, name),
            )
        self.completed += 1

    def _finish_retry(self, name: str, *, rate_limited: bool, error: str) -> None:
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT attempts, max_attempts FROM enrich_jobs WHERE name=?", (name,)
            ).fetchone()
            attempts = (row[0] if row else 0) + 1
            maxa = row[1] if row else self.max_attempts
            if attempts >= maxa:
                status = "failed"
                not_before = 0.0
                self.failed += 1
            else:
                status = "retry"
                if rate_limited:
                    not_before = now + self.rate_limit_cooldown
                    self.rate_limited += 1
                else:
                    delay = min(self.backoff_cap, self.base_backoff * (2 ** (attempts - 1)))
                    not_before = now + delay
            with self._conn:
                self._conn.execute(
                    "UPDATE enrich_jobs SET status=?, attempts=?, not_before=?, "
                    "updated_at=?, last_error=? WHERE name=?",
                    (status, attempts, not_before, now, error[:500], name),
                )
            self._wake.notify_all()

    # -- stats -----------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) FROM enrich_jobs GROUP BY status"
            ).fetchall()
            counts = {r[0]: r[1] for r in rows}
            oldest = self._conn.execute(
                "SELECT MIN(enqueued_at) FROM enrich_jobs WHERE status IN ('queued','retry','leased')"
            ).fetchone()[0]
        return {
            "backend": "sqlite",
            "db": str(self.db),
            "queued": counts.get("queued", 0),
            "leased": counts.get("leased", 0),
            "retry": counts.get("retry", 0),
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
            "pending_total": counts.get("queued", 0) + counts.get("retry", 0) + counts.get("leased", 0),
            "oldest_pending_age_s": round(time.time() - oldest, 1) if oldest else 0.0,
            "session": {
                "enqueued": self.enqueued,
                "deduped": self.deduped,
                "completed": self.completed,
                "failed": self.failed,
                "rate_limited": self.rate_limited,
            },
        }

    # -- worker ----------------------------------------------------------

    def start(self, workers: int = 2) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        for i in range(max(1, workers)):
            threading.Thread(target=self._worker, name=f"durable-enrich-{i}", daemon=True).start()

    def _worker(self) -> None:
        from ingest.manager import enrich_event

        while True:
            job = self._claim()
            if job is None:
                with self._wake:
                    self._wake.wait(timeout=5.0)
                continue
            name, lc, sp = job
            ok = False
            rate = False
            err = ""
            try:
                ok = bool(enrich_event(name, fetch_lightcurve=lc, fetch_spectra=sp, force=False))
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                low = err.lower()
                if "429" in low or "rate limit" in low:
                    rate = True
            if ok:
                self._finish_ok(name)
                try:
                    # Acknowledged only after committed output — schedule publication.
                    from ingest.publication import mark_ingested
                    from ingest.manager import SUPERNOVAE_OUTPUT

                    hits = list(Path(SUPERNOVAE_OUTPUT).glob(f"sne-*/{name}.json"))
                    if hits:
                        mark_ingested(name, hits[0])
                except Exception:
                    pass
            else:
                self._finish_retry(name, rate_limited=rate, error=err or "enrich returned False")


_QUEUE: Optional[DurableEnrichmentQueue] = None


def get_queue() -> DurableEnrichmentQueue:
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = DurableEnrichmentQueue(
            max_attempts=int(os.environ.get("SNE_ENRICH_ATTEMPTS", "3")),
            job_timeout=float(os.environ.get("SNE_ENRICH_TIMEOUT", "45")),
            base_backoff=float(os.environ.get("SNE_ENRICH_BACKOFF", "30")),
            rate_limit_cooldown=float(os.environ.get("SNE_ENRICH_RATE_COOLDOWN", "120")),
        )
    return _QUEUE
