"""Retroactively stamp candidate/unverified on existing suspicious backfill merges.

Does not delete measurements. Idempotent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.association_policy import flags_for_backfill, stamp_candidate  # noqa: E402
from ingest.manager import SUPERNOVAE_OUTPUT, atomic_write_json  # noqa: E402


def retrofit(years: list[int], dry_run: bool = True) -> dict:
    root = Path(SUPERNOVAE_OUTPUT)
    stats = {"files": 0, "events": 0, "stamped_points": 0, "events_touched": 0}
    for folder in sorted(root.glob("sne-*")):
        for fpath in folder.glob("*.json"):
            try:
                raw = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, dict) or not raw:
                continue
            stats["files"] += 1
            changed = False
            for name, meta in raw.items():
                if not isinstance(meta, dict):
                    continue
                stats["events"] += 1
                bf = meta.get("_backfill")
                if not isinstance(bf, dict):
                    continue
                oid = bf.get("ztf_oid") or ""
                year = bf.get("discovery_year")
                if not year:
                    dd = meta.get("discoverdate")
                    if isinstance(dd, list) and dd and isinstance(dd[0], dict):
                        disc = str(dd[0].get("value") or "")
                        if disc[:4].isdigit():
                            year = int(disc[:4])
                year_mismatched = bool(bf.get("year_mismatched"))
                if not year_mismatched and year and oid and len(oid) >= 5:
                    year_mismatched = oid[3:5] != f"{int(year) % 100:02d}"
                if year and not bf.get("discovery_year"):
                    bf["discovery_year"] = int(year)
                bf["year_mismatched"] = year_mismatched
                flags = flags_for_backfill(
                    year_mismatched=year_mismatched,
                    detections_added=int(bf.get("detections_added") or 0),
                    sep_arcsec=bf.get("angular_separation_arcsec"),
                )
                # Also honour flags already on _backfill
                for f in bf.get("suspicious_flags") or []:
                    if f not in flags:
                        flags.append(f)
                if not flags:
                    continue
                bf["suspicious_flags"] = flags
                bf["association_status"] = "unverified"
                n = 0
                new_ph = []
                for p in meta.get("photometry") or []:
                    if not isinstance(p, dict):
                        new_ph.append(p)
                        continue
                    # Only stamp ALeRCE / matching oid points from this backfill.
                    if p.get("association_oid") == oid or (
                        p.get("provider") == "ALeRCE" and str(p.get("telescope", "")).upper() == "ZTF"
                    ):
                        p = stamp_candidate(p, flags, oid=oid or None)
                        n += 1
                        changed = True
                    new_ph.append(p)
                meta["photometry"] = new_ph
                stats["stamped_points"] += n
                if n:
                    stats["events_touched"] += 1
            if changed and not dry_run:
                atomic_write_json(fpath, raw)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2025")
    ap.add_argument("--apply", action="store_true", help="Write changes (default dry-run)")
    args = ap.parse_args()
    years = [int(y) for y in args.years.split(",") if y.strip()]
    # years filter unused in path walk for simplicity — corpus is small enough
    stats = retrofit(years, dry_run=not args.apply)
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
