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


# 9. weighted fairness: aged (priority) backlog cannot starve fresh jobs, and
#    fresh arrivals cannot starve aged backlog — both make progress.
def test_no_starvation_either_direction(tmp_path):
    q = _queue(tmp_path, aged_share=0.5, aging_seconds=10**9)  # aging off; pure weighting
    # Seed a large aged backlog.
    for i in range(50):
        q.enqueue(f"AGED{i}", priority=True)
    # Continuously add fresh work while draining; fresh must still be claimed.
    claimed = []
    fresh_added = 0
    for _ in range(120):
        q.enqueue(f"FRESH{fresh_added}"); fresh_added += 1
        job = q._claim()
        if job is None:
            break
        claimed.append(job[0])
        q._finish_ok(job[0])
    fresh_claimed = sum(1 for n in claimed if n.startswith("FRESH"))
    aged_claimed = sum(1 for n in claimed if n.startswith("AGED"))
    # With ~50/50 weighting, both classes get served (neither is starved).
    assert fresh_claimed > 0, "aged backlog starved fresh jobs"
    assert aged_claimed > 0, "fresh arrivals starved aged backlog"
    # Roughly balanced (not 100% one class) under equal shares.
    assert 0.2 <= fresh_claimed / max(1, len(claimed)) <= 0.8


# 10. aging promotes a long-waited fresh job to priority (starvation guard).
def test_aging_promotes_old_fresh_job(tmp_path):
    q = _queue(tmp_path, aging_seconds=0.01)
    q.enqueue("OLDFRESH")
    # Re-enqueue after the aging window: should be promoted to priority=1.
    import time as _t
    _t.sleep(0.02)
    q.enqueue("OLDFRESH")  # deduped, but aged -> promoted
    pr = q._conn.execute("SELECT priority FROM enrich_jobs WHERE name='OLDFRESH'").fetchone()[0]
    assert pr == 1


# 11. Sustained arrivals with simultaneous aging: when many fresh jobs age into the
#     priority class at once, the weighted allocation must keep BOTH classes
#     progressing — no runaway starvation of either side.
def test_sustained_arrivals_with_simultaneous_aging(tmp_path):
    q = _queue(tmp_path, aged_share=0.5, aging_seconds=0.03)
    import time as _t

    claimed = []
    # Simulate a live stream: keep enqueuing fresh work while a worker drains.
    # Old fresh jobs age into priority; the weighted selector must not let the
    # (growing) aged class starve brand-new arrivals, nor vice versa.
    for round_ in range(400):
        q.enqueue(f"F{round_}")
        job = q._claim()
        if job is None:
            _t.sleep(0.002)
            continue
        claimed.append((job[0], round_))
        q._finish_ok(job[0])

    # How far "behind" the newest enqueued job the claimed job was, at claim time.
    # If the selector is fair, lag stays bounded (jobs are served roughly in order,
    # not left behind while the opposite class monopolises).
    lags = [r - int(n[1:]) for (n, r) in claimed if n.startswith("F")]
    assert len(claimed) > 200, f"worker barely progressed: {len(claimed)} claims"
    # Every job eventually completes: nothing starved to the end of the run.
    final = q.stats()
    assert final["pending_total"] == 0, f"jobs left unclaimed: {final}"
    # Bounded lag: the oldest unclaimed job at any point didn't wait for the whole
    # run. With aging active, max lag should be well under the run length.
    assert max(lags, default=0) < 300, f"some job waited nearly the whole run: max lag {max(lags)}"


# 12. Aging + weighting combined: even when a large batch ages into priority at the
#     same instant, fresh jobs enqueued afterward still get served within a bounded
#     number of claims (weighted share guarantees it).
def test_fresh_served_after_mass_aging(tmp_path):
    q = _queue(tmp_path, aged_share=0.5, aging_seconds=0.01)
    import time as _t
    # Enqueue a big batch, let it ALL age into priority simultaneously.
    for i in range(60):
        q.enqueue(f"OLD{i}")
    _t.sleep(0.03)
    q._claim(); q._finish_ok("OLD0")  # trigger the aging pass once
    aged_count = q._conn.execute("SELECT COUNT(*) FROM enrich_jobs WHERE priority=1 AND status='queued'").fetchone()[0]
    assert aged_count >= 50, f"expected mass aging, got {aged_count}"
    # Now fresh arrivals must still be served within a bounded window despite the
    # large aged class. Enqueue fresh and count how many claims until it's taken.
    q.enqueue("NEW1")
    q.enqueue("NEW2")
    seen = set()
    for _ in range(40):
        job = q._claim()
        if job is None:
            break
        seen.add(job[0])
        q._finish_ok(job[0])
        if {"NEW1", "NEW2"} <= seen:
            break
    assert {"NEW1", "NEW2"} <= seen, "fresh jobs starved by a mass-aged priority class"
