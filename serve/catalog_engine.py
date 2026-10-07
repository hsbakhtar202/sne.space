#!/usr/bin/env python3
"""High-Performance Native Catalog Engine for sne.space.

Maintains an in-memory index of all 110,000+ explosive cosmic transients,
merging baseline catalog archives with live modern survey events (2025-2029).
Powers sub-5ms multi-field search, classification filtering, sorting, pagination,
and server-side rendering (SSR) of initial table states.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("sne.catalog")

WWW = Path(__file__).resolve().parent / "www"
SUPERNOVAE_OUTPUT = WWW / "astrocats/astrocats/supernovae/output"
RECENT_PATH = WWW / "assets/recent-catalog.min.json"
SNE_RECENT_DIR = SUPERNOVAE_OUTPUT / "sne-2025-2029"


def _extract_val(obj: Any, key: str) -> str:
    if not obj:
        return ""
    v = obj.get(key)
    if not v:
        return ""
    if isinstance(v, list) and v:
        item = v[0]
        return str(item.get("value", item) if isinstance(item, dict) else item).strip()
    if isinstance(v, dict):
        return str(v.get("value", "")).strip()
    return str(v).strip()


def _extract_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s in ("—", "None", "nan", "null"):
        return None
    try:
        f = float(s)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _extract_int_count(val: Any) -> int:
    if not val:
        return 0
    s = str(val).strip()
    if not s or s == "—":
        return 0
    try:
        parts = s.split(",")
        return max(0, int(parts[0].strip()))
    except (ValueError, TypeError, IndexError):
        return 0


def _format_relative_age(date_str: str) -> str:
    if not date_str:
        return ""
    clean = date_str.replace("/", "-").strip()
    parts = clean.split("-")
    if len(parts) < 3:
        return ""
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        ev_dt = datetime(y, m, d, tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        days = (now_dt - ev_dt).days
        if days < 0:
            return "today"
        if days == 0:
            return "today"
        if days == 1:
            return "1d ago"
        if days < 30:
            return f"{days}d ago"
        if days < 365:
            months = days // 30
            return f"{months}mo ago"
        years = days // 365
        return f"{years}y ago"
    except Exception:
        return ""


def _clean_date_for_sort(d: str, reverse: bool) -> str:
    if not d or d in ("—", "None", "null") or not d[0].isdigit():
        return "0000/00/00" if reverse else "9999/99/99"
    parts = d.replace("-", "/").split("/")
    if len(parts) >= 3:
        y = parts[0].zfill(4)
        m = parts[1].zfill(2)
        day = parts[2].zfill(2)
        return f"{y}/{m}/{day}"
    return parts[0].zfill(4)


def _classify_type_badge(claimed_type: str) -> str:
    ct = claimed_type.lower()
    if not ct or ct == "—":
        return "badge-unknown"
    if "ia" in ct or "i-a" in ct:
        return "badge-ia"
    if "ii" in ct:
        return "badge-ii"
    if "ib" in ct or "ic" in ct:
        return "badge-ibc"
    if "slsn" in ct or "superluminous" in ct:
        return "badge-slsn"
    if "tde" in ct or "tidal" in ct:
        return "badge-tde"
    return "badge-other"


class CatalogEngine:
    _instance: Optional["CatalogEngine"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []
        self._name_index: dict[str, int] = {}
        self._loaded = False
        self._loading = False
        self._last_loaded_time = 0.0
        self._total_transients = 0
        self._total_with_spectra = 0
        self._total_with_photometry = 0

    @classmethod
    def get_instance(cls) -> "CatalogEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self.reload()

    def reload(self) -> None:
        with self._lock:
            if self._loading:
                return
            self._loading = True

        try:
            t0 = time.time()
            items_by_name: dict[str, dict[str, Any]] = {}

            # 1. First ingest all events in modern era directory (sne-2025-2029)
            if SNE_RECENT_DIR.is_dir():
                for p in SNE_RECENT_DIR.glob("*.json"):
                    try:
                        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
                        name = list(data.keys())[0]
                        ev = data[name]
                        rec = self._parse_event_dict_to_record(name, ev)
                        if rec:
                            items_by_name[name.lower()] = rec
                    except Exception as exc:
                        logger.debug("Failed reading modern event %s: %s", p, exc)

            # 2. Ingest recent catalog rows
            if RECENT_PATH.is_file():
                try:
                    recent_rows = json.loads(RECENT_PATH.read_text(encoding="utf-8"))
                    for r in recent_rows:
                        name = r.get("name", "")
                        if not name:
                            continue
                        k = name.lower()
                        if k not in items_by_name:
                            rec = self._parse_catalog_row_to_record(r)
                            if rec:
                                items_by_name[k] = rec
                except Exception as exc:
                    logger.warning("Failed reading recent catalog: %s", exc)

            # 3. Load master baseline catalog (catalog.min.json or catalog.min.json.gz)
            base_json = SUPERNOVAE_OUTPUT / "catalog.min.json"
            base_gz = SUPERNOVAE_OUTPUT / "catalog.min.json.gz"

            raw_cat: list[dict[str, Any]] = []
            if base_json.is_file():
                try:
                    raw_cat = json.loads(base_json.read_text(encoding="utf-8"))
                except Exception:
                    pass
            elif base_gz.is_file():
                try:
                    decompressed = gzip.decompress(base_gz.read_bytes())
                    raw_cat = json.loads(decompressed.decode("utf-8"))
                except Exception:
                    pass

            for r in raw_cat:
                name = r.get("name", "")
                if not name:
                    continue
                k = name.lower()
                if k not in items_by_name:
                    rec = self._parse_catalog_row_to_record(r)
                    if rec:
                        items_by_name[k] = rec

            # Flatten items
            all_items = list(items_by_name.values())

            # Sort default: discover date descending (newest first)
            all_items.sort(key=lambda x: (_clean_date_for_sort(x.get("date"), reverse=True), x.get("name") or ""), reverse=True)

            name_idx = {item["name"].lower(): idx for idx, item in enumerate(all_items)}

            # Tally statistics
            n_spec = sum(1 for it in all_items if it.get("spec", 0) > 0)
            n_phot = sum(1 for it in all_items if it.get("phot", 0) > 0)

            with self._lock:
                self._items = all_items
                self._name_index = name_idx
                self._total_transients = len(all_items)
                self._total_with_spectra = n_spec
                self._total_with_photometry = n_phot
                self._loaded = True
                self._loading = False
                self._last_loaded_time = time.time()

            logger.info(
                "CatalogEngine indexed %d transients (%d with spectra, %d with photometry) in %.2fs",
                len(all_items),
                n_spec,
                n_phot,
                time.time() - t0,
            )

        except Exception as exc:
            logger.exception("Error loading catalog index: %s", exc)
            with self._lock:
                self._loading = False

    def _parse_event_dict_to_record(self, name: str, ev: dict[str, Any]) -> Optional[dict[str, Any]]:
        disc_date = _extract_val(ev, "discoverdate")
        c_type = _extract_val(ev, "claimedtype")
        ra = _extract_val(ev, "ra")
        dec = _extract_val(ev, "dec")
        host = _extract_val(ev, "host")
        disc = _extract_val(ev, "discoverer")
        z = _extract_float(_extract_val(ev, "redshift"))

        mag_val = _extract_float(_extract_val(ev, "maxappmag"))
        if mag_val is None and ev.get("photometry"):
            mags = [float(ph["magnitude"]) for ph in ev["photometry"] if "magnitude" in ph and _extract_float(ph.get("magnitude")) is not None]
            if mags:
                mag_val = round(min(mags), 2)

        n_phot = len(ev.get("photometry", []))
        n_spec = len(ev.get("spectra", []))

        aliases_list = []
        if ev.get("alias"):
            for a in ev["alias"]:
                aval = a.get("value", a) if isinstance(a, dict) else str(a)
                if aval and aval != name and aval not in aliases_list:
                    aliases_list.append(str(aval))

        search_tokens = [name.lower()] + [a.lower() for a in aliases_list]
        if c_type:
            search_tokens.append(c_type.lower())
        if disc:
            search_tokens.append(disc.lower())
        if host:
            search_tokens.append(host.lower())
        search_blob = " ".join(search_tokens)

        return {
            "name": name,
            "aliases": aliases_list,
            "type": c_type or "—",
            "type_badge": _classify_type_badge(c_type),
            "date": disc_date or "—",
            "age": _format_relative_age(disc_date),
            "mag": mag_val,
            "z": z,
            "ra": ra or "—",
            "dec": dec or "—",
            "host": host or "—",
            "disc": disc or "—",
            "spec": n_spec,
            "phot": n_phot,
            "search_blob": search_blob,
        }

    def _parse_catalog_row_to_record(self, r: dict[str, Any]) -> Optional[dict[str, Any]]:
        name = r.get("name", "")
        if not name:
            return None

        disc_date = _extract_val(r, "discoverdate")
        c_type = _extract_val(r, "claimedtype")
        ra = _extract_val(r, "ra")
        dec = _extract_val(r, "dec")
        host = _extract_val(r, "host")
        disc = _extract_val(r, "discoverer")
        z = _extract_float(_extract_val(r, "redshift"))
        mag_val = _extract_float(_extract_val(r, "maxappmag"))

        n_spec = _extract_int_count(r.get("spectralink"))
        n_phot = _extract_int_count(r.get("photolink"))

        aliases_list = []
        if isinstance(r.get("alias"), list):
            for a in r["alias"]:
                aval = a.get("value", a) if isinstance(a, dict) else str(a)
                if aval and aval != name and aval not in aliases_list:
                    aliases_list.append(str(aval))

        search_tokens = [name.lower()] + [a.lower() for a in aliases_list]
        if c_type:
            search_tokens.append(c_type.lower())
        if disc:
            search_tokens.append(disc.lower())
        if host:
            search_tokens.append(host.lower())
        search_blob = " ".join(search_tokens)

        return {
            "name": name,
            "aliases": aliases_list,
            "type": c_type or "—",
            "type_badge": _classify_type_badge(c_type),
            "date": disc_date or "—",
            "age": _format_relative_age(disc_date),
            "mag": mag_val,
            "z": z,
            "ra": ra or "—",
            "dec": dec or "—",
            "host": host or "—",
            "disc": disc or "—",
            "spec": n_spec,
            "phot": n_phot,
            "search_blob": search_blob,
        }

    def query(
        self,
        q: str = "",
        type_filter: str = "",
        has_spectra: Optional[bool] = None,
        has_photometry: Optional[bool] = None,
        sort: str = "discoverdate",
        order: str = "desc",
        page: int = 1,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Perform sub-5ms multi-criteria search and sorting across the catalog."""
        self.ensure_loaded()

        q_clean = q.strip().lower()
        type_clean = type_filter.strip().lower()
        limit = max(1, min(limit, 250))
        page = max(1, page)

        filtered = self._items

        # 1. Full-text / Substring search
        if q_clean:
            filtered = [it for it in filtered if q_clean in it["search_blob"]]

        # 2. Type filtering
        if type_clean and type_clean not in ("all", "any"):
            if type_clean == "ia":
                filtered = [it for it in filtered if "ia" in it["type"].lower() or "i-a" in it["type"].lower()]
            elif type_clean == "ii":
                filtered = [it for it in filtered if "ii" in it["type"].lower()]
            elif type_clean in ("ibc", "ib/c"):
                filtered = [it for it in filtered if "ib" in it["type"].lower() or "ic" in it["type"].lower()]
            elif type_clean == "slsn":
                filtered = [it for it in filtered if "slsn" in it["type"].lower() or "superluminous" in it["type"].lower()]
            elif type_clean == "tde":
                filtered = [it for it in filtered if "tde" in it["type"].lower() or "tidal" in it["type"].lower()]
            else:
                filtered = [it for it in filtered if type_clean in it["type"].lower()]

        # 3. Has spectra toggle
        if has_spectra is True:
            filtered = [it for it in filtered if it.get("spec", 0) > 0]
        elif has_spectra is False:
            filtered = [it for it in filtered if it.get("spec", 0) == 0]

        # 4. Has photometry toggle
        if has_photometry is True:
            filtered = [it for it in filtered if it.get("phot", 0) > 0]
        elif has_photometry is False:
            filtered = [it for it in filtered if it.get("phot", 0) == 0]

        total = len(filtered)
        pages = max(1, math.ceil(total / limit))
        page = min(page, pages)

        # 5. Sorting
        reverse = order.lower() == "desc"
        sort_key = sort.lower()

        if sort_key in ("discoverdate", "date"):
            filtered = sorted(filtered, key=lambda x: _clean_date_for_sort(x.get("date"), reverse=reverse), reverse=reverse)
        elif sort_key == "name":
            filtered = sorted(filtered, key=lambda x: x.get("name", "").lower(), reverse=reverse)
        elif sort_key in ("claimedtype", "type"):
            filtered = sorted(filtered, key=lambda x: x.get("type", "").lower(), reverse=reverse)
        elif sort_key in ("redshift", "z"):
            if reverse:
                filtered = sorted(filtered, key=lambda x: (x.get("z") is not None, x.get("z") if x.get("z") is not None else -999.0), reverse=True)
            else:
                filtered = sorted(filtered, key=lambda x: (x.get("z") is None, x.get("z") if x.get("z") is not None else 999.0))
        elif sort_key in ("maxappmag", "mag"):
            if reverse:
                filtered = sorted(filtered, key=lambda x: (x.get("mag") is not None, x.get("mag") if x.get("mag") is not None else -999.0), reverse=True)
            else:
                filtered = sorted(filtered, key=lambda x: (x.get("mag") is None, x.get("mag") if x.get("mag") is not None else 999.0))
        elif sort_key in ("spectralink", "spec"):
            filtered = sorted(filtered, key=lambda x: x.get("spec", 0), reverse=reverse)
        elif sort_key in ("photolink", "phot"):
            filtered = sorted(filtered, key=lambda x: x.get("phot", 0), reverse=reverse)

        start = (page - 1) * limit
        end = start + limit
        paged_items = filtered[start:end]

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
            "has_next": page < pages,
            "has_prev": page > 1,
            "items": paged_items,
        }

    def render_rows_html(self, items: list[dict[str, Any]]) -> str:
        """Render fast, semantic table rows for SSR or dynamic DOM hydration."""
        out = []
        for r in items:
            nm = r["name"]
            c_type = r["type"]
            badge_class = r["type_badge"]
            disc_date = r["date"]
            age = r["age"]
            mag_str = f"{r['mag']:.2f}" if r.get("mag") is not None else "—"
            z_str = f"{r['z']:.4f}".rstrip("0").rstrip(".") if r.get("z") is not None else "—"
            ra = r.get("ra", "—")
            dec = r.get("dec", "—")
            host = r.get("host", "—")
            spec = r.get("spec", 0)
            phot = r.get("phot", 0)

            # Build spectra pill
            if spec > 0:
                spec_html = f'<a href="/sne/{nm}/#spectra" class="pill-badge pill-spec" title="{spec} calibrated spectra available">✨ {spec}</a>'
            else:
                spec_html = '<span class="pill-dim">—</span>'

            # Build light curve pill
            if phot > 0:
                phot_html = f'<a href="/sne/{nm}/#lightcurve" class="pill-badge pill-phot" title="{phot} photometry observations">📈 {phot}</a>'
            else:
                phot_html = '<span class="pill-dim">—</span>'

            # Age badge
            age_badge = f'<span class="sub-age">{age}</span>' if age else ""

            row_html = f"""<tr data-name="{nm}">
  <td class="cell-name">
    <a href="/sne/{nm}/" class="name-link">{nm}</a>
  </td>
  <td class="cell-type"><span class="type-pill {badge_class}">{c_type}</span></td>
  <td class="cell-date"><span class="val-date">{disc_date}</span>{age_badge}</td>
  <td class="cell-num">{z_str}</td>
  <td class="cell-num">{mag_str}</td>
  <td class="cell-coords"><span class="coord-tag" title="Click to copy coordinates" onclick="navigator.clipboard.writeText('{ra} {dec}'); this.classList.add('copied'); setTimeout(()=>this.classList.remove('copied'),1200);">{ra}, {dec}</span></td>
  <td class="cell-host">{host}</td>
  <td class="cell-spec">{spec_html}</td>
  <td class="cell-phot">{phot_html}</td>
  <td class="cell-actions">
    <a href="/sne/{nm}/" class="btn-action btn-pro" title="Professional Cockpit">🔭 Pro</a>
    <a href="/sne/{nm}/story" class="btn-action btn-story" title="Story Dossier">📖 Story</a>
  </td>
</tr>"""
            out.append(row_html)
        return "\n".join(out)

    def export_csv(
        self,
        q: str = "",
        type_filter: str = "",
        has_spectra: Optional[bool] = None,
        has_photometry: Optional[bool] = None,
        sort: str = "discoverdate",
        order: str = "desc",
        max_rows: int = 5000,
    ) -> str:
        """Export current filtered view to standard RFC4180 CSV format."""
        res = self.query(
            q=q,
            type_filter=type_filter,
            has_spectra=has_spectra,
            has_photometry=has_photometry,
            sort=sort,
            order=order,
            page=1,
            limit=max_rows,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["name", "claimed_type", "discover_date", "redshift", "max_app_mag", "ra", "dec", "host_galaxy", "discoverer", "spectra_count", "photometry_count", "url"])
        for r in res["items"]:
            writer.writerow([
                r["name"],
                r["type"],
                r["date"],
                r["z"] if r.get("z") is not None else "",
                r["mag"] if r.get("mag") is not None else "",
                r["ra"],
                r["dec"],
                r["host"],
                r["disc"],
                r["spec"],
                r["phot"],
                f"https://sne.space/sne/{r['name']}/",
            ])
        return output.getvalue()


def sync_all_recent_partitions() -> int:
    """Scan sne-2025-2029 and sync into recent-catalog.min.json and names.min.json."""
    if not SNE_RECENT_DIR.is_dir():
        return 0

    rows: list[tuple[str, dict[str, Any]]] = []
    names_map: dict[str, list[str]] = {}

    names_file = SUPERNOVAE_OUTPUT / "names.min.json"
    if names_file.is_file():
        try:
            names_map = json.loads(names_file.read_text(encoding="utf-8"))
        except Exception:
            names_map = {}

    for p in SNE_RECENT_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            name = list(data.keys())[0]
            ev = data[name]

            disc_date = _extract_val(ev, "discoverdate")
            max_date = _extract_val(ev, "maxdate") or disc_date
            disc = _extract_val(ev, "discoverer")
            c_type = _extract_val(ev, "claimedtype")
            ra = _extract_val(ev, "ra")
            dec = _extract_val(ev, "dec")
            host = _extract_val(ev, "host")
            z = _extract_val(ev, "redshift")

            mag_val = ""
            if ev.get("maxappmag"):
                mag_val = _extract_val(ev, "maxappmag")
            elif ev.get("photometry"):
                mags = [float(ph["magnitude"]) for ph in ev["photometry"] if "magnitude" in ph and _extract_float(ph.get("magnitude")) is not None]
                if mags:
                    mag_val = f"{min(mags):.2f}"

            n_phot = len(ev.get("photometry", []))
            n_spec = len(ev.get("spectra", []))

            aliases = []
            if ev.get("alias"):
                for a in ev["alias"]:
                    aval = a.get("value", a) if isinstance(a, dict) else str(a)
                    if aval:
                        aliases.append({"value": str(aval)})
            if not aliases:
                aliases = [{"value": name}]

            # Update names_map
            alias_strings = [a["value"] for a in aliases]
            if name not in names_map:
                names_map[name] = alias_strings
            else:
                existing = set(names_map[name])
                for al in alias_strings:
                    if al not in existing:
                        names_map[name].append(al)

            row = {
                "name": name,
                "alias": aliases,
                "discoverer": [{"value": disc}] if disc else [],
                "discoverdate": [{"value": disc_date}] if disc_date else [],
                "maxdate": [{"value": max_date}] if max_date else [],
                "maxappmag": [{"value": str(mag_val)}] if mag_val else [],
                "ra": [{"value": ra}] if ra else [],
                "dec": [{"value": dec}] if dec else [],
                "claimedtype": [{"value": c_type}] if c_type else [],
                "photolink": f"{n_phot},0" if n_phot else "0",
                "spectralink": f"{n_spec}" if n_spec else "0",
            }
            if host:
                row["host"] = [{"value": host}]
            if z:
                row["redshift"] = [{"value": str(z)}]

            rows.append((disc_date or "", row))
        except Exception as exc:
            logger.warning("Error syncing %s: %s", p, exc)

    rows.sort(key=lambda x: x[0], reverse=True)
    all_recent = [r[1] for r in rows]

    # Write recent-catalog.min.json
    RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECENT_PATH.write_text(json.dumps(all_recent, separators=(",", ":")), encoding="utf-8")

    # Write names.min.json
    try:
        names_file.write_text(json.dumps(names_map, separators=(",", ":")), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed updating names.min.json: %s", exc)

    # Invalidate catalog engine
    engine = CatalogEngine.get_instance()
    engine.reload()

    return len(all_recent)
