#!/usr/bin/env python3
"""Mark structurally malformed photometry without inventing timestamps.

Preserves original upstream JSON. Writes a sidecar quarantine report listing
measurements that must be excluded from time-series inference.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TARGETS = [
    "MLS180112:023607+270428",
    "MLS190104:122254+341818",
]


def find_file(staging_repos: Path, name: str) -> Optional[Path]:
    for part in staging_repos.iterdir():
        if not part.is_dir():
            continue
        for p in part.rglob(f"{name}.json"):
            if ".git" not in p.parts:
                return p
    return None


def mark_event(name: str, path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    meta = raw.get(name) or next(iter(raw.values()))
    phot = meta.get("photometry") or []
    flagged = []
    for i, p in enumerate(phot):
        if not isinstance(p, dict):
            flagged.append({"index": i, "reason": "not_object"})
            continue
        reasons = []
        if p.get("time") is None or p.get("time") == "":
            reasons.append("missing_time")
        has_mag = p.get("magnitude") is not None
        has_ul = bool(p.get("upperlimit")) or p.get("kind") == "non_detection"
        if not has_mag and not has_ul:
            reasons.append("missing_mag_and_ul")
        if reasons:
            flagged.append(
                {
                    "index": i,
                    "reasons": reasons,
                    "preserved_fields": {
                        k: p.get(k)
                        for k in ("magnitude", "band", "filter", "source", "telescope")
                        if k in p
                    },
                    "time_invented": False,
                    "exclude_from_time_series": "missing_time" in reasons,
                }
            )
    return {
        "name": name,
        "path": str(path),
        "phot_n": len(phot),
        "flagged_n": len(flagged),
        "flagged": flagged,
        "action": "preserve_original; mark incomplete; do_not_invent_timestamps",
        "original_bytes": path.stat().st_size,
        "original_untouched": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--staging-root",
        type=Path,
        default=ROOT / "staging/astrocats-restore",
    )
    ap.add_argument("--names", nargs="*", default=DEFAULT_TARGETS)
    args = ap.parse_args()
    repos = args.staging_root / "repos"
    rows = []
    for name in args.names:
        path = find_file(repos, name)
        if path is None:
            rows.append({"name": name, "error": "file_not_found_in_staging"})
            continue
        rows.append(mark_event(name, path))
    report = {
        "drawn_at_utc": datetime.now(timezone.utc).isoformat(),
        "records": rows,
        "policy": [
            "Do not invent timestamps",
            "Exclude missing-time points from time-dependent scientific inference",
            "Structural audit ≠ scientific measurement audit",
            "Original upstream files left unmodified",
        ],
        "live_data_untouched": True,
    }
    out = args.staging_root / "MALFORMED_PHOTOMETRY_REPORT.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"n": len(rows), "flagged": [
        {"name": r.get("name"), "flagged_n": r.get("flagged_n"), "error": r.get("error")}
        for r in rows
    ]}, indent=2))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
