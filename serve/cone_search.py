"""
sne.space — IVOA Simple Cone Search & VOTable Service
Compliant with IVOA Simple Cone Search (SCS) Recommendation v1.03 and VOTable v1.4.
Enables Topcat, Aladin Desktop, and astropy.vo to query 110,222+ supernovae.
"""

from __future__ import annotations

import heapq
import json
import math
import os
import re
import threading
import time
import xml.sax.saxutils as saxutils
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
# Fallback only — prefer SNE_DATA_DIR / volume catalog (plain or .gz). The baked
# catalog.min.json is dockerignored, so hardcoding the repo path yields an empty
# neighbor index in production.
_BAKED_CAT = ROOT / "serve/www/astrocats/astrocats/supernovae/output/catalog.min.json"

# In-memory spatial index: list of (x, y, z, ra_deg, dec_deg, meta_summary)
_SPATIAL_INDEX: list[tuple[float, float, float, float, float, dict[str, Any]]] = []
_INDEX_INITIALIZED = False
_INDEX_LOCK = threading.Lock()
_INDEX_STATUS = "uninitialized"  # ok | empty | missing_catalog | error
_INDEX_ERROR = ""


def _resolve_catalog_paths() -> list[Path]:
    """Catalog JSON sources for the neighbor index, most authoritative first."""
    paths: list[Path] = []
    try:
        from data_paths import resolve_output_dir
    except ImportError:
        try:
            from serve.data_paths import resolve_output_dir
        except ImportError:
            resolve_output_dir = None  # type: ignore
    roots: list[Path] = []
    if resolve_output_dir is not None:
        try:
            roots.append(resolve_output_dir())
        except Exception:
            pass
    roots.append(_BAKED_CAT.parent)
    seen: set[str] = set()
    for root in roots:
        for name in ("catalog.min.json", "catalog.min.json.gz"):
            p = root / name
            key = str(p.resolve()) if p.exists() else str(p)
            if key in seen:
                continue
            seen.add(key)
            if p.is_file():
                paths.append(p)
    # Runtime overlays (recent discoveries) — optional.
    runtime = (os.environ.get("SNE_RUNTIME_DIR") or "").strip()
    if runtime:
        for name in ("recent-catalog.min.json", "published-updates.min.json"):
            p = Path(runtime) / name
            if p.is_file():
                paths.append(p)
    return paths


def _open_catalog_path(path: Path):
    """Yield a text file handle for plain JSON or gzip-compressed JSON."""
    import gzip

    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


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


def _first_value(ev: dict, key: str) -> str:
    """First ``value`` of a list-of-dicts field, or ''."""
    v = ev.get(key)
    if isinstance(v, list) and v:
        item = v[0]
        if isinstance(item, dict):
            return str(item.get("value", "") or "")
        return str(item)
    if isinstance(v, dict):
        return str(v.get("value", "") or "")
    return ""


def _parse_date(s: str):
    """Parse a catalog discoverdate into a datetime, or None.

    Hoisted out of find_closest_events so the index build can pre-compute it once
    instead of reconstructing a datetime for every catalog point on every page.
    """
    if not s or s == "—":
        return None
    clean = str(s).strip().replace("-", "/").split()[0]
    parts = clean.split("/")
    try:
        from datetime import datetime as _dt

        return _dt(
            int(parts[0]),
            int(parts[1]) if len(parts) > 1 else 1,
            int(parts[2]) if len(parts) > 2 else 1,
        )
    except Exception:
        return None


def _parse_z(s: str) -> float | None:
    """Parse a catalog redshift into a positive float, or None."""
    if not s or s == "—":
        return None
    try:
        clean = re.sub(r"[^0-9.]", "", str(s))
        if not clean:
            return None
        z = float(clean)
        return z if z > 0 else None
    except Exception:
        return None


def _iter_catalog(path: Path):
    """Stream catalog array elements without a full ``json.loads``.

    The previous implementation parsed the whole 53 MB catalog into a list and
    then built a second list of tuples, holding ~635 MB of transient garbage at
    startup. Streaming keeps peak near the buffer size.
    """
    import json as _json

    decoder = _json.JSONDecoder()
    with _open_catalog_path(path) as fh:
        head = fh.read(1)
        while head and head.isspace():
            head = fh.read(1)
        if head != "[":
            return
        buf = ""
        eof = False
        while not eof:
            chunk = fh.read(1 << 20)
            if chunk:
                buf += chunk
            else:
                eof = True
            while True:
                stripped = buf.lstrip()
                if stripped is not buf:
                    buf = stripped
                if not buf:
                    break
                ch = buf[0]
                if ch in ",]":
                    buf = buf[1:]
                    continue
                try:
                    obj, end = decoder.raw_decode(buf)
                except ValueError:
                    if eof:
                        buf = ""
                    break
                yield obj
                buf = buf[end:]


def _append_event(pts: list, seen: set[str], ev: dict) -> None:
    if not isinstance(ev, dict):
        return
    name = ev.get("name", "")
    if not name:
        return
    norm = str(name).lower().replace(" ", "").replace("-", "")
    if norm in seen:
        return
    ra_val = _first_value(ev, "ra")
    dec_val = _first_value(ev, "dec")
    ra_deg = _parse_coord(ra_val)
    dec_deg = _parse_coord(dec_val)
    if ra_deg is None or dec_deg is None:
        return

    # In sexagesimal hours format, RA might be in hours (0..24)
    if ra_val and ":" in str(ra_val) and ra_deg < 24.0:
        ra_deg *= 15.0

    r_rad = math.radians(ra_deg)
    d_rad = math.radians(dec_deg)
    x = math.cos(d_rad) * math.cos(r_rad)
    y = math.cos(d_rad) * math.sin(r_rad)
    z = math.sin(d_rad)

    disc_str = _first_value(ev, "discoverdate")
    z_str = _first_value(ev, "redshift")
    seen.add(norm)
    pts.append((
        x, y, z, round(ra_deg, 6), round(dec_deg, 6),
        {
            "name": name,
            "type": _first_value(ev, "claimedtype"),
            "redshift": z_str,
            "maxappmag": _first_value(ev, "maxappmag"),
            "discoverdate": disc_str,
            "host": _first_value(ev, "host"),
            "_disc_dt": _parse_date(disc_str),
            "_z": _parse_z(z_str),
        },
    ))


def init_cone_index() -> int:
    """Initialize the 3D unit vector spatial index from the volume catalog.

    Resolves ``SNE_DATA_DIR`` / ``catalog.min.json(.gz)`` first so Docker
    deployments (where the baked plain JSON is dockerignored) still index
    ~110k events. Streams sources so startup does not allocate a second full
    copy of the catalog.
    """
    global _SPATIAL_INDEX, _INDEX_INITIALIZED, _INDEX_STATUS, _INDEX_ERROR
    if _INDEX_INITIALIZED:
        return len(_SPATIAL_INDEX)

    with _INDEX_LOCK:
        if _INDEX_INITIALIZED:
            return len(_SPATIAL_INDEX)

        sources = _resolve_catalog_paths()
        if not sources:
            _SPATIAL_INDEX = []
            _INDEX_INITIALIZED = True
            _INDEX_STATUS = "missing_catalog"
            _INDEX_ERROR = "No catalog.min.json(.gz) found under SNE_DATA_DIR or baked path"
            print(f"[ConeIndex] {_INDEX_ERROR}", flush=True)
            return 0

        t0 = time.time()
        pts: list = []
        seen: set[str] = set()
        try:
            for src in sources:
                for ev in _iter_catalog(src):
                    _append_event(pts, seen, ev)
        except Exception as exc:  # noqa: BLE001
            _SPATIAL_INDEX = []
            _INDEX_INITIALIZED = True
            _INDEX_STATUS = "error"
            _INDEX_ERROR = str(exc)
            print(f"[ConeIndex] build failed: {exc}", flush=True)
            return 0

        _SPATIAL_INDEX = pts
        _INDEX_INITIALIZED = True
        if not pts:
            _INDEX_STATUS = "empty"
            _INDEX_ERROR = f"Catalog sources readable but yielded 0 points: {[str(s) for s in sources]}"
        else:
            _INDEX_STATUS = "ok"
            _INDEX_ERROR = ""
        print(
            f"[ConeIndex] {len(pts)} points in {time.time() - t0:.2f}s "
            f"from {len(sources)} source(s) status={_INDEX_STATUS}",
            flush=True,
        )
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
) -> dict[str, Any]:
    """Find catalog transients closest to this event in sky separation, discovery time, and cosmic distance.

    Returns sky/time/cosmic lists plus ``_status`` / ``_index_size`` / ``_error`` so
    the UI can distinguish "search unavailable" from "no neighbors exist".
    """
    n = init_cone_index() if not _INDEX_INITIALIZED else len(_SPATIAL_INDEX)
    if n == 0 or _INDEX_STATUS in ("missing_catalog", "empty", "error"):
        return {
            "sky": [],
            "time": [],
            "cosmic": [],
            "_status": "unavailable",
            "_index_size": n,
            "_error": _INDEX_ERROR or f"Neighbor index status={_INDEX_STATUS}",
        }

    r0 = math.radians(ra_deg) if ra_deg is not None else None
    d0 = math.radians(dec_deg) if dec_deg is not None else None
    x0 = math.cos(d0) * math.cos(r0) if r0 is not None and d0 is not None else None
    y0 = math.cos(d0) * math.sin(r0) if r0 is not None and d0 is not None else None
    z0 = math.sin(d0) if d0 is not None else None

    _parse_d = _parse_date
    t0 = _parse_d(discoverdate_str)
    z_target = _parse_z(redshift_str)

    # Bounded heaps instead of three full-length lists that are then sorted.
    # The previous version appended one tuple per catalog point per dimension
    # (3 x 105,668 tuples), sorted all three, and kept only 3 results -- measured
    # 345 ms of pure allocation and sorting for a single event page. A size-limited
    # heap does the same selection in one pass with 9 retained entries.
    # The trailing counter breaks ties without ever comparing the metadata dicts
    # (heapq would otherwise raise on equal distances).
    sky_heap: list[tuple[float, int, float, float, dict[str, Any]]] = []
    time_heap: list[tuple[int, int, int, dict[str, Any]]] = []
    cosmic_heap: list[tuple[float, int, float, dict[str, Any]]] = []

    norm_name = name.lower().replace(" ", "").replace("-", "")
    # Compute the sky separation only when coordinates are known; hoist the
    # constant radians conversion out of the loop.
    have_sky = x0 is not None and y0 is not None and z0 is not None
    _acos, _degrees = math.acos, math.degrees

    seq = 0
    for x, y, z, tra, tdec, meta in _SPATIAL_INDEX:
        seq += 1
        m_name = meta.get("name", "")
        if m_name.lower().replace(" ", "").replace("-", "") == norm_name:
            continue

        # Sky separation. negated so a size-limited min-heap keeps the smallest.
        if have_sky:
            dot = x0 * x + y0 * y + z0 * z
            if dot > 1.0:
                dot = 1.0
            elif dot < -1.0:
                dot = -1.0
            sep_deg = _degrees(_acos(dot))
            if len(sky_heap) < limit:
                heapq.heappush(sky_heap, (-sep_deg, seq, tra, tdec, meta))
            elif sep_deg < -sky_heap[0][0]:
                heapq.heapreplace(sky_heap, (-sep_deg, seq, tra, tdec, meta))

        # Discovery time. The date was pre-parsed at index build; only fall back
        # to parsing when the cached value is absent.
        if t0 is not None:
            t_disc = meta.get("_disc_dt")
            if t_disc is None:
                disc_val = meta.get("discoverdate", "")
                if disc_val:
                    t_disc = _parse_d(disc_val)
            if t_disc is not None:
                delta_days = (t_disc - t0).days
                key = abs(delta_days)
                if len(time_heap) < limit:
                    heapq.heappush(time_heap, (-key, seq, delta_days, meta))
                elif key < -time_heap[0][0]:
                    heapq.heapreplace(time_heap, (-key, seq, delta_days, meta))

        # Cosmic redshift delta
        if z_target is not None:
            z_raw = meta.get("_z")
            if z_raw is None:
                z_raw = meta.get("redshift")
            if z_raw:
                try:
                    z_val = float(z_raw)
                    if z_val > 0:
                        delta_z = abs(z_val - z_target)
                        if len(cosmic_heap) < limit:
                            heapq.heappush(cosmic_heap, (-delta_z, seq, z_val, meta))
                        elif delta_z < -cosmic_heap[0][0]:
                            heapq.heapreplace(cosmic_heap, (-delta_z, seq, z_val, meta))
                except Exception:
                    pass

    by_sky = sorted(sky_heap, key=lambda item: -item[0])
    by_time = sorted(time_heap, key=lambda item: -item[0])
    by_cosmic = sorted(cosmic_heap, key=lambda item: -item[0])

    def _clean(m: dict[str, Any]) -> dict[str, Any]:
        # Strip the private pre-parsed fields so they never reach the HTML layer.
        return {k: v for k, v in m.items() if not k.startswith("_")}

    sky_res = []
    for neg_sep, _seq, tra, tdec, m in by_sky[:limit]:
        sep_deg = -neg_sep
        item = _clean(m)
        item["separation_arcmin"] = round(sep_deg * 60.0, 1)
        item["separation_deg"] = round(sep_deg, 3)
        item["ra"] = tra
        item["dec"] = tdec
        sky_res.append(item)

    time_res = []
    for neg_days, _seq, delta_days, m in by_time[:limit]:
        abs_days = -neg_days
        item = _clean(m)
        item["delta_days"] = delta_days
        item["abs_delta_days"] = abs_days
        time_res.append(item)

    cosmic_res = []
    for neg_dz, _seq, z_val, m in by_cosmic[:limit]:
        delta_z = -neg_dz
        item = _clean(m)
        item["delta_z"] = round(delta_z, 4)
        item["target_z"] = z_target
        item["est_light_years_m"] = round(z_val * 4200.0 * 3.26156, 1) if z_val < 0.1 else round(z_val * 13800.0, 1)
        cosmic_res.append(item)

    return {
        "sky": sky_res,
        "time": time_res,
        "cosmic": cosmic_res,
        "_status": "ok",
        "_index_size": len(_SPATIAL_INDEX),
        "_error": "",
    }

