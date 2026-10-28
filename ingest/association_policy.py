"""Association quarantine policy for broker photometry.

Positional + outburst-window matches are evidence, not conclusive identity.
Year-mismatched ZTF OIDs and unusually large recoveries are retained as
*candidate* measurements with provenance, but excluded from derived scientific
claims (peak magnitude, lifecycle brightness, active-outburst phase) until
reviewed.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


SUSPICIOUS_FLAGS = frozenset({
    "year_mismatched_ztf_oid",
    "high_detection_recovery",
    "very_high_detection_recovery",
    "sep_gt_2_arcsec",
})


def is_candidate_point(p: dict) -> bool:
    if not isinstance(p, dict):
        return False
    status = str(p.get("association_status") or "").lower()
    if status in {"unverified", "candidate", "quarantined"}:
        return True
    if p.get("candidate") is True:
        return True
    flags = p.get("suspicious_flags") or []
    if isinstance(flags, list) and any(f in SUSPICIOUS_FLAGS for f in flags):
        return True
    return False


def scientific_photometry(points: Iterable[dict]) -> List[dict]:
    """Points eligible for derived scientific conclusions (peak / lifecycle)."""
    return [p for p in points if isinstance(p, dict) and not is_candidate_point(p)]


def stamp_candidate(p: dict, flags: List[str], oid: Optional[str] = None) -> dict:
    """Mark a photometry point as association-unverified candidate (in place)."""
    p = dict(p)
    p["association_status"] = "unverified"
    p["candidate"] = True
    existing = list(p.get("suspicious_flags") or [])
    for f in flags:
        if f not in existing:
            existing.append(f)
    p["suspicious_flags"] = existing
    if oid:
        p["association_oid"] = oid
    return p


def flags_for_backfill(*, year_mismatched: bool, detections_added: int, sep_arcsec: Optional[float]) -> List[str]:
    flags: List[str] = []
    if year_mismatched:
        flags.append("year_mismatched_ztf_oid")
    if detections_added >= 50:
        flags.append("high_detection_recovery")
    if detections_added >= 100:
        flags.append("very_high_detection_recovery")
    if sep_arcsec is not None and sep_arcsec > 2.0:
        flags.append("sep_gt_2_arcsec")
    return flags
