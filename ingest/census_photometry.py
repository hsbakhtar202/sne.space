#!/usr/bin/env python3
"""Raw vs verified multipoint census + quarantine reconciliation for a discovery year."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.association_policy import is_candidate_point  # noqa: E402
from ingest.backfill_photometry import (  # noqa: E402
    CHECKPOINT_PATH,
    REJECT_LOG_PATH,
    iter_sparse_events,
    load_checkpoint,
    usable_outburst_detections,
    verified_outburst_detections,
)
from ingest.manager import SUPERNOVAE_OUTPUT  # noqa: E402


def _is_detection(p: dict) -> bool:
    if p.get("upperlimit") or p.get("kind") == "non_detection":
        return False
    if str(p.get("magnitude", "")).startswith(">"):
        return False
    return p.get("magnitude") is not None


def census_year(year: int) -> dict:
    root = Path(SUPERNOVAE_OUTPUT)
    raw_mp = ver_mp = single_raw = single_ver = zero = 0
    total = 0
    candidate_events = 0
    year_mismatch_events = 0

    # Quarantine reconciliation populations
    q_det = q_lim = q_other = 0
    q_from_backfill_det = 0
    all_alerce_det = all_alerce_lim = 0
    backfill_det_claimed = 0
    backfill_lim_claimed = 0

    for folder in sorted(root.glob("sne-*")):
        for fpath in folder.glob("*.json"):
            try:
                raw = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not raw:
                continue
            name = next(iter(raw))
            meta = raw[name]
            if not isinstance(meta, dict):
                continue
            dd = meta.get("discoverdate")
            disc = ""
            if isinstance(dd, list) and dd and isinstance(dd[0], dict):
                disc = str(dd[0].get("value") or "")
            if not disc.startswith(str(year)):
                continue
            total += 1
            raw_d = usable_outburst_detections(meta)
            ver_d = verified_outburst_detections(meta)
            nr, nv = len(raw_d), len(ver_d)
            if nr == 0:
                zero += 1
            elif nr == 1:
                single_raw += 1
            else:
                raw_mp += 1
            if nv == 0:
                pass
            elif nv == 1:
                single_ver += 1
            else:
                ver_mp += 1

            ph = meta.get("photometry") or []
            if any(isinstance(p, dict) and is_candidate_point(p) for p in ph):
                candidate_events += 1
            bf = meta.get("_backfill") if isinstance(meta.get("_backfill"), dict) else {}
            if bf.get("year_mismatched"):
                year_mismatch_events += 1
            backfill_det_claimed += int(bf.get("detections_added") or 0)
            backfill_lim_claimed += int(bf.get("nondetections_added") or 0)

            for p in ph:
                if not isinstance(p, dict):
                    continue
                is_alerce = str(p.get("provider") or "") == "ALeRCE" or str(p.get("telescope") or "").upper() == "ZTF"
                det = _is_detection(p)
                if is_alerce:
                    if det:
                        all_alerce_det += 1
                    else:
                        all_alerce_lim += 1
                if is_candidate_point(p):
                    if det:
                        q_det += 1
                        if is_alerce:
                            q_from_backfill_det += 1
                    elif p.get("upperlimit") or p.get("kind") == "non_detection":
                        q_lim += 1
                    else:
                        q_other += 1

    cp = load_checkpoint() if CHECKPOINT_PATH.is_file() else {}
    stats = cp.get("stats") or {}
    done = set(cp.get("completed") or [])
    remaining = sum(1 for _, n, _, _ in iter_sparse_events(years=[year], max_detections=1) if n not in done)

    # Events that are raw multipoint but NOT verified multipoint
    raw_only_mp = raw_mp - ver_mp  # approximate; better count below
    # recount dependency
    raw_not_verified = 0
    for folder in root.glob("sne-*"):
        for fpath in folder.glob("*.json"):
            try:
                raw = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not raw:
                continue
            meta = raw[next(iter(raw))]
            if not isinstance(meta, dict):
                continue
            dd = meta.get("discoverdate")
            disc = str(dd[0].get("value") or "") if isinstance(dd, list) and dd and isinstance(dd[0], dict) else ""
            if not disc.startswith(str(year)):
                continue
            if len(usable_outburst_detections(meta)) >= 2 and len(verified_outburst_detections(meta)) < 2:
                raw_not_verified += 1

    reject_reasons = Counter()
    if REJECT_LOG_PATH.is_file():
        for line in REJECT_LOG_PATH.read_text(errors="replace").splitlines()[-8000:]:
            try:
                row = json.loads(line)
                reject_reasons[str(row.get("reason") or "unknown").split(" oid=")[0]] += 1
            except Exception:
                pass

    return {
        "year": year,
        "denominator_events": total,
        "raw_multipoint": raw_mp,
        "raw_multipoint_pct": round(100.0 * raw_mp / total, 1) if total else 0,
        "verified_multipoint": ver_mp,
        "verified_multipoint_pct": round(100.0 * ver_mp / total, 1) if total else 0,
        "raw_multipoint_not_verified": raw_not_verified,
        "single_raw": single_raw,
        "single_verified": single_ver,
        "zero_outburst_detections": zero,
        "candidate_quarantine_events": candidate_events,
        "year_mismatch_events": year_mismatch_events,
        "quarantine_reconciliation": {
            "note": (
                "Quarantined observation count includes detections + upper limits + "
                "any previously existing points stamped unverified. Checkpoint "
                "detections_added counts new detections only."
            ),
            "quarantined_detections": q_det,
            "quarantined_upper_limits": q_lim,
            "quarantined_other": q_other,
            "quarantined_total": q_det + q_lim + q_other,
            "quarantined_alerce_like_detections": q_from_backfill_det,
            "checkpoint_detections_added": int(stats.get("detections_added") or backfill_det_claimed),
            "checkpoint_nondetections_added": int(stats.get("nondetections_added") or backfill_lim_claimed),
            "on_disk_alerce_detections": all_alerce_det,
            "on_disk_alerce_limits": all_alerce_lim,
        },
        "checkpoint": {
            "completed": len(done),
            "attempted": int(stats.get("attempted") or 0),
            "enriched": int(stats.get("enriched") or 0),
            "no_ztf": int(stats.get("no_ztf") or 0),
            "no_alerce": int(stats.get("no_alerce") or 0),
            "assoc_reject": int(stats.get("assoc_reject") or 0),
            "remaining_sparse_not_checkpointed": remaining,
        },
        "reject_reason_top": reject_reasons.most_common(12),
    }


def cumulative_rates(log_path: Path) -> dict:
    """Longer-window processed vs enriched rates from backfill log."""
    if not log_path.is_file():
        return {}
    pat = re.compile(
        r"^\[(\d{2}):(\d{2}):(\d{2})\].* INFO (enriched|no_ztf|no_alerce|assoc_reject|no_new_points) "
    )
    rows = []
    for line in log_path.read_text(errors="replace").splitlines():
        m = pat.match(line)
        if not m:
            continue
        h, mi, s = map(int, m.groups()[:3])
        rows.append((h * 3600 + mi * 60 + s, m.group(4)))
    if len(rows) < 2:
        return {"samples": len(rows)}
    # Cumulative from first to last, handling midnight wrap once
    t0, t1 = rows[0][0], rows[-1][0]
    dur = t1 - t0
    if dur <= 0:
        dur += 86400
    n = len(rows)
    e = sum(1 for _, st in rows if st == "enriched")
    return {
        "log_path": str(log_path),
        "samples": n,
        "enriched_samples": e,
        "window_s": dur,
        "window_h": round(dur / 3600, 2),
        "processed_per_hour_cumulative": round(n / dur * 3600, 1),
        "enriched_per_hour_cumulative": round(e / dur * 3600, 1),
        "enrichment_success_fraction": round(e / n, 3) if n else 0,
        "note": "Use cumulative processed/hr for ETA; burst windows overstate sustainable rate.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2025")
    ap.add_argument("--log", type=Path, default=Path("/tmp/backfill_2025_full.log"))
    ap.add_argument("--out", type=Path, default=Path("/tmp/census_2025.json"))
    args = ap.parse_args()
    years = [int(y) for y in args.years.split(",") if y.strip()]
    payload = {
        "censuses": [census_year(y) for y in years],
        "rates_cumulative": cumulative_rates(args.log),
    }
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
