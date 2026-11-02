"""Durable enrichment queue: restart recovery, backoff, dedup, terminal failure."""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


deq = _load("durable_enrich_queue", "ingest/durable_enrich_queue.py")


def _queue(tmp: Path, **kw) -> deq.DurableEnrichmentQueue:
    return deq.DurableEnrichmentQueue(db=tmp / "q.db", base_backoff=0.01, backoff_cap=0.05, **kw)


# 1. durable enqueue survives "restart" (fresh connection on same db)
def test_enqueue_survives_restart(tmp_path):
    db = tmp_path / "q.db"
    q1 = deq.DurableEnrichmentQueue(db=db)
    assert q1.enqueue("SN2020abc") is True
    q1._conn.close()
    q2 = deq.DurableEnrichmentQueue(db=db)
    s = q2.stats()
    assert s["queued"] == 1
    assert s["pending_total"] == 1


# 2. dedup by name while in-flight
def test_dedup_by_name(tmp_path):
    q = _queue(tmp_path)
    assert q.enqueue("SN2020abc") is True
    assert q.enqueue("SN2020abc") is False  # duplicate
    assert q.stats()["queued"] == 1
    assert q.deduped == 1


# 3. done is terminal and persists
def test_finish_ok_terminal(tmp_path):
    q = _queue(tmp_path)
    q.enqueue("SN2020abc")
    job = q._claim()
    assert job and job[0] == "SN2020abc"
    q._finish_ok("SN2020abc")
    assert q.stats()["done"] == 1
    assert q._claim() is None  # not re-claimed


# 4. retry with backoff -> not immediately claimable, then requeued
def test_retry_backoff(tmp_path):
    q = _queue(tmp_path)
    q.enqueue("SN2020abc")
    q._claim()
    q._finish_retry("SN2020abc", rate_limited=False, error="boom")
    assert q._claim() is None  # backoff: not_before in future
    # force the backoff to elapse
    q._conn.execute("UPDATE enrich_jobs SET not_before=0 WHERE name='SN2020abc'")
    q._conn.commit()
    job = q._claim()
    assert job and job[0] == "SN2020abc"
    assert q.stats()["retry"] == 0  # now leased


# 5. terminal failure after max_attempts
def test_terminal_failure(tmp_path):
    q = _queue(tmp_path, max_attempts=2)
    q.enqueue("SN2020abc")
    for _ in range(2):
        q._conn.execute("UPDATE enrich_jobs SET not_before=0")
        q._conn.commit()
        job = q._claim()
        assert job is not None, "job should be claimable before terminal failure"
        q._finish_retry("SN2020abc", rate_limited=False, error="x")
    assert q.stats()["failed"] == 1
    assert q._claim() is None


# 6. rate limit uses the longer cooldown and is counted
def test_rate_limit_cooldown(tmp_path):
    q = _queue(tmp_path, rate_limit_cooldown=99.0)
    q.enqueue("SN2020abc")
    q._claim()
    q._finish_retry("SN2020abc", rate_limited=True, error="429 rate limit")
    assert q.rate_limited == 1
    nb = q._conn.execute("SELECT not_before FROM enrich_jobs WHERE name='SN2020abc'").fetchone()[0]
    assert nb > time.time() + 50  # long cooldown, not the short backoff


# 7. expired lease is reclaimed (worker crash recovery)
def test_expired_lease_reclaimed(tmp_path):
    q = _queue(tmp_path, lease_seconds=0.01)
    q.enqueue("SN2020abc")
    q._claim()
    time.sleep(0.05)  # let the lease expire
    job = q._claim()  # should reclaim the expired lease
    assert job and job[0] == "SN2020abc"


# 8. oldest_pending_age reflects a backlogged job
def test_oldest_pending_age(tmp_path):
    q = _queue(tmp_path)
    q.enqueue("SN2020abc")
    q._conn.execute("UPDATE enrich_jobs SET enqueued_at=enqueued_at-100")
    q._conn.commit()
    assert q.stats()["oldest_pending_age_s"] >= 99
