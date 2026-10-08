"""ALeRCE broker client for ZTF light curves and photometry."""
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CACHE_DIR = Path("ingest/cache/alerce")
CONE_CACHE_DIR = Path("ingest/cache/alerce/cones")
FID_TO_BAND = {1: "g", 2: "r", 3: "i"}


def find_ztf_object_by_coords(
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float = 6.0,
    timeout: int = 5,
    use_cache: bool = True,
) -> Optional[str]:
    """Query ALeRCE /objects/ cone search to find the ZTF object ID corresponding to sky coordinates."""
    if ra_deg is None or dec_deg is None or dec_deg < -32.0:
        return None

    CONE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    coord_key = f"{ra_deg:.5f}_{dec_deg:.5f}_{radius_arcsec:.1f}"
    cache_file = CONE_CACHE_DIR / f"{coord_key}.json"

    if use_cache and cache_file.is_file():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8")).get("oid")
        except Exception:
            pass

    url = f"https://api.alerce.online/ztf/v1/objects/?ra={ra_deg:.5f}&dec={dec_deg:.5f}&radius={radius_arcsec:.1f}&page_size=3"
    headers = {
        "User-Agent": "OpenSupernovaCatalog-Ingest/2.0 (https://sne.space)",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                if items and items[0].get("oid"):
                    oid = items[0]["oid"]
                    try:
                        cache_file.write_text(json.dumps({"oid": oid}), encoding="utf-8")
                    except Exception:
                        pass
                    return oid
                else:
                    try:
                        cache_file.write_text(json.dumps({"oid": None}), encoding="utf-8")
                    except Exception:
                        pass
    except Exception as e:
        logger.debug(f"ALeRCE cone search failed for {coord_key}: {e}")

    return None


def get_alerce_lightcurve(
    ztf_oid: str,
    timeout: int = 10,
    use_cache: bool = True,
    max_cache_age: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch ZTF light curve from ALeRCE REST API with local disk caching and TTL support."""
    if not ztf_oid:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{ztf_oid}.json"

    if use_cache and cache_path.is_file():
        is_fresh = True
        if max_cache_age is not None:
            is_fresh = (time.time() - cache_path.stat().st_mtime) <= max_cache_age
        if is_fresh:
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.debug(f"Cache read error for {ztf_oid}: {e}")

    url = f"https://api.alerce.online/ztf/v1/objects/{ztf_oid}/lightcurve"
    headers = {
        "User-Agent": "OpenSupernovaCatalog-Ingest/2.0 (https://sne.space)",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                tmp_path = cache_path.with_name(f".{cache_path.name}.tmp.{os.getpid()}")
                tmp_path.write_text(json.dumps(data), encoding="utf-8")
                os.replace(tmp_path, cache_path)
                return data
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.debug(f"ALeRCE 404 for {ztf_oid}")
        else:
            logger.warning(f"ALeRCE HTTP {e.code} for {ztf_oid}: {e.reason}")
    except Exception as e:
        logger.warning(f"ALeRCE request failed for {ztf_oid}: {e}")

    return None


def convert_alerce_to_astrocats_photometry(
    alerce_data: Dict[str, Any],
    source_alias: str,
    include_non_detections: bool = False
) -> List[Dict[str, Any]]:
    """Convert ALeRCE detections and non-detections into AstroCats photometry format."""
    photometry: List[Dict[str, Any]] = []

    detections = alerce_data.get("detections", [])
    for d in detections:
        mjd = d.get("mjd")
        mag = d.get("magpsf")
        e_mag = d.get("sigmapsf")
        fid = d.get("fid")

        if mjd is None or mag is None:
            continue

        band = FID_TO_BAND.get(fid, str(fid) if fid else "")
        photo_entry: Dict[str, Any] = {
            "time": f"{mjd:.5f}",
            "magnitude": f"{mag:.4f}",
            "band": band,
            "telescope": "ZTF",
            "instrument": "ZTF",
            "u_time": "MJD",
            "source": source_alias,
        }
        if e_mag is not None and e_mag > 0:
            photo_entry["e_magnitude"] = f"{e_mag:.4f}"

        photometry.append(photo_entry)

    if include_non_detections:
        non_detections = alerce_data.get("non_detections", [])
        for nd in non_detections:
            mjd = nd.get("mjd")
            diffmaglim = nd.get("diffmaglim")
            fid = nd.get("fid")
            if mjd is None or diffmaglim is None:
                continue

            band = FID_TO_BAND.get(fid, str(fid) if fid else "")
            photometry.append({
                "time": f"{mjd:.5f}",
                "magnitude": f"{diffmaglim:.4f}",
                "upperlimit": True,
                "band": band,
                "telescope": "ZTF",
                "u_time": "MJD",
                "source": source_alias,
            })

    # Sort chronologically by MJD time
    photometry.sort(key=lambda x: float(x["time"]))
    return photometry
