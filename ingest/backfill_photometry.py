"""Resumable historical ALeRCE photometry backfill for sparse local events.

``pull_recent(days=40)`` only revisits the trailing discovery window. The 2025
corpus is almost entirely outside that window, so sparse TNS stubs never receive
broker light curves from the 15-minute scheduler alone.

This job:
  - Scans on-disk event JSON for sparse outburst photometry (0 or 1 detection)
  - Resolves ZTF object IDs from aliases or ALeRCE cone search
  - Fetches ALeRCE detections + non-detections (kept distinct via ``kind``)
  - Validates basic association (oid present; optional RA/Dec proximity)
  - Deduplicates with candid / (kind, time, band) keys
  - Merges into existing records without deleting original TNS measurements
  - Checkpoints progress so restarts resume; logs rejects with reasons
  - Yields API budget to ``pull_recent`` via ``provider_quota``

Usage:
  python3 -m ingest.backfill_photometry --years 2025 --limit 50 --dry-run
  python3 -m ingest.backfill_photometry --years 2025,2026 --resume
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.alerce import (  # noqa: E402
    convert_alerce_to_astrocats_photometry,
    find_ztf_object_by_coords,
    get_alerce_lightcurve,
    photometry_dedupe_key,
)
from ingest.coordinates import ra_dec_to_deg  # noqa: E402
from ingest.manager import SUPERNOVAE_OUTPUT, atomic_write_json  # noqa: E402
from ingest import provider_quota  # noqa: E402
from ingest.association_policy import flags_for_backfill, stamp_candidate, is_candidate_point  # noqa: E402
from ingest.event_file_lock import event_file_lock  # noqa: E402
from ingest.provider_quota import backfill_mode  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill_photometry")

try:
    from serve.data_paths import runtime_write_path
except Exception:  # noqa: BLE001
    def runtime_write_path(name: str) -> Path:  # type: ignore
        p = ROOT / "serve" / "cache" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

CHECKPOINT_PATH = runtime_write_path("backfill_photometry_checkpoint.json")
REJECT_LOG_PATH = runtime_write_path("backfill_photometry_rejects.jsonl")
STATS_PATH = runtime_write_path("backfill_photometry_stats.json")


def _get_val(meta: dict, key: str) -> Optional[str]:
    v = meta.get(key)
    if isinstance(v, list) and v:
        first = v[0]
        return str(first.get("value")) if isinstance(first, dict) else str(first)
    if isinstance(v, str):
        return v
    return None


def _parse_ymd(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    m = re.match(r"\s*(\d{4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})", str(s))
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
    except Exception:
        return None


def _ymd_to_mjd(dt: datetime) -> float:
    return 40587.0 + dt.timestamp() / 86400.0


def usable_outburst_detections(meta: dict, *, verified_only: bool = False) -> List[dict]:
    """Return non-upperlimit photometry associated with the outburst window.

    When ``verified_only`` is True, exclude ``association_status=unverified`` /
    candidate points (retained for provenance, not scientific interpretation).
    """
    disc = _parse_ymd(_get_val(meta, "discoverdate"))
    disc_mjd = _ymd_to_mjd(disc) if disc else None
    out: List[dict] = []
    for p in meta.get("photometry") or []:
        if not isinstance(p, dict):
            continue
        if p.get("upperlimit") or p.get("kind") == "non_detection":
            continue
        if str(p.get("magnitude", "")).startswith(">"):
            continue
        if p.get("magnitude") is None:
            continue
        if verified_only and is_candidate_point(p):
            continue
        try:
            t = float(p["time"]) if p.get("time") is not None else None
        except Exception:
            continue
        if disc_mjd is not None and t is not None and t < disc_mjd - 60.0:
            continue
        out.append(p)
    return out


def verified_outburst_detections(meta: dict) -> List[dict]:
    """Outburst detections eligible for scientific claims."""
    return usable_outburst_detections(meta, verified_only=True)


def ztf_alias(meta: dict, prefer_year: Optional[int] = None) -> Optional[str]:
    """Return a ZTF object id, preferring IDs whose YY matches discovery year.

    TNS internal_names sometimes list an older ZTF variable in the same field.
    Preferring ZTF{yy}... for a 2025 discovery avoids attaching years of unrelated
    host photometry when a same-year alert ID exists.
    """
    ids: List[str] = []
    for a in meta.get("alias") or []:
        val = a.get("value") if isinstance(a, dict) else str(a)
        if val and str(val).startswith("ZTF") and len(str(val)) >= 12:
            ids.append(str(val))
    if not ids:
        return None
    if prefer_year is not None:
        yy = f"{prefer_year % 100:02d}"
        for i in ids:
            # ZTF25abxdetz → year code starts at index 3
            if len(i) >= 5 and i[3:5] == yy:
                return i
    return ids[0]


def discover_year(meta: dict, fallback_folder: str) -> int:
    disc = _parse_ymd(_get_val(meta, "discoverdate"))
    if disc:
        return disc.year
    m = re.search(r"(\d{4})", fallback_folder)
    return int(m.group(1)) if m else 0


def iter_sparse_events(
    years: Optional[Iterable[int]] = None,
    max_detections: int = 1,
) -> Iterable[Tuple[Path, str, dict, int]]:
    """Yield (path, name, meta, usable_detection_count) for sparse events."""
    year_set = set(years) if years else None
    root = Path(SUPERNOVAE_OUTPUT)
    folders = sorted(root.glob("sne-*"), reverse=True)
    for folder in folders:
        for fpath in sorted(folder.glob("*.json")):
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
            y = discover_year(meta, folder.name)
            if year_set is not None and y not in year_set:
                continue
            dets = usable_outburst_detections(meta)
            if len(dets) > max_detections:
                continue
            yield fpath, name, meta, len(dets)


def _get_or_add_source(event: dict, name: str, url: str) -> str:
    sources = event.setdefault("sources", [])
    for s in sources:
        if isinstance(s, dict) and s.get("name") == name:
            return str(s.get("alias") or "1")
    alias = str(len(sources) + 1)
    sources.append({
        "name": name,
        "url": url,
        "secondary": True,
        "alias": alias,
    })
    return alias


def _coords_deg(meta: dict) -> Optional[Tuple[float, float]]:
    ra = _get_val(meta, "ra")
    dec = _get_val(meta, "dec")
    if not ra or not dec:
        return None
    try:
        return ra_dec_to_deg(ra, dec)
    except Exception:
        return None


def validate_association(
    meta: dict,
    ztf_oid: str,
    alerce_data: dict,
    max_sep_arcsec: float = 5.0,
) -> Tuple[bool, str]:
    """Basic object association checks before merging."""
    dets = [d for d in (alerce_data.get("detections") or []) if isinstance(d, dict)]
    if not dets and not (alerce_data.get("non_detections") or []):
        return False, "empty_alerce_lightcurve"
    coords = _coords_deg(meta)
    if coords is None:
        return True, "no_local_coords_skip_sep_check"
    ra0, dec0 = coords
    # Use first detection with coordinates
    for d in dets[:20]:
        if d.get("ra") is None or d.get("dec") is None:
            continue
        try:
            dra = (float(d["ra"]) - ra0) * 3600.0 * max(0.1, abs(__import__("math").cos(__import__("math").radians(dec0))))
            ddec = (float(d["dec"]) - dec0) * 3600.0
            sep = (dra * dra + ddec * ddec) ** 0.5
        except Exception:
            continue
        if sep <= max_sep_arcsec:
            return True, f"sep_ok_{sep:.2f}arcsec"
        return False, f"coord_mismatch_sep_{sep:.1f}arcsec_oid_{ztf_oid}"
    return True, "no_detection_coords_skip_sep_check"


def merge_photometry(
    event: dict,
    new_pts: List[dict],
) -> Tuple[int, int, List[dict]]:
    """Merge new points; return (added, skipped_dupes, rejected_with_reason_dicts)."""
    existing = event.setdefault("photometry", [])
    keys = {photometry_dedupe_key(p) for p in existing if isinstance(p, dict)}
    added = 0
    skipped = 0
    rejected: List[dict] = []
    for p in new_pts:
        if not isinstance(p, dict):
            rejected.append({"reason": "not_a_dict", "point": str(p)[:120]})
            continue
        # Reject nonsensical magnitudes
        try:
            mag = float(p.get("magnitude"))
            t = float(p.get("time"))
        except Exception:
            rejected.append({"reason": "unparseable_mag_or_time", "point": {k: p.get(k) for k in ("time", "magnitude", "band", "kind")}})
            continue
        if mag < -5 or mag > 40:
            rejected.append({"reason": "magnitude_out_of_range", "mag": mag, "time": t})
            continue
        key = photometry_dedupe_key(p)
        if key in keys:
            skipped += 1
            continue
        existing.append(p)
        keys.add(key)
        added += 1
    existing.sort(key=lambda x: float(x.get("time", 0)) if isinstance(x, dict) else 0)
    return added, skipped, rejected


def load_checkpoint() -> dict:
    if CHECKPOINT_PATH.is_file():
        try:
            return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "completed": [],
        "failed": {},
        "stats": {
            "attempted": 0,
            "enriched": 0,
            "already_rich": 0,
            "no_ztf": 0,
            "no_alerce": 0,
            "assoc_reject": 0,
            "detections_added": 0,
            "nondetections_added": 0,
        },
    }


def save_checkpoint(state: dict) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHECKPOINT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(CHECKPOINT_PATH)


def log_reject(name: str, reason: str, detail: dict | None = None) -> None:
    REJECT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "name": name,
        "reason": reason,
        "detail": detail or {},
    }
    with REJECT_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def filter_to_outburst_window(
    points: List[dict],
    disc_mjd: Optional[float],
    pre_days: float = 60.0,
) -> Tuple[List[dict], int]:
    """Keep points at/after discovery-60d; return (kept, dropped_count)."""
    if disc_mjd is None:
        return points, 0
    kept: List[dict] = []
    dropped = 0
    for p in points:
        try:
            tt = float(p.get("time"))
        except Exception:
            dropped += 1
            continue
        if tt < disc_mjd - pre_days:
            dropped += 1
            continue
        kept.append(p)
    return kept, dropped



def backfill_one(
    fpath: Path,
    name: str,
    meta: dict,
    *,
    dry_run: bool = False,
    force_refresh: bool = False,
) -> dict:
    """Enrich one sparse event. Returns a result dict; never deletes local data."""
    result = {
        "name": name,
        "path": str(fpath),
        "status": "ok",
        "detections_added": 0,
        "nondetections_added": 0,
        "before": len(usable_outburst_detections(meta)),
        "after": None,
        "ztf_oid": None,
        "reason": None,
    }
    year = discover_year(meta, fpath.parent.name)
    oid = ztf_alias(meta, prefer_year=year or None)
    if not oid:
        coords = _coords_deg(meta)
        if coords and coords[1] >= -32.0:
            oid = find_ztf_object_by_coords(coords[0], coords[1])
            if oid and not dry_run:
                meta.setdefault("alias", []).append({
                    "value": oid,
                    "source": "ALeRCE Cone Match",
                })
        if not oid:
            # Still try TNS object photometry for AT/SN names without a ZTF id.
            try:
                from ingest.tns_photometry import apply_tns_photometry_to_event
                bare = name[2:] if name.startswith(("SN", "AT")) else name
                tns_src = _get_or_add_source(
                    meta,
                    name="Transient Name Server",
                    url=f"https://www.wis-tns.org/object/{bare}",
                )
                before = len(meta.get("photometry") or [])
                cov = apply_tns_photometry_to_event(meta, bare, source_alias=tns_src)
                after = len(meta.get("photometry") or [])
                if cov.get("status") == "ok" and after > before:
                    if not dry_run:
                        atomic_write_json(fpath, {name: meta})
                    result["status"] = "ok_tns"
                    result["detections_added"] = after - before
                    result["after"] = len(usable_outburst_detections(meta))
                    result["reason"] = (
                        f"no_ztf_tns_ok det={cov.get('n_detections')} "
                        f"lim={cov.get('n_limits')}"
                    )
                    return result
                result["status"] = "no_ztf"
                result["reason"] = (
                    f"no_ztf_alias_or_cone_match; tns_status={cov.get('status')}"
                )
            except Exception as exc:  # noqa: BLE001
                result["status"] = "no_ztf"
                result["reason"] = f"no_ztf_alias_or_cone_match; tns_exc={exc}"
            log_reject(name, result["reason"])
            return result
    result["ztf_oid"] = oid

    # Year-mismatched aliases must be the cone-search best match at event coords.
    if year and oid and len(oid) >= 5 and oid[3:5] != f"{year % 100:02d}":
        coords = _coords_deg(meta)
        if not coords or coords[1] < -32.0:
            result["status"] = "assoc_reject"
            result["reason"] = f"year_mismatch_oid_without_coords oid={oid}"
            log_reject(name, result["reason"], {"oid": oid, "year": year})
            return result
        cone_oid = find_ztf_object_by_coords(coords[0], coords[1], radius_arcsec=3.0)
        if cone_oid != oid:
            result["status"] = "assoc_reject"
            result["reason"] = (
                f"year_mismatch_oid_not_cone_best alias={oid} cone={cone_oid}"
            )
            log_reject(name, result["reason"], {"oid": oid, "cone": cone_oid, "year": year})
            return result

    cache_age = 0 if force_refresh else 7 * 86400
    lc = get_alerce_lightcurve(oid, max_cache_age=cache_age)
    if not lc:
        # ALeRCE miss is not evidence that no observations exist — try TNS.
        try:
            from ingest.tns_photometry import apply_tns_photometry_to_event
            bare = name[2:] if name.startswith(("SN", "AT")) else name
            tns_src = _get_or_add_source(
                meta,
                name="Transient Name Server",
                url=f"https://www.wis-tns.org/object/{bare}",
            )
            before = len(meta.get("photometry") or [])
            cov = apply_tns_photometry_to_event(meta, bare, source_alias=tns_src)
            after = len(meta.get("photometry") or [])
            added = max(0, after - before)
            if cov.get("status") == "ok" and after > before:
                if not dry_run:
                    atomic_write_json(fpath, {name: meta})
                result["status"] = "ok_tns"
                result["detections_added"] = after - before
                result["after"] = len(usable_outburst_detections(meta))
                result["reason"] = (
                    f"alerce_empty_tns_ok det={cov.get('n_detections')} "
                    f"lim={cov.get('n_limits')}"
                )
                return result
            result["status"] = "no_alerce"
            result["reason"] = (
                f"alerce_empty_or_error oid={oid}; "
                f"tns_status={cov.get('status')} tns_err={cov.get('error')}"
            )
        except Exception as exc:  # noqa: BLE001
            result["status"] = "no_alerce"
            result["reason"] = f"alerce_empty_or_error oid={oid}; tns_exc={exc}"
        log_reject(name, result["reason"], {"oid": oid})
        return result

    ok, assoc_reason = validate_association(meta, oid, lc)
    if not ok:
        result["status"] = "assoc_reject"
        result["reason"] = assoc_reason
        log_reject(name, assoc_reason, {"oid": oid})
        return result

    src_alias = _get_or_add_source(
        meta, name="ALeRCE / ZTF", url=f"https://alerce.online/object/{oid}"
    )
    dets = convert_alerce_to_astrocats_photometry(
        lc, source_alias=src_alias, include_detections=True, include_non_detections=False
    )
    nondets = convert_alerce_to_astrocats_photometry(
        lc, source_alias=src_alias, include_detections=False, include_non_detections=True
    )
    disc = _parse_ymd(_get_val(meta, "discoverdate"))
    disc_mjd = _ymd_to_mjd(disc) if disc else None
    dets, dropped_d = filter_to_outburst_window(dets, disc_mjd)
    nondets, dropped_n = filter_to_outburst_window(nondets, disc_mjd)
    if dropped_d or dropped_n:
        log_reject(name, "pre_discovery_points_dropped", {
            "oid": oid, "dropped_detections": dropped_d, "dropped_nondetections": dropped_n,
        })
    # If a year-mismatched ZTF id yields zero outburst-window detections, reject.
    yy_ok = True
    if year and oid and len(oid) >= 5:
        yy_ok = oid[3:5] == f"{year % 100:02d}"
    if not dets and not yy_ok:
        result["status"] = "assoc_reject"
        result["reason"] = f"old_ztf_oid_no_outburst_window_points oid={oid}"
        log_reject(name, result["reason"], {"oid": oid, "year": year})
        return result

    if dry_run:
        # Estimate adds without writing
        existing_keys = {photometry_dedupe_key(p) for p in (meta.get("photometry") or []) if isinstance(p, dict)}
        add_d = sum(1 for p in dets if photometry_dedupe_key(p) not in existing_keys)
        add_n = sum(1 for p in nondets if photometry_dedupe_key(p) not in existing_keys)
        result["detections_added"] = add_d
        result["nondetections_added"] = add_n
        result["after"] = result["before"] + add_d
        result["status"] = "dry_run"
        result["reason"] = assoc_reason
        return result

    year_mismatched = bool(year and oid and len(oid) >= 5 and oid[3:5] != f"{year % 100:02d}")
    sep_arcsec = None
    if isinstance(assoc_reason, str) and assoc_reason.startswith("sep_ok_"):
        try:
            sep_arcsec = float(assoc_reason.split("sep_ok_")[1].replace("arcsec", ""))
        except Exception:
            sep_arcsec = None
    # Quarantine stamp prep (counts refreshed after locked merge).
    prelim_flags = flags_for_backfill(
        year_mismatched=year_mismatched,
        detections_added=len(dets),
        sep_arcsec=sep_arcsec,
    )
    stamped_dets = []
    stamped_nondets = []
    for _p in dets:
        _p = dict(_p)
        _p["association_oid"] = oid
        _p["association_sep"] = assoc_reason
        if prelim_flags:
            _p = stamp_candidate(_p, prelim_flags, oid=oid)
        stamped_dets.append(_p)
    for _p in nondets:
        _p = dict(_p)
        _p["association_oid"] = oid
        _p["association_sep"] = assoc_reason
        if prelim_flags:
            _p = stamp_candidate(_p, prelim_flags, oid=oid)
        stamped_nondets.append(_p)

    # Full RMW under cross-process event lock: reload latest file, merge, write.
    with event_file_lock(fpath):
        try:
            fresh = json.loads(fpath.read_text(encoding="utf-8"))
            if isinstance(fresh, dict) and name in fresh and isinstance(fresh[name], dict):
                meta = fresh[name]
        except Exception:
            pass
        add_d, skip_d, rej_d = merge_photometry(meta, stamped_dets)
        add_n, skip_n, rej_n = merge_photometry(meta, stamped_nondets)
        for r in rej_d + rej_n:
            log_reject(name, r.get("reason", "merge_reject"), r)
        flags = flags_for_backfill(
            year_mismatched=year_mismatched,
            detections_added=add_d,
            sep_arcsec=sep_arcsec,
        )
        # Re-stamp if final flags differ (e.g. high-N based on added count).
        if flags and flags != prelim_flags:
            new_ph = []
            for p in meta.get("photometry") or []:
                if isinstance(p, dict) and p.get("association_oid") == oid:
                    p = stamp_candidate(p, flags, oid=oid)
                new_ph.append(p)
            meta["photometry"] = new_ph

        meta["_backfill"] = {
            "provider": "ALeRCE",
            "ztf_oid": oid,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "detections_added": add_d,
            "nondetections_added": add_n,
            "association": assoc_reason,
            "angular_separation_arcsec": sep_arcsec,
            "discovery_year": year,
            "oid_year_code": oid[3:5] if oid and len(oid) >= 5 else None,
            "year_mismatched": year_mismatched,
            "suspicious_flags": flags,
            "association_status": "unverified" if flags else "positional_window",
            "pre_discovery_dropped_detections": dropped_d,
            "pre_discovery_dropped_nondetections": dropped_n,
        }
        if flags:
            log_reject(name, "suspicious_association_flagged", {
                "oid": oid, "flags": flags, "detections_added": add_d, "sep_arcsec": sep_arcsec,
            })
        atomic_write_json(fpath, {name: meta})

    result["detections_added"] = add_d
    result["nondetections_added"] = add_n
    result["after"] = len(usable_outburst_detections(meta))
    result["after_verified"] = len(verified_outburst_detections(meta))
    result["reason"] = assoc_reason
    result["status"] = "enriched" if (add_d > 0 or add_n > 0) else "no_new_points"
    return result


def run_backfill(
    years: List[int],
    limit: int = 0,
    dry_run: bool = False,
    resume: bool = True,
    force_refresh: bool = False,
    sleep_s: float = 0.0,
) -> dict:
    state = load_checkpoint() if resume else {
        "completed": [],
        "failed": {},
        "stats": {
            "attempted": 0, "enriched": 0, "already_rich": 0, "no_ztf": 0,
            "no_alerce": 0, "assoc_reject": 0, "detections_added": 0,
            "nondetections_added": 0,
        },
    }
    done = set(state.get("completed") or [])
    stats = state.setdefault("stats", {})
    processed = 0

    log.info(
        "Backfill start years=%s limit=%s dry_run=%s resume=%s checkpoint=%s",
        years, limit, dry_run, resume, CHECKPOINT_PATH,
    )

    with backfill_mode():
      for fpath, name, meta, n_before in iter_sparse_events(years=years, max_detections=1):
        if name in done:
            continue
        if limit and processed >= limit:
            break

        # Yield to recent discovery ingest (full-cycle holders, not 120s timer)
        provider_quota.wait_for_recent_priority()

        processed += 1
        stats["attempted"] = int(stats.get("attempted", 0)) + 1
        try:
            result = backfill_one(
                fpath, name, meta, dry_run=dry_run, force_refresh=force_refresh
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("backfill failed for %s", name)
            state.setdefault("failed", {})[name] = str(exc)
            log_reject(name, "exception", {"error": str(exc)})
            save_checkpoint(state)
            continue

        status = result["status"]
        if status == "enriched" or (status == "dry_run" and result["detections_added"] > 0):
            stats["enriched"] = int(stats.get("enriched", 0)) + 1
        elif status == "no_ztf":
            stats["no_ztf"] = int(stats.get("no_ztf", 0)) + 1
        elif status == "no_alerce":
            stats["no_alerce"] = int(stats.get("no_alerce", 0)) + 1
        elif status == "assoc_reject":
            stats["assoc_reject"] = int(stats.get("assoc_reject", 0)) + 1

        stats["detections_added"] = int(stats.get("detections_added", 0)) + int(result.get("detections_added") or 0)
        stats["nondetections_added"] = int(stats.get("nondetections_added", 0)) + int(result.get("nondetections_added") or 0)

        if not dry_run:
            done.add(name)
            state["completed"] = sorted(done)
        save_checkpoint(state)
        STATS_PATH.write_text(json.dumps({"stats": stats, "last": result}, indent=2), encoding="utf-8")

        log.info(
            "%s %s before=%s after=%s +det=%s +lim=%s oid=%s",
            status, name, result.get("before"), result.get("after"),
            result.get("detections_added"), result.get("nondetections_added"),
            result.get("ztf_oid"),
        )
        if sleep_s > 0:
            time.sleep(sleep_s)

    summary = {
        "processed_this_run": processed,
        "stats": stats,
        "completed_total": len(done),
        "checkpoint": str(CHECKPOINT_PATH),
        "reject_log": str(REJECT_LOG_PATH),
    }
    log.info("Backfill summary: %s", json.dumps(summary))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Historical ALeRCE photometry backfill")
    ap.add_argument("--years", default="2025", help="Comma-separated discovery years")
    ap.add_argument("--limit", type=int, default=0, help="Max events this run (0=all)")
    ap.add_argument("--dry-run", action="store_true", help="Fetch/estimate only; do not write JSON")
    ap.add_argument("--no-resume", action="store_true", help="Ignore checkpoint completed set")
    ap.add_argument("--force-refresh", action="store_true", help="Bypass ALeRCE disk cache TTL")
    ap.add_argument("--sleep", type=float, default=0.0, help="Extra sleep between events")
    args = ap.parse_args()
    years = [int(y.strip()) for y in args.years.split(",") if y.strip()]
    run_backfill(
        years=years,
        limit=args.limit,
        dry_run=args.dry_run,
        resume=not args.no_resume,
        force_refresh=args.force_refresh,
        sleep_s=args.sleep,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
