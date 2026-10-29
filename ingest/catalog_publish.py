#!/usr/bin/env python3
"""Batch-publish event-file updates into catalog listings + CatalogStore.

Synchronization can rewrite hundreds of event JSON files while ``catalog.min.json``
and the SQLite index still show stale ``photolink`` values. This module:

1. Converts updated event files into catalog-shaped items
2. Merges them into an idempotent overlay (``published-updates.min.json``)
3. Upserts those rows into CatalogStore without a full 110k rebuild
4. Exposes helpers the live server uses to merge overlay-by-name into the
   public catalog payload

Quarantine is preserved: candidate/unverified photometry is never promoted.
``photolink`` counts raw outburst-window detections (incl. unverified) so the
listing reflects recovered observations; ``verified_phot`` is stored on the
item for scientific-acceptance reporting.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.association_policy import is_candidate_point  # noqa: E402
from ingest.backfill_photometry import (  # noqa: E402
    usable_outburst_detections,
    verified_outburst_detections,
)
from ingest.manager import SUPERNOVAE_OUTPUT, atomic_write_json  # noqa: E402

OVERLAY_NAME = "published-updates.min.json"


def overlay_path() -> Path:
    """Resolve overlay path at call time (honours current ``SNE_RUNTIME_DIR``)."""
    try:
        from serve import data_paths
        # Re-resolve each call — module-level RUNTIME_DIR is fixed at import.
        d = data_paths.resolve_runtime_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d / OVERLAY_NAME
    except Exception:
        p = ROOT / "serve" / "www" / "assets" / OVERLAY_NAME
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def _val(meta: dict, key: str) -> str:
    v = meta.get(key)
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return str(v[0].get("value") or "").strip()
    if isinstance(v, str):
        return v.strip()
    return ""


def event_to_catalog_item(name: str, meta: dict) -> dict[str, Any]:
    """Build a catalog.min.json-shaped record from an on-disk event body."""
    raw_dets = usable_outburst_detections(meta)
    ver_dets = verified_outburst_detections(meta)
    n_lim = sum(
        1
        for p in (meta.get("photometry") or [])
        if isinstance(p, dict)
        and (p.get("upperlimit") or p.get("kind") == "non_detection")
    )
    n_spec = len(meta.get("spectra") or [])
    aliases = []
    for a in meta.get("alias") or []:
        aval = a.get("value") if isinstance(a, dict) else str(a)
        if aval and aval != name and aval not in aliases:
            aliases.append(str(aval))
    claimed = _val(meta, "claimedtype") or "unclassified"
    disc = _val(meta, "discoverdate")
    host = _val(meta, "host")
    z = _val(meta, "redshift")
    # Listing magnitude: prefer explicit maxappmag, else discovery mag. Kind must
    # stay honest — a lone discovery point is not a fitted peak.
    mag = _val(meta, "maxappmag")
    mag_kind = ""
    mm = meta.get("maxappmag")
    if isinstance(mm, list) and mm and isinstance(mm[0], dict):
        mag_kind = str(mm[0].get("kind") or "")
    if not mag:
        mag = _val(meta, "discoverymag")
        if mag:
            mag_kind = "discovery"
    elif not mag_kind:
        mag_kind = "brightest_observed" if len(raw_dets) >= 2 else "discovery"
    mag_entry = []
    if mag:
        mag_entry = [{"value": mag, "kind": mag_kind or "discovery"}]
    item: dict[str, Any] = {
        "name": name,
        "alias": [{"value": name}] + [{"value": a} for a in aliases],
        "discoverer": [{"value": _val(meta, "discoverer")}] if _val(meta, "discoverer") else [],
        "discoverdate": [{"value": disc}] if disc else [],
        "maxdate": [{"value": _val(meta, "maxdate")}] if _val(meta, "maxdate") else [],
        "maxappmag": mag_entry,
        "ra": [{"value": _val(meta, "ra")}] if _val(meta, "ra") else [],
        "dec": [{"value": _val(meta, "dec")}] if _val(meta, "dec") else [],
        "claimedtype": [{"value": claimed}],
        "photolink": f"{len(raw_dets)},{n_lim}",
        "spectralink": str(n_spec),
        # Extension fields (ignored by older clients; used for agreement tests)
        "verified_phot": len(ver_dets),
        "raw_phot": len(raw_dets),
        "quarantined": any(
            isinstance(p, dict) and is_candidate_point(p) for p in (meta.get("photometry") or [])
        ),
    }
    if host:
        item["host"] = [{"value": host}]
    if z:
        item["redshift"] = [{"value": z}]
    return item


def load_event_file(path: Path) -> Optional[tuple[str, dict]]:
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


def merge_overlay(existing: List[dict], updates: Sequence[dict]) -> List[dict]:
    """Idempotent name-keyed merge; later updates win."""
    by_name = {str(i.get("name")): i for i in existing if isinstance(i, dict) and i.get("name")}
    for u in updates:
        if isinstance(u, dict) and u.get("name"):
            by_name[str(u["name"])] = u
    return list(by_name.values())


def apply_overlay_to_catalog_list(base: List[dict], overlay: List[dict]) -> List[dict]:
    """Replace matching names in ``base`` with overlay items; prepend new names."""
    if not overlay:
        return base
    by_name = {str(i.get("name")): i for i in overlay if isinstance(i, dict) and i.get("name")}
    out = []
    seen = set()
    for row in base:
        if not isinstance(row, dict):
            continue
        n = str(row.get("name") or "")
        if n in by_name:
            out.append(by_name.pop(n))
            seen.add(n)
        else:
            out.append(row)
    # New events not in base
    for n, item in by_name.items():
        if n not in seen:
            out.insert(0, item)
    return out


def atomic_write_json_array(path: Path, items: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(items, separators=(",", ":"))
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        raise


def publish_catalog_items(
    items: Sequence[dict],
    *,
    catalog_db: Optional[Path] = None,
    write_overlay: bool = True,
    overlay_file: Optional[Path] = None,
) -> dict[str, Any]:
    """Upsert catalog-shaped rows into overlay + CatalogStore (no event JSON required).

    Used by ``pull_recent`` so discovery stubs enter SQLite immediately — before
    enrichment finishes — so ``/api/transients`` agrees with the homepage SSR.
    """
    clean = [i for i in items if isinstance(i, dict) and i.get("name")]
    result: dict[str, Any] = {
        "items": len(clean),
        "overlay_path": str(overlay_file or overlay_path()),
        "upserted": 0,
        "quarantine_preserved": sum(1 for i in clean if i.get("quarantined")),
    }
    if not clean:
        return result

    if write_overlay:
        op = Path(overlay_file) if overlay_file is not None else overlay_path()
        existing: List[dict] = []
        if op.is_file():
            try:
                raw = json.loads(op.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    existing = [x for x in raw if isinstance(x, dict)]
            except Exception:
                existing = []
        merged = merge_overlay(existing, clean)
        atomic_write_json_array(op, merged)
        result["overlay_size"] = len(merged)

    db_path = catalog_db
    if db_path is None:
        db_path = Path(SUPERNOVAE_OUTPUT) / ".index" / "catalog.db"
    if db_path.is_file():
        from serve.catalog_store import CatalogStore

        store = CatalogStore(db_path)
        store.load_existing()
        result["upserted"] = store.upsert_catalog_items(clean)
    else:
        result["upserted"] = 0
        result["note"] = f"no catalog db at {db_path}; overlay written only"

    return result


def publish_event_files(
    paths: Iterable[Path],
    *,
    catalog_db: Optional[Path] = None,
    write_overlay: bool = True,
) -> dict[str, Any]:
    """Batch-publish event files → overlay + CatalogStore upsert."""
    items: List[dict] = []
    for path in paths:
        loaded = load_event_file(Path(path))
        if not loaded:
            continue
        name, meta = loaded
        items.append(event_to_catalog_item(name, meta))
    return publish_catalog_items(
        items, catalog_db=catalog_db, write_overlay=write_overlay
    )


def publish_names(names: Sequence[str], **kwargs: Any) -> dict[str, Any]:
    root = Path(SUPERNOVAE_OUTPUT)
    paths = []
    for name in names:
        hits = list(root.glob(f"sne-*/{name}.json"))
        paths.extend(hits)
    return publish_event_files(paths, **kwargs)


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch-publish event updates into catalog overlay + SQLite")
    ap.add_argument("--files", nargs="*", default=[], help="Event JSON paths")
    ap.add_argument("--names", nargs="*", default=[], help="Event names to locate under SUPERNOVAE_OUTPUT")
    ap.add_argument("--from-checkpoint", action="store_true", help="Publish all checkpoint-completed names")
    ap.add_argument(
        "--folder",
        type=str,
        default="",
        help="Glob folder under SUPERNOVAE_OUTPUT (e.g. sne-2025-2029) to republish metadata",
    )
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--catalog-db", type=Path, default=None)
    args = ap.parse_args()

    paths: List[Path] = [Path(p) for p in args.files]
    if args.names:
        root = Path(SUPERNOVAE_OUTPUT)
        for n in args.names:
            paths.extend(root.glob(f"sne-*/{n}.json"))
    if args.folder:
        folder = Path(SUPERNOVAE_OUTPUT) / args.folder
        if folder.is_dir():
            paths.extend(sorted(folder.glob("*.json")))
    if args.from_checkpoint:
        from ingest.backfill_photometry import load_checkpoint
        completed = load_checkpoint().get("completed") or []
        if args.limit:
            completed = completed[: args.limit]
        root = Path(SUPERNOVAE_OUTPUT)
        for n in completed:
            hits = list(root.glob(f"sne-*/{n}.json"))
            paths.extend(hits)

    # de-dupe paths
    uniq = list(dict.fromkeys(paths))
    if args.limit:
        uniq = uniq[: args.limit]
    result = publish_event_files(uniq, catalog_db=args.catalog_db)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
