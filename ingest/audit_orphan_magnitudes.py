#!/usr/bin/env python3
"""Catalog-wide audit: orphan maxappmag scalars vs persisted photometry.

Reports how many events advertise magnitudes / photolink counts without
storing observation arrays — the false-completeness failure mode.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.manager import SUPERNOVAE_OUTPUT  # noqa: E402


def _val(meta: dict, key: str) -> str:
    v = meta.get(key)
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return str(v[0].get("value") or "").strip()
    if isinstance(v, str):
        return v.strip()
    return ""


def _phot_counts(meta: dict) -> tuple[int, int]:
    ph = meta.get("photometry") or []
    if not isinstance(ph, list):
        return 0, 0
    n_det = 0
    n_lim = 0
    for p in ph:
        if not isinstance(p, dict):
            continue
        if p.get("upperlimit") or p.get("kind") == "non_detection" or str(p.get("magnitude", "")).startswith(">"):
            n_lim += 1
        elif p.get("magnitude") is not None:
            n_det += 1
    return n_det, n_lim


def _photolink_claimed(meta: dict) -> tuple[int, int]:
    raw = str(meta.get("photolink") or "0")
    parts = raw.split(",")
    try:
        a = int(parts[0] or 0)
    except ValueError:
        a = 0
    try:
        b = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        b = 0
    return a, b


def audit(root: Path, limit: int = 0) -> dict:
    stats: Counter = Counter()
    orphans: list[str] = []
    fake_links: list[str] = []
    discovery_as_peak: list[str] = []
    scanned = 0

    for folder in sorted(root.glob("sne-*")):
        for fpath in folder.glob("*.json"):
            try:
                raw = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                stats["unreadable"] += 1
                continue
            if not isinstance(raw, dict) or not raw:
                continue
            name = next(iter(raw))
            meta = raw[name]
            if not isinstance(meta, dict):
                continue
            scanned += 1
            n_det, n_lim = _phot_counts(meta)
            claimed_det, claimed_lim = _photolink_claimed(meta)
            has_mag = bool(_val(meta, "maxappmag") or _val(meta, "discoverymag"))
            max_kind = ""
            mm = meta.get("maxappmag")
            if isinstance(mm, list) and mm and isinstance(mm[0], dict):
                max_kind = str(mm[0].get("kind") or "")

            if n_det > 0:
                stats["with_detections"] += 1
            else:
                stats["zero_detections"] += 1
            if n_lim > 0:
                stats["with_limits"] += 1
            if has_mag and n_det == 0:
                stats["orphan_scalar_mag"] += 1
                if len(orphans) < 50:
                    orphans.append(name)
            if claimed_det > 0 and n_det == 0:
                stats["fake_photolink"] += 1
                if len(fake_links) < 50:
                    fake_links.append(f"{name}:{claimed_det}")
            if max_kind in ("discovery", "discovery_mag") or (
                has_mag and n_det <= 1 and max_kind not in ("brightest_observed", "fitted_peak")
            ):
                if n_det <= 1 and _val(meta, "maxappmag"):
                    stats["discovery_labeled_as_listing_mag"] += 1
                    if max_kind in ("", "fitted_peak", "peak") and n_det <= 1:
                        stats["possible_peak_mislabel"] += 1
                        if len(discovery_as_peak) < 50:
                            discovery_as_peak.append(name)
            if limit and scanned >= limit:
                break
        if limit and scanned >= limit:
            break

    return {
        "scanned": scanned,
        "stats": dict(stats),
        "orphan_examples": orphans,
        "fake_photolink_examples": fake_links,
        "peak_mislabel_examples": discovery_as_peak,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(SUPERNOVAE_OUTPUT))
    ap.add_argument("--limit", type=int, default=0, help="Stop after N events (0=all)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = audit(args.root, limit=args.limit)
    if args.json:
        print(json.dumps(report, indent=2))
        return
    print(f"Scanned {report['scanned']} events under {args.root}")
    for k, v in sorted(report["stats"].items()):
        print(f"  {k}: {v}")
    if report["orphan_examples"]:
        print("orphan scalar examples:", ", ".join(report["orphan_examples"][:20]))
    if report["fake_photolink_examples"]:
        print("fake photolink examples:", ", ".join(report["fake_photolink_examples"][:20]))


if __name__ == "__main__":
    main()
