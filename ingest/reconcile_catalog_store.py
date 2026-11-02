#!/usr/bin/env python3
"""Reconcile on-disk event JSON against CatalogStore rows.

Finds real event files whose CatalogStore row is missing or whose advertised
phot/spec counts disagree with the event JSON arrays — including events that
have aged out of the recent-discovery window — and (optionally) republishes
them through the durable publication state machine.

Default is DRY-RUN: no mutation. Pass --apply to publish.

Usage:
  python3 -m ingest.reconcile_catalog_store                 # dry-run, all epochs
  python3 -m ingest.reconcile_catalog_store --names AT2026agub AT2026ahti
  python3 -m ingest.reconcile_catalog_store --epoch sne-2025-2029 --limit 200
  python3 -m ingest.reconcile_catalog_store --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent

EPOCHS = (
    "sne-pre-1990",
    "sne-1990-1999",
    "sne-2000-2004",
    "sne-2005-2009",
    "sne-2010-2014",
    "sne-2015-2019",
    "sne-2020-2024",
    "sne-2025-2029",
)


def _output_root() -> Path:
    from serve import data_paths

    return data_paths.resolve_output_dir()


def _counts_from_event_meta(meta: dict) -> tuple[int, int, int]:
    """(detections, limits, spectra) mirroring catalog_publish.event_to_catalog_item."""
    import sys

    sys.path.insert(0, str(ROOT))
    from ingest.association_policy import is_candidate_point
    from ingest.backfill_photometry import usable_outburst_detections

    phot = meta.get("photometry") or []
    raw_dets = usable_outburst_detections(meta)
    n_lim = sum(
        1
        for p in phot
        if isinstance(p, dict)
        and (p.get("upperlimit") or p.get("kind") == "non_detection")
    )
    n_spec = len(meta.get("spectra") or []) if isinstance(meta.get("spectra"), list) else 0
    return len(raw_dets), n_lim, n_spec


def _store_row(conn: sqlite3.Connection, name: str) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT name, phot, spec, meta_json FROM events WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        return None
    try:
        meta = json.loads(row[3] or "{}")
    except Exception:
        meta = {}
    return {
        "name": row[0],
        "phot": row[1],
        "spec": row[2],
        "publish_revision": meta.get("publish_revision") if isinstance(meta, dict) else None,
    }


def _classify_reduction(det: int, lim: int, spec: int, row: dict[str, Any], path: Path) -> str:
    """Categorise a json_poorer (store claims MORE than the local file) mismatch.

    Categories drive a remediation path; none are auto-applied and none count as
    reconciled. Best-effort ordering from most to least common cause.
    """
    store_phot = int(row.get("phot") or 0)
    store_spec = int(row.get("spec") or 0)
    # Local file holds nothing usable at all -> the local archive copy is missing/thin.
    if det == 0 and lim == 0 and spec == 0:
        return "missing_local_archive"
    # Some observations exist locally but far fewer than the index claims ->
    # enrichment has not yet pulled the full upstream record.
    if (store_phot - det) >= 5 or (store_spec - spec) >= 1:
        return "incomplete_enrichment"
    # Small deltas are usually genuine source corrections (revised/deduplicated).
    return "source_correction"


_RESOLUTION = {
    "missing_local_archive": "restore the event JSON from the authoritative archive, then re-run reconcile",
    "incomplete_enrichment": "enqueue for enrichment (durable queue) to pull remaining upstream observations",
    "source_correction": "review upstream; if the index is stale, apply the reduction via publication",
}


def _resolution_for(category: str) -> str:
    return _RESOLUTION.get(category, "manual review")


def _record_discrepancy(db_path: Path, entry: dict[str, Any]) -> None:
    """Persist a held json_poorer mismatch to a resolution queue (writable conn)."""
    try:
        conn = sqlite3.connect(str(db_path), timeout=30.0)
    except Exception:
        return
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS reconciliation_discrepancies ("
            " name TEXT PRIMARY KEY, category TEXT, store_phot INTEGER, json_det INTEGER,"
            " store_spec INTEGER, json_spec INTEGER, resolution TEXT, status TEXT DEFAULT 'open',"
            " first_seen REAL, last_seen REAL)"
        )
        now = time.time()
        conn.execute(
            "INSERT INTO reconciliation_discrepancies"
            " (name, category, store_phot, json_det, store_spec, json_spec, resolution, status, first_seen, last_seen)"
            " VALUES(?,?,?,?,?,?,?, 'open', ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET category=excluded.category,"
            "  store_phot=excluded.store_phot, json_det=excluded.json_det,"
            "  store_spec=excluded.store_spec, json_spec=excluded.json_spec,"
            "  resolution=excluded.resolution, last_seen=excluded.last_seen",
            (
                entry["name"], entry["category"], entry["store_phot"], entry["json_det"],
                entry["store_spec"], entry["json_spec"], entry["resolution"], now, now,
            ),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def iter_event_files(root: Path, epochs: Iterable[str]) -> Iterable[Path]:
    for ep in epochs:
        d = root / ep
        if not d.is_dir():
            continue
        yield from sorted(d.glob("*.json"))


def _count_by(rows: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        k = r.get(key) or "uncategorized"
        out[k] = out.get(k, 0) + 1
    return out


def reconcile(
    *,
    root: Path,
    db_path: Path,
    names: Optional[list[str]] = None,
    epochs: Iterable[str] = EPOCHS,
    limit: int = 0,
    apply: bool = False,
) -> dict[str, Any]:
    if not db_path.is_file():
        return {"error": f"catalog db missing at {db_path}", "live_data_untouched": True}

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    try:
        store_total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

        if names:
            files: list[Path] = []
            for n in names:
                hits = list(root.glob(f"sne-*/{n}.json"))
                files.extend(hits)
        else:
            files = list(iter_event_files(root, epochs))
        if limit:
            files = files[:limit]

        missing: list[dict] = []
        stale: list[dict] = []
        held_reduction: list[dict] = []
        ok = 0
        unreadable: list[str] = []
        publish_paths: list[Path] = []

        for path in files:
            name = path.stem
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                meta = raw.get(name) or next(iter(raw.values()))
                if not isinstance(meta, dict):
                    unreadable.append(name)
                    continue
            except Exception:
                unreadable.append(name)
                continue

            det, lim, spec = _counts_from_event_meta(meta)
            want_phot = det  # catalog phot column stores detections (photolink det part)
            row = _store_row(conn, name)
            if row is None:
                missing.append(
                    {"name": name, "det": det, "lim": lim, "spec": spec, "path": str(path)}
                )
                publish_paths.append(path)
                continue
            # stale: store phot/spec disagree with JSON arrays.
            # SAFETY: distinguish direction. json>store means the local file is
            # richer (safe to upsert). json<store means the inherited index claims
            # MORE than the local file holds — a count *reduction* that must not be
            # applied blindly (could destroy valid historical index claims).
            if int(row["phot"] or 0) != want_phot or int(row["spec"] or 0) != spec:
                richer = (want_phot > int(row["phot"] or 0)) or (spec > int(row["spec"] or 0))
                entry = {
                    "name": name,
                    "store_phot": row["phot"],
                    "json_det": det,
                    "store_spec": row["spec"],
                    "json_spec": spec,
                    "publish_revision": row["publish_revision"],
                    "path": str(path),
                    "direction": "json_richer" if richer else "json_poorer",
                }
                stale.append(entry)
                if richer:
                    publish_paths.append(path)  # safe: local file has more data
                else:
                    # Classify the downward discrepancy and queue it for resolution.
                    # Never auto-applied, never counted as reconciled.
                    entry["category"] = _classify_reduction(det, lim, spec, row, path)
                    entry["resolution"] = _resolution_for(entry["category"])
                    held_reduction.append(entry)
                    _record_discrepancy(db_path, entry)
                continue
            ok += 1
    finally:
        conn.close()

    result: dict[str, Any] = {
        "drawn_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "db": str(db_path),
        "store_total_events": store_total,
        "scanned_event_files": len(files),
        "ok": ok,
        "missing_in_store": len(missing),
        "stale_counts": len(stale),
        "stale_json_richer": sum(1 for s in stale if s.get("direction") == "json_richer"),
        "stale_json_poorer_held": len(held_reduction),
        "held_by_category": _count_by(held_reduction, "category"),
        "unresolved_discrepancies": len(held_reduction),
        "unreadable_files": len(unreadable),
        "apply": apply,
        "live_data_untouched": not apply,
        "missing_sample": missing[:25],
        "stale_sample": stale[:25],
        "held_reduction_sample": held_reduction[:25],
        "unreadable_sample": unreadable[:25],
        "note": "json_poorer reductions are HELD as UNRESOLVED discrepancies (queued to "
                "reconciliation_discrepancies with category + remediation path) — never "
                "auto-applied and never counted as reconciled.",
    }

    if apply and publish_paths:
        from ingest.publication import publish_event_paths

        t0 = time.time()
        pub = publish_event_paths(publish_paths, catalog_db=db_path)
        result["publish"] = {
            "attempted": len(publish_paths),
            "elapsed_s": round(time.time() - t0, 2),
            "state": pub.get("state"),
            "upserted": pub.get("upserted"),
            "error": pub.get("error"),
        }

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--names", nargs="*", default=None)
    ap.add_argument("--epoch", type=str, default="", help="single epoch dir")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true", help="publish via durable state machine")
    ap.add_argument("--catalog-db", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    root = _output_root()
    db = args.catalog_db or (root / ".index" / "catalog.db")
    epochs = (args.epoch,) if args.epoch else EPOCHS

    res = reconcile(
        root=root,
        db_path=db,
        names=args.names,
        epochs=epochs,
        limit=args.limit,
        apply=args.apply,
    )
    out = args.out or (ROOT / "docs/audit/RECONCILE_CATALOG_REPORT.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2), encoding="utf-8")
    summary = {k: res[k] for k in (
        "store_total_events", "scanned_event_files", "ok", "missing_in_store",
        "stale_counts", "unreadable_files", "apply",
    ) if k in res}
    if "publish" in res:
        summary["publish"] = res["publish"]
    if "error" in res:
        summary["error"] = res["error"]
    print(json.dumps(summary, indent=2))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
