"""IAU Transient Name Server (TNS) ingest and event builder."""
import csv
import io
import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Set, Tuple

from ingest.alerce import convert_alerce_to_astrocats_photometry, get_alerce_lightcurve
from ingest.coordinates import deg_to_ra_dec, parse_float_safe, parse_iso_datetime
from ingest.wiserep import convert_wiserep_to_astrocats_spectra, search_wiserep_spectra

logger = logging.getLogger(__name__)

DEFAULT_ZIP_PATH = Path("ingest/cache/tns_public_objects.csv.zip")
OSC_SCHEMA_URL = "https://github.com/astrocatalogs/supernovae/blob/d3ef5fc/SCHEMA.md"
OSC_BIBCODE = "2017ApJ...835...64G"
OSC_REFERENCE = "Guillochon et al. (2017)"
OSC_URL = "https://sne.space"


def stream_tns_rows(
    zip_path: Path = DEFAULT_ZIP_PATH,
    target_years: Optional[Set[str]] = None,
    classified_only: bool = True,
    target_names: Optional[Set[str]] = None
) -> Generator[Dict[str, str], None, None]:
    """Stream filtered rows from the TNS public objects CSV archive."""
    if not zip_path.is_file():
        raise FileNotFoundError(f"TNS ZIP archive not found at {zip_path}")

    with zipfile.ZipFile(zip_path, "r") as z:
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
    enrich_wiserep: bool = False
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

    # Initial Photometry (Discovery Magnitude)
    disc_mag_val = parse_float_safe(row.get("discoverymag"))
    disc_filter = row.get("filter", "").strip()
    photometry: List[Dict[str, Any]] = []

    if disc_mag_val is not None and disc_mjd is not None:
        photo_entry: Dict[str, Any] = {
            "time": f"{disc_mjd:.5f}",
            "magnitude": f"{disc_mag_val:.2f}",
            "band": disc_filter or "Clear",
            "u_time": "MJD",
            "source": disc_source_alias,
        }
        if reporting_group and reporting_group.lower() != "none":
            photo_entry["telescope"] = reporting_group
        photometry.append(photo_entry)

    # Optional Enrichment: ALeRCE ZTF Light Curve
    if enrich_alerce:
        ztf_oid = None
        for a in alias_list:
            if a.startswith("ZTF") and len(a) >= 12:
                ztf_oid = a
                break

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
                photometry.extend(ztf_photo)

    if photometry:
        photometry.sort(key=lambda x: float(x.get("time", 0)))
        event["photometry"] = photometry

    # Optional Enrichment: WISeREP Classification Spectra
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
            spectra = convert_wiserep_to_astrocats_spectra(
                wiserep_rows, source_alias=wiserep_source_alias, max_spectra=3
            )
            if spectra:
                event["spectra"] = spectra

    return canonical_name, {canonical_name: event}
