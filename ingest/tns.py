"""IAU Transient Name Server (TNS) ingest and event builder."""
import csv
import io
import json
import logging
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Set, Tuple

from ingest.alerce import (
    convert_alerce_to_astrocats_photometry,
    find_ztf_object_by_coords,
    get_alerce_lightcurve,
)
from ingest.coordinates import deg_to_ra_dec, parse_float_safe, parse_iso_datetime
from ingest.tns_spectra import convert_tns_to_astrocats_spectra, is_duplicate_spectrum, search_tns_spectra
from ingest.tns_photometry import apply_tns_photometry_to_event, photometry_merge
from ingest.wiserep import convert_wiserep_to_astrocats_spectra, search_wiserep_spectra

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZIP_PATH = Path("ingest/cache/tns_public_objects.csv.zip")
OSC_SCHEMA_URL = "https://github.com/astrocatalogs/supernovae/blob/d3ef5fc/SCHEMA.md"
OSC_BIBCODE = "2017ApJ...835...64G"
OSC_REFERENCE = "Guillochon et al. (2017)"
OSC_URL = "https://sne.space"


def resolve_tns_public_zip(zip_path: Optional[Path] = None) -> Path:
    """Locate the TNS public-objects ZIP across env, runtime volume, and repo paths.

    Production images historically omitted ``ingest/cache/`` via ``.dockerignore``,
    so a CWD-relative default alone 404s EnrichQueue. Prefer an explicit env path,
    then the durable runtime volume, then absolute repo-relative locations.

    An explicit ``zip_path`` argument is strict (no fallback): callers that pass a
    path mean that path.
    """
    if zip_path is not None:
        return Path(zip_path)

    candidates: List[Path] = []
    env_zip = (os.environ.get("SNE_TNS_PUBLIC_ZIP") or "").strip()
    if env_zip:
        candidates.append(Path(env_zip))
    runtime_dir = (os.environ.get("SNE_RUNTIME_DIR") or "").strip()
    if runtime_dir:
        candidates.append(Path(runtime_dir) / "tns_public_objects.csv.zip")
    candidates.extend(
        [
            _REPO_ROOT / "ingest" / "cache" / "tns_public_objects.csv.zip",
            Path("/app/ingest/cache/tns_public_objects.csv.zip"),
            Path("ingest/cache/tns_public_objects.csv.zip"),
            DEFAULT_ZIP_PATH,
        ]
    )
    seen: Set[str] = set()
    for cand in candidates:
        key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        if cand.is_file():
            return cand
    return candidates[0] if candidates else DEFAULT_ZIP_PATH


def stream_tns_rows(
    zip_path: Optional[Path] = None,
    target_years: Optional[Set[str]] = None,
    classified_only: bool = True,
    target_names: Optional[Set[str]] = None
) -> Generator[Dict[str, str], None, None]:
    """Stream filtered rows from the TNS public objects CSV archive."""
    resolved = resolve_tns_public_zip(zip_path)
    if not resolved.is_file():
        raise FileNotFoundError(f"TNS ZIP archive not found at {resolved}")

    with zipfile.ZipFile(resolved, "r") as z:
        with z.open("tns_public_objects.csv", "r") as f:
            # Skip timestamp header line
            f.readline()
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
            for row in reader:
                obj_name = row.get("name", "").strip()
                if not obj_name:
                    continue

                if target_names and obj_name not in target_names and f"SN{obj_name}" not in target_names and f"AT{obj_name}" not in target_names:
                    continue

                disc_date = row.get("discoverydate", "").strip()
                disc_year = disc_date[:4] if disc_date else ""

                if target_years and disc_year not in target_years:
                    continue

                sn_type = row.get("type", "").strip()
                prefix = row.get("name_prefix", "").strip()

                if classified_only and not sn_type and prefix != "SN":
                    continue

                yield row


def parse_aliases(prefix: str, name: str, internal_names: str) -> List[str]:
    """Generate comprehensive alias set from TNS name and survey designations."""
    aliases: Set[str] = set()

    clean_name = name.strip()
    # Canonical forms
    aliases.add(f"{prefix}{clean_name}")
    if prefix == "SN":
        aliases.add(f"AT{clean_name}")
        aliases.add(f"SN {clean_name}")
    elif prefix == "AT":
        aliases.add(f"SN{clean_name}")
        aliases.add(f"AT {clean_name}")
    aliases.add(clean_name)

    if internal_names:
        for item in internal_names.split(","):
            raw = item.strip()
            if raw and raw != "-" and raw.lower() != "none":
                aliases.add(raw)
                # If survey name has variations like 'SN 2024ggi'
                if raw.startswith("SN "):
                    aliases.add(f"SN{raw[3:].strip()}")
                elif raw.startswith("AT "):
                    aliases.add(f"AT{raw[3:].strip()}")

    # Stable sorted return
    return sorted(aliases, key=lambda x: (len(x), x))


def build_event_dict(
    row: Dict[str, str],
    enrich_alerce: bool = False,
    enrich_wiserep: bool = False,
    enrich_tns_spectra: bool = True,
    tns_photometry_result: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Transform a TNS row into a full AstroCats JSON event dict."""
    prefix = row.get("name_prefix", "SN").strip() or "SN"
    name = row.get("name", "").strip()
    canonical_name = f"{prefix}{name}"

    sources: List[Dict[str, Any]] = []
    source_counter = 1

    # Source 1: TNS
    tns_source_alias = str(source_counter)
    sources.append({
        "name": "Transient Name Server",
        "url": f"https://www.wis-tns.org/object/{name}",
        "alias": tns_source_alias,
    })
    source_counter += 1

    # Source 2: ADS Discovery Bibcode (if present)
    disc_bibcode = row.get("Discovery_ADS_bibcode", "").strip()
    disc_source_alias = tns_source_alias
    if disc_bibcode:
        disc_source_alias = str(source_counter)
        reporters = row.get("reporters", "").strip()
        ref_text = reporters.split(",")[0].strip() if reporters else "Discovery Report"
        sources.append({
            "name": disc_bibcode,
            "bibcode": disc_bibcode,
            "reference": ref_text,
            "alias": disc_source_alias,
        })
        source_counter += 1

    # Source: Open Supernova Catalog provenance
    osc_source_alias = str(source_counter)
    sources.append({
        "name": "The Open Supernova Catalog",
        "bibcode": OSC_BIBCODE,
        "reference": OSC_REFERENCE,
        "secondary": True,
        "url": OSC_URL,
        "alias": osc_source_alias,
    })
    source_counter += 1

    # Aliases
    internal_names = row.get("internal_names", "")
    alias_list = parse_aliases(prefix, name, internal_names)
    alias_entries = [{"value": a, "source": tns_source_alias} for a in alias_list]

    event: Dict[str, Any] = {
        "schema": OSC_SCHEMA_URL,
        "name": canonical_name,
        "sources": sources,
        "alias": alias_entries,
    }

    # Coordinates
    ra_val = parse_float_safe(row.get("ra"))
    dec_val = parse_float_safe(row.get("declination"))
    if ra_val is not None and dec_val is not None:
        ra_str, dec_str = deg_to_ra_dec(ra_val, dec_val)
        event["ra"] = [{
            "value": ra_str,
            "u_value": "hours",
            "source": tns_source_alias,
        }]
        event["dec"] = [{
            "value": dec_str,
            "u_value": "degrees",
            "source": tns_source_alias,
        }]

    # Claimed Type
    raw_type = row.get("type", "").strip()
    if raw_type:
        clean_type = raw_type
        if clean_type.startswith("SN "):
            clean_type = clean_type[3:].strip()
        elif clean_type.startswith("SN"):
            clean_type = clean_type[2:].strip()
        event["claimedtype"] = [{
            "value": clean_type,
            "source": tns_source_alias,
        }]

    # Redshift
    z_val = parse_float_safe(row.get("redshift"))
    if z_val is not None:
        event["redshift"] = [{
            "value": f"{z_val:.6g}",
            "kind": "spectroscopic",
            "source": tns_source_alias,
        }]

    # Discoverer
    reporters = row.get("reporters", "").strip()
    reporting_group = row.get("reporting_group", "").strip()
    discoverer_text = reporters or reporting_group
    if discoverer_text:
        event["discoverer"] = [{
            "value": discoverer_text,
            "source": tns_source_alias,
        }]

    # Discovery Date
    disc_date_raw = row.get("discoverydate", "").strip()
    parsed_date = parse_iso_datetime(disc_date_raw)
    disc_mjd: Optional[float] = None
    if parsed_date:
        _, disc_mjd, cat_date = parsed_date
        event["discoverdate"] = [{
            "value": cat_date,
            "source": tns_source_alias,
        }]

    # Discovery magnitude is a distinct quantity — never silently promoted to a
    # fitted peak. Persist it with explicit semantics; photometry points come
    # from TNS/ALeRCE observation tables below.
    disc_mag_val = parse_float_safe(row.get("discoverymag"))
    disc_filter = row.get("filter", "").strip()
    photometry: List[Dict[str, Any]] = []

    if disc_mag_val is not None:
        disc_entry: Dict[str, Any] = {
            "value": f"{disc_mag_val:g}",
            "kind": "discovery",
            "source": disc_source_alias,
        }
        if disc_filter:
            disc_entry["band"] = disc_filter
        if disc_mjd is not None:
            disc_entry["time"] = f"{disc_mjd:.5f}"
            disc_entry["u_time"] = "MJD"
        event["discoverymag"] = [disc_entry]

    # Optional Enrichment: ALeRCE ZTF Light Curve
    alerce_cov: Dict[str, Any] = {"status": "unavailable"}
    if enrich_alerce:
        ztf_oid = None
        for a in alias_list:
            # Internal-name fields can be space/comma joined; take a clean ZTF token.
            for token in str(a).replace(",", " ").split():
                if token.startswith("ZTF") and len(token) >= 12 and " " not in token:
                    ztf_oid = token
                    break
            if ztf_oid:
                break

        if not ztf_oid and ra_val is not None and dec_val is not None:
            ztf_oid = find_ztf_object_by_coords(ra_val, dec_val)
            if ztf_oid and ztf_oid not in alias_list:
                alias_list.append(ztf_oid)
                event["alias"].append({"value": ztf_oid, "source": tns_source_alias})

        if ztf_oid:
            alerce_data = get_alerce_lightcurve(ztf_oid)
            if alerce_data:
                alerce_source_alias = str(source_counter)
                sources.append({
                    "name": "ALeRCE / ZTF",
                    "url": f"https://alerce.online/object/{ztf_oid}",
                    "secondary": True,
                    "alias": alerce_source_alias,
                })
                source_counter += 1
                ztf_photo = convert_alerce_to_astrocats_photometry(
                    alerce_data, source_alias=alerce_source_alias
                )
                photometry = photometry_merge(photometry, ztf_photo)
                alerce_cov = {
                    "status": "ok",
                    "n_detections": sum(1 for p in ztf_photo if not p.get("upperlimit")),
                    "n_limits": sum(1 for p in ztf_photo if p.get("upperlimit")),
                }
            else:
                alerce_cov = {"status": "empty", "oid": ztf_oid}
        else:
            alerce_cov = {"status": "empty", "oid": None}

    event["photometry"] = photometry
    event.setdefault("photometry_ingest", {})["alerce"] = alerce_cov

    # TNS object photometry (detections + upper limits). Always attempted so an
    # ALeRCE miss cannot erase real TNS observations for fresh ZTF alerts.
    apply_tns_photometry_to_event(
        event,
        name,
        source_alias=tns_source_alias,
        fetch_result=tns_photometry_result,
    )

    # Magnitude summary fields derived only from persisted detections.
    dets = [
        p for p in (event.get("photometry") or [])
        if isinstance(p, dict)
        and not p.get("upperlimit")
        and p.get("kind") != "non_detection"
        and p.get("magnitude") is not None
        and not str(p.get("magnitude")).startswith(">")
    ]
    if len(dets) >= 2:
        try:
            brightest = min(dets, key=lambda p: float(p["magnitude"]))
            event["maxappmag"] = [{
                "value": str(brightest["magnitude"]),
                "kind": "brightest_observed",
                "source": brightest.get("source", tns_source_alias),
            }]
            if brightest.get("time"):
                event["maxdate"] = [{
                    "value": row.get("discoverydate", "")[:10].replace("-", "/"),
                    "source": tns_source_alias,
                }]
        except Exception:
            pass
    elif disc_mag_val is not None and not event.get("maxappmag"):
        # Listing convenience only — kind marks it as discovery, never fitted peak.
        event["maxappmag"] = [{
            "value": f"{disc_mag_val:g}",
            "kind": "discovery",
            "source": disc_source_alias,
        }]

    # Spectra Enrichment: Direct TNS Public Spectra and/or WISeREP
    all_spectra: List[Dict[str, Any]] = []

    if enrich_tns_spectra:
        tns_spec_rows = search_tns_spectra(name)
        if tns_spec_rows:
            tns_spectra = convert_tns_to_astrocats_spectra(
                tns_spec_rows, source_alias=tns_source_alias, max_spectra=5
            )
            for s in tns_spectra:
                if not is_duplicate_spectrum(s, all_spectra):
                    all_spectra.append(s)

    if enrich_wiserep:
        wiserep_rows = search_wiserep_spectra(name)
        if wiserep_rows:
            wiserep_source_alias = str(source_counter)
            sources.append({
                "name": "WISeREP",
                "bibcode": "2012PASP..124..668Y",
                "reference": "Yaron & Gal-Yam (2012)",
                "secondary": True,
                "url": "https://www.wiserep.org",
                "alias": wiserep_source_alias,
            })
            source_counter += 1
            wiserep_specs = convert_wiserep_to_astrocats_spectra(
                wiserep_rows, source_alias=wiserep_source_alias, max_spectra=5
            )
            for s in wiserep_specs:
                if not is_duplicate_spectrum(s, all_spectra):
                    all_spectra.append(s)

    if all_spectra:
        event["spectra"] = all_spectra

    return canonical_name, {canonical_name: event}
