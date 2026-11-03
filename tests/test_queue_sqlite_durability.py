"""SQLite durability for the durable enrichment queue against a real filesystem.

Covers: WAL mode, transaction atomicity (enqueue committed before return), lease
recovery after an abrupt close (no clean shutdown), and concurrent multi-worker
claiming with no double-claims. Uses a real on-disk db (tmp_path), NOT in-memory,
so it exercises the same filesystem semantics as the persistent volume.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


deq = _load("durable_enrich_queue", "ingest/durable_enrich_queue.py")


def test_wal_mode_enabled(tmp_path):
    q = deq.DurableEnrichmentQueue(db=tmp_path / "q.db")
    mode = q._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    # A WAL sidecar file appears once there's activity on a real filesystem.
    q.enqueue("SN2020wal")
    q._conn.commit()
    assert (tmp_path / "q.db").is_file()
    q._conn.close()


def test_enqueue_is_transactionally_durable_before_return(tmp_path):
    # A separate connection must see the job immediately after enqueue returns
    # (i.e. the INSERT was committed, not left in an open transaction).
    db = tmp_path / "q.db"
    q = deq.DurableEnrichmentQueue(db=db)
    assert q.enqueue("SN2020durable") is True
    other = sqlite3.connect(str(db), timeout=30.0)
    row = other.execute("SELECT status FROM enrich_jobs WHERE name='SN2020durable'").fetchone()
    other.close()
    assert row is not None and row[0] == "queued"
    q._conn.close()


def test_lease_recovery_after_abrupt_close(tmp_path):
    # Simulate a worker that leases a job then dies without finish (no clean close).
    db = tmp_path / "q.db"
    q1 = deq.DurableEnrichmentQueue(db=db, lease_seconds=0.05)
    q1.enqueue("SN2020lease")
    job = q1._claim()
    assert job is not None
    # Abrupt termination: drop the connection object without stop()/commit.
    q1._conn = None  # type: ignore[assignment]

    time.sleep(0.1)  # let the lease expire
    q2 = deq.DurableEnrichmentQueue(db=db)
    reclaimed = q2._claim()  # expired lease must be reclaimed
    assert reclaimed is not None and reclaimed[0] == "SN2020lease"
    q2._conn.close()


def test_concurrent_workers_no_double_claim(tmp_path):
    # N threads racing _claim() on the same jobs must never claim the same job twice.
    db = tmp_path / "q.db"
    q = deq.DurableEnrichmentQueue(db=db, lease_seconds=30.0)
    for i in range(60):
        q.enqueue(f"SN{i:03d}")

    claimed: list[str] = []
    lock = threading.Lock()

    def work():
        while True:
            job = q._claim()
            if job is None:
                return
            with lock:
                claimed.append(job[0])
            q._finish_ok(job[0])

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(claimed) == 60, f"expected 60 claims, got {len(claimed)}"
    assert len(set(claimed)) == 60, "duplicate claim detected (race)"
    assert q.stats()["done"] == 60
    q._conn.close()


def test_finished_job_not_reclaimable_after_reopen(tmp_path):
    db = tmp_path / "q.db"
    q1 = deq.DurableEnrichmentQueue(db=db)
    q1.enqueue("SN2020done")
    q1._claim()
    q1._finish_ok("SN2020done")
    q1._conn.close()
    q2 = deq.DurableEnrichmentQueue(db=db)
    assert q2._claim() is None
    assert q2.stats()["done"] == 1
    q2._conn.close()
