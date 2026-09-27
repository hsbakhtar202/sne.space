"""
sne.space — IVOA Simple Cone Search & VOTable Service
Compliant with IVOA Simple Cone Search (SCS) Recommendation v1.03 and VOTable v1.4.
Enables Topcat, Aladin Desktop, and astropy.vo to query 110,222+ supernovae.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
import xml.sax.saxutils as saxutils
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CAT_FILE = ROOT / "serve/www/astrocats/astrocats/supernovae/output/catalog.min.json"

# In-memory spatial index: list of (x, y, z, ra_deg, dec_deg, meta_summary)
_SPATIAL_INDEX: list[tuple[float, float, float, float, float, dict[str, Any]]] = []
_INDEX_INITIALIZED = False
_INDEX_LOCK = threading.Lock()


def _parse_coord(val: Any) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s == "—":
        return None
    try:
        return float(s)
    except ValueError:
        pass
    parts = s.split(":")
    if len(parts) == 3:
        try:
            sign = -1.0 if s.startswith("-") else 1.0
            p0 = abs(float(parts[0]))
            p1 = float(parts[1])
            p2 = float(parts[2])
            return sign * (p0 + p1 / 60.0 + p2 / 3600.0)
        except Exception:
            return None
    return None


def init_cone_index() -> int:
    """Initialize the 3D unit vector spatial index from catalog.min.json."""
    global _SPATIAL_INDEX, _INDEX_INITIALIZED
    if _INDEX_INITIALIZED:
        return len(_SPATIAL_INDEX)

    with _INDEX_LOCK:
        if _INDEX_INITIALIZED:
            return len(_SPATIAL_INDEX)

        if not CAT_FILE.is_file():
            return 0

        t0 = time.time()
        try:
            catalog = json.loads(CAT_FILE.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return 0

    pts = []
    for ev in catalog:
        name = ev.get("name", "")
        ra_entry = ev.get("ra", [{}])
        dec_entry = ev.get("dec", [{}])
        ra_val = ra_entry[0].get("value") if isinstance(ra_entry, list) and ra_entry else None
        dec_val = dec_entry[0].get("value") if isinstance(dec_entry, list) and dec_entry else None

        ra_deg = _parse_coord(ra_val)
        dec_deg = _parse_coord(dec_val)
        if ra_deg is None or dec_deg is None:
            continue

        # In sexagesimal hours format, RA might be in hours (0..24)
        if ra_val and ":" in str(ra_val) and ra_deg < 24.0:
            ra_deg *= 15.0

        r_rad = math.radians(ra_deg)
        d_rad = math.radians(dec_deg)
        x = math.cos(d_rad) * math.cos(r_rad)
        y = math.cos(d_rad) * math.sin(r_rad)
        z = math.sin(d_rad)

        ctype = ev.get("claimedtype", [{}])[0].get("value", "") if ev.get("claimedtype") else ""
        z_val = ev.get("redshift", [{}])[0].get("value", "") if ev.get("redshift") else ""
        mag = ev.get("maxappmag", [{}])[0].get("value", "") if ev.get("maxappmag") else ""
        disc = ev.get("discoverdate", [{}])[0].get("value", "") if ev.get("discoverdate") else ""
        host = ev.get("host", [{}])[0].get("value", "") if ev.get("host") else ""

        pts.append((
            x, y, z, round(ra_deg, 6), round(dec_deg, 6),
            {
                "name": name,
                "type": ctype,
                "redshift": z_val,
                "maxappmag": mag,
                "discoverdate": disc,
                "host": host
            }
        ))

    _SPATIAL_INDEX = pts
    _INDEX_INITIALIZED = True
    return len(_SPATIAL_INDEX)


def cone_search(
    ra_deg: float,
    dec_deg: float,
    sr_deg: float,
    max_results: int = 500
) -> list[dict[str, Any]]:
    """Execute rapid 3D spherical dot-product cone search."""
    if not _INDEX_INITIALIZED:
        init_cone_index()

    r0_rad = math.radians(ra_deg)
    d0_rad = math.radians(dec_deg)
    x0 = math.cos(d0_rad) * math.cos(r0_rad)
    y0 = math.cos(d0_rad) * math.sin(r0_rad)
    z0 = math.sin(d0_rad)

    # Clamping search radius between 0.0001 and 10 degrees
    sr_clamped = max(0.0001, min(10.0, sr_deg))
    cos_lim = math.cos(math.radians(sr_clamped))

    hits = []
    for x, y, z, t_ra, t_dec, meta in _SPATIAL_INDEX:
        dot = x * x0 + y * y0 + z * z0
        if dot >= cos_lim:
            # Separation in arcseconds
            sep_rad = math.acos(max(-1.0, min(1.0, dot)))
            sep_arcsec = math.degrees(sep_rad) * 3600.0

            hit = dict(meta)
            hit["ra"] = t_ra
            hit["dec"] = t_dec
            hit["separation_arcsec"] = round(sep_arcsec, 2)
            hits.append(hit)

    # Sort by angular separation from cone center
    hits.sort(key=lambda h: h["separation_arcsec"])
    return hits[:max_results]


def format_votable(hits: list[dict[str, Any]], ra: float, dec: float, sr: float) -> str:
    """Format cone search results into standard IVOA VOTable XML."""
    rows = []
    for h in hits:
        name = saxutils.escape(h.get("name", ""))
        ctype = saxutils.escape(h.get("type", ""))
        disc = saxutils.escape(h.get("discoverdate", ""))
        host = saxutils.escape(h.get("host", ""))
        z_str = str(h.get("redshift", ""))
        mag_str = str(h.get("maxappmag", ""))
        sep_str = f"{h.get('separation_arcsec', 0.0):.2f}"

        rows.append(
            f"        <TR><TD>{name}</TD><TD>{h['ra']:.6f}</TD><TD>{h['dec']:.6f}</TD>"
            f"<TD>{sep_str}</TD><TD>{ctype}</TD><TD>{z_str}</TD><TD>{mag_str}</TD>"
            f"<TD>{disc}</TD><TD>{host}</TD></TR>"
        )

    table_data = "\n".join(rows)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<VOTABLE version="1.4" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns="http://www.ivoa.net/xml/VOTable/v1.4">
  <RESOURCE type="results">
    <DESCRIPTION>Open Supernova Catalog (sne.space) IVOA Cone Search</DESCRIPTION>
    <INFO name="QUERY_STATUS" value="OK"/>
    <INFO name="POS" value="{ra:.6f},{dec:.6f}"/>
    <INFO name="SR" value="{sr:.6f}"/>
    <INFO name="COUNT" value="{len(hits)}"/>
    <TABLE name="supernovae">
      <FIELD name="name" ucd="meta.id;meta.main" datatype="char" arraysize="*" />
      <FIELD name="ra" ucd="pos.eq.ra;meta.main" datatype="double" unit="deg" />
      <FIELD name="dec" ucd="pos.eq.dec;meta.main" datatype="double" unit="deg" />
      <FIELD name="separation_arcsec" ucd="pos.angDistance" datatype="float" unit="arcsec" />
      <FIELD name="claimedtype" ucd="src.class" datatype="char" arraysize="*" />
      <FIELD name="redshift" ucd="src.redshift" datatype="char" arraysize="*" />
      <FIELD name="maxappmag" ucd="phot.mag" datatype="char" arraysize="*" />
      <FIELD name="discoverdate" ucd="time.epoch" datatype="char" arraysize="*" />
      <FIELD name="host" ucd="meta.id.parent" datatype="char" arraysize="*" />
      <DATA>
        <TABLEDATA>
{table_data}
        </TABLEDATA>
      </DATA>
    </TABLE>
  </RESOURCE>
</VOTABLE>"""


def find_closest_events(
    name: str,
    ra_deg: float | None = None,
    dec_deg: float | None = None,
    discoverdate_str: str = "",
    redshift_str: str = "",
    limit: int = 3
) -> dict[str, list[dict[str, Any]]]:
    """Find catalog transients closest to this event in sky separation, discovery time, and cosmic distance."""
    if not _INDEX_INITIALIZED:
        init_cone_index()

    from datetime import datetime

    r0 = math.radians(ra_deg) if ra_deg is not None else None
    d0 = math.radians(dec_deg) if dec_deg is not None else None
    x0 = math.cos(d0) * math.cos(r0) if r0 is not None and d0 is not None else None
    y0 = math.cos(d0) * math.sin(r0) if r0 is not None and d0 is not None else None
    z0 = math.sin(d0) if d0 is not None else None

    def _parse_d(s: str) -> datetime | None:
        if not s or s == "—":
            return None
        clean = s.strip().replace("-", "/").split()[0]
        pts = clean.split("/")
        try:
            return datetime(int(pts[0]), int(pts[1]) if len(pts) > 1 else 1, int(pts[2]) if len(pts) > 2 else 1)
        except Exception:
            return None

    t0 = _parse_d(discoverdate_str)
    z_target: float | None = None
    if redshift_str and redshift_str != "—":
        try:
            clean_z = re.sub(r"[^0-9.]", "", redshift_str)
            if clean_z:
                z_target = float(clean_z)
        except Exception:
            pass

    by_sky: list[tuple[float, float, float, dict[str, Any]]] = []
    by_time: list[tuple[int, int, dict[str, Any]]] = []
    by_cosmic: list[tuple[float, float, dict[str, Any]]] = []

    norm_name = name.lower().replace(" ", "").replace("-", "")

    for x, y, z, tra, tdec, meta in _SPATIAL_INDEX:
        m_name = meta.get("name", "")
        if m_name.lower().replace(" ", "").replace("-", "") == norm_name:
            continue

        # Sky separation
        if x0 is not None and y0 is not None and z0 is not None:
            dot = max(-1.0, min(1.0, x0 * x + y0 * y + z0 * z))
            sep_deg = math.degrees(math.acos(dot))
            by_sky.append((sep_deg, tra, tdec, meta))

        # Discovery time
        disc_val = meta.get("discoverdate", "")
        if t0 is not None and disc_val:
            t_disc = _parse_d(disc_val)
            if t_disc is not None:
                delta_days = (t_disc - t0).days
                by_time.append((abs(delta_days), delta_days, meta))

        # Cosmic redshift delta
        if z_target is not None and meta.get("redshift"):
            try:
                z_val = float(meta["redshift"])
                if z_val > 0:
                    delta_z = abs(z_val - z_target)
                    by_cosmic.append((delta_z, z_val, meta))
            except Exception:
                pass

    by_sky.sort(key=lambda item: item[0])
    by_time.sort(key=lambda item: item[0])
    by_cosmic.sort(key=lambda item: item[0])

    sky_res = []
    for sep_deg, tra, tdec, m in by_sky[:limit]:
        item = dict(m)
        item["separation_arcmin"] = round(sep_deg * 60.0, 1)
        item["separation_deg"] = round(sep_deg, 3)
        item["ra"] = tra
        item["dec"] = tdec
        sky_res.append(item)

    time_res = []
    for abs_days, delta_days, m in by_time[:limit]:
        item = dict(m)
        item["delta_days"] = delta_days
        item["abs_delta_days"] = abs_days
        time_res.append(item)

    cosmic_res = []
    for delta_z, z_val, m in by_cosmic[:limit]:
        item = dict(m)
        item["delta_z"] = round(delta_z, 4)
        item["target_z"] = z_target
        item["est_light_years_m"] = round(z_val * 4200.0 * 3.26156, 1) if z_val < 0.1 else round(z_val * 13800.0, 1)
        cosmic_res.append(item)

    return {
        "sky": sky_res,
        "time": time_res,
        "cosmic": cosmic_res
    }

