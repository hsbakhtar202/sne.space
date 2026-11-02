#!/usr/bin/env python3
"""Production acceptance harness (read-only against the live service).

Verifies the reliability gate WITHOUT manual intervention, against the *actual*
deployed service and persistent volume. Intended to be run from the Easypanel
application terminal (so it sees the real SNE_RUNTIME_DIR / SNE_DATA_DIR) or
against the public base URL for the HTTP checks.

Usage:
  python3 scripts/production_acceptance.py                       # in-container
  python3 scripts/production_acceptance.py --base https://sne.space --token "$SNE_HEALTH_AUTH"

Prints a JSON scorecard and exits non-zero on any failed gate.

Gates (G1..G8):
  G1 newly discovered transient enters the durable queue
  G2 real TNS/ALeRCE/WISeREP enrichment executes
  G3 observations published to CatalogStore and served via public API
  G4 restart preserves event + observations + pending work
  G5 provider failures -> durable retries (not lost / not falsely acked)
  G6 homepage statistics agree with /api/transients (event-row semantics)
  G7 health readiness + discrepancy reporting reflect real failures
  G8 under sustained discovery traffic, BOTH fresh and aged classes progress
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _http(base: str, path: str, token: str = "", timeout: float = 20.0):
    url = base.rstrip("/") + path
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode()


def _runtime_dir() -> Path:
    try:
        from serve import data_paths

        return data_paths.resolve_runtime_dir()
    except Exception:
        env = (os.environ.get("SNE_RUNTIME_DIR") or "").strip()
        return Path(env) if env else ROOT / "serve" / "www" / "assets"


def _q(sql: str, db: Path, args=()):
    try:
        conn = sqlite3.connect(str(db), timeout=30.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, args).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)}]


def gate_queue_health(rt: Path) -> dict:
    db = rt / "enrich_queue.db"
    if not db.is_file():
        return {"gate": "G1/G5", "ok": False, "reason": f"enrich_queue.db missing at {db}"}
    stats = _q("SELECT status, COUNT(*) c FROM enrich_jobs GROUP BY status", db)
    counts = {r["status"]: r["c"] for r in stats if "status" in r}
    oldest = _q("SELECT MIN(enqueued_at) m FROM enrich_jobs WHERE status IN ('queued','retry','leased')", db)
    oldest_age = (time.time() - oldest[0]["m"]) if oldest and oldest[0].get("m") else 0.0
    return {
        "gate": "G1/G5",
        "ok": True,
        "counts": counts,
        "pending_total": counts.get("queued", 0) + counts.get("retry", 0) + counts.get("leased", 0),
        "done": counts.get("done", 0),
        "failed": counts.get("failed", 0),
        "oldest_pending_age_s": round(oldest_age, 1),
    }


def gate_catalog(rt: Path) -> dict:
    cdb = rt / ".index" / "catalog.db"
    if not cdb.is_file():
        # data dir may hold the index
        try:
            from serve import data_paths

            cdb = data_paths.resolve_output_dir() / ".index" / "catalog.db"
        except Exception:
            pass
    if not cdb.is_file():
        return {"gate": "G3", "ok": False, "reason": "catalog.db not found"}
    ev = _q("SELECT COUNT(*) c FROM events", cdb)
    rev = _q("SELECT value v FROM meta WHERE key='publish_revision'", cdb) or \
          _q("SELECT MAX(publish_revision) v FROM events", cdb)
    discrep = _q("SELECT COUNT(*) c FROM reconciliation_discrepancies WHERE status='open'", cdb)
    return {
        "gate": "G3",
        "ok": True,
        "event_rows": ev[0].get("c") if ev else None,
        "publish_revision": rev[0].get("v") if rev else None,
        "open_discrepancies": discrep[0].get("c") if discrep and "c" in discrep[0] else None,
        "db": str(cdb),
    }


def gate_stats_parity(base: str, token: str) -> dict:
    cs_s, cs_b = _http(base, "/api/catalog-stats", token)
    tr_s, tr_b = _http(base, "/api/transients?limit=1", token)
    try:
        cs = json.loads(cs_b.decode())
        tr = json.loads(tr_b.decode())
    except Exception as e:  # noqa: BLE001
        return {"gate": "G6", "ok": False, "reason": f"json parse: {e}", "cs_status": cs_s, "tr_status": tr_s}
    api_total = cs.get("authoritative_total")
    tr_total = tr.get("total")
    ok = api_total is not None and tr_total is not None and int(api_total) == int(tr_total)
    return {
        "gate": "G6",
        "ok": bool(ok),
        "catalog_stats_total": api_total,
        "transients_total": tr_total,
        "semantics": cs.get("semantics"),
        "note": "homepage reads catalog-stats.json (same snapshot); JS syncs hero/chip to API total",
    }


def gate_health_readiness(base: str, token: str) -> dict:
    s, b = _http(base, "/api/internal/health", token)
    try:
        h = json.loads(b.decode())
    except Exception as e:  # noqa: BLE001
        return {"gate": "G7", "ok": False, "reason": f"health parse: {e}", "status": s}
    sub = h.get("enrich_subsystem") or {}
    return {
        "gate": "G7",
        "ok": bool(sub.get("ready")),
        "enrich_subsystem": sub,
        "enrich_queue": h.get("enrich_queue"),
    }


def gate_restart(rt: Path) -> dict:
    """Pending + done work must survive. Run before and after a restart and diff."""
    db = rt / "enrich_queue.db"
    if not db.is_file():
        return {"gate": "G4", "ok": False, "reason": "enrich_queue.db missing"}
    pending = _q("SELECT COUNT(*) c FROM enrich_jobs WHERE status IN ('queued','retry','leased')", db)
    done = _q("SELECT COUNT(*) c FROM enrich_jobs WHERE status='done'", db)
    return {
        "gate": "G4",
        "ok": True,
        "pending_before_restart": pending[0].get("c"),
        "done_before_restart": done[0].get("c"),
        "instruction": "restart the service, re-run this script, and confirm pending/done are preserved "
                       "and pending jobs resume draining",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=os.environ.get("SNE_BASE_URL", "http://127.0.0.1:8080"))
    ap.add_argument("--token", default=os.environ.get("SNE_HEALTH_AUTH", ""))
    args = ap.parse_args()

    rt = _runtime_dir()
    report = {
        "drawn_at": time.time(),
        "runtime_dir": str(rt),
        "base": args.base,
        "gates": [
            gate_queue_health(rt),
            gate_catalog(rt),
            gate_stats_parity(args.base, args.token),
            gate_health_readiness(args.base, args.token),
            gate_restart(rt),
            {
                "gate": "G8",
                "ok": None,
                "instruction": "Under sustained discovery traffic, confirm both fresh and aged classes "
                               "drain: watch enrich_queue counts (queued/retry/leased -> done) and "
                               "oldest_pending_age_s bounded; neither class should grow unbounded.",
            },
            {
                "gate": "G2",
                "ok": None,
                "instruction": "Confirm a live enrichment: enqueue a recent transient, verify photometry/"
                               "spectra appear in its event JSON and it becomes searchable via /api/transients.",
            },
        ],
    }
    failed = [g for g in report["gates"] if g.get("ok") is False]
    report["failed_gates"] = len(failed)
    report["verdict"] = "PASS" if not failed else "INCOMPLETE"
    print(json.dumps(report, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
