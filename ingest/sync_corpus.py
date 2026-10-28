#!/usr/bin/env python3
"""Compare/merge event corpora for production sync (default: dry-run).

Merge direction: local recovered corpus → remote (production/staging) target.

Rules:
  - Union photometry by candid / (kind,time,band,telescope)
  - On same key with magnitude conflict: keep remote, flag conflict
  - Never delete remote-only events or remote-only points
  - Classification/claimedtype conflicts: keep remote, flag
  - Apply uses ``event_file_lock`` + re-read before merge (RMW-safe)
  - Apply refuses without ``--i-understand``

Example:
  python3 -m ingest.sync_corpus \\
    --local /path/to/recovered/output \\
    --remote /path/to/production/output \\
    --years 2025 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.alerce import photometry_dedupe_key  # noqa: E402
from ingest.event_file_lock import event_file_lock  # noqa: E402
from ingest.manager import atomic_write_json  # noqa: E402

MAG_TOL = 0.05


def _load_event(path: Path) -> Optional[Tuple[str, dict]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict) or not raw:
        return None
    name = next(iter(raw))
    meta = raw[name]
    if not isinstance(meta, dict):
        return None
    return name, meta


def _discovery_year(meta: dict) -> int:
    dd = meta.get("discoverdate")
    if isinstance(dd, list) and dd and isinstance(dd[0], dict):
        disc = str(dd[0].get("value") or "")
        if disc[:4].isdigit():
            return int(disc[:4])
    return 0


def _claimedtype(meta: dict) -> str:
    ct = meta.get("claimedtype")
    if isinstance(ct, list) and ct and isinstance(ct[0], dict):
        return str(ct[0].get("value") or "").strip()
    if isinstance(ct, str):
        return ct.strip()
    return ""


def merge_event_into_remote(
    remote_meta: dict,
    local_meta: dict,
    *,
    mag_tol: float = MAG_TOL,
) -> Dict[str, Any]:
    """Merge local into a copy of remote_meta. Returns (merged_meta, report)."""
    merged = json.loads(json.dumps(remote_meta))  # deep copy via JSON
    report: Dict[str, Any] = {
        "would_add": 0,
        "conflicts": [],
        "class_conflicts": [],
        "preserved_remote_points": 0,
        "added_points": [],
    }

    remote_ph = [p for p in (merged.get("photometry") or []) if isinstance(p, dict)]
    local_ph = [p for p in (local_meta.get("photometry") or []) if isinstance(p, dict)]
    report["preserved_remote_points"] = len(remote_ph)
    keys = {photometry_dedupe_key(p): i for i, p in enumerate(remote_ph)}

    for p in local_ph:
        k = photometry_dedupe_key(p)
        if k not in keys:
            remote_ph.append(p)
            keys[k] = len(remote_ph) - 1
            report["would_add"] += 1
            report["added_points"].append({
                "key": list(k) if isinstance(k, tuple) else k,
                "magnitude": p.get("magnitude"),
                "association_status": p.get("association_status"),
            })
            continue
        existing = remote_ph[keys[k]]
        try:
            if abs(float(existing.get("magnitude")) - float(p.get("magnitude"))) > mag_tol:
                report["conflicts"].append({
                    "key": list(k) if isinstance(k, tuple) else k,
                    "remote_mag": existing.get("magnitude"),
                    "local_mag": p.get("magnitude"),
                    "action": "keep_remote",
                })
        except Exception:
            pass

    merged["photometry"] = remote_ph

    # Classification: keep remote if set; flag conflict when both set and differ
    r_ct = _claimedtype(merged)
    l_ct = _claimedtype(local_meta)
    if r_ct and l_ct and r_ct.lower() != l_ct.lower():
        report["class_conflicts"].append({
            "remote": r_ct,
            "local": l_ct,
            "action": "keep_remote",
        })
    elif not r_ct and l_ct:
        merged["claimedtype"] = local_meta.get("claimedtype")

    # Spectra: keep remote; fill only when remote empty
    if not (merged.get("spectra") or []) and (local_meta.get("spectra") or []):
        merged["spectra"] = local_meta["spectra"]

    # Backfill provenance: keep newer remote _backfill if present; else take local
    r_bf = merged.get("_backfill") if isinstance(merged.get("_backfill"), dict) else None
    l_bf = local_meta.get("_backfill") if isinstance(local_meta.get("_backfill"), dict) else None
    if l_bf and (not r_bf or str(l_bf.get("updated_utc") or "") > str(r_bf.get("updated_utc") or "")):
        if r_bf and r_bf.get("updated_utc") and l_bf.get("updated_utc"):
            if str(r_bf["updated_utc"]) >= str(l_bf["updated_utc"]):
                pass  # keep remote
            else:
                merged["_backfill"] = l_bf
        elif not r_bf:
            merged["_backfill"] = l_bf

    report["conflict_count"] = len(report["conflicts"])
    report["class_conflict_count"] = len(report["class_conflicts"])
    return {"merged": merged, "report": report}


def merge_photometry_union(prod: dict, local: dict, mag_tol: float = MAG_TOL) -> dict:
    """Dry-run stats wrapper (backward compatible)."""
    out = merge_event_into_remote(prod, local, mag_tol=mag_tol)
    r = out["report"]
    return {
        "production_points": r["preserved_remote_points"],
        "local_points": len([p for p in (local.get("photometry") or []) if isinstance(p, dict)]),
        "would_add": r["would_add"],
        "conflicts": r["conflict_count"],
        "class_conflicts": r["class_conflict_count"],
        "conflict_samples": r["conflicts"][:5],
        "add_samples": r["added_points"][:5],
    }


def apply_merge_to_remote_file(
    remote_path: Path,
    local_meta: dict,
    *,
    staging_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """RMW-safe apply: lock → re-read remote → merge → atomic write (or staging)."""
    with event_file_lock(remote_path):
        loaded = _load_event(remote_path)
        if not loaded:
            return {"status": "missing_remote", "path": str(remote_path)}
        name, remote_meta = loaded
        out = merge_event_into_remote(remote_meta, local_meta)
        envelope = {name: out["merged"]}
        if staging_dir is not None:
            staging_dir.mkdir(parents=True, exist_ok=True)
            dest = staging_dir / remote_path.name
            dest.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
            return {"status": "staged", "path": str(dest), "report": out["report"]}
        written = atomic_write_json(remote_path, envelope, skip_if_unchanged=True)
        return {
            "status": "written" if written else "unchanged",
            "path": str(remote_path),
            "report": out["report"],
        }


def post_sync_cache_notes() -> dict:
    """Document what production must refresh after sync. Not auto-run against live."""
    return {
        "event_page_cache": (
            "Rendered pages are versioned by event-file st_mtime_ns+size. "
            "Atomic rewrite bumps mtime → next request misses cache."
        ),
        "catalog_publication": (
            "After apply, sync_corpus batch-publishes via ingest.catalog_publish: "
            "writes published-updates.min.json overlay + CatalogStore.upsert_catalog_items. "
            "Live /catalog merges overlay by name (no full 110k rewrite). "
            "Quarantine flags are preserved; candidate photometry is not promoted."
        ),
        "required_ops_steps": [
            "1. Backup sne_data volume (--backup-remote)",
            "2. Sync event JSON under event_file_lock",
            "3. Automatic batch catalog publish (overlay + SQLite upsert)",
            "4. Spot-check event page photometry vs catalog photolink vs CatalogStore.phot",
        ],
    }


def _index_corpus(root: Path) -> Dict[str, Path]:
    if not root.is_dir():
        return {}
    return {p.name: p for p in root.glob("sne-*/**/*.json")}


def run_compare(
    local_root: Path,
    remote_root: Path,
    years: set[int],
    *,
    apply: bool = False,
    staging_dir: Optional[Path] = None,
) -> dict:
    local_files = _index_corpus(local_root)
    remote_files = _index_corpus(remote_root)
    summary: Dict[str, Any] = {
        "local_only": 0,
        "remote_only": 0,
        "both": 0,
        "would_add_points": 0,
        "conflicts": 0,
        "class_conflicts": 0,
        "files_compared": 0,
        "applied": 0,
        "dry_run": not apply,
        "cache_notes": post_sync_cache_notes(),
        "published": None,
    }
    details = []
    remote_only_names = set(remote_files) - set(local_files)
    applied_paths: List[Path] = []

    for fname, lpath in sorted(local_files.items()):
        loaded = _load_event(lpath)
        if not loaded:
            continue
        ename, lmeta = loaded
        year = _discovery_year(lmeta)
        if years and year not in years:
            continue
        rpath = remote_files.get(fname)
        if rpath is None:
            summary["local_only"] += 1
            continue
        rloaded = _load_event(rpath)
        if not rloaded:
            summary["local_only"] += 1
            continue
        summary["both"] += 1
        summary["files_compared"] += 1
        _, rmeta = rloaded
        m = merge_photometry_union(rmeta, lmeta)
        summary["would_add_points"] += m["would_add"]
        summary["conflicts"] += m["conflicts"]
        summary["class_conflicts"] += m.get("class_conflicts", 0)
        if m["would_add"] or m["conflicts"] or m.get("class_conflicts"):
            details.append({"name": ename, **m})
        if apply:
            res = apply_merge_to_remote_file(rpath, lmeta, staging_dir=staging_dir)
            if res.get("status") in {"written", "staged"}:
                summary["applied"] += 1
                if res.get("status") == "written":
                    applied_paths.append(rpath)
                elif res.get("status") == "staged" and res.get("path"):
                    applied_paths.append(Path(res["path"]))

    # Count remote-only within year filter when possible
    remote_only_year = 0
    for fname in remote_only_names:
        loaded = _load_event(remote_files[fname])
        if not loaded:
            continue
        _, meta = loaded
        y = _discovery_year(meta)
        if not years or y in years or y == 0:
            remote_only_year += 1
    summary["remote_only"] = remote_only_year
    summary["sample_details"] = details[:30]

    # Batch catalog publication after successful writes (not staging-only dry paths)
    if apply and applied_paths and staging_dir is None:
        try:
            from ingest.catalog_publish import publish_event_files
            summary["published"] = publish_event_files(applied_paths)
        except Exception as exc:  # noqa: BLE001
            summary["published"] = {"error": str(exc)}
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Corpus sync dry-run / apply")
    ap.add_argument("--local", type=Path, required=True)
    ap.add_argument("--remote", type=Path, required=True, help="Production (or staging) corpus root")
    ap.add_argument("--years", default="2025")
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--i-understand", action="store_true")
    ap.add_argument("--staging", type=Path, default=None, help="Write merges here instead of remote")
    ap.add_argument("--backup-remote", type=Path, default=None, help="Copy remote tree here before apply")
    ap.add_argument("--out", type=Path, default=Path("/tmp/sync_dry_run_summary.json"))
    args = ap.parse_args()
    if args.apply and not args.i_understand:
        print("Refusing --apply without --i-understand", file=sys.stderr)
        return 2

    years = {int(y) for y in args.years.split(",") if y.strip()}
    if args.apply and args.backup_remote:
        args.backup_remote.parent.mkdir(parents=True, exist_ok=True)
        if args.backup_remote.exists():
            shutil.rmtree(args.backup_remote)
        shutil.copytree(args.remote, args.backup_remote)

    summary = run_compare(
        args.local,
        args.remote,
        years,
        apply=args.apply,
        staging_dir=args.staging,
    )
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
