"""ALeRCE broker client for ZTF light curves and photometry."""
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from ingest import provider_quota
except Exception:  # noqa: BLE001
    provider_quota = None  # type: ignore

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

    alerce_base = (os.environ.get("SNE_ALERCE_BASE") or "https://api.alerce.online/ztf/v1").rstrip("/")
    url = f"{alerce_base}/objects/?ra={ra_deg:.5f}&dec={dec_deg:.5f}&radius={radius_arcsec:.1f}&page_size=3"
    headers = {
        "User-Agent": "OpenSupernovaCatalog-Ingest/2.0 (https://sne.space)",
        "Accept": "application/json",
    }
    if provider_quota is not None:
        provider_quota.acquire("alerce")
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                if provider_quota is not None:
                    provider_quota.record_success("alerce")
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

    # Reject malformed OIDs (e.g. unsplit internal-name blobs).
    ztf_oid = str(ztf_oid or "").strip().split()[0]
    if not (ztf_oid.startswith("ZTF") and len(ztf_oid) >= 12):
        return None
    alerce_base = (os.environ.get("SNE_ALERCE_BASE") or "https://api.alerce.online/ztf/v1").rstrip("/")
    url = f"{alerce_base}/objects/{ztf_oid}/lightcurve"
    headers = {
        "User-Agent": "OpenSupernovaCatalog-Ingest/2.0 (https://sne.space)",
        "Accept": "application/json",
    }
    if provider_quota is not None:
        provider_quota.acquire("alerce")
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                if provider_quota is not None:
                    provider_quota.record_success("alerce")
                data = json.loads(resp.read().decode("utf-8"))
                tmp_path = cache_path.with_name(f".{cache_path.name}.tmp.{os.getpid()}")
                tmp_path.write_text(json.dumps(data), encoding="utf-8")
                os.replace(tmp_path, cache_path)
                return data
    except urllib.error.HTTPError as e:
        if e.code == 429:
            reset = None
            try:
                reset = float(e.headers.get("x-rate-limit-reset") or e.headers.get("retry-after") or 0) or None
            except Exception:
                reset = None
            if provider_quota is not None:
                provider_quota.record_429("alerce", reset)
            logger.warning(f"ALeRCE 429 for {ztf_oid}; backing off")
        elif e.code == 404:
            logger.debug(f"ALeRCE 404 for {ztf_oid}")
        else:
            logger.warning(f"ALeRCE HTTP {e.code} for {ztf_oid}: {e.reason}")
    except Exception as e:
        logger.warning(f"ALeRCE request failed for {ztf_oid}: {e}")

    return None


def convert_alerce_to_astrocats_photometry(
    alerce_data: Dict[str, Any],
    source_alias: str,
    include_non_detections: bool = True,
    include_detections: bool = True,
) -> List[Dict[str, Any]]:
    """Convert ALeRCE light-curve payload into AstroCats photometry entries.

    Detections and non-detections stay distinguishable:
      - detections: ``kind="detection"``, magnitude = magpsf, optional candid
      - non-detections: ``kind="non_detection"``, ``upperlimit=True``,
        magnitude = diffmaglim (limit, not a flux measurement)

    Forced photometry is NOT mixed in here — ALeRCE exposes it via a separate
    endpoint and must be ingested explicitly if ever required.
    """
    photometry: List[Dict[str, Any]] = []

    if include_detections:
        for d in alerce_data.get("detections", []) or []:
            if not isinstance(d, dict):
                continue
            mjd = d.get("mjd")
            mag = d.get("magpsf")
            e_mag = d.get("sigmapsf")
            fid = d.get("fid")
            if mjd is None or mag is None:
                continue
            band = FID_TO_BAND.get(fid, str(fid) if fid else "")
            photo_entry: Dict[str, Any] = {
                "time": f"{float(mjd):.5f}",
                "magnitude": f"{float(mag):.4f}",
                "band": band,
                "telescope": "ZTF",
                "instrument": "ZTF",
                "u_time": "MJD",
                "source": source_alias,
                "kind": "detection",
                "survey": "ZTF",
                "provider": "ALeRCE",
            }
            candid = d.get("candid") or d.get("candid_alert")
            if candid is not None:
                photo_entry["candid"] = str(candid)
            if e_mag is not None:
                try:
                    if float(e_mag) > 0:
                        photo_entry["e_magnitude"] = f"{float(e_mag):.4f}"
                except Exception:
                    pass
            # Provenance for association checks
            if d.get("ra") is not None and d.get("dec") is not None:
                photo_entry["ra"] = f"{float(d['ra']):.6f}"
                photo_entry["dec"] = f"{float(d['dec']):.6f}"
            photometry.append(photo_entry)

    if include_non_detections:
        for nd in alerce_data.get("non_detections", []) or []:
            if not isinstance(nd, dict):
                continue
            mjd = nd.get("mjd")
            diffmaglim = nd.get("diffmaglim")
            fid = nd.get("fid")
            if mjd is None or diffmaglim is None:
                continue
            band = FID_TO_BAND.get(fid, str(fid) if fid else "")
            photometry.append({
                "time": f"{float(mjd):.5f}",
                "magnitude": f"{float(diffmaglim):.4f}",
                "upperlimit": True,
                "kind": "non_detection",
                "band": band,
                "telescope": "ZTF",
                "instrument": "ZTF",
                "u_time": "MJD",
                "source": source_alias,
                "survey": "ZTF",
                "provider": "ALeRCE",
            })

    photometry.sort(key=lambda x: float(x["time"]))
    return photometry


def photometry_dedupe_key(p: Dict[str, Any]) -> Tuple:
    """Stable identity for merging photometry without collapsing detections into limits."""
    candid = p.get("candid")
    if candid:
        return ("candid", str(candid))
    kind = "non_detection" if (p.get("upperlimit") or p.get("kind") == "non_detection") else "detection"
    try:
        t = round(float(p.get("time", 0)), 5)
    except Exception:
        t = 0.0
    return (kind, t, str(p.get("band") or ""), str(p.get("telescope") or ""))


