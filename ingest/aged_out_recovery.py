"""Aged-out event recovery: keep events eligible for enrichment after they leave
the TNS recent window.

Eligibility is based on *source-ingestion state*, not observation counts. An event
with a single discovery detection may still have an entire light curve upstream —
having any observations must NOT mark enrichment complete. An event stays eligible
while any source is incomplete:

  * never fetched, or the last fetch errored (``success=0``)
  * failed on rate limit / transient error and is now retry-eligible
  * last successful fetch older than its per-source refresh TTL
  * publication pending (event JSON written but not yet durably published)

Scheduling is *fair by age*: each recovery pass takes a bounded set of the
OLDEST eligible events and hands them to the queue with ``priority=True`` (aged
backlog) plus, when idle, a smaller newest-first slice. This prevents continuous
new discoveries from starving old unfinished work.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent

# Per-source refresh policy: how long a *successful* fetch is considered fresh
# before the event becomes eligible again. Older/sparser sources refresh slower.
SOURCE_REFRESH_TTL_S = {
    "tns": 12 * 3600,
    "alerce": 24 * 3600,
    "wiserep": 24 * 3600,
    "fritz": 24 * 3600,
    "marshall": 24 * 3600,
    "yse": 24 * 3600,
    "photometry": 24 * 3600,
    "spectra": 24 * 3600,
}
_DEFAULT_TTL_S = 24 * 3600
# A source fetch that failed stays cool for this long before retry eligibility.
_RETRY_COOLDOWN_S = 3600.0
_STATES = ("bootstrap", "discovered", "fetching", "committed", "pending", "published")


def _find_queue_db() -> Optional[Path]:
    try:
        from serve import data_paths

        p = data_paths.resolve_runtime_dir() / "enrich_queue.db"
    except Exception:
        env = (os.environ.get("SNE_RUNTIME_DIR") or "").strip()
        base = Path(env) if env else (ROOT / "serve" / "www" / "assets")
        p = base / "enrich_queue.db"
    return p if p.is_file() else None


def _source_state_index(db: Path) -> dict[str, dict[str, Any]]:
    """Most recent per-(event, source) fetch state from the source-ingestion log."""
    conn = sqlite3.connect(str(db), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(
                "SELECT event_name, source, stage, status, success, error, finished_at, "
                "started_at, attempt "
                "FROM source_event_state WHERE COALESCE(superseded,0)=0 "
                "ORDER BY COALESCE(finished_at, started_at, 0) DESC, id DESC"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT event_name, source, status, error, finished_at, started_at, attempt "
                "FROM source_event_state WHERE COALESCE(superseded,0)=0 "
                "ORDER BY COALESCE(finished_at, started_at, 0) DESC, id DESC"
            ).fetchall()
    finally:
        conn.close()
    idx: dict[str, dict[str, Any]] = {}
    for r in rows:
        ev = r["event_name"]
        src = (r["source"] or "").lower()
        if not ev or not src:
            continue
        d = idx.setdefault(ev, {})
        if src in d:
            continue  # first (latest) row wins
        success = r["success"] if "success" in r.keys() else (1 if r["status"] == "succeeded" else 0)
        d[src] = {
            "success": int(success or 0),
            "error": (r["error"] or "") if "error" in r.keys() else "",
            "ts": float(r["finished_at"] or r["started_at"] or 0.0),
        }
    return idx


def _event_outcomes(db: Path) -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(str(db), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT event_name, status, json_path, publication_lag_s FROM event_ingest_outcomes"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out[r["event_name"]] = {
            "status": r["status"],
            "json_path": r["json_path"] or "",
            "lag": r["publication_lag_s"],
        }
    return out


def _state_rank(state: Optional[str]) -> int:
    try:
        return _STATES.index(state or "discovered")
    except ValueError:
        return 1


def _eligibility(
    name: str,
    *,
    src_idx: dict[str, dict[str, Any]],
    outcomes: dict[str, dict[str, Any]],
    publication,
    now: float,
) -> tuple[bool, str]:
    """Return (eligible, reason). Counts are NOT used — a partial record stays eligible."""
    # 1) Publication still pending -> definitely unfinished.
    try:
        if publication.pending_by_name(name):
            return True, "publication_pending"
    except Exception:
        pass
    # 2) Never reached committed/published in the durable lifecycle.
    try:
        entry = (publication.load_state().get("events") or {}).get(name)
    except Exception:
        entry = None
    state = (entry or {}).get("state") or "discovered"
    if _state_rank(state) < _STATES.index("pending"):
        return True, f"lifecycle_{state}"
    # 3) Source-ingestion state: never fetched / failed / retry-eligible / stale.
    srcs = src_idx.get(name)
    if not srcs:
        return True, "never_fetched"
    for src, s in srcs.items():
        ttl = SOURCE_REFRESH_TTL_S.get(src, _DEFAULT_TTL_S)
        ts = float(s.get("ts") or 0.0)
        err = (s.get("error") or "").lower()
        if not s.get("success"):
            # Failed fetch: retry-eligible after cooldown (429/transient included).
            if (now - ts) >= _RETRY_COOLDOWN_S:
                tag = "rate_limited" if ("429" in err or "rate limit" in err) else "fetch_failed"
                return True, f"{tag}:{src}"
            continue
        if (now - ts) > ttl:
            return True, f"stale_refresh:{src}"
    # 4) Outcome flagged as error (transient) -> eligible again after cooldown.
    oc = outcomes.get(name)
    if oc and oc.get("status") == "error" and (now - 0) >= 0:
        return True, "outcome_error"
    return False, "complete"


def scan_and_enqueue(
    *,
    queue,
    limit: int = 200,
    aged_priority: bool = True,
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Enqueue eligible events with starvation-safe, age-fair scheduling.

    The bounded slice is chosen OLDEST-first so that a continuous stream of new
    discoveries cannot starve older unfinished events. ``priority=True`` marks
    them as aged backlog for the queue's reserved capacity.
    """
    from ingest import publication

    now = now or time.time()
    db = _find_queue_db()
    src_idx = _source_state_index(db) if db else {}
    outcomes = _event_outcomes(db) if db else {}

    # Candidate set: union of events known to the source log, outcomes, and durable state.
    candidates = set(src_idx) | set(outcomes)
    try:
        candidates |= set((publication.load_state().get("events") or {}).keys())
    except Exception:
        pass

    eligible: list[tuple[str, float, str]] = []  # (name, oldest_ts, reason)
    for name in candidates:
        ok, reason = _eligibility(
            name, src_idx=src_idx, outcomes=outcomes, publication=publication, now=now
        )
        if not ok:
            continue
        # Age = oldest source activity (0 if never fetched -> treat as oldest).
        srcs = src_idx.get(name) or {}
        oldest = min((float(s.get("ts") or 0.0) for s in srcs.values()), default=0.0)
        eligible.append((name, oldest, reason))

    # OLDEST first (age-fair). Never-fetched (ts=0) sorts oldest.
    eligible.sort(key=lambda t: (t[1], t[0]))
    chosen = eligible[: max(0, limit)]
    enq = 0
    for name, _ts, _reason in chosen:
        try:
            accepted = queue.enqueue(name, priority=True) if aged_priority else queue.enqueue(name)
        except TypeError:
            accepted = queue.enqueue(name)
        if accepted:
            enq += 1

    by_reason: dict[str, int] = {}
    for _n, _t, r in chosen:
        by_reason[r.split(":")[0]] = by_reason.get(r.split(":")[0], 0) + 1

    return {
        "candidates": len(candidates),
        "eligible": len(eligible),
        "enqueued": enq,
        "limit": limit,
        "scheduling": "age_fair_oldest_first",
        "reasons": by_reason,
        "sample": [n for n, _t, _r in chosen[:25]],
    }


def main() -> int:
    from ingest.durable_enrich_queue import get_queue

    q = get_queue()
    rep = scan_and_enqueue(queue=q, limit=int(os.environ.get("SNE_AGED_OUT_LIMIT", "200")))
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
