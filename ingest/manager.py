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
    find_ztf_object_by_coords,
    get_alerce_lightcurve,
)
from ingest.astronomy import compute_cosmology, compute_peak_magnitudes, fetch_irsa_dust
from ingest.coordinates import ra_dec_to_deg
from ingest.tns import build_event_dict, stream_tns_rows
from ingest.tns_spectra import convert_tns_to_astrocats_spectra, is_duplicate_spectrum, search_tns_spectra
from ingest.wiserep import convert_wiserep_to_astrocats_spectra, search_wiserep_spectra

logger = logging.getLogger(__name__)

_OUTPUT_CANDIDATES = [
    Path("serve/www/astrocats/astrocats/supernovae/output"),
    Path(__file__).resolve().parent.parent / "serve/www/astrocats/astrocats/supernovae/output",
    Path("vendor/astrocats/astrocats/supernovae/output"),
]
SUPERNOVAE_OUTPUT = next((p for p in _OUTPUT_CANDIDATES if p.is_dir()), _OUTPUT_CANDIDATES[0])

_enrich_locks: Dict[str, threading.Lock] = {}
_enrich_meta_lock = threading.Lock()


def get_object_lock(name: str) -> threading.Lock:
    """Retrieve or create an in-process mutex lock for a specific supernova."""
    with _enrich_meta_lock:
        if name not in _enrich_locks:
            _enrich_locks[name] = threading.Lock()
        return _enrich_locks[name]


def atomic_write_json(file_path: Path, data: Any) -> None:
    """Write JSON data to disk atomically using temporary file and os.replace."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    # Temporary file in same directory guarantees same filesystem for atomic rename
    tmp_path = file_path.with_name(f".{file_path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp_path, file_path)
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
            # Fetch row from TNS
            bare_name = clean_name[2:] if clean_name.startswith(("SN", "AT")) else clean_name
            rows = list(stream_tns_rows(target_names={bare_name}, classified_only=False))
            if not rows:
                print(f"Error: Could not find '{object_name}' in TNS database or local catalog.")
                return False
            cname, event_data = build_event_dict(rows[0], enrich_alerce=False, enrich_wiserep=False)
            disc_date = rows[0].get("discoverydate", "")
            year = int(disc_date[:4]) if disc_date[:4].isdigit() else 2025
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
                    print(f"Retrieved {len(photo)} photometry detections from ALeRCE.")
                    # Merge into event photometry
                    existing_pts = {
                        (round(float(p.get("time", 0)), 3), p.get("band", ""))
                        for p in event.get("photometry", [])
                    }
                    for p in photo:
                        t = round(float(p.get("time", 0)), 3)
                        b = p.get("band", "")
                        if (t, b) not in existing_pts:
                            event.setdefault("photometry", []).append(p)
                            existing_pts.add((t, b))
                    event["photometry"].sort(key=lambda x: float(x.get("time", 0)))

        # Fetch TNS and WISeREP spectra
        if fetch_spectra:
            tns_id = key[2:] if key.startswith(("SN", "AT")) else key
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

        # Peak Apparent and Absolute Magnitudes
        if "photometry" in event and event["photometry"]:
            peaks = compute_peak_magnitudes(event["photometry"], dl_mpc=dl_val, z=z_val)
            if peaks:
                for k, val in peaks.items():
                    if k in ("max_source", "maxvisual_source"):
                        continue
                    src = peaks.get("max_source", "1")
                    event[k] = [{
                        "value": str(val),
                        "derived": True,
                        "source": src,
                    }]

        atomic_write_json(file_path, event_data)
        # Keep flat json/ in sync if it exists
        flat_json = SUPERNOVAE_OUTPUT / "json" / file_path.name
        if flat_json.parent.is_dir():
            try:
                atomic_write_json(flat_json, event_data)
            except Exception:
                pass
        print(f"Updated {file_path.name} with enriched broker data.")
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
