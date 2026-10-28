#!/usr/bin/env python3
"""Backfill TNS photometry for orphan discovery-magnitude stubs.

Prioritizes recent ZTF/Fritz events that have a scalar magnitude (or ZTF
alias) but zero persisted photometry detections. Uses the same merge path
as enrich_event so repeated runs stay idempotent.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.manager import SUPERNOVAE_OUTPUT, enrich_event  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill_tns_photometry")


def _val(meta: dict, key: str) -> str:
    v = meta.get(key)
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return str(v[0].get("value") or "").strip()
    if isinstance(v, str):
        return v.strip()
    return ""


def _n_detections(meta: dict) -> int:
    n = 0
    for p in meta.get("photometry") or []:
        if not isinstance(p, dict):
            continue
        if p.get("upperlimit") or p.get("kind") == "non_detection":
            continue
        if p.get("magnitude") is not None and not str(p.get("magnitude")).startswith(">"):
            n += 1
    return n


def _has_ztf(meta: dict, name: str) -> bool:
    if "ZTF" in name.upper():
        return True
    for a in meta.get("alias") or []:
        if isinstance(a, dict) and str(a.get("value") or "").upper().startswith("ZTF"):
            return True
    return False


def find_orphan_stubs(
    root: Path,
    *,
    years: Optional[List[int]] = None,
    ztf_only: bool = True,
    limit: int = 0,
) -> List[str]:
    names: List[str] = []
    folders = sorted(root.glob("sne-*"))
    if years:
        want = {f"sne-{y}-{y + 4}" if False else None for y in years}
        # Folder naming is sne-YYYY-YYYY (decade buckets) — match by year in filename.
        folders = [f for f in folders if any(str(y) in f.name for y in years)]
    for folder in folders:
        for fpath in sorted(folder.glob("*.json"), reverse=True):
            try:
                raw = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, dict) or not raw:
                continue
            name = next(iter(raw))
            meta = raw[name]
            if not isinstance(meta, dict):
                continue
            if years:
                # Prefer discovery year when available.
                disc = _val(meta, "discoverdate") or _val(meta, "discoverymag")
                year_ok = any(str(y) in name or str(y) in disc for y in years)
                if not year_ok and not any(str(y) in fpath.name for y in years):
                    # Still allow if folder matched year band.
                    pass
            if _n_detections(meta) > 0:
                continue
            has_mag = bool(_val(meta, "maxappmag") or _val(meta, "discoverymag"))
            if not has_mag and not _has_ztf(meta, name):
                continue
            if ztf_only and not _has_ztf(meta, name):
                # Recent TNS AT names without ZTF alias yet — still recoverable via TNS page.
                if not name.startswith(("AT20", "SN20")):
                    continue
            names.append(name)
            if limit and len(names) >= limit:
                return names
    return names


def run(names: List[str], *, dry_run: bool = False, force: bool = False) -> Dict[str, Any]:
    stats = {"ok": 0, "fail": 0, "skipped": 0, "names_ok": [], "names_fail": []}
    for name in names:
        if dry_run:
            log.info("dry-run would enrich %s", name)
            stats["skipped"] += 1
            continue
        try:
            ok = enrich_event(name, fetch_lightcurve=True, fetch_spectra=False, force=force)
        except Exception as exc:  # noqa: BLE001
            log.warning("enrich raised for %s: %s", name, exc)
            ok = False
        if ok:
            stats["ok"] += 1
            stats["names_ok"].append(name)
            log.info("enriched %s", name)
        else:
            stats["fail"] += 1
            stats["names_fail"].append(name)
            log.warning("enrich failed for %s", name)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(SUPERNOVAE_OUTPUT))
    ap.add_argument("--years", type=str, default="2025,2026", help="Comma years to prioritize")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--all-surveys", action="store_true", help="Do not prefer ZTF-named stubs")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--names", type=str, default="", help="Comma-separated explicit names")
    args = ap.parse_args()

    if args.names.strip():
        names = [n.strip() for n in args.names.split(",") if n.strip()]
    else:
        years = [int(x) for x in args.years.split(",") if x.strip().isdigit()]
        names = find_orphan_stubs(
            args.root,
            years=years,
            ztf_only=not args.all_surveys,
            limit=args.limit,
        )
    log.info("candidates=%d", len(names))
    stats = run(names, dry_run=args.dry_run, force=args.force)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
