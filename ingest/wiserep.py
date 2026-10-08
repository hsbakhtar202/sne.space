"""WISeREP client for public classification spectra."""
import io
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ingest.coordinates import parse_iso_datetime

logger = logging.getLogger(__name__)

CACHE_META_DIR = Path("ingest/cache/wiserep/metadata")
CACHE_SPEC_DIR = Path("ingest/cache/wiserep/spectra")


def clean_object_name_for_wiserep(name: str) -> str:
    """Extract standard year+suffix or strip leading SN/AT for query."""
    s = name.strip()
    if s.startswith("SN ") or s.startswith("AT "):
        return s[3:].strip()
    if s.startswith("SN") or s.startswith("AT"):
        return s[2:].strip()
    return s


def search_wiserep_spectra(
    object_name: str,
    timeout: int = 15,
    use_cache: bool = True,
    max_cache_age: Optional[int] = None,
) -> List[Dict[str, str]]:
    """Query WISeREP for spectra records of a transient object with TTL support."""
    clean_name = clean_object_name_for_wiserep(object_name)
    if not clean_name:
        return []

    CACHE_META_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_META_DIR / f"{clean_name}.json"

    if use_cache and cache_path.is_file():
        is_fresh = True
        if max_cache_age is not None:
            is_fresh = (time.time() - cache_path.stat().st_mtime) <= max_cache_age
        if is_fresh:
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.debug(f"Cache read error for WISeREP {clean_name}: {e}")

    url = f"https://www.wiserep.org/search/spectra?name={clean_name}&format=tsv"
    headers = {
        "User-Agent": "Mozilla/5.0 (OpenSupernovaCatalog-Ingest/2.0; https://sne.space)",
        "Accept": "*/*",
    }
    req = urllib.request.Request(url, headers=headers)
    results: List[Dict[str, str]] = []

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                with z.open("wiserep_spectra.tsv") as f:
                    content = f.read().decode("utf-8", errors="replace")
                    lines = [line for line in content.splitlines() if line.strip()]
                    if len(lines) > 1:
                        header = lines[0].split("\t")
                        for line in lines[1:]:
                            parts = line.split("\t")
                            if len(parts) >= len(header):
                                row = dict(zip(header, parts))
                                ascii_url = row.get("Ascii file", "").strip()
                                # Only keep rows that match the object name and have an ascii file
                                row_obj = row.get("IAU name", "").strip()
                                if ascii_url and clean_name.lower() in row_obj.lower().replace(" ", ""):
                                    results.append(row)

        tmp_path = cache_path.with_name(f".{cache_path.name}.tmp.{os.getpid()}")
        tmp_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        os.replace(tmp_path, cache_path)
        return results
    except Exception as e:
        logger.warning(f"WISeREP search failed for {clean_name}: {e}")
        return []


def download_ascii_spectrum(
    url: str,
    timeout: int = 30,
    max_points: int = 5000,
    use_cache: bool = True
) -> Optional[List[List[str]]]:
    """Download and parse an ASCII spectrum file into [[wavelength, flux], ...]."""
    if not url or not url.startswith("http"):
        return None

    CACHE_SPEC_DIR.mkdir(parents=True, exist_ok=True)
    filename = url.split("/")[-1]
    cache_path = CACHE_SPEC_DIR / filename

    text = None
    if use_cache and cache_path.is_file():
        try:
            text = cache_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if text is None:
        headers = {"User-Agent": "Mozilla/5.0 (sne.space ingest)"}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                cache_path.write_text(text, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to download spectrum from {url}: {e}")
            return None

    # Parse wavelength and flux columns
    data_points: List[List[str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("%"):
            continue
        parts = re.split(r"[\s,]+", line)
        if len(parts) >= 2:
            try:
                wl = float(parts[0])
                fl = float(parts[1])
                data_points.append([f"{wl:.2f}", f"{fl:.5e}"])
            except ValueError:
                continue

    # Downsample if overly dense
    if len(data_points) > max_points:
        step = len(data_points) // max_points + 1
        data_points = data_points[::step]

    return data_points if data_points else None


def convert_wiserep_to_astrocats_spectra(
    wiserep_rows: List[Dict[str, str]],
    source_alias: str,
    max_spectra: int = 5
) -> List[Dict[str, Any]]:
    """Convert WISeREP search rows into AstroCats spectrum dictionaries."""
    spectra: List[Dict[str, Any]] = []

    for row in wiserep_rows[:max_spectra]:
        ascii_url = row.get("Ascii file", "").strip()
        if not ascii_url:
            continue

        data_points = download_ascii_spectrum(ascii_url)
        if not data_points:
            continue

        obs_date = row.get("Obs-date", "").strip()
        mjd_val = ""
        jd_str = row.get("JD", "").strip()
        if jd_str:
            try:
                mjd_val = f"{float(jd_str) - 2400000.5:.4f}"
            except ValueError:
                pass
        if not mjd_val and obs_date:
            parsed = parse_iso_datetime(obs_date)
            if parsed:
                mjd_val = f"{parsed[1]:.4f}"

        spec_entry: Dict[str, Any] = {
            "time": mjd_val or obs_date,
            "filename": ascii_url.split("/")[-1],
            "telescope": row.get("Telescope", "").strip(),
            "instrument": row.get("Instrument", "").strip(),
            "u_time": "MJD" if mjd_val else "",
            "u_wavelengths": "Angstrom",
            "u_fluxes": "erg/s/cm^2/Angstrom",
            "source": source_alias,
            "data": data_points,
        }
        # Clean empty keys
        spec_entry = {k: v for k, v in spec_entry.items() if v}
        spectra.append(spec_entry)

    return spectra
