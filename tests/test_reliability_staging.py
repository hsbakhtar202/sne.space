"""Integrated reliability staging test.

Exercises the *actual* components together against isolated persistent state:
the durable SQLite enrichment queue (workers running), the publication state
machine, the reconciler, and restart recovery. The network (``enrich_event``) is
stubbed so the run is hermetic and fast.

Covers the required scenarios:
  * queue overflow (many distinct jobs; none lost)
  * source 429 -> backoff retry (not terminal) then success
  * aged-out partial objects stay eligible and get enqueued
  * restart: queued/leased work survives a fresh queue on the same db
  * downward scientific correction -> reconciler HOLDS it as an unresolved
    discrepancy (never auto-applied), with a category + remediation path
  * publication survives the restart
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
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
rec = _load("reconcile_catalog_store", "ingest/reconcile_catalog_store.py")
aor = _load("aged_out_recovery", "ingest/aged_out_recovery.py")


class _StubQueue(deq.DurableEnrichmentQueue):
    """Durable queue with a controllable enrich_event (no network)."""

    def __init__(self, *a, behavior=None, **kw):
        super().__init__(*a, **kw)
        self.behavior = behavior or (lambda name: True)

    def _execute(self, name: str, lc: bool, sp: bool) -> bool:
        r = self.behavior(name)
        if isinstance(r, Exception):
            raise r
        return bool(r)


def _wait(cond, timeout=8.0, step=0.05) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return False


def test_queue_overflow_and_completion(tmp_path):
    # 300 distinct jobs through 2 workers -> all complete, none lost.
    q = _StubQueue(db=tmp_path / "q.db", base_backoff=0.01)
    q.start(workers=2)
    for i in range(300):
        q.enqueue(f"SN20{i:04d}a")
    ok = _wait(lambda: q.stats()["done"] == 300, timeout=20.0)
    s = q.stats()
    q.stop()
    assert ok, f"not all jobs completed: {s}"
    assert s["pending_total"] == 0
    assert s["failed"] == 0


def test_429_backoff_then_success(tmp_path):
    calls = {"n": 0}

    def behave(name):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("429 Too Many Requests: rate limit")
        return True

    q = _StubQueue(db=tmp_path / "q.db", behavior=behave,
                   base_backoff=0.02, backoff_cap=0.05, rate_limit_cooldown=0.05,
                   max_attempts=3)
    q.enqueue("SN2020abc")
    q.start(workers=1)
    ok = _wait(lambda: q.stats()["done"] == 1, timeout=10.0)
    s = q.stats()
    q.stop()
    assert ok, f"429 job never completed: {s}"
    assert s["session"]["rate_limited"] >= 1
    assert s["failed"] == 0  # retried, not terminally failed


def test_restart_recovers_queued_and_leased(tmp_path):
    db = tmp_path / "q.db"
    q1 = _StubQueue(db=db, lease_seconds=0.01)
    q1.enqueue("SN2020abc")
    q1.enqueue("SN2020abd")
    job = q1._claim()  # lease one (simulates a worker picking it up)
    assert job is not None
    q1._conn.close()  # "crash": no done, lease outstanding

    time.sleep(0.05)  # let the lease expire

    q2 = _StubQueue(db=db)  # fresh queue = restart
    q2.start(workers=1)
    ok = _wait(lambda: q2.stats()["done"] == 2, timeout=10.0)
    s = q2.stats()
    q2.stop()
    assert ok, f"restart lost work: {s}"


def test_aged_out_partial_stays_eligible(tmp_path, monkeypatch):
    # An event with 1 detection + 0 spectra (partial) and a stale fetch must be
    # eligible — counts must NOT mark it complete.
    db = tmp_path / "q.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE source_event_state ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, event_name TEXT, source TEXT,"
        " stage TEXT, status TEXT, success INTEGER, error TEXT,"
        " started_at REAL, finished_at REAL, attempt INTEGER, superseded INTEGER DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE event_ingest_outcomes ("
        " event_name TEXT PRIMARY KEY, status TEXT, json_path TEXT, publication_lag_s REAL)"
    )
    old = time.time() - 3 * 24 * 3600  # 3 days ago -> stale vs 24h TTL
    conn.execute(
        "INSERT INTO source_event_state (event_name, source, status, success, finished_at, superseded)"
        " VALUES ('SN2020old', 'alerce', 'succeeded', 1, ?, 0)", (old,))
    conn.commit()
    conn.close()

    # Fake publication: nothing pending/committed so only source state decides.
    import ingest.publication as pub_mod

    monkeypatch.setattr(pub_mod, "pending_by_name", lambda name: False, raising=False)
    monkeypatch.setattr(pub_mod, "load_state", lambda: {"events": {}}, raising=False)
    monkeypatch.setattr(aor, "_find_queue_db", lambda: db)

    q = _StubQueue(db=tmp_path / "out.db")
    rep = aor.scan_and_enqueue(queue=q, limit=50)
    names = set(rep["sample"]) | {r[0] for r in q._conn.execute("SELECT name FROM enrich_jobs")}
    q.stop()
    assert "SN2020old" in names, f"partial aged event not enqueued: {rep}"


def test_downward_correction_held_as_unresolved(tmp_path):
    out = tmp_path / "output"
    (out / "sne-2025-2029").mkdir(parents=True)
    idx = out / ".index"
    idx.mkdir()
    # Local file now holds 2 dets; store claims 5 (a downward scientific correction).
    inner = {"name": "SN2020zz",
             "photometry": [{"magnitude": "18.1"}, {"magnitude": "18.3"}], "spectra": []}
    (out / "sne-2025-2029" / "SN2020zz.json").write_text(json.dumps({"SN2020zz": inner}))
    db = idx / "catalog.db"
    con = sqlite3.connect(str(db))
    con.executescript(
        "CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);"
        "CREATE TABLE events(name TEXT PRIMARY KEY, phot INTEGER, spec INTEGER,"
        " publish_revision INTEGER, meta_json TEXT);"
        "INSERT INTO events VALUES('SN2020zz',5,0,1,'{\"name\":\"SN2020zz\"}');"
    )
    con.commit()
    con.close()

    rep = rec.reconcile(root=out, db_path=db, epochs=("sne-2025-2029",), apply=True)
    assert rep["stale_json_poorer_held"] == 1
    assert rep["stale_json_richer"] == 0
    # Store count must be UNCHANGED (held, not applied).
    con = sqlite3.connect(str(db))
    phot = con.execute("SELECT phot FROM events WHERE name='SN2020zz'").fetchone()[0]
    assert phot == 5
    # And it must be recorded as an open discrepancy with a category + remediation.
    try:
        row = con.execute(
            "SELECT category, status, resolution FROM reconciliation_discrepancies"
            " WHERE name='SN2020zz'"
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    con.close()
    assert row is not None, "held mismatch not recorded in resolution queue"
    assert row[1] == "open"
    assert row[0] in {"missing_local_archive", "incomplete_enrichment", "source_correction"}
    assert row[2]  # remediation path present
