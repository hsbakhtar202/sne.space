"""Transient Name Server (TNS) client for classification spectra."""
import datetime
import io
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CACHE_META_DIR = Path("ingest/cache/tns/metadata")
CACHE_SPEC_DIR = Path("ingest/cache/tns/spectra")

TNS_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def clean_object_name(name: str) -> str:
    """Extract standard bare designation (e.g. '2026acow' from 'SN 2026acow' or 'AT2026acow')."""
    s = name.strip()
    if s.startswith("SN ") or s.startswith("AT "):
        return s[3:].strip()
    if s.startswith("SN") or s.startswith("AT") or s.startswith("sn") or s.startswith("at"):
        return s[2:].strip()
    return s


def parse_tns_datetime_to_mjd(dt_str: str) -> Optional[float]:
    """Convert TNS UTC date string ('YYYY-MM-DD HH:MM:SS') to Modified Julian Date (MJD)."""
    if not dt_str:
        return None
    try:
        clean = dt_str.replace("T", " ").strip().split(".")[0]
        dt = datetime.datetime.strptime(clean, "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp() / 86400.0 + 40587.0
    except Exception:
        pass
    # Try date only
    try:
        parts = dt_str.split()[0].replace("-", "/").split("/")
        if len(parts) >= 3 and parts[0].isdigit():
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            dt = datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc)
            return dt.timestamp() / 86400.0 + 40587.0
    except Exception:
        pass
    return None


def search_tns_spectra(
    object_name: str,
    timeout: int = 12,
    use_cache: bool = True,
    max_cache_age: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Scrape and extract spectra metadata records for an object from its TNS page."""
    clean_name = clean_object_name(object_name)
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
                logger.debug(f"Cache read error for TNS {clean_name}: {e}")

    url = f"https://www.wis-tns.org/object/{clean_name}"
    headers = {"User-Agent": TNS_USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    req = urllib.request.Request(url, headers=headers)

    html = ""
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                reset_val = e.headers.get("x-rate-limit-reset", "")
                try:
                    wait_sec = float(reset_val) + 1.0
                except (ValueError, TypeError):
                    wait_sec = 10.0 * (attempt + 1)
                logger.warning(f"TNS 429 rate limit hit for {clean_name}. Backing off for {wait_sec:.1f}s (reset header)...")
                time.sleep(wait_sec)
                continue
            elif e.code == 404:
                logger.debug(f"TNS object {clean_name} not found (404).")
                return []
            else:
                logger.warning(f"TNS HTTP error for {clean_name}: {e}")
                return []
        except Exception as e:
            logger.warning(f"TNS request failed for {clean_name}: {e}")
            return []

    if not html:
        return []

    # Parse spectrum rows from HTML
    # TNS uses: <tr class="spectrum-row spectrum-rowXXXX ..."> ... </tr>
    rows = re.findall(r'<tr[^>]*class=[\"\'][^\"\']*spectrum-row[^\"\']*[\"\'][^>]*>(.*?)</tr>', html, re.S)
    results: List[Dict[str, Any]] = []
    seen_urls = set()

    for r in rows:
        ascii_m = re.search(r'<td[^>]*class=[\"\'][^\"\']*cell-asciifile[^\"\']*[\"\'][^>]*>.*?href=[\"\']([^\"\']+)[\"\']', r, re.S)
        if not ascii_m:
            continue
        ascii_url = ascii_m.group(1).strip()
        if not ascii_url.startswith("http"):
            if ascii_url.startswith("/"):
                ascii_url = f"https://www.wis-tns.org{ascii_url}"
            else:
                continue

        if ascii_url in seen_urls:
            continue
        seen_urls.add(ascii_url)

        obs_m = re.search(r'<td[^>]*class=[\"\'][^\"\']*cell-obsdate[^\"\']*[\"\'][^>]*>(.*?)</td>', r, re.S)
        tel_m = re.search(r'<td[^>]*class=[\"\'][^\"\']*cell-tel_inst[^\"\']*[\"\'][^>]*>(.*?)</td>', r, re.S)
        source_m = re.search(r'<td[^>]*class=[\"\'][^\"\']*cell-source_group_name[^\"\']*[\"\'][^>]*>(.*?)</td>', r, re.S)
        spec_id_m = re.search(r'<td[^>]*class=[\"\'][^\"\']*cell-id[^\"\']*[\"\'][^>]*>(.*?)</td>', r, re.S)

        obs_date = obs_m.group(1).strip() if obs_m else ""
        tel_inst = tel_m.group(1).strip() if tel_m else ""
        source_grp = source_m.group(1).strip() if source_m else ""
        spec_id = spec_id_m.group(1).strip() if spec_id_m else ""

        tel = ""
        inst = ""
        if "/" in tel_inst:
            parts = [p.strip() for p in tel_inst.split("/", 1)]
            tel, inst = parts[0], parts[1]
        elif tel_inst:
            tel = tel_inst

        results.append({
            "spec_id": spec_id,
            "obs_date": obs_date,
            "telescope": tel,
            "instrument": inst,
            "source_group": source_grp,
            "ascii_url": ascii_url,
            "filename": ascii_url.split("/")[-1],
        })

    # Cache metadata
    try:
        tmp_path = cache_path.with_name(f".{cache_path.name}.tmp.{os.getpid()}")
        tmp_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        os.replace(tmp_path, cache_path)
    except Exception as e:
        logger.debug(f"Failed to cache TNS spectra metadata for {clean_name}: {e}")

    return results


def download_tns_ascii_spectrum(
    url: str,
    timeout: int = 12,
    max_points: int = 5000,
    use_cache: bool = True
) -> Optional[List[List[str]]]:
    """Download and parse an ASCII/DAT/TXT spectrum file from TNS."""
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
        headers = {"User-Agent": TNS_USER_AGENT}
        req = urllib.request.Request(url, headers=headers)
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    text = resp.read().decode("utf-8", errors="replace")
                    tmp_cache = cache_path.with_name(f".{filename}.tmp.{os.getpid()}")
                    tmp_cache.write_text(text, encoding="utf-8")
                    os.replace(tmp_cache, cache_path)
                    break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    reset_val = e.headers.get("x-rate-limit-reset", "")
                    try:
                        wait_sec = float(reset_val) + 1.0
                    except (ValueError, TypeError):
                        wait_sec = 10.0 * (attempt + 1)
                    logger.warning(f"TNS 429 rate limit hit downloading {filename}. Backing off for {wait_sec:.1f}s...")
                    time.sleep(wait_sec)
                    continue
                logger.warning(f"Failed to download TNS spectrum from {url}: {e}")
                return None
            except Exception as e:
                logger.warning(f"Failed to download TNS spectrum from {url}: {e}")
                return None

    if not text:
        return None

    # Parse wavelength and flux columns
    data_points: List[List[str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("%") or line.startswith("@") or line.startswith(";"):
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


def convert_tns_to_astrocats_spectra(
    tns_rows: List[Dict[str, Any]],
    source_alias: str,
    max_spectra: int = 10
) -> List[Dict[str, Any]]:
    """Convert scraped TNS spectra records into canonical AstroCats format."""
    spectra: List[Dict[str, Any]] = []

    for row in tns_rows[:max_spectra]:
        ascii_url = row.get("ascii_url", "").strip()
        if not ascii_url:
            continue

        data_points = download_tns_ascii_spectrum(ascii_url)
        if not data_points:
            continue

        obs_date = row.get("obs_date", "").strip()
        mjd = parse_tns_datetime_to_mjd(obs_date)
        mjd_str = f"{mjd:.4f}" if mjd is not None else ""

        spec_entry: Dict[str, Any] = {
            "time": mjd_str or obs_date,
            "filename": row.get("filename") or ascii_url.split("/")[-1],
            "telescope": row.get("telescope", "").strip(),
            "instrument": row.get("instrument", "").strip(),
            "u_time": "MJD" if mjd_str else "",
            "u_wavelengths": "Angstrom",
            "u_fluxes": "erg/s/cm^2/Angstrom",
            "source": source_alias,
            "data": data_points,
        }
        # Clean empty keys
        spec_entry = {k: v for k, v in spec_entry.items() if v}
        spectra.append(spec_entry)

    return spectra


def is_duplicate_spectrum(cand: Dict[str, Any], existing_list: List[Dict[str, Any]]) -> bool:
    """Check if candidate spectrum matches an already recorded spectrum (same filename or epoch+instrument)."""
    cand_fn = cand.get("filename", "").strip()
    cand_time = cand.get("time", "")
    cand_tel = (cand.get("telescope") or "").lower().strip()
    cand_inst = (cand.get("instrument") or "").lower().strip()

    cand_mjd: Optional[float] = None
    if cand_time:
        try:
            cand_mjd = float(cand_time)
        except ValueError:
            pass

    for ex in existing_list:
        ex_fn = ex.get("filename", "").strip()
        if cand_fn and ex_fn and cand_fn == ex_fn:
            return True

        ex_time = ex.get("time", "")
        ex_tel = (ex.get("telescope") or "").lower().strip()
        ex_inst = (ex.get("instrument") or "").lower().strip()

        # Check telescope/instrument match
        match_inst = (cand_inst and cand_inst == ex_inst) or (cand_tel and cand_tel == ex_tel)

        if match_inst:
            if cand_mjd is not None:
                try:
                    ex_mjd = float(ex_time)
                    if abs(cand_mjd - ex_mjd) < 0.05:  # within ~1 hour
                        return True
                except ValueError:
                    pass
            elif cand_time and ex_time:
                # Compare date substring (YYYY-MM-DD)
                c_d = str(cand_time).split()[0].replace("-", "/")
                e_d = str(ex_time).split()[0].replace("-", "/")
                if c_d == e_d:
                    return True

    return False

