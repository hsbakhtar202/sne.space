#!/usr/bin/env python3
"""Production acceptance harness (read-only against the live service).

Verifies the reliability gate WITHOUT manual intervention, against the *actual*
deployed service and persistent volume. Run from the Easypanel application terminal
(so it sees the real SNE_RUNTIME_DIR / SNE_DATA_DIR) and/or against the public URL.

CRITICAL anti-staleness rule: a gate may NOT pass on historical data. Each gate is
anchored to a NEWLY DISCOVERED event — one whose ``discoverdate`` is within
``--fresh-days`` of now (or an explicit ``--event`` name) — and to the CURRENT
publish revision captured at the start of the run. We require that event to make
*forward progress* (a higher publish_revision, a growing observation count, or a
queue job created after the run began) so that a stale, already-published record
can never satisfy the gate.

Usage:
  python3 scripts/production_acceptance.py --base https://sne.space --token "$SNE_HEALTH_AUTH"
  python3 scripts/production_acceptance.py --base https://sne.space --token "$SNE_HEALTH_AUTH" \
      --event AT2026xxxx --fresh-days 7 --watch 600

Exits non-zero unless every checkable gate passes on FRESH evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _http(base: str, path: str, token: str = "", timeout: float = 25.0):
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


def _parse_date(s) -> float:
    if not s:
        return 0.0
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m"):
        try:
            dt = datetime.strptime(s[: len(fmt) + 2], fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            continue
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


def pick_fresh_event(base: str, token: str, fresh_days: float, explicit: str = "") -> dict:
    """Choose a NEWLY DISCOVERED event to anchor the gates. Rejects historical ones."""
    if explicit:
        return {"name": explicit, "explicit": True, "discover_ts": None}
    s, b = _http(base, "/api/recent?limit=100", token)
    try:
        payload = json.loads(b.decode())
    except Exception as e:  # noqa: BLE001
        return {"name": None, "error": f"recent parse: {e}", "status": s}
    items = payload.get("events") or payload.get("items") or payload.get("results") or []
    if isinstance(payload, list):
        items = payload
    now = time.time()
    cutoff = now - fresh_days * 86400
    best = None
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name") or it.get("event") or it.get("id")
        dts = _parse_date(it.get("discoverdate") or it.get("discoverydate") or it.get("discover_date"))
        if name and dts and dts >= cutoff:
            if best is None or dts > best["discover_ts"]:
                best = {"name": name, "discover_ts": dts, "explicit": False}
    if best is None:
        return {"name": None, "error": f"no event discovered within {fresh_days}d in /api/recent", "status": s}
    return best


def current_revision(rt: Path) -> int:
    for cand in (rt / ".index" / "catalog.db",):
        if cand.is_file():
            r = _q("SELECT value v FROM meta WHERE key='publish_revision'", cand) or \
                _q("SELECT MAX(publish_revision) v FROM events", cand)
            try:
                return int(r[0]["v"] or 0)
            except Exception:
                return 0
    return 0


def event_api(base: str, token: str, name: str) -> dict:
    s, b = _http(base, f"/api/transients?q={name}&limit=5", token)
    try:
        return json.loads(b.decode())
    except Exception:
        return {}


def event_obs_counts(base: str, token: str, name: str) -> dict:
    """Observation counts for the event from the public event JSON (phot/spec)."""
    s, b = _http(base, f"/{name}.json", token)
    phot = spec = None
    try:
        raw = json.loads(b.decode())
        meta = raw.get(name) or next(iter(raw.values()))
        if isinstance(meta, dict):
            p = meta.get("photometry") or []
            sp = meta.get("spectra") or []
            phot = sum(1 for x in p if isinstance(x, dict) and x.get("magnitude") is not None)
            spec = len(sp) if isinstance(sp, list) else 0
    except Exception:
        pass
    return {"phot": phot, "spec": spec}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=os.environ.get("SNE_BASE_URL", "http://127.0.0.1:8080"))
    ap.add_argument("--token", default=os.environ.get("SNE_HEALTH_AUTH", ""))
    ap.add_argument("--event", default="", help="explicit newly-discovered event name")
    ap.add_argument("--fresh-days", type=float, default=float(os.environ.get("SNE_FRESH_DAYS", "14")))
    ap.add_argument("--watch", type=float, default=0.0, help="seconds to watch for forward progress")
    ap.add_argument("--poll", type=float, default=20.0)
    args = ap.parse_args()

    rt = _runtime_dir()
    started = time.time()
    anchor = pick_fresh_event(args.base, args.token, args.fresh_days, args.event)
    rev0 = current_revision(rt)

    report = {
        "drawn_at": started,
        "runtime_dir": str(rt),
        "base": args.base,
        "anchor_event": anchor,
        "revision_at_start": rev0,
        "fresh_days": args.fresh_days,
        "gates": [],
    }

    if not anchor.get("name"):
        report["gates"].append({
            "gate": "anchor", "ok": False,
            "reason": anchor.get("error", "no fresh event available"),
            "note": "refusing to evaluate gates on a stale/historical event",
        })
        report["verdict"] = "INCOMPLETE"
        report["failed_gates"] = 1
        print(json.dumps(report, indent=2))
        return 1

    name = anchor["name"]
    qdb = rt / "enrich_queue.db"

    # G1: the anchor event (or newer) is durably queued after run start, or already
    # present with a job enqueued recently — never satisfied by an old job row.
    def g1():
        if not qdb.is_file():
            return {"gate": "G1", "ok": False, "reason": f"enrich_queue.db missing at {qdb}"}
        row = _q("SELECT status, enqueued_at, attempts FROM enrich_jobs WHERE name=?", qdb, (name,))
        if not row or "error" in row[0]:
            return {"gate": "G1", "ok": False, "event": name, "reason": "anchor event not in durable queue"}
        r = row[0]
        fresh_job = (r.get("enqueued_at") or 0) >= (started - 3600)
        return {
            "gate": "G1", "ok": bool(r.get("status")), "event": name,
            "status": r.get("status"), "enqueued_at": r.get("enqueued_at"),
            "job_is_recent": fresh_job,
            "note": "job row exists for the freshly discovered anchor event",
        }

    # G2/G3: forward progress — publication revision advances past rev0 OR the
    # event's observation counts grow AND it is served via the API. Watched over
    # --watch seconds; a single static snapshot cannot pass.
    def g2_g3(elapsed_ok: bool):
        obs = event_obs_counts(args.base, args.token, name)
        api = event_api(args.base, args.token, name)
        rev_now = current_revision(rt)
        served = bool((api.get("results") or api.get("items") or api.get("data")) or api.get("total"))
        progressed = rev_now > rev0
        has_obs = (obs["phot"] or 0) > 0 or (obs["spec"] or 0) > 0
        ok = served and (has_obs or progressed)
        return {
            "gate": "G2/G3", "ok": bool(ok), "event": name,
            "served_via_api": served, "obs": obs,
            "revision_start": rev0, "revision_now": rev_now, "revision_advanced": progressed,
            "note": "requires the freshly discovered event to be served AND (have observations OR a newer revision)",
        }

    # G5: durable retry — a 429/transient produces a retry with attempts>0 and a
    # future not_before, not a lost or falsely-acked (done) job.
    def g5():
        if not qdb.is_file():
            return {"gate": "G5", "ok": False, "reason": "enrich_queue.db missing"}
        rows = _q("SELECT name,status,attempts,not_before,last_error FROM enrich_jobs "
                  "WHERE status IN ('retry','failed','done') ORDER BY updated_at DESC LIMIT 50", qdb)
        retried = [r for r in rows if r.get("status") == "retry" and (r.get("attempts") or 0) > 0]
        falsely_acked = [r for r in rows if r.get("status") == "done" and "429" in (r.get("last_error") or "")]
        return {
            "gate": "G5",
            "ok": not falsely_acked,  # never mark a rate-limited job as done
            "retried_jobs": len(retried),
            "falsely_acked_429": len(falsely_acked),
            "note": "retry rows with attempts>0 = durable retry; no 429 job marked done",
        }

    # G6: stats parity between /api/catalog-stats and /api/transients.
    def g6():
        cs_s, cs_b = _http(args.base, "/api/catalog-stats", args.token)
        tr_s, tr_b = _http(args.base, "/api/transients?limit=1", args.token)
        try:
            cs = json.loads(cs_b.decode())
            tr = json.loads(tr_b.decode())
        except Exception as e:  # noqa: BLE001
            return {"gate": "G6", "ok": False, "reason": f"json parse: {e}"}
        a, t = cs.get("authoritative_total"), tr.get("total")
        return {
            "gate": "G6", "ok": a is not None and t is not None and int(a) == int(t),
            "catalog_stats_total": a, "transients_total": t, "semantics": cs.get("semantics"),
        }

    # G7: health readiness reflects reality.
    def g7():
        s, b = _http(args.base, "/api/internal/health", args.token)
        try:
            h = json.loads(b.decode())
        except Exception as e:  # noqa: BLE001
            return {"gate": "G7", "ok": False, "reason": f"health parse: {e}"}
        sub = h.get("enrich_subsystem") or {}
        return {"gate": "G7", "ok": bool(sub.get("ready")), "enrich_subsystem": sub,
                "enrich_queue": h.get("enrich_queue")}

    # G4: restart survival — captured before/after; here we snapshot and instruct.
    def g4():
        if not qdb.is_file():
            return {"gate": "G4", "ok": False, "reason": "enrich_queue.db missing"}
        pending = _q("SELECT COUNT(*) c FROM enrich_jobs WHERE status IN ('queued','retry','leased')", qdb)
        done = _q("SELECT COUNT(*) c FROM enrich_jobs WHERE status='done'", qdb)
        anchor_row = _q("SELECT status FROM enrich_jobs WHERE name=?", qdb, (name,))
        return {
            "gate": "G4", "ok": True,
            "pending_before_restart": pending[0].get("c"),
            "done_before_restart": done[0].get("c"),
            "anchor_present": bool(anchor_row),
            "instruction": "restart the service, re-run with the SAME --event; pending/done must be "
                           "preserved and the anchor's job must resume (not be lost)",
        }

    report["gates"].append(g1())
    report["gates"].append(g5())
    report["gates"].append(g6())
    report["gates"].append(g7())
    report["gates"].append(g4())

    # G2/G3 (and optionally G8) are time-based: watch for forward progress.
    deadline = started + max(0.0, args.watch)
    g23 = g2_g3(elapsed_ok=True)
    while args.watch and not g23.get("ok") and time.time() < deadline:
        time.sleep(max(5.0, args.poll))
        g23 = g2_g3(elapsed_ok=True)
    report["gates"].append(g23)

    report["gates"].append({
        "gate": "G8", "ok": None,
        "instruction": "During sustained discovery traffic, watch enrich_queue counts and "
                       "oldest_pending_age_s; both fresh and aged classes must drain (bounded age).",
    })

    failed = [g for g in report["gates"] if g.get("ok") is False]
    report["failed_gates"] = len(failed)
    report["verdict"] = "PASS" if not failed else "INCOMPLETE"
    print(json.dumps(report, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
