"""TNS photometry ingestion: structured API first, HTML table fallback.

Fetches detections and non-detections for a TNS object, converts them to
AstroCats photometry records, and merges them idempotently with existing
broker photometry (ALeRCE / OSC). Coverage status is returned so callers can
distinguish empty upstream data from fetch failures.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ingest.alerce import photometry_dedupe_key
from ingest.tns_spectra import TNS_USER_AGENT, clean_object_name, parse_tns_datetime_to_mjd

logger = logging.getLogger(__name__)

CACHE_DIR = Path("ingest/cache/tns/photometry")

# Coverage statuses recorded on event["photometry_ingest"]["tns"]["status"].
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_UNAVAILABLE = "unavailable"
STATUS_ERROR = "error"


def _jd_to_mjd(jd: float) -> float:
    return jd - 2400000.5


def _cell_text(cell_html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", cell_html)
    return re.sub(r"\s+", " ", text).strip()


def _parse_float(val: str) -> Optional[float]:
    s = (val or "").strip().replace(",", "")
    if not s or s in {"—", "-", "n/a", "N/A"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def extract_ztf_oid_from_html(html: str) -> Optional[str]:
    """Pull a ZTF internal name from a TNS object page when present."""
    m = re.search(r"\b(ZTF\d{2}[a-z]{4,})\b", html, re.I)
    return m.group(1) if m else None


def parse_tns_object_header(html: str) -> Dict[str, str]:
    """Extract discovery header fields from a TNS object HTML page."""
    out: Dict[str, str] = {}
    if not html:
        return out
    ztf = extract_ztf_oid_from_html(html)
    if ztf:
        out["internal_names"] = ztf
    m = re.search(
        r"RA/DEC\s*\(2000\)\s*([0-9:.+-]+)\s+([0-9:.+-]+)",
        re.sub(r"<[^>]+>", " ", html),
        re.I,
    )
    if m:
        out["ra_sexagesimal"] = m.group(1).strip()
        out["dec_sexagesimal"] = m.group(2).strip()
    m = re.search(r"Discovery Mag\s*([0-9.]+)", re.sub(r"<[^>]+>", " ", html), re.I)
    if m:
        out["discoverymag"] = m.group(1)
    m = re.search(r"Filter\s*([A-Za-z0-9_+\-]+)", re.sub(r"<[^>]+>", " ", html), re.I)
    if m:
        out["filter"] = m.group(1)
    # Obs-date of first detection row as discovery date fallback
    m = re.search(
        r'<td[^>]*class=["\'][^"\']*cell-obs[^"\']*["\'][^>]*>\s*([0-9]{4}-[0-9]{2}-[0-9]{2}[^<]*)',
        html,
        re.I,
    )
    if not m:
        m = re.search(r"(20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", html)
    if m:
        out["discoverydate"] = m.group(1).strip()
    return out


def parse_tns_photometry_html(html: str) -> List[Dict[str, Any]]:
    """Parse the TNS ``photometry-results-table`` into AstroCats-shaped rows.

    Duplicate table rows that share observation attributes collapse to one
    record (TNS often lists the discovery detection twice with different IDs).
    """
    if not html:
        return []
    m = re.search(
        r'<table[^>]*class=["\'][^"\']*photometry-results-table[^"\']*["\'][^>]*>(.*?)</table>',
        html,
        re.I | re.S,
    )
    if not m:
        return []
    table = m.group(1)
    rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.I | re.S)
    if not rows_html:
        return []

    header_cells = re.findall(r"<th[^>]*>(.*?)</th>", rows_html[0], re.I | re.S)
    headers = [_cell_text(h).lower() for h in header_cells]
    if not headers:
        return []

    def col(*names: str) -> Optional[int]:
        for i, h in enumerate(headers):
            for n in names:
                if n in h:
                    return i
        return None

    i_id = col("id")
    i_obs = col("obs-date", "obs date")
    i_jd = col("jd")
    i_mag = col("mag. / flux", "mag")
    i_err = col("err")
    i_lim = col("lim. mag", "lim mag", "limiting")
    i_filter = col("filter")
    i_tel = col("tel / inst", "tel", "inst")
    i_remarks = col("remarks")

    out: List[Dict[str, Any]] = []
    seen: set[Tuple] = set()

    for row_html in rows_html[1:]:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.I | re.S)
        if not cells:
            continue
        vals = [_cell_text(c) for c in cells]

        def get(idx: Optional[int]) -> str:
            if idx is None or idx >= len(vals):
                return ""
            return vals[idx]

        remarks = get(i_remarks).lower()
        mag_val = _parse_float(get(i_mag))
        lim_val = _parse_float(get(i_lim))
        err_val = _parse_float(get(i_err))
        band = get(i_filter) or "Clear"
        tel = get(i_tel)
        tns_id = get(i_id)

        mjd: Optional[float] = None
        jd_val = _parse_float(get(i_jd))
        if jd_val is not None and jd_val > 1e6:
            mjd = _jd_to_mjd(jd_val)
        if mjd is None:
            mjd = parse_tns_datetime_to_mjd(get(i_obs))
        if mjd is None:
            continue

        is_limit = bool(lim_val is not None and mag_val is None) or (
            "non detection" in remarks or "non-detection" in remarks or "last non detection" in remarks
        )
        if is_limit:
            if lim_val is None:
                continue
            entry = {
                "time": f"{mjd:.5f}",
                "magnitude": f"{lim_val:.4f}".rstrip("0").rstrip(".") or f"{lim_val:g}",
                "band": band,
                "u_time": "MJD",
                "upperlimit": True,
                "kind": "non_detection",
            }
        else:
            if mag_val is None:
                continue
            entry = {
                "time": f"{mjd:.5f}",
                "magnitude": f"{mag_val:.4f}".rstrip("0").rstrip(".") or f"{mag_val:g}",
                "band": band,
                "u_time": "MJD",
                "upperlimit": False,
                "kind": "detection",
            }
            if err_val is not None:
                entry["e_magnitude"] = f"{err_val:.6f}".rstrip("0").rstrip(".") or f"{err_val:g}"

        if tel:
            entry["telescope"] = tel
        if tns_id:
            entry["tns_photometry_id"] = tns_id
            entry["candid"] = f"tns:{tns_id}"

        key = photometry_dedupe_key(entry)
        # Also collapse TNS twin IDs that share the same physical observation.
        phys = (
            "non_detection" if entry.get("upperlimit") else "detection",
            round(float(entry["time"]), 5),
            str(entry.get("band") or ""),
            str(entry.get("magnitude") or ""),
            str(entry.get("e_magnitude") or ""),
        )
        if key in seen or phys in seen:
            continue
        seen.add(key)
        seen.add(phys)
        out.append(entry)

    out.sort(key=lambda p: float(p.get("time", 0)))
    return out


def photometry_merge(
    existing: List[Dict[str, Any]],
    incoming: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Idempotent merge: keep existing points, append non-duplicate incoming."""
    merged: List[Dict[str, Any]] = []
    keys: set[Tuple] = set()
    phys_keys: set[Tuple] = set()

    def _phys(p: Dict[str, Any]) -> Tuple:
        kind = "non_detection" if (p.get("upperlimit") or p.get("kind") == "non_detection") else "detection"
        try:
            t = round(float(p.get("time", 0)), 5)
        except Exception:
            t = 0.0
        try:
            mag = f"{float(p.get('magnitude')):.4f}" if p.get("magnitude") is not None else ""
        except Exception:
            mag = str(p.get("magnitude") or "")
        return (kind, t, str(p.get("band") or ""), mag)

    for p in list(existing or []) + list(incoming or []):
        if not isinstance(p, dict):
            continue
        k = photometry_dedupe_key(p)
        pk = _phys(p)
        if k in keys or pk in phys_keys:
            continue
        keys.add(k)
        phys_keys.add(pk)
        merged.append(p)
    merged.sort(key=lambda x: float(x.get("time", 0) or 0))
    return merged


def _fetch_tns_api_photometry(clean_name: str, timeout: int) -> Optional[Dict[str, Any]]:
    """Try the authenticated TNS object API when credentials are configured.

    Returns a parsed payload dict on HTTP 200, ``None`` when credentials are
    absent or the endpoint is unauthorized/unavailable so the HTML fallback can
    run. Raises on unexpected transport errors after logging.
    """
    api_key = (os.environ.get("SNE_TNS_API_KEY") or os.environ.get("TNS_API_KEY") or "").strip()
    bot_id = (os.environ.get("SNE_TNS_BOT_ID") or os.environ.get("TNS_BOT_ID") or "").strip()
    bot_name = (os.environ.get("SNE_TNS_BOT_NAME") or os.environ.get("TNS_BOT_NAME") or "").strip()
    if not api_key:
        return None

    api_base = (os.environ.get("SNE_TNS_API_BASE") or "https://www.wis-tns.org/api/get").rstrip("/")
    url = f"{api_base}/object"
    markers = []
    if bot_id:
        markers.append(f'tns_id="{bot_id}"')
    if bot_name:
        markers.append(f'tns_name="{bot_name}"')
    markers.append(f'api_key="{api_key}"')
    headers = {
        "User-Agent": TNS_USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": f'tns_marker {{"{"; ".join(markers)}"}}',
    }
    # TNS expects form field ``api_key`` + JSON body ``data``.
    import urllib.parse

    payload = json.dumps({"objname": clean_name, "photometry": "1"})
    body = urllib.parse.urlencode({"api_key": api_key, "data": payload}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": headers["User-Agent"],
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            logger.info("TNS API photometry unavailable for %s: HTTP %s", clean_name, e.code)
            return None
        raise
    except Exception as exc:
        logger.warning("TNS API photometry failed for %s: %s", clean_name, exc)
        return None


def _rows_from_tns_api_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert a TNS get/object photometry list into AstroCats rows when present."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        photo = data.get("photometry") or data.get("photometry_list") or []
        obj = data.get("reply") if isinstance(data.get("reply"), dict) else data
        if not photo and isinstance(obj, dict):
            photo = obj.get("photometry") or []
    else:
        photo = []
    if not isinstance(photo, list):
        return []
    rows: List[Dict[str, Any]] = []
    for item in photo:
        if not isinstance(item, dict):
            continue
        # Field names vary across TNS API versions.
        mag = item.get("flux") or item.get("mag") or item.get("magnitude")
        lim = item.get("limflux") or item.get("limmag") or item.get("limiting_flux")
        err = item.get("fluxerr") or item.get("magerr") or item.get("e_magnitude")
        filt = item.get("filters") or item.get("filter") or item.get("band") or "Clear"
        tel = item.get("instrument") or item.get("telescope") or ""
        jd = item.get("jd") or item.get("JD")
        obs = item.get("obsdate") or item.get("observationdate") or ""
        remarks = str(item.get("remarks") or "")
        mjd = None
        try:
            if jd is not None:
                mjd = _jd_to_mjd(float(jd))
        except Exception:
            mjd = None
        if mjd is None:
            mjd = parse_tns_datetime_to_mjd(str(obs))
        if mjd is None:
            continue
        is_limit = bool(item.get("upperlimit")) or (mag in (None, "") and lim not in (None, ""))
        if "non detection" in remarks.lower():
            is_limit = True
        entry: Dict[str, Any] = {
            "time": f"{float(mjd):.5f}",
            "band": str(filt),
            "u_time": "MJD",
        }
        if tel:
            entry["telescope"] = str(tel)
        pid = item.get("id") or item.get("photometry_id")
        if pid is not None:
            entry["tns_photometry_id"] = str(pid)
            entry["candid"] = f"tns:{pid}"
        if is_limit:
            try:
                entry["magnitude"] = f"{float(lim):g}"
            except Exception:
                continue
            entry["upperlimit"] = True
            entry["kind"] = "non_detection"
        else:
            try:
                entry["magnitude"] = f"{float(mag):g}"
            except Exception:
                continue
            entry["upperlimit"] = False
            entry["kind"] = "detection"
            try:
                if err not in (None, ""):
                    entry["e_magnitude"] = f"{float(err):g}"
            except Exception:
                pass
        rows.append(entry)
    return photometry_merge([], rows)


def fetch_tns_photometry(
    object_name: str,
    timeout: int = 12,
    use_cache: bool = True,
    max_cache_age: Optional[int] = None,
) -> Dict[str, Any]:
    """Fetch TNS photometry for ``object_name``.

    Returns a coverage dict::

        {
          "status": "ok"|"empty"|"unavailable"|"error",
          "n_detections": int,
          "n_limits": int,
          "rows": [...],
          "ztf_oid": str|None,
          "source": "tns_api"|"tns_html"|None,
          "error": str|None,
        }
    """
    clean = clean_object_name(object_name)
    result: Dict[str, Any] = {
        "status": STATUS_UNAVAILABLE,
        "n_detections": 0,
        "n_limits": 0,
        "rows": [],
        "ztf_oid": None,
        "source": None,
        "error": None,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not clean:
        result["status"] = STATUS_ERROR
        result["error"] = "empty object name"
        return result

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{clean}.json"
    if use_cache and cache_path.is_file():
        fresh = True
        if max_cache_age is not None:
            fresh = (time.time() - cache_path.stat().st_mtime) <= max_cache_age
        if fresh:
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and "rows" in cached:
                    return cached
            except Exception:
                pass

    rows: List[Dict[str, Any]] = []
    source = None
    ztf_oid = None

    # 1) Structured API when credentials exist.
    try:
        api_payload = _fetch_tns_api_photometry(clean, timeout=timeout)
    except Exception as exc:
        logger.warning("TNS API photometry error for %s: %s", clean, exc)
        api_payload = None
        result["error"] = str(exc)
    if api_payload is not None:
        rows = _rows_from_tns_api_payload(api_payload)
        source = "tns_api"
        # Even an authorized empty list is informative.
        if not rows and not result.get("error"):
            # Fall through to HTML — some API replies omit photometry arrays.
            pass
        elif rows:
            result["status"] = STATUS_OK
            result["rows"] = rows
            result["source"] = source
            result["n_detections"] = sum(1 for r in rows if not r.get("upperlimit"))
            result["n_limits"] = sum(1 for r in rows if r.get("upperlimit"))
            try:
                cache_path.write_text(json.dumps(result), encoding="utf-8")
            except Exception:
                pass
            return result

    # 2) HTML object page (same transport as spectra ingest).
    tns_object_base = (os.environ.get("SNE_TNS_OBJECT_BASE") or "https://www.wis-tns.org/object").rstrip("/")
    url = f"{tns_object_base}/{clean}"
    html = ""
    try:
        try:
            from ingest import provider_quota
            provider_quota.acquire("tns")
        except Exception:
            provider_quota = None  # type: ignore
        req = urllib.request.Request(
            url,
            headers={"User-Agent": TNS_USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        if provider_quota is not None:
            provider_quota.record_success("tns")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            result["status"] = STATUS_EMPTY
            result["error"] = "tns object 404"
            return result
        if e.code == 429:
            result["status"] = STATUS_UNAVAILABLE
            result["error"] = "tns rate limited"
            try:
                from ingest import provider_quota as pq
                pq.record_429("tns", 20.0)
            except Exception:
                pass
            return result
        result["status"] = STATUS_ERROR
        result["error"] = f"HTTP {e.code}"
        return result
    except Exception as exc:
        result["status"] = STATUS_ERROR
        result["error"] = str(exc)
        return result

    if not html:
        result["status"] = STATUS_UNAVAILABLE
        result["error"] = "empty html"
        return result

    ztf_oid = extract_ztf_oid_from_html(html)
    header = parse_tns_object_header(html)
    rows = parse_tns_photometry_html(html)
    source = "tns_html"
    result["ztf_oid"] = ztf_oid or header.get("internal_names")
    result["source"] = source
    result["header"] = header
    result["rows"] = rows
    result["n_detections"] = sum(1 for r in rows if not r.get("upperlimit"))
    result["n_limits"] = sum(1 for r in rows if r.get("upperlimit"))
    if rows:
        result["status"] = STATUS_OK
    else:
        # Page loaded but no photometry table / rows.
        result["status"] = STATUS_EMPTY
    try:
        cache_path.write_text(json.dumps(result), encoding="utf-8")
    except Exception:
        pass
    return result


def apply_tns_photometry_to_event(
    event: Dict[str, Any],
    object_name: str,
    source_alias: str = "1",
    *,
    fetch_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge TNS photometry into an event body; record coverage; return coverage dict."""
    cov = fetch_result if fetch_result is not None else fetch_tns_photometry(object_name)
    rows = []
    for r in cov.get("rows") or []:
        if not isinstance(r, dict):
            continue
        entry = dict(r)
        entry.setdefault("source", source_alias)
        rows.append(entry)

    existing = [p for p in (event.get("photometry") or []) if isinstance(p, dict)]
    event["photometry"] = photometry_merge(existing, rows)

    ztf = cov.get("ztf_oid")
    if ztf:
        aliases = event.setdefault("alias", [])
        have = {a.get("value") for a in aliases if isinstance(a, dict)}
        if ztf not in have:
            aliases.append({"value": ztf, "source": source_alias})

    # Enrich discoverymag with uncertainty/band from the matching detection when
    # the TNS listing scalar lacked e_mag.
    dets = [
        p for p in event["photometry"]
        if isinstance(p, dict)
        and not p.get("upperlimit")
        and p.get("kind") != "non_detection"
        and p.get("magnitude") is not None
    ]
    if dets:
        best = min(dets, key=lambda p: float(p["magnitude"]))
        dm = event.get("discoverymag")
        if isinstance(dm, list) and dm and isinstance(dm[0], dict):
            entry = dm[0]
            if best.get("e_magnitude") and not entry.get("e_value") and not entry.get("e_magnitude"):
                entry["e_value"] = str(best["e_magnitude"])
            if best.get("band") and not entry.get("band"):
                entry["band"] = best["band"]
            entry.setdefault("kind", "discovery")
        elif not dm:
            disc: Dict[str, Any] = {
                "value": str(best["magnitude"]),
                "kind": "discovery",
                "source": source_alias,
            }
            if best.get("e_magnitude"):
                disc["e_value"] = str(best["e_magnitude"])
            if best.get("band"):
                disc["band"] = best["band"]
            event["discoverymag"] = [disc]

    ingest_meta = event.setdefault("photometry_ingest", {})
    if not isinstance(ingest_meta, dict):
        ingest_meta = {}
        event["photometry_ingest"] = ingest_meta
    ingest_meta["tns"] = {
        "status": cov.get("status"),
        "n_detections": cov.get("n_detections", 0),
        "n_limits": cov.get("n_limits", 0),
        "source": cov.get("source"),
        "fetched_at": cov.get("fetched_at"),
        "error": cov.get("error"),
    }
    return cov
