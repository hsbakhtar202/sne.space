"""Catalog Ingest Manager orchestrating file placement, merging, and rebuilding."""
import datetime
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ingest.alerce import (
    convert_alerce_to_astrocats_photometry,
    photometry_dedupe_key,
    find_ztf_object_by_coords,
    get_alerce_lightcurve,
)
from ingest.astronomy import compute_cosmology, compute_peak_magnitudes, fetch_irsa_dust
from ingest.coordinates import ra_dec_to_deg
from ingest.tns import build_event_dict, stream_tns_rows
from ingest.tns_spectra import convert_tns_to_astrocats_spectra, is_duplicate_spectrum, search_tns_spectra
from ingest.wiserep import convert_wiserep_to_astrocats_spectra, search_wiserep_spectra

logger = logging.getLogger(__name__)

# Log missing TNS ZIP once per process — every EnrichQueue miss used to reprint it.
_TNS_ZIP_WARNED = False

_OUTPUT_CANDIDATES = [
    Path("serve/www/astrocats/astrocats/supernovae/output"),
    Path(__file__).resolve().parent.parent / "serve/www/astrocats/astrocats/supernovae/output",
    Path("vendor/astrocats/astrocats/supernovae/output"),
]


def _resolve_output_dir() -> Path:
    """Resolve the writable corpus directory, honouring the durable volume.

    This used to hardcode the in-image path. In a container that path is the
    *ephemeral* layer while the named volume is mounted at ``/data/...``, so every
    ingested event was written outside the volume and vanished on redeploy even
    though the volume was mounted correctly. ``serve/data_paths.py`` already
    resolves SNE_DATA_DIR first; delegate to it so ingest and the web server can
    never disagree about where data lives.
    """
    try:
        import sys as _sys

        _root = Path(__file__).resolve().parent.parent
        if str(_root) not in _sys.path:
            _sys.path.insert(0, str(_root))
        from serve.data_paths import OUTPUT_DIR as _durable_dir

        if _durable_dir and _durable_dir.is_dir():
            return _durable_dir
    except Exception as exc:  # noqa: BLE001
        logger.warning("data_paths unavailable, using legacy output path: %s", exc)
    return next((p for p in _OUTPUT_CANDIDATES if p.is_dir()), _OUTPUT_CANDIDATES[0])


SUPERNOVAE_OUTPUT = _resolve_output_dir()

_enrich_locks: Dict[str, threading.Lock] = {}
_enrich_meta_lock = threading.Lock()


def get_object_lock(name: str) -> threading.Lock:
    """Retrieve or create an in-process mutex lock for a specific supernova.

    Cross-process RMW also requires ``ingest.event_file_lock.event_file_lock``
    around the reload→merge→write window (used by enrich_event / backfill / sync).
    """
    with _enrich_meta_lock:
        if name not in _enrich_locks:
            _enrich_locks[name] = threading.Lock()
        return _enrich_locks[name]


def atomic_write_json(file_path: Path, data: Any, skip_if_unchanged: bool = True) -> bool:
    """Write JSON data to disk atomically using temporary file and os.replace.

    Returns ``True`` when the file was written, ``False`` when an identical file
    already existed.

    ``skip_if_unchanged`` matters more than it looks. An enrichment run that finds
    nothing new used to rewrite the file with byte-identical content, which bumped
    ``st_mtime_ns``. The rendered-page cache versions entries by mtime+size, so
    every no-op enrichment invalidated a perfectly good cached page and forced a
    full ~40 ms re-render on the next request -- and since rendering schedules more
    enrichment, that became a self-sustaining loop. Comparing serialised bytes
    first makes a no-op genuinely a no-op.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2)
    if skip_if_unchanged:
        try:
            if file_path.is_file() and file_path.read_text(encoding="utf-8") == payload:
                return False
        except OSError:
            pass  # Unreadable existing file: fall through and rewrite it.
    # Temporary file in same directory guarantees same filesystem for atomic rename
    tmp_path = file_path.with_name(f".{file_path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, file_path)
        return True
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise


def parse_event_discovery_date(event_obj: Dict[str, Any]) -> Optional[datetime.date]:
    """Extract and parse discovery date from event dict."""
    disc = event_obj.get("discoverdate", [])
    if isinstance(disc, list) and disc:
        val = disc[0].get("value") if isinstance(disc[0], dict) else disc[0]
    elif isinstance(disc, str):
        val = disc
    else:
        return None

    if not val:
        return None

    val_clean = str(val).split()[0].replace("-", "/").split(".")[0]
    parts = val_clean.split("/")
    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
        try:
            return datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            return None
    return None


def is_event_stale(event_data: Dict[str, Any], file_path: Optional[Path]) -> Tuple[bool, int]:
    """
    Determine if an event needs enrichment or re-enrichment.
    Returns (is_stale, ttl_seconds).
    
    TTL Rules for Astronomical Cadence:
    - Never enriched (missing ebv/lumdist or has <= 1 photo point and 0 spectra): Always stale (TTL = 0).
    - Active Phase (discovered <= 60 days ago): Rapid light curve changes; TTL = 24 hours (86,400s).
    - Plateau / Nebular Phase (discovered 61-180 days ago): Moderate evolution; TTL = 7 days (604,800s).
    - Historical (> 180 days ago): Static archive; TTL = infinite (is_stale = False).
    """
    if not file_path or not file_path.is_file():
        return True, 0

    key = list(event_data.keys())[0] if event_data else ""
    event = event_data.get(key, {})

    has_cosmology = bool(event.get("lumdist") and event.get("ebv"))
    photo_count = len(event.get("photometry", []))
    spec_count = len(event.get("spectra", []))
    if not has_cosmology or (photo_count <= 1 and spec_count == 0):
        return True, 0

    disc_date = parse_event_discovery_date(event)
    if not disc_date:
        return False, 86400 * 365

    age_days = (datetime.date.today() - disc_date).days
    if age_days < 0:
        age_days = 0

    if age_days <= 60:
        ttl = 86400  # 24 hours for active supernovae
    elif age_days <= 180:
        ttl = 86400 * 7  # 7 days for medium phase
    else:
        return False, 86400 * 365  # Historical, static

    file_age = time.time() - file_path.stat().st_mtime
    return file_age >= ttl, ttl


def is_file_stale(file_path: Path) -> bool:
    """Helper to check if a file on disk is stale without loading everything manually."""
    if not file_path.is_file():
        return True
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        stale, _ = is_event_stale(data, file_path)
        return stale
    except Exception:
        return True


def get_target_repo_folder(year: int) -> Path:
    """Determine destination repo folder based on discovery year."""
    if year <= 1989:
        return SUPERNOVAE_OUTPUT / "sne-pre-1990"
    elif year <= 1999:
        return SUPERNOVAE_OUTPUT / "sne-1990-1999"
    elif year <= 2004:
        return SUPERNOVAE_OUTPUT / "sne-2000-2004"
    elif year <= 2009:
        return SUPERNOVAE_OUTPUT / "sne-2005-2009"
    elif year <= 2014:
        return SUPERNOVAE_OUTPUT / "sne-2010-2014"
    elif year <= 2019:
        return SUPERNOVAE_OUTPUT / "sne-2015-2019"
    elif year <= 2024:
        return SUPERNOVAE_OUTPUT / "sne-2020-2024"
    else:
        return SUPERNOVAE_OUTPUT / "sne-2025-2029"


def find_existing_event_file(name: str) -> Optional[Path]:
    """Search for an existing JSON file for an event across all repos."""
    clean = name.strip()
    cands = [clean, clean.replace("SN", "AT"), clean.replace("AT", "SN")]
    for cand in cands:
        fn = f"{cand}.json"
        for folder in SUPERNOVAE_OUTPUT.glob("sne-*"):
            p = folder / fn
            if p.is_file():
                return p
    return None


def merge_event_data(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Merge incoming event metadata into an existing event dictionary."""
    ex_name = list(existing.keys())[0]
    inc_name = list(incoming.keys())[0]
    ex_obj = existing[ex_name]
    inc_obj = incoming[inc_name]

    # Merge sources with deduplication
    ex_sources = ex_obj.setdefault("sources", [])
    inc_sources = inc_obj.get("sources", [])
    source_alias_map = {}

    for isrc in inc_sources:
        match_alias = None
        for esrc in ex_sources:
            if esrc.get("bibcode") and esrc.get("bibcode") == isrc.get("bibcode"):
                match_alias = esrc.get("alias")
                break
            if esrc.get("name") and esrc.get("name") == isrc.get("name"):
                match_alias = esrc.get("alias")
                break
        if match_alias is not None:
            source_alias_map[isrc.get("alias")] = match_alias
        else:
            new_alias = str(len(ex_sources) + 1)
            source_alias_map[isrc.get("alias")] = new_alias
            isrc_copy = dict(isrc)
            isrc_copy["alias"] = new_alias
            ex_sources.append(isrc_copy)

    # Merge aliases
    ex_aliases = {a.get("value") for a in ex_obj.get("alias", []) if isinstance(a, dict)}
    for a in inc_obj.get("alias", []):
        val = a.get("value")
        if val and val not in ex_aliases:
            src = source_alias_map.get(a.get("source"), "1")
            ex_obj.setdefault("alias", []).append({"value": val, "source": src})
            ex_aliases.add(val)

    # Add missing primary quantities
    for key in ("ra", "dec", "claimedtype", "redshift", "discoverdate", "discoverer"):
        if key not in ex_obj and key in inc_obj:
            val_list = inc_obj[key]
            # Remap sources
            remapped = []
            for item in val_list:
                item_copy = dict(item)
                item_copy["source"] = source_alias_map.get(item.get("source"), "1")
                remapped.append(item_copy)
            ex_obj[key] = remapped

    # Merge photometry
    if "photometry" in inc_obj:
        ex_photo = ex_obj.setdefault("photometry", [])
        # Set of existing (time, band) tuples
        existing_pts = set()
        for p in ex_photo:
            try:
                t = round(float(p.get("time", 0)), 3)
                b = p.get("band", "")
                existing_pts.add((t, b))
            except Exception:
                pass

        for p in inc_obj["photometry"]:
            try:
                t = round(float(p.get("time", 0)), 3)
                b = p.get("band", "")
                if (t, b) not in existing_pts:
                    p_copy = dict(p)
                    p_copy["source"] = source_alias_map.get(p.get("source"), "1")
                    ex_photo.append(p_copy)
                    existing_pts.add((t, b))
            except Exception:
                pass

        ex_photo.sort(key=lambda x: float(x.get("time", 0)))

    # Merge spectra
    if "spectra" in inc_obj:
        ex_spectra = ex_obj.setdefault("spectra", [])
        existing_filenames = {s.get("filename") for s in ex_spectra if s.get("filename")}
        for s in inc_obj["spectra"]:
            fn = s.get("filename")
            if fn and fn not in existing_filenames:
                s_copy = dict(s)
                s_copy["source"] = source_alias_map.get(s.get("source"), "1")
                ex_spectra.append(s_copy)
                existing_filenames.add(fn)

    return existing


def ingest_tns_batch(
    target_years: Set[str] = {"2022", "2023", "2024", "2025", "2026"},
    classified_only: bool = True,
    overwrite: bool = False,
    enrich_brokers: bool = False,
    limit: Optional[int] = None
) -> Tuple[int, int, int]:
    """Ingest TNS records into the catalog.
    
    Returns (created_count, merged_count, skipped_count).
    """
    SUPERNOVAE_OUTPUT.mkdir(parents=True, exist_ok=True)
    # Ensure sne-2025-2029 folder exists
    (SUPERNOVAE_OUTPUT / "sne-2025-2029").mkdir(parents=True, exist_ok=True)

    created_count = 0
    merged_count = 0
    skipped_count = 0

    rows_gen = stream_tns_rows(
        target_years=target_years,
        classified_only=classified_only
    )

    t0 = time.time()
    for row in rows_gen:
        if limit is not None and (created_count + merged_count) >= limit:
            break

        prefix = row.get("name_prefix", "SN").strip() or "SN"
        name = row.get("name", "").strip()
        cname = f"{prefix}{name}"

        # Determine year
        disc_date = row.get("discoverydate", "").strip()
        year = 2025
        if disc_date[:4].isdigit():
            year = int(disc_date[:4])

        dest_folder = get_target_repo_folder(year)
        dest_folder.mkdir(parents=True, exist_ok=True)
        dest_file = dest_folder / f"{cname}.json"

        existing_path = find_existing_event_file(cname)

        if existing_path and not overwrite and not enrich_brokers:
            skipped_count += 1
            continue

        cname, event_dict = build_event_dict(
            row,
            enrich_alerce=enrich_brokers,
            enrich_wiserep=enrich_brokers,
            enrich_tns_spectra=enrich_brokers,
        )

        if existing_path and existing_path.is_file():
            try:
                ex_data = json.loads(existing_path.read_text(encoding="utf-8"))
                merged = merge_event_data(ex_data, event_dict)
                atomic_write_json(existing_path, merged)
                merged_count += 1
            except Exception as e:
                logger.error(f"Error merging {cname}: {e}")
                atomic_write_json(dest_file, event_dict)
                created_count += 1
        else:
            atomic_write_json(dest_file, event_dict)
            created_count += 1

        total = created_count + merged_count
        if total > 0 and total % 1000 == 0:
            elapsed = time.time() - t0
            rate = total / max(elapsed, 0.001)
            print(f"[Ingest] Processed {total} events ({rate:.1f} events/sec)...")

    elapsed = time.time() - t0
    print(f"[Ingest Complete] Created: {created_count}, Merged: {merged_count}, Skipped: {skipped_count} in {elapsed:.1f}s")
    return created_count, merged_count, skipped_count


def _get_or_add_source(
    event: Dict[str, Any],
    name: str,
    bibcode: Optional[str] = None,
    reference: Optional[str] = None,
    url: Optional[str] = None,
    secondary: bool = False
) -> str:
    """Find existing source alias or add a new source entry."""
    sources = event.setdefault("sources", [])
    for s in sources:
        if bibcode and s.get("bibcode") == bibcode:
            return s.get("alias", "1")
        if name and s.get("name") == name:
            return s.get("alias", "1")
    new_alias = str(len(sources) + 1)
    new_src: Dict[str, Any] = {"name": name, "alias": new_alias}
    if bibcode:
        new_src["bibcode"] = bibcode
    if reference:
        new_src["reference"] = reference
    if url:
        new_src["url"] = url
    if secondary:
        new_src["secondary"] = True
    sources.append(new_src)
    return new_alias


def enrich_event(
    object_name: str,
    fetch_lightcurve: bool = True,
    fetch_spectra: bool = True,
    force: bool = False,
) -> bool:
    """Enrich a single event with ALeRCE light curves and WISeREP spectra, thread-safe with TTL caching."""
    clean_name = object_name.strip()
    if clean_name.startswith("sn") or clean_name.startswith("at"):
        clean_name = clean_name[:2].upper() + clean_name[2:]

    # Mutex lock per supernova to prevent concurrent API stampedes or write races
    obj_lock = get_object_lock(clean_name)
    with obj_lock:
        file_path = find_existing_event_file(clean_name)
        event_data = None

        if file_path and file_path.is_file():
            try:
                event_data = json.loads(file_path.read_text(encoding="utf-8"))
                # Fast exit if another thread already refreshed this event while we waited
                if not force:
                    stale, _ = is_event_stale(event_data, file_path)
                    if not stale:
                        return True
            except Exception as e:
                logger.warning(f"Error loading {file_path}: {e}")

        if not event_data:
            # Prefer the public-objects ZIP; when the object is newer than the ZIP
            # (or the archive is absent), bootstrap from the TNS object page so
            # photometry is not silently discarded.
            bare_name = clean_name[2:] if clean_name.startswith(("SN", "AT")) else clean_name
            rows: List[Dict[str, str]] = []
            try:
                rows = list(stream_tns_rows(target_names={bare_name}, classified_only=False))
            except FileNotFoundError as exc:
                global _TNS_ZIP_WARNED
                if not _TNS_ZIP_WARNED:
                    _TNS_ZIP_WARNED = True
                    logger.warning("TNS public catalog unavailable: %s", exc)
                    print(f"Warning: {exc}", flush=True)
            if rows:
                cname, event_data = build_event_dict(
                    rows[0], enrich_alerce=False, enrich_wiserep=False, enrich_tns_spectra=False
                )
                disc_date = rows[0].get("discoverydate", "")
                year = int(disc_date[:4]) if disc_date[:4].isdigit() else 2026
            else:
                from ingest.tns_photometry import fetch_tns_photometry
                from ingest.coordinates import ra_dec_to_deg

                cov = fetch_tns_photometry(bare_name, use_cache=False)
                if cov.get("status") not in ("ok", "empty"):
                    print(
                        f"Error: Could not find '{object_name}' in TNS ZIP or object page "
                        f"(status={cov.get('status')} err={cov.get('error')}).",
                        flush=True,
                    )
                    return False
                header = cov.get("header") or {}
                prefix = "AT" if clean_name.startswith("AT") else (
                    "SN" if clean_name.startswith("SN") else "AT"
                )
                ra_sex = header.get("ra_sexagesimal", "")
                dec_sex = header.get("dec_sexagesimal", "")
                ra_deg = dec_deg = None
                if ra_sex and dec_sex:
                    try:
                        ra_deg, dec_deg = ra_dec_to_deg(ra_sex, dec_sex)
                    except Exception:
                        ra_deg = dec_deg = None
                sparse = {
                    "name_prefix": prefix,
                    "name": bare_name,
                    "ra": f"{ra_deg:.8f}" if ra_deg is not None else "",
                    "declination": f"{dec_deg:.8f}" if dec_deg is not None else "",
                    "type": "",
                    "redshift": "",
                    "reporters": "",
                    "reporting_group": "",
                    "internal_names": header.get("internal_names") or cov.get("ztf_oid") or "",
                    "Discovery_ADS_bibcode": "",
                    "discoverydate": header.get("discoverydate") or "",
                    "discoverymag": header.get("discoverymag") or "",
                    "filter": header.get("filter") or "",
                }
                cname, event_data = build_event_dict(
                    sparse,
                    enrich_alerce=False,
                    enrich_wiserep=False,
                    enrich_tns_spectra=False,
                    tns_photometry_result=cov,
                )
                disc_date = sparse.get("discoverydate") or ""
                year = int(disc_date[:4]) if disc_date[:4].isdigit() else 2026
            dest_folder = get_target_repo_folder(year)
            dest_folder.mkdir(parents=True, exist_ok=True)
            file_path = dest_folder / f"{cname}.json"

        key = list(event_data.keys())[0]
        event = event_data[key]
        aliases = [a.get("value") for a in event.get("alias", []) if isinstance(a, dict)]

        # Determine TTL for upstream broker requests
        stale, ttl = is_event_stale(event_data, file_path)
        broker_cache_age = 0 if force else (ttl if ttl > 0 else 86400)

        # Fetch ALeRCE lightcurve
        if fetch_lightcurve:
            ztf_oid = None
            for a in aliases:
                if a.startswith("ZTF") and len(a) >= 12:
                    ztf_oid = a
                    break

            if not ztf_oid:
                # Attempt coordinate-based cone match in ALeRCE for any transient observed by ZTF
                ra_entry = event.get("ra", [{}])[0].get("value")
                dec_entry = event.get("dec", [{}])[0].get("value")
                if ra_entry and dec_entry:
                    from ingest.coordinates import ra_dec_to_deg
                    coords_deg = ra_dec_to_deg(ra_entry, dec_entry)
                    if coords_deg:
                        r_deg, d_deg = coords_deg
                        if d_deg >= -32.0:
                            matched_oid = find_ztf_object_by_coords(r_deg, d_deg)
                            if matched_oid:
                                ztf_oid = matched_oid
                                if not any(a.get("value") == ztf_oid for a in event.get("alias", [])):
                                    event.setdefault("alias", []).append({"value": ztf_oid, "source": "ALeRCE Cone Match"})

            if ztf_oid:
                print(f"Querying ALeRCE for ZTF ID {ztf_oid}...")
                lc = get_alerce_lightcurve(ztf_oid, max_cache_age=broker_cache_age)
                if lc:
                    # Add ALeRCE source
                    src_alias = _get_or_add_source(
                        event,
                        name="ALeRCE / ZTF",
                        url=f"https://alerce.online/object/{ztf_oid}",
                        secondary=True,
                    )
                    photo = convert_alerce_to_astrocats_photometry(lc, source_alias=src_alias)
                    print(f"Retrieved {len(photo)} photometry points from ALeRCE "
                          f"(detections+limits; kinds preserved).")
                    existing_keys = {
                        photometry_dedupe_key(p)
                        for p in event.get("photometry", [])
                        if isinstance(p, dict)
                    }
                    for p in photo:
                        pkey = photometry_dedupe_key(p)
                        if pkey not in existing_keys:
                            event.setdefault("photometry", []).append(p)
                            existing_keys.add(pkey)
                    event["photometry"].sort(key=lambda x: float(x.get("time", 0)))
                    event.setdefault("photometry_ingest", {})["alerce"] = {
                        "status": "ok",
                        "n_points": len(photo),
                    }
                else:
                    event.setdefault("photometry_ingest", {})["alerce"] = {
                        "status": "empty",
                        "oid": ztf_oid,
                    }
            else:
                event.setdefault("photometry_ingest", {})["alerce"] = {"status": "empty"}

        # TNS photometry fallback / complement — ALeRCE absence is not evidence
        # that no observations exist (fresh ZTF alerts often miss ALeRCE).
        prior_tns = (event.get("photometry_ingest") or {}).get("tns") or {}
        if prior_tns.get("status") == "ok" and not force:
            print(
                f"[TNS Photometry] {clean_name}: already ok "
                f"det={prior_tns.get('n_detections')} lim={prior_tns.get('n_limits')}",
                flush=True,
            )
        else:
            try:
                from ingest.tns_photometry import apply_tns_photometry_to_event
                tns_id = clean_name[2:] if clean_name.startswith(("SN", "AT")) else clean_name
                tns_src = _get_or_add_source(
                    event,
                    name="Transient Name Server",
                    url=f"https://www.wis-tns.org/object/{tns_id}",
                    secondary=True,
                )
                cov = apply_tns_photometry_to_event(event, tns_id, source_alias=tns_src)
                print(
                    f"[TNS Photometry] {clean_name}: status={cov.get('status')} "
                    f"det={cov.get('n_detections')} lim={cov.get('n_limits')} "
                    f"via={cov.get('source')}",
                    flush=True,
                )
            except Exception as exc:
                logger.warning("TNS photometry enrich failed for %s: %s", clean_name, exc)
                event.setdefault("photometry_ingest", {})["tns"] = {
                    "status": "error",
                    "error": str(exc),
                }

        # Fetch TNS and WISeREP spectra
        if fetch_spectra:
            tns_id = clean_name[2:] if clean_name.startswith(("SN", "AT")) else clean_name
            current_spectra = event.setdefault("spectra", [])

            # 1. Query TNS directly for public classification spectra
            try:
                print(f"Querying TNS for {tns_id} classification spectra...")
                trows = search_tns_spectra(tns_id, max_cache_age=broker_cache_age)
                if trows:
                    tns_alias = _get_or_add_source(
                        event,
                        name="Transient Name Server",
                        url=f"https://www.wis-tns.org/object/{tns_id}",
                        secondary=True,
                    )
                    tspecs = convert_tns_to_astrocats_spectra(trows, source_alias=tns_alias, max_spectra=5)
                    print(f"Retrieved {len(tspecs)} spectra from TNS.")
                    for s in tspecs:
                        if not is_duplicate_spectrum(s, current_spectra):
                            current_spectra.append(s)
            except Exception as e:
                logger.warning(f"TNS spectra query failed for {tns_id}: {e}")

            # 2. Query WISeREP (merge any non-duplicate calibrated spectra)
            try:
                print(f"Querying WISeREP for {tns_id} spectra...")
                wrows = search_wiserep_spectra(tns_id, max_cache_age=broker_cache_age)
                if wrows:
                    src_alias = _get_or_add_source(
                        event,
                        name="WISeREP",
                        bibcode="2012PASP..124..668Y",
                        reference="Yaron & Gal-Yam (2012)",
                        url="https://www.wiserep.org",
                        secondary=True,
                    )
                    specs = convert_wiserep_to_astrocats_spectra(wrows, source_alias=src_alias, max_spectra=5)
                    print(f"Retrieved {len(specs)} spectra from WISeREP.")
                    for s in specs:
                        if not is_duplicate_spectrum(s, current_spectra):
                            current_spectra.append(s)
            except Exception as e:
                logger.warning(f"WISeREP spectra query failed for {tns_id}: {e}")

        # Calculate Cosmological Distances & Recession Velocity
        dl_val = None
        z_val = None
        if "redshift" in event and event["redshift"]:
            try:
                z_val = float(event["redshift"][0].get("value", 0))
                if z_val > 0:
                    cosmo = compute_cosmology(z_val)
                    if cosmo:
                        planck_src = _get_or_add_source(
                            event,
                            name="Planck 2015",
                            bibcode="2016A&A...594A..13P",
                            reference="Planck Collaboration (2016)",
                            secondary=True,
                        )
                        dl_val = cosmo["lumdist"]
                        event["lumdist"] = [{
                            "value": str(cosmo["lumdist"]),
                            "derived": True,
                            "u_value": "Mpc",
                            "source": planck_src,
                        }]
                        event["comovingdist"] = [{
                            "value": str(cosmo["comovingdist"]),
                            "derived": True,
                            "u_value": "Mpc",
                            "source": planck_src,
                        }]
                        event["velocity"] = [{
                            "value": str(cosmo["velocity"]),
                            "derived": True,
                            "u_value": "km/s",
                            "source": planck_src,
                        }]
            except (ValueError, TypeError):
                pass

        # Query NASA/IPAC IRSA for Galactic Line-of-Sight Dust Extinction E(B-V)
        if "ra" in event and "dec" in event and event["ra"] and event["dec"]:
            ra_str = event["ra"][0].get("value", "")
            dec_str = event["dec"][0].get("value", "")
            if ra_str and dec_str and ":" in ra_str:
                try:
                    ra_deg, dec_deg = ra_dec_to_deg(ra_str, dec_str)
                    ebv_val, ebv_err = fetch_irsa_dust(ra_deg, dec_deg)
                    if ebv_val:
                        sandf_src = _get_or_add_source(
                            event,
                            name="Schlafly & Finkbeiner (2011)",
                            bibcode="2011ApJ...737..103S",
                            reference="Schlafly & Finkbeiner (2011)",
                            secondary=True,
                        )
                        ebv_entry: Dict[str, Any] = {
                            "value": ebv_val,
                            "derived": True,
                            "source": sandf_src,
                        }
                        if ebv_err:
                            ebv_entry["e_value"] = ebv_err
                        event["ebv"] = [ebv_entry]
                except Exception:
                    pass

        # Peak Apparent and Absolute Magnitudes — only when ≥2 detections
        # establish a light-curve peak. A single discovery point stays in
        # discoverymag / brightest_observed_mag, never as fitted peak.
        if "photometry" in event and event["photometry"]:
            peaks = compute_peak_magnitudes(event["photometry"], dl_mpc=dl_val, z=z_val)
            if peaks:
                src = peaks.get("max_source") or peaks.get("brightest_observed_source") or "1"
                bright = peaks.get("brightest_observed_mag")
                if bright is not None:
                    event["brightest_observed_mag"] = [{
                        "value": str(bright),
                        "kind": "brightest_observed",
                        "band": peaks.get("brightest_observed_band") or "",
                        "source": src,
                    }]
                if peaks.get("peak_established"):
                    for k in (
                        "maxappmag", "maxdate", "maxband",
                        "maxabsmag", "maxvisualappmag", "maxvisualdate",
                        "maxvisualband", "maxvisualabsmag",
                    ):
                        if k not in peaks:
                            continue
                        event[k] = [{
                            "value": str(peaks[k]),
                            "kind": "fitted_peak" if k.endswith("mag") else "peak_epoch",
                            "derived": True,
                            "source": src,
                        }]
                else:
                    # Strip fabricated peaks; keep discovery-tagged scalars.
                    for k in (
                        "maxappmag", "maxdate", "maxband",
                        "maxabsmag", "maxvisualappmag", "maxvisualdate",
                        "maxvisualband", "maxvisualabsmag",
                    ):
                        entries = event.get(k)
                        if not isinstance(entries, list):
                            event.pop(k, None)
                            continue
                        kept = []
                        for e in entries:
                            if not isinstance(e, dict):
                                continue
                            kind = e.get("kind") or ""
                            if kind in ("discovery", "listing"):
                                kept.append(e)
                            elif e.get("derived") or kind in ("fitted_peak", "peak_epoch"):
                                continue
                            else:
                                e = dict(e)
                                e["kind"] = "discovery"
                                kept.append(e)
                        if kept:
                            event[k] = kept
                        else:
                            event.pop(k, None)

        from ingest.event_file_lock import event_file_lock
        with event_file_lock(file_path):
            # Re-read under lock so concurrent backfill/sync cannot be clobbered.
            try:
                latest = json.loads(file_path.read_text(encoding="utf-8"))
                if isinstance(latest, dict) and latest:
                    # Prefer our enriched body but keep any photometry keys added
                    # by a concurrent writer that we do not already have.
                    # photometry_dedupe_key is imported at module scope — do NOT
                    # re-import it here; a local import makes the name unbound for
                    # the whole function and crashes EnrichQueue after ALeRCE returns.
                    our_name = next(iter(event_data))
                    if our_name in latest and isinstance(latest[our_name], dict):
                        theirs = latest[our_name]
                        ours = event_data[our_name]
                        their_ph = [p for p in (theirs.get("photometry") or []) if isinstance(p, dict)]
                        our_ph = [p for p in (ours.get("photometry") or []) if isinstance(p, dict)]
                        keys = {photometry_dedupe_key(p) for p in our_ph}
                        for p in their_ph:
                            k = photometry_dedupe_key(p)
                            if k not in keys:
                                our_ph.append(p)
                                keys.add(k)
                        ours["photometry"] = our_ph
            except Exception:
                pass
            atomic_write_json(file_path, event_data)
            flat_json = SUPERNOVAE_OUTPUT / "json" / file_path.name
            if flat_json.parent.is_dir():
                try:
                    atomic_write_json(flat_json, event_data)
                except Exception:
                    pass
        print(f"Updated {file_path.name} with enriched broker data.")
        # Homepage /api/transients reads CatalogStore + published-updates overlay.
        # Without a publish here, enriched maxappmag/photometry stay invisible in
        # the table even though the event page shows them.
        try:
            from ingest.publication import publish_event_paths
            pub = publish_event_paths([file_path])
            if pub.get("state") == "failed":
                logger.warning(
                    "catalog publish after enrich failed for %s: %s",
                    file_path.name,
                    pub.get("error"),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog publish after enrich raised for %s: %s", file_path.name, exc)
        return True


def run_webcat_rebuild() -> int:
    """Run astrocats webcat to regenerate aggregates."""
    print("[Rebuild] Running webcat aggregate regeneration...")
    cmd = [
        "uv", "run", "python", "-m", "astrocats.scripts.webcat",
        "-c", "sne", "--no-write-html", "--no-collect-hosts"
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_BASE))
    return proc.returncode
