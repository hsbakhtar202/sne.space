#!/usr/bin/env python3
"""Threaded local sne.space server (S1.2 / S1.3).

Serves the historical path layout with concurrent static file I/O so the
27 MB catalog.min.json ajax load does not stall behind PHP's single thread.
Dynamic pages (/ and /sne|/event) are rendered via PHP CLI against www/.
"""
from __future__ import annotations

import csv
import collections
import datetime
from functools import lru_cache
import gzip
import io
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
mimetypes.add_type("image/webp", ".webp")
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from ingest.manager import enrich_event, is_file_stale
except Exception:
    enrich_event = None
    is_file_stale = None

try:
    from event_render import render_pro_cockpit, render_story_mode, extract_coords, classify_event_tier
except Exception:
    try:
        from serve.event_render import render_pro_cockpit, render_story_mode, extract_coords, classify_event_tier
    except Exception:
        render_pro_cockpit = None
        render_story_mode = None
        extract_coords = None
        classify_event_tier = None

try:
    from radar import render_radar_page, scan_catalog_targets, compute_observability_for_targets
except Exception:
    try:
        from serve.radar import render_radar_page, scan_catalog_targets, compute_observability_for_targets
    except Exception:
        render_radar_page = None
        scan_catalog_targets = None
        compute_observability_for_targets = None

try:
    from cone_search import cone_search, format_votable, init_cone_index
except Exception:
    try:
        from serve.cone_search import cone_search, format_votable, init_cone_index
    except Exception:
        cone_search = None
        format_votable = None
        init_cone_index = None

try:
    from sitemaps import get_sitemap
except Exception:
    try:
        from serve.sitemaps import get_sitemap
    except Exception:
        get_sitemap = None

try:
    from faq_render import render_faq_page
except Exception:
    try:
        from serve.faq_render import render_faq_page
    except Exception:
        render_faq_page = None

try:
    from api_render import render_api_docs_page
except Exception:
    try:
        from serve.api_render import render_api_docs_page
    except Exception:
        render_api_docs_page = None

ROOT = Path(__file__).resolve().parent
WWW = ROOT / "www"
PHP = os.environ.get("PHP_BIN", "php")
HOST = os.environ.get("OSC_HOST", "127.0.0.1")
PORT = int(os.environ.get("OSC_PORT", "8080"))

_START_TIME = time.time()
_API_STATS_LOCK = threading.Lock()
_API_STATS = {
    "started_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "total_requests": 0,
    "api_requests": 0,
    "unique_ips": set(),
    "top_targets": collections.Counter(),
    "top_user_agents": collections.Counter(),
    "top_paths": collections.Counter(),
    "status_codes": collections.Counter(),
    "recent_requests": collections.deque(maxlen=100),
}


def _record_api_stat(ip: str, host: str, path: str, method: str, code: int, size: int, dur_ms: float, ua: str):
    with _API_STATS_LOCK:
        _API_STATS["total_requests"] += 1
        _API_STATS["unique_ips"].add(ip)
        _API_STATS["status_codes"][str(code)] += 1
        clean_path = path.split("?")[0]
        _API_STATS["top_paths"][clean_path] += 1

        is_api = host.startswith("api.") or clean_path.startswith(("/api", "/cone", "/catalog", "/sne/")) or clean_path.endswith((".json", ".csv"))
        if is_api:
            _API_STATS["api_requests"] += 1
            ua_clean = ua[:60] if ua else "unknown"
            _API_STATS["top_user_agents"][ua_clean] += 1

            m = re.match(r"^/(?:api/|sne/)?([A-Za-z0-9+_-]+)(?:\.[a-z]+|/[a-z]+)?$", clean_path)
            if m:
                target_cand = m.group(1).upper()
                if target_cand not in ("API", "CATALOG", "CONE", "RADAR", "RECENT", "SEARCH", "BY-TYPE", "DOCS", "FAQS", "SITEMAP", "STATS", "TELEMETRY", "COUNT"):
                    _API_STATS["top_targets"][target_cand] += 1

        _API_STATS["recent_requests"].appendleft({
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "ip": ip,
            "host": host,
            "method": method,
            "path": path,
            "status": code,
            "bytes": size,
            "duration_ms": round(dur_ms, 1),
            "user_agent": ua[:80] if ua else "-"
        })


def _php_render(script: Path, env: dict | None = None, query: str = "") -> bytes:
    run_env = os.environ.copy()
    run_env["OSC_DOCROOT"] = str(WWW)
    run_env["DOCUMENT_ROOT"] = str(WWW)
    if env:
        run_env.update(env)
    # Simulate CGI-ish vars for event.php
    run_env.setdefault("REQUEST_METHOD", "GET")
    if query:
        run_env["QUERY_STRING"] = query
    proc = subprocess.run(
        [PHP, str(script)],
        cwd=str(WWW),
        env=run_env,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 and not proc.stdout:
        return (b"<pre>PHP error\n" + proc.stderr + b"</pre>")
    return proc.stdout


@lru_cache(maxsize=1)
def _names_maps() -> tuple[dict, dict]:
    names = {}
    names_by = {}
    p = WWW / "astrocats/astrocats/supernovae/output/names.min.json"
    pb = WWW / "astrocats/astrocats/supernovae/output/names-by.min.json"
    if p.is_file():
        names = json.loads(p.read_text())
    if pb.is_file():
        names_by = json.loads(pb.read_text())
    return names, names_by


def _normalize_event_name(eventname: str) -> str:
    eventname = urllib.parse.unquote(eventname).replace(".html", "")
    if eventname[:3].isdigit() and len(eventname) <= 4:
        eventname = "SN" + eventname
    if eventname[:4].isdigit() and not eventname[4:5].isdigit():
        eventname = "SN" + eventname
    if eventname.startswith("sn"):
        eventname = "SN" + eventname[2:]
    if eventname.startswith("SN "):
        eventname = "SN" + eventname[3:]
    if eventname.startswith("SN") and eventname[2:5].isdigit():
        if len(eventname) == 7:
            eventname = eventname.upper()
        else:
            eventname = eventname[:6] + eventname[6:].lower()
    return eventname


def _html_exists(name: str) -> bool:
    base = WWW / "astrocats/astrocats/supernovae/output/html" / name
    html = base.with_suffix(".html")
    gz = Path(str(base) + ".html.gz")
    if html.is_file() and html.stat().st_size > 0:
        return True
    if gz.is_file() and gz.stat().st_size > 0:
        return True
    return False


@lru_cache(maxsize=1)
def _alias_lookup_map() -> dict[str, str]:
    names, names_by = _names_maps()
    alias_map: dict[str, str] = {}
    for mapping in (names, names_by):
        for canon, aliases in mapping.items():
            alias_map[canon.lower()] = canon
            alias_map[canon.lower().replace(" ", "")] = canon
            if isinstance(aliases, list):
                for a in aliases:
                    if isinstance(a, str):
                        alias_map[a.lower()] = canon
                        alias_map[a.lower().replace(" ", "")] = canon
    return alias_map


def _ensure_catalog_files():
    """Ensure catalog.min.json is uncompressed and available on disk."""
    cat_gz = WWW / "astrocats/astrocats/supernovae/output/catalog.min.json.gz"
    cat_json = WWW / "astrocats/astrocats/supernovae/output/catalog.min.json"
    if cat_gz.is_file() and (not cat_json.is_file() or cat_json.stat().st_size == 0):
        try:
            import gzip
            with gzip.open(cat_gz, "rb") as f_in:
                cat_json.write_bytes(f_in.read())
            print("Extracted catalog.min.json from catalog.min.json.gz", flush=True)
        except Exception as e:
            print(f"Warning: could not extract catalog.min.json.gz: {e}", flush=True)


def _find_event_file_direct(raw_name: str) -> tuple[str | None, Path | None]:
    """Fast direct filesystem check for event JSON before hitting alias maps or Levenshtein."""
    output_dir = WWW / "astrocats/astrocats/supernovae/output"
    target = _normalize_event_name(raw_name)
    clean = target.replace("/", "_")
    candidates = list(output_dir.glob(f"sne-*/{clean}.json"))
    candidates.append(output_dir / "json" / f"{clean}.json")
    for c in candidates:
        if c.is_file():
            return target, c

    flip = clean.replace("SN", "AT") if clean.startswith("SN") else clean.replace("AT", "SN")
    flip_candidates = list(output_dir.glob(f"sne-*/{flip}.json"))
    flip_candidates.append(output_dir / "json" / f"{flip}.json")
    for c in flip_candidates:
        if c.is_file():
            return flip, c

    return None, None


def _fetch_remote_event(name: str) -> tuple[str | None, Path | None]:
    """Fetch event JSON from upstream repositories or live astronomical brokers and cache locally."""
    clean = _normalize_event_name(name)
    output_dir = WWW / "astrocats/astrocats/supernovae/output"

    match = re.search(r'(?<!\d)(19\d{2}|20\d{2})(?!\d)', clean)
    hist_match = re.search(r'(?<!\d)(?:SN|AT)?(\d{3,4})(?!\d)', clean, re.IGNORECASE) if not match else None

    # Fast sanity check: must resemble a transient designation or catalog entry
    has_astro_prefix = bool(re.search(r'^(SN|AT|ASASSN|Gaia|ZTF|PS1|CSS|MLS|MASTER|DES|OGLE|IPTF)', clean, re.IGNORECASE))
    if not (match or hist_match or has_astro_prefix):
        return None, None

    if match:
        year = int(match.group(1))
    elif hist_match and int(hist_match.group(1)) < 1900:
        year = int(hist_match.group(1))
    else:
        year = 2026

    if year <= 1989:
        epoch = "sne-pre-1990"
    elif year <= 1999:
        epoch = "sne-1990-1999"
    elif year <= 2004:
        epoch = "sne-2000-2004"
    elif year <= 2009:
        epoch = "sne-2005-2009"
    elif year <= 2014:
        epoch = "sne-2010-2014"
    elif year <= 2019:
        epoch = "sne-2015-2019"
    elif year <= 2024:
        epoch = "sne-2020-2024"
    else:
        epoch = "sne-2025-2029"

    # 1. Targeted check in the specific epoch repo and boneyard
    repos_to_try = [epoch, "sne-boneyard"]

    for r in repos_to_try:
        for cand_name in (clean, clean.replace("SN", "AT"), clean.replace("AT", "SN")):
            url = f"https://raw.githubusercontent.com/astrocatalogs/{r}/master/{cand_name}.json"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "sne.space/1.0"})
                with urllib.request.urlopen(req, timeout=2.5) as resp:
                    if resp.status == 200:
                        data = resp.read()
                        if data and len(data) > 10:
                            target_dir = output_dir / r
                            target_dir.mkdir(parents=True, exist_ok=True)
                            target_file = target_dir / f"{clean}.json"
                            target_file.write_bytes(data)
                            return clean, target_file
            except Exception:
                pass

    # 2. Try live ingest/enrichment from TNS / ALeRCE / WISeREP if modern
    if enrich_event is not None and year >= 2018:
        try:
            ok = enrich_event(clean, force=True)
            if ok:
                c, fp = _find_event_file_direct(clean)
                if fp and fp.is_file():
                    return c, fp
        except Exception:
            pass

    return None, None


def _resolve_event(raw: str) -> tuple[str | None, str | None]:
    """Return (canonical_name, entered_if_fuzzy). Fast O(1) lookup with fuzzy fallback."""
    oname = urllib.parse.unquote(raw).strip()
    eventname = _normalize_event_name(oname)

    # 0. Fast direct disk check: handles modern/ingested events instantly
    direct_name, direct_path = _find_event_file_direct(eventname)
    if direct_name:
        return direct_name, None

    alias_map = _alias_lookup_map()

    # 1. Fast O(1) alias check
    for cand in (
        eventname.lower(),
        oname.lower(),
        eventname.lower().replace(" ", ""),
        oname.lower().replace(" ", ""),
        eventname.lower().replace("sn", "at"),
        eventname.lower().replace("at", "sn"),
    ):
        if cand in alias_map:
            canon = alias_map[cand]
            for c in (canon, canon.replace("SN", "AT")):
                if _html_exists(c.replace("/", "_")):
                    return c, None
            return canon, None

    # 2. Regex pattern recognition for standard IAU transient designations (e.g. SN2023ixf, AT2024nrb)
    clean_test = eventname.upper().replace(" ", "")
    if re.match(r'^(SN|AT)?\d{4}[A-Z]{1,4}$', clean_test, re.IGNORECASE):
        if not clean_test.startswith(("SN", "AT")):
            clean_test = "SN" + clean_test
        return clean_test, oname

    # 3. Levenshtein fallback for typos (with length difference pruning for 60x speedup)
    target_len = len(eventname)
    if target_len >= 3:
        names, names_by = _names_maps()
        levs: dict[str, int] = {}
        for mapping in (names, names_by):
            for name, aliases in mapping.items():
                if not isinstance(aliases, list):
                    continue
                min_lev = 100
                for alias in aliases:
                    if not isinstance(alias, str):
                        continue
                    if abs(len(alias) - target_len) >= 3:
                        continue
                    try:
                        lev = _levenshtein(alias, eventname)
                    except Exception:
                        lev = 100
                    if lev < min_lev:
                        min_lev = lev
                        if lev <= 1:
                            return name, oname
                if min_lev < 3:
                    levs[name] = min_lev

        if levs and min(levs.values()) < 3:
            lev_name = min(levs, key=levs.get)
            return lev_name, oname
    return None, None


def _find_event_file(raw_name: str) -> tuple[str | None, Path | None]:
    """Locate the JSON file for an event or alias across all supernova era repositories."""
    direct_name, direct_path = _find_event_file_direct(raw_name)
    if direct_path:
        return direct_name, direct_path

    resolved, _ = _resolve_event(raw_name)
    if resolved:
        d_name, d_path = _find_event_file_direct(resolved)
        if d_path:
            return d_name, d_path
        # On-demand streaming from GitHub archives or live TNS / ALeRCE / WISeREP
        return _fetch_remote_event(resolved)

    norm = _normalize_event_name(raw_name)
    return _fetch_remote_event(norm)


@lru_cache(maxsize=1)
def _catalog_csv_bytes() -> bytes:
    csv_file = WWW / "astrocats/astrocats/supernovae/output/catalog.csv"
    if csv_file.is_file():
        return csv_file.read_bytes()
    cat_file = WWW / "astrocats/astrocats/supernovae/output/catalog.min.json"
    if not cat_file.is_file():
        return b""
    with open(cat_file, "r", encoding="utf-8") as f:
        cat = json.load(f)
    cols = ["name", "claimedtype", "discoverdate", "maxdate", "maxappmag", "ra", "dec", "discoverer"]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(cols)
    for row in cat:
        vals = []
        for c in cols:
            v = row.get(c, "")
            if isinstance(v, list) and v:
                v = v[0].get("value", "") if isinstance(v[0], dict) else str(v[0])
            elif isinstance(v, dict):
                v = v.get("value", "")
            vals.append(str(v))
        writer.writerow(vals)
    data = out.getvalue().encode("utf-8")
    try:
        csv_file.write_bytes(data)
    except Exception:
        pass
    return data


def _parse_coord_str(val: Any) -> float | None:
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


def _parse_ra(val: Any) -> float | None:
    deg = _parse_coord_str(val)
    if deg is not None and ":" in str(val) and deg < 24.0:
        deg *= 15.0
    return deg


def _parse_dec(val: Any) -> float | None:
    return _parse_coord_str(val)


def _photometry_to_csv(photo_list: list[dict], selected_cols: list[str] | None = None, event_name: str | None = None) -> bytes:
    cols = selected_cols if selected_cols else ["time", "magnitude", "e_magnitude", "band", "telescope", "instrument", "source"]
    out = io.StringIO()
    writer = csv.writer(out)
    if event_name:
        writer.writerow(["event"] + cols)
        for p in photo_list:
            writer.writerow([event_name] + [p.get(c, "") for c in cols])
    else:
        writer.writerow(cols)
        for p in photo_list:
            writer.writerow([p.get(c, "") for c in cols])
    return out.getvalue().encode("utf-8")


def _levenshtein(a: str, b: str) -> int:
    # Match PHP costs: insert=3, replace=1, delete=3 — approximate with std costs
    # PHP: levenshtein($alias, $eventname, 3, 1, 3) = ins, rep, del
    la, lb = len(a), len(b)
    if abs(la - lb) > 10:
        return 100
    prev = list(range(0, (lb + 1) * 3, 3))  # deletions
    for i, ca in enumerate(a, 1):
        cur = [i * 3]  # insertions
        for j, cb in enumerate(b, 1):
            ins = cur[j - 1] + 3
            delete = prev[j] + 3
            rep = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, rep))
        prev = cur
    return prev[-1]


def _find_event_json(name: str) -> Path | None:
    _, fp = _find_event_file(name)
    return fp


def _val(obj, key: str, default: str = "—") -> str:
    v = obj.get(key)
    if not v:
        return default
    if isinstance(v, list) and v:
        item = v[0]
        if isinstance(item, dict):
            return str(item.get("value", default))
        return str(item)
    if isinstance(v, dict):
        return str(v.get("value", default))
    return str(v)


def _fallback_event_page(name: str, entered: str | None = None) -> bytes:
    """Catalog metadata page when Bokeh HTML has not been generated yet."""
    path = _find_event_json(name)
    meta = {}
    aliases = []
    if path:
        try:
            raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            # Event JSON is { "Name": { ...fields } }
            if isinstance(raw, dict) and len(raw) == 1:
                meta = next(iter(raw.values()))
            elif isinstance(raw, dict):
                meta = raw.get(name) or raw
        except Exception:
            meta = {}
    if isinstance(meta.get("alias"), list):
        aliases = [
            a.get("value", a) if isinstance(a, dict) else a for a in meta["alias"]
        ]
    warn = ""
    if entered is not None:
        warn = (
            f'<p class="warn"><strong>Warning:</strong> Exact event name '
            f'"{urllib.parse.unquote(entered)}" not found, returning closest match.</p>'
        )
    photo_list = meta.get("photometry", [])
    photo_count = len(photo_list)
    if photo_count > 0:
        photo_display = f"{photo_count} observation{'s' if photo_count != 1 else ''}"
    else:
        photo_display = _val(meta, "photolink", "none")

    spec_list = meta.get("spectra", [])
    spec_count = len(spec_list)
    if spec_count > 0:
        spec_display = f"{spec_count} spectrum" if spec_count == 1 else f"{spec_count} spectra"
    else:
        spec_display = _val(meta, "spectralink", "none")

    sources_list = meta.get("sources", [])
    sources_links = []
    for s in sources_list:
        s_name = s.get("name") or s.get("bibcode") or s.get("alias") or "Source"
        s_url = s.get("url")
        if not s_url and s.get("bibcode"):
            s_url = f"https://ui.adsabs.harvard.edu/abs/{urllib.parse.quote(s['bibcode'])}"
        if s_url:
            sources_links.append(f'<a href="{s_url}" target="_blank" rel="noopener">{s_name}</a>')
        else:
            sources_links.append(str(s_name))
    sources_display = ", ".join(sources_links) if sources_links else "—"

    lumdist_str = _val(meta, "lumdist")
    if lumdist_str != "—" and not lumdist_str.endswith("Mpc"):
        lumdist_str += " Mpc"
    vel_str = _val(meta, "velocity")
    if vel_str != "—" and not vel_str.endswith("km/s"):
        vel_str += " km/s"
    ebv_str = _val(meta, "ebv")
    if ebv_str != "—" and not ebv_str.endswith("mag"):
        ebv_str += " mag"

    rows = [
        ("Name", name),
        ("Aliases", ", ".join(str(a) for a in aliases[:12]) or "—"),
        ("Discover date", _val(meta, "discoverdate")),
        ("Discoverer", _val(meta, "discoverer")),
        ("Max date", _val(meta, "maxdate")),
        ("Type", _val(meta, "claimedtype")),
        ("R.A.", _val(meta, "ra")),
        ("Dec.", _val(meta, "dec")),
        ("Redshift", _val(meta, "redshift")),
        ("Recession Velocity", vel_str),
        ("Luminosity Dist.", lumdist_str),
        ("Peak Apparent Mag", _val(meta, "maxappmag")),
        ("Peak Absolute Mag", _val(meta, "maxabsmag")),
        ("Galactic Extinction", ebv_str),
        ("Host", _val(meta, "host")),
        ("Photometry", photo_display),
        ("Spectra", spec_display),
        ("Sources", sources_display),
    ]
    trs = "".join(
        f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows
    )

    extra_sections = []
    if photo_count > 0:
        sample_photo = photo_list[:15]
        photo_rows = "".join(
            f"<tr><td>{p.get('time', '—')}</td><td>{p.get('magnitude', '—')}</td>"
            f"<td>{p.get('e_magnitude', '—')}</td><td>{p.get('band', '—')}</td>"
            f"<td>{p.get('telescope', p.get('instrument', '—'))}</td></tr>"
            for p in sample_photo
        )
        note_p = '<p class="note">Showing first 15 points. Full light curve in JSON.</p>' if photo_count > 15 else ""
        extra_sections.append(
            f'<section class="extra-block"><h2>Photometry ({photo_count} points)</h2>'
            f'<div class="tbl-wrap"><table class="sub-table"><thead><tr>'
            f'<th>Time (MJD)</th><th>Mag</th><th>± Err</th><th>Band</th><th>Telescope / Inst</th>'
            f'</tr></thead><tbody>{photo_rows}</tbody></table></div>'
            f'{note_p}'
            f'</section>'
        )

    if spec_count > 0:
        spec_rows = "".join(
            f"<tr><td>{s.get('time', '—')}</td><td>{s.get('telescope', '—')}</td>"
            f"<td>{s.get('instrument', '—')}</td><td>{len(s.get('data', []))} pts</td>"
            f"<td>{s.get('filename', '—')}</td></tr>"
            for s in spec_list
        )
        extra_sections.append(
            f'<section class="extra-block"><h2>Calibrated Spectra ({spec_count})</h2>'
            f'<div class="tbl-wrap"><table class="sub-table"><thead><tr>'
            f'<th>Time (MJD)</th><th>Telescope</th><th>Instrument</th><th>Resolution</th><th>Filename</th>'
            f'</tr></thead><tbody>{spec_rows}</tbody></table></div></section>'
        )

    sections_html = "".join(extra_sections)

    enrich_action = ""
    if enrich_event is not None:
        if photo_count <= 1 and spec_count == 0:
            enrich_action = f'<a class="btn-enrich" href="?enrich=1" style="background:#0969da;color:#fff;padding:0.35rem 0.75rem;border-radius:4px;text-decoration:none;font-weight:600">⚡ Enrich with ALeRCE &amp; WISeREP</a>'
        else:
            enrich_action = f'<a class="btn-re-enrich" href="?enrich=1" style="color:var(--muted);text-decoration:underline;font-size:0.9rem">Re-check ALeRCE/WISeREP</a>'

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} — Open Supernova Catalog</title>
<link rel="stylesheet" href="/assets/ia.css">
<style>
  .warn {{ color: #b36b00; }}
  table.meta {{ width: 100%; border-collapse: collapse; background: #fff; }}
  table.meta th, table.meta td {{ text-align: left; padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--line); vertical-align: top; }}
  table.meta th {{ width: 10rem; color: var(--muted); font-weight: 600; }}
  .actions {{ margin-top: 1.25rem; display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; }}
  .actions a {{ color: var(--accent); }}
  .extra-block {{ margin-top: 2rem; }}
  .extra-block h2 {{ font-size: 1.2rem; margin-bottom: 0.5rem; }}
  .tbl-wrap {{ overflow-x: auto; background: #fff; border: 1px solid var(--line); border-radius: 4px; }}
  table.sub-table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  table.sub-table th, table.sub-table td {{ text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--line); }}
  table.sub-table th {{ background: #f7f7f7; font-weight: 600; }}
</style></head><body>
<header class="site">
  <a class="brand" href="/" title="sne.space — The Open Supernova Catalog"><img src="/assets/img/logo-plain.webp" alt="sne.space" class="brand-logo-ia"><span>Open Supernova Catalog</span></a>
  <nav><a href="/">Catalog</a><a href="/download/">Download</a></nav>
</header>
<main>
  {warn}
  <h1>{name}</h1>
  <table class="meta">{trs}</table>
  {sections_html}
  <p class="actions">
    {enrich_action}
    <a href="/sne/{urllib.parse.quote(name)}.json">Download JSON</a>
    <a href="/{urllib.parse.quote(name)}/photometry?format=csv">Photometry CSV</a>
    <a href="/astrocats/astrocats/supernovae/output/json/{name.replace('/', '_')}.json">output/json</a>
  </p>
</main></body></html>"""
    return html.encode()


def _not_found_page(name: str) -> bytes:
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Transient '{name}' Not Found — sne.space</title>
  <style>
    :root {{ --bg: #070a12; --card: #0d1424; --border: #1e293b; --accent: #38bdf8; --text: #e2e8f0; }}
    body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 0; display: flex; flex-direction: column; min-height: 100vh; }}
    .site {{ background: #070a12; border-bottom: 1px solid var(--border); padding: 0.75rem 1.5rem; display: flex; align-items: center; justify-content: space-between; }}
    .brand-logo-ia {{ height: 32px; width: auto; vertical-align: middle; }}
    .site nav a {{ color: var(--accent); margin-left: 1rem; text-decoration: none; font-weight: 500; }}
    main.nf-wrap {{ max-width: 680px; margin: 4rem auto; padding: 2.5rem; background: var(--card); border: 1px solid var(--border); border-radius: 12px; text-align: center; box-shadow: 0 8px 32px rgba(0,0,0,0.4); }}
    h1 {{ color: #fff; margin-top: 0; font-size: 1.8rem; }}
    p {{ color: #94a3b8; line-height: 1.6; font-size: 1rem; margin-bottom: 1.5rem; }}
    .search-box {{ display: flex; gap: 0.5rem; margin-bottom: 2rem; }}
    .search-box input {{ flex: 1; background: #070a12; border: 1px solid var(--border); color: #fff; border-radius: 6px; padding: 0.6rem 0.9rem; font-size: 0.95rem; }}
    .search-box button {{ background: #0284c7; color: #fff; border: none; border-radius: 6px; padding: 0.6rem 1.2rem; font-weight: 600; cursor: pointer; }}
    .landmarks {{ display: flex; flex-wrap: wrap; gap: 0.5rem; justify-content: center; }}
    .landmarks a {{ padding: 0.35rem 0.75rem; background: rgba(56,189,248,0.1); border: 1px solid rgba(56,189,248,0.25); color: var(--accent); border-radius: 4px; text-decoration: none; font-size: 0.85rem; font-weight: 500; }}
    .btn-home {{ display: inline-block; margin-top: 1.5rem; color: #94a3b8; text-decoration: none; font-size: 0.9rem; }}
  </style>
</head>
<body>
  <header class="site">
    <a href="/" title="sne.space — The Open Supernova Catalog"><img src="/assets/img/logo-color.webp" alt="sne.space" class="brand-logo-ia"></a>
    <nav><a href="/">Catalog</a><a href="/radar">Radar</a><a href="/faq">FAQs</a><a href="/api/docs">API</a></nav>
  </header>
  <main class="nf-wrap">
    <div style="font-size:2.5rem;margin-bottom:0.75rem;">🔭</div>
    <h1>Transient '{name}' Not Found</h1>
    <p>This supernova or transient designation could not be located in the catalog archives or upstream astronomical brokers (TNS, ALeRCE, WISeREP).</p>
    <form class="search-box" action="/" method="GET"
          toolname="search_supernovae" 
          tool-name="search_supernovae" 
          tooldescription="Search 110,000+ supernovae and transients by IAU designation, name, or survey alias" 
          tool-description="Search 110,000+ supernovae and transients by IAU designation, name, or survey alias" 
          toolschema='{{"type":"object","properties":{{"q":{{"type":"string","description":"Supernova designation, IAU name, or survey alias"}}}},"required":["q"]}}' 
          tool-schema='{{"type":"object","properties":{{"q":{{"type":"string","description":"Supernova designation, IAU name, or survey alias"}}}},"required":["q"]}}' 
          toolautosubmit 
          tool-autosubmit 
          role="search"
          onsubmit="event.preventDefault(); var q=this.q.value.trim(); if(q) window.location.href='/sne/'+encodeURIComponent(q)+'/';">
      <input type="search" name="q" placeholder="Search 110,000+ supernovae..." 
             toolparamtitle="supernova_query" 
             tool-param-title="supernova_query" 
             toolparamdescription="Supernova IAU designation, catalog name, or survey alias" 
             tool-param-description="Supernova IAU designation, catalog name, or survey alias" 
             aria-label="Search supernovae" required>
      <button type="submit">Search</button>
    </form>
    <div style="font-size:0.8rem;color:#64748b;margin-bottom:0.75rem;text-transform:uppercase;letter-spacing:0.05em;font-weight:600;">Benchmark Supernovae</div>
    <div class="landmarks">
      <a href="/sne/SN2023ixf/">SN 2023ixf</a>
      <a href="/sne/SN1987A/">SN 1987A</a>
      <a href="/sne/SN2011fe/">SN 2011fe</a>
      <a href="/sne/SN2014J/">SN 2014J</a>
      <a href="/sne/SN2024nrb/">SN 2024nrb</a>
    </div>
    <div><a class="btn-home" href="/">← Return to Full Catalog</a></div>
  </main>
  <script src="/assets/webmcp.js"></script>
</body>
</html>"""
    return html.encode("utf-8")


_CATALOG_LOOKUP_LOCK = threading.Lock()
_CATALOG_LOOKUP: dict[str, dict] | None = None


def _get_catalog_entry(raw_name: str) -> dict | None:
    """Fast indexed lookup of summary metadata from catalog.min.json for all 110,000+ supernovae."""
    global _CATALOG_LOOKUP
    if _CATALOG_LOOKUP is None:
        with _CATALOG_LOOKUP_LOCK:
            if _CATALOG_LOOKUP is None:
                cat_file = WWW / "astrocats/astrocats/supernovae/output/catalog.min.json"
                cat_gz = WWW / "astrocats/astrocats/supernovae/output/catalog.min.json.gz"
                lookup = {}
                raw_data = None
                try:
                    if cat_file.is_file():
                        raw_data = cat_file.read_bytes()
                    elif cat_gz.is_file():
                        raw_data = gzip.decompress(cat_gz.read_bytes())
                    if raw_data:
                        items = json.loads(raw_data)
                        if isinstance(items, list):
                            for item in items:
                                nm = item.get("name")
                                if nm:
                                    lookup[nm.lower()] = item
                                    lookup[nm.lower().replace(" ", "")] = item
                                    for a in item.get("alias", []):
                                        aval = a.get("value") if isinstance(a, dict) else str(a)
                                        if aval:
                                            lookup[aval.lower()] = item
                                            lookup[aval.lower().replace(" ", "")] = item
                except Exception:
                    pass
                _CATALOG_LOOKUP = lookup
    target = _normalize_event_name(raw_name).lower()
    return _CATALOG_LOOKUP.get(target) or _CATALOG_LOOKUP.get(target.replace(" ", ""))


def _event_page(name: str, entered: str | None = None, is_story: bool = False, fp: Path | None = None) -> tuple[int, bytes]:
    fn = name.replace("/", "_")
    legacy_exists = _html_exists(fn)
    path = fp or _find_event_json(name)
    meta = {}
    if path and path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(raw, dict) and len(raw) == 1:
                meta = next(iter(raw.values()))
            elif isinstance(raw, dict):
                meta = raw.get(name) or raw
        except Exception:
            meta = {}
    if not meta or not (meta.get("ra") or meta.get("photometry") or meta.get("claimedtype") or meta.get("dec")):
        cat_meta = _get_catalog_entry(entered or name)
        if cat_meta:
            meta = cat_meta
        else:
            return 404, _not_found_page(entered or name)
    if is_story and render_story_mode is not None:
        return 200, render_story_mode(name, meta, entered).encode("utf-8")
    if render_pro_cockpit is not None:
        return 200, render_pro_cockpit(name, meta, entered, legacy_html_exists=legacy_exists).encode("utf-8")
    return 200, _fallback_event_page(name, entered)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WWW), **kwargs)

    def log_message(self, fmt, *args):
        # Clean structured logging is emitted in _send and _redirect
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        fmt = query.get("format", [""])[0].lower()

        # Real-time API Telemetry & Stats Dashboard: /api/stats, /api/telemetry
        if path in ("/api/stats", "/api/telemetry"):
            with _API_STATS_LOCK:
                summary = {
                    "service": "Open Supernova Catalog (sne.space)",
                    "started_at": _API_STATS["started_at"],
                    "uptime_seconds": round(time.time() - _START_TIME, 1),
                    "total_requests": _API_STATS["total_requests"],
                    "api_requests": _API_STATS["api_requests"],
                    "unique_visitors_count": len(_API_STATS["unique_ips"]),
                    "status_distribution": dict(_API_STATS["status_codes"]),
                    "top_supernova_targets": [{"target": k, "count": v} for k, v in _API_STATS["top_targets"].most_common(15)],
                    "top_user_agents": [{"user_agent": k, "count": v} for k, v in _API_STATS["top_user_agents"].most_common(15)],
                    "top_endpoints": [{"path": k, "count": v} for k, v in _API_STATS["top_paths"].most_common(15)],
                    "recent_requests": list(_API_STATS["recent_requests"])[:50]
                }
            self._send(200, "application/json; charset=utf-8", json.dumps(summary, indent=2).encode("utf-8"), {"Cache-Control": "no-cache"})
            return

        # Legacy OACAPI Badge Counter Endpoint: /api-count.php, /api/count
        if path in ("/api-count.php", "/api/count"):
            with _API_STATS_LOCK:
                resp = {
                    "count": _API_STATS["total_requests"],
                    "api_count": _API_STATS["api_requests"],
                    "unique": len(_API_STATS["unique_ips"]),
                    "top5": [k for k, _ in _API_STATS["top_targets"].most_common(5)]
                }
            self._send(200, "application/json; charset=utf-8", json.dumps(resp, indent=2).encode("utf-8"), {"Cache-Control": "no-cache"})
            return

        if path in ("/", "/index.php", "/index.html"):
            body = _php_render(WWW / "index.php")
            self._send(200, "text/html; charset=utf-8", body)
            return

        enrich_req = query.get("enrich", [""])[0].lower() in ("1", "true")

        # 0. On-demand Enrichment API endpoint: /api/{event}/enrich
        if path.startswith("/api/") and path.endswith("/enrich"):
            api_parts = [p for p in path.strip("/").split("/") if p]
            if len(api_parts) == 3 and api_parts[0] == "api" and api_parts[2] == "enrich":
                raw_event = api_parts[1]
                canon, _ = _resolve_event(raw_event)
                if canon and enrich_event is not None:
                    enrich_event(canon, force=True)
                    canon, fp = _find_event_file(canon)
                    if fp and fp.is_file():
                        data = fp.read_bytes()
                        self._send(200, "application/json; charset=utf-8", data)
                        return
                self._send(404, "application/json", b'{"error":"event could not be enriched"}')
                return

        # Sitemaps Engine (Google 50,000 URLs per file compliant)
        if path == "/sitemap.xml" or (path.startswith("/sitemap_") and path.endswith(".xml")):
            s_name = path.lstrip("/")
            if get_sitemap is not None:
                data = get_sitemap(s_name)
                if data:
                    self._send(200, "application/xml; charset=utf-8", data)
                    return
            self._send(404, "text/plain", b"Sitemap not found")
            return

        # Agentic Resource Discovery & AI Metadata Manifests
        if path == "/robots.txt":
            r_file = WWW / "robots.txt"
            if r_file.is_file():
                self._send(200, "text/plain; charset=utf-8", r_file.read_bytes())
                return
        if path == "/llms.txt":
            f_llms = WWW / "llms.txt"
            if f_llms.is_file():
                self._send(200, "text/markdown; charset=utf-8", f_llms.read_bytes(), {"Cache-Control": "public, max-age=3600"})
                return
        if path == "/llms-full.txt":
            f_full = WWW / "llms-full.txt"
            if f_full.is_file():
                self._send(200, "text/markdown; charset=utf-8", f_full.read_bytes(), {"Cache-Control": "public, max-age=3600"})
                return
        if path in ("/.well-known/ai-catalog.json", "/.well-known/ai-catalog"):
            f_cat = WWW / ".well-known/ai-catalog.json"
            if f_cat.is_file():
                self._send(200, "application/json; charset=utf-8", f_cat.read_bytes(), {"Cache-Control": "public, max-age=3600"})
                return
        if path in ("/.well-known/ard.json", "/.well-known/ard"):
            f_ard = WWW / ".well-known/ard.json"
            if f_ard.is_file():
                self._send(200, "application/json; charset=utf-8", f_ard.read_bytes(), {"Cache-Control": "public, max-age=3600"})
                return
        if path in ("/.well-known/agent-card.json", "/.well-known/agent-card"):
            f_ac = WWW / ".well-known/agent-card.json"
            if f_ac.is_file():
                self._send(200, "application/json; charset=utf-8", f_ac.read_bytes(), {"Cache-Control": "public, max-age=3600"})
                return
        if path in ("/.well-known/mcp/server-card.json", "/.well-known/mcp/server-card"):
            f_sc = WWW / ".well-known/mcp/server-card.json"
            if f_sc.is_file():
                self._send(200, "application/json; charset=utf-8", f_sc.read_bytes(), {"Cache-Control": "public, max-age=3600"})
                return

        # Master Frequently Asked Questions (FAQ) Hub: /faq, /faqs, /faq/
        if path in ("/faq", "/faqs", "/faq/"):
            if render_faq_page is not None:
                body = render_faq_page().encode("utf-8")
                self._send(200, "text/html; charset=utf-8", body)
                return

        # Developer & API Documentation Page: /api/docs, /docs, /api/docs/
        if path in ("/api/docs", "/docs", "/api/docs/", "/api-docs"):
            if render_api_docs_page is not None:
                body = render_api_docs_page().encode("utf-8")
                self._send(200, "text/html; charset=utf-8", body)
                return

        # Modern Deep Imagery Cutout API: /api/{event}/cutout, /api/cutout
        is_api_cutout = path == "/api/cutout" or (path.startswith("/api/") and path.endswith("/cutout"))
        if is_api_cutout:
            target_ra = None
            target_dec = None
            if path != "/api/cutout":
                # Extracted event name from /api/{event}/cutout
                ev_part = path.split("/")[2]
                c_name, fp = _find_event_file(ev_part)
                if fp and fp.is_file() and extract_coords is not None:
                    try:
                        ev_d = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
                        ev_m = next(iter(ev_d.values())) if len(ev_d) == 1 else ev_d.get(c_name, ev_d)
                        target_ra, target_dec, _, _ = extract_coords(ev_m)
                    except Exception:
                        pass
            if target_ra is None:
                try:
                    target_ra = float(query.get("ra", query.get("RA", [""]))[0])
                    target_dec = float(query.get("dec", query.get("DEC", [""]))[0])
                except (ValueError, IndexError):
                    pass

            if target_ra is not None and target_dec is not None:
                layer = query.get("layer", query.get("survey", ["optical"]))[0].lower()
                size = query.get("size", query.get("pixels", ["500"]))[0]
                fov = query.get("fov", ["0.1"])[0]

                if layer in ("desi", "dr10", "legacy"):
                    dest_url = f"https://www.legacysurvey.org/viewer/cutout.jpg?ra={target_ra:.6f}&dec={target_dec:.6f}&layer=ls-dr10&pixscale=0.262&size={size}"
                elif layer in ("panstarrs", "ps1"):
                    dest_url = f"https://alasky.cds.unistra.fr/hips-image-services/hips2fits?hips=P/PanSTARRS/DR1/color-z-zg-g&ra={target_ra:.6f}&dec={target_dec:.6f}&width={size}&height={size}&fov={fov}&format=jpg"
                elif layer in ("wise", "allwise", "ir"):
                    dest_url = f"https://alasky.cds.unistra.fr/hips-image-services/hips2fits?hips=P/allWISE/color&ra={target_ra:.6f}&dec={target_dec:.6f}&width={size}&height={size}&fov={fov}&format=jpg"
                elif layer in ("2mass", "nir"):
                    dest_url = f"https://alasky.cds.unistra.fr/hips-image-services/hips2fits?hips=P/2MASS/color&ra={target_ra:.6f}&dec={target_dec:.6f}&width={size}&height={size}&fov={fov}&format=jpg"
                elif layer in ("dss2", "dss", "archival"):
                    dest_url = f"https://alasky.cds.unistra.fr/hips-image-services/hips2fits?hips=P/DSS2/color&ra={target_ra:.6f}&dec={target_dec:.6f}&width={size}&height={size}&fov={fov}&format=jpg"
                else:
                    # Default optical: DESI Legacy DR10 or Pan-STARRS1 if Dec >= -30
                    if target_dec >= -30.0:
                        dest_url = f"https://alasky.cds.unistra.fr/hips-image-services/hips2fits?hips=P/PanSTARRS/DR1/color-z-zg-g&ra={target_ra:.6f}&dec={target_dec:.6f}&width={size}&height={size}&fov={fov}&format=jpg"
                    else:
                        dest_url = f"https://www.legacysurvey.org/viewer/cutout.jpg?ra={target_ra:.6f}&dec={target_dec:.6f}&layer=ls-dr10&pixscale=0.262&size={size}"

                self._redirect(302, dest_url)
                return
            else:
                self._send(400, "text/plain", b"Error: Missing valid coordinates (ra, dec) or recognized event name.")
                return

        # Sharded XML Sitemaps: /sitemap.xml, /sitemap_index.xml, /sitemap_*.xml
        if path.startswith("/sitemap") and path.endswith(".xml") and get_sitemap is not None:
            xml_bytes = get_sitemap(path)
            if xml_bytes:
                self._send(200, "application/xml; charset=utf-8", xml_bytes)
                return
            else:
                self._send(404, "application/xml; charset=utf-8", b'<?xml version="1.0" encoding="UTF-8"?><error>Sitemap shard not found</error>')
                return

        # Observers Radar & Real-Time Alerts: /radar, /tonight, /api/radar.json
        if path in ("/radar", "/tonight", "/radar/"):
            if render_radar_page is not None:
                obs = query.get("obs", ["keck"])[0]
                filter_mode = query.get("filter", ["rising"])[0]
                body = render_radar_page(obs_key=obs, filter_mode=filter_mode).encode("utf-8")
                self._send(200, "text/html; charset=utf-8", body)
                return

        if path in ("/api/radar.json", "/api/radar"):
            if scan_catalog_targets is not None and compute_observability_for_targets is not None:
                obs = query.get("obs", ["keck"])[0]
                targets = scan_catalog_targets()
                enriched = compute_observability_for_targets(targets, obs_key=obs)
                if fmt == "csv":
                    import io, csv
                    output = io.StringIO()
                    writer = csv.writer(output)
                    writer.writerow(["Name", "Type", "RA", "Dec", "Latest_Mag", "Band", "Trend", "Min_Airmass", "Observable_Hours"])
                    for t in enriched:
                        writer.writerow([t["name"], t["type"], t["ra_str"], t["dec_str"], t["latest_mag"], t["band"], t["trend"], t["min_airmass"], t["observable_hours"]])
                    self._send(200, "text/csv; charset=utf-8", output.getvalue().encode("utf-8"), {
                        "Content-Disposition": 'attachment; filename="radar_targets.csv"'
                    })
                    return
                body = json.dumps({"observatory": obs, "count": len(enriched), "targets": enriched}, indent=2).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", body)
                return

        # Supernova Search API: /api/search?q=...
        if path == "/api/search":
            q_val = query.get("q", query.get("query", [""]))[0].strip()
            if not q_val:
                self._send(400, "application/json; charset=utf-8", json.dumps({"error": "Missing required 'q' parameter"}).encode("utf-8"))
                return

            results = []
            canon, entered = _resolve_event(q_val)
            if canon:
                entry = _get_catalog_entry(canon) or {}
                results.append({
                    "name": canon,
                    "url": f"/sne/{urllib.parse.quote(canon)}/",
                    "json_url": f"/sne/{urllib.parse.quote(canon)}.json",
                    "exact": True,
                    "claimedtype": entry.get("claimedtype", {}).get("value") if isinstance(entry.get("claimedtype"), dict) else entry.get("claimedtype", "—"),
                    "ra": entry.get("ra", {}).get("value") if isinstance(entry.get("ra"), dict) else entry.get("ra", "—"),
                    "dec": entry.get("dec", {}).get("value") if isinstance(entry.get("dec"), dict) else entry.get("dec", "—"),
                    "discoverdate": entry.get("discoverdate", {}).get("value") if isinstance(entry.get("discoverdate"), dict) else entry.get("discoverdate", "—"),
                    "maxappmag": entry.get("maxappmag", {}).get("value") if isinstance(entry.get("maxappmag"), dict) else entry.get("maxappmag", "—"),
                })

            q_clean = q_val.lower().replace(" ", "").replace("-", "")
            alias_map = _alias_lookup_map()
            added = {canon} if canon else set()
            for alias_key, c_name in alias_map.items():
                if len(results) >= 25:
                    break
                if q_clean in alias_key and c_name not in added:
                    added.add(c_name)
                    entry = _get_catalog_entry(c_name) or {}
                    results.append({
                        "name": c_name,
                        "url": f"/sne/{urllib.parse.quote(c_name)}/",
                        "json_url": f"/sne/{urllib.parse.quote(c_name)}.json",
                        "exact": False,
                        "claimedtype": entry.get("claimedtype", {}).get("value") if isinstance(entry.get("claimedtype"), dict) else entry.get("claimedtype", "—"),
                        "ra": entry.get("ra", {}).get("value") if isinstance(entry.get("ra"), dict) else entry.get("ra", "—"),
                        "dec": entry.get("dec", {}).get("value") if isinstance(entry.get("dec"), dict) else entry.get("dec", "—"),
                        "discoverdate": entry.get("discoverdate", {}).get("value") if isinstance(entry.get("discoverdate"), dict) else entry.get("discoverdate", "—"),
                        "maxappmag": entry.get("maxappmag", {}).get("value") if isinstance(entry.get("maxappmag"), dict) else entry.get("maxappmag", "—"),
                    })

            resp = {
                "query": q_val,
                "count": len(results),
                "results": results
            }
            self._send(200, "application/json; charset=utf-8", json.dumps(resp, indent=2).encode("utf-8"))
            return

        # Recent Supernova Discoveries API: /api/recent, /api/recent-discoveries
        if path in ("/api/recent", "/api/recent-discoveries"):
            f_recent = WWW / "assets/recent-events.json"
            if f_recent.is_file():
                self._send(200, "application/json; charset=utf-8", f_recent.read_bytes(), {"Cache-Control": "public, max-age=300"})
                return
            elif get_radar_targets is not None:
                targets = get_radar_targets("keck")
                limit = int(query.get("limit", ["25"])[0])
                resp = {"count": min(len(targets), limit), "results": targets[:limit]}
                self._send(200, "application/json; charset=utf-8", json.dumps(resp, indent=2).encode("utf-8"))
                return

        # Classification Type Filter API: /api/by-type
        if path == "/api/by-type":
            target_type = query.get("type", [""])[0].strip().lower()
            limit = int(query.get("limit", ["25"])[0])
            _get_catalog_entry("SN2023ixf")  # Ensure _CATALOG_LOOKUP is loaded
            matches = []
            seen = set()
            if _CATALOG_LOOKUP:
                for name_k, meta in _CATALOG_LOOKUP.items():
                    if not isinstance(meta, dict):
                        continue
                    c_name = meta.get("name")
                    if not c_name or c_name in seen:
                        continue
                    ctype = meta.get("claimedtype", {})
                    ctype_val = str(ctype.get("value") or "").lower() if isinstance(ctype, dict) else str(ctype or "").lower()
                    if target_type in ctype_val:
                        seen.add(c_name)
                        matches.append({
                            "name": c_name,
                            "type": meta.get("claimedtype", {}).get("value") if isinstance(meta.get("claimedtype"), dict) else meta.get("claimedtype", "—"),
                            "ra": meta.get("ra", {}).get("value") if isinstance(meta.get("ra"), dict) else meta.get("ra", "—"),
                            "dec": meta.get("dec", {}).get("value") if isinstance(meta.get("dec"), dict) else meta.get("dec", "—"),
                            "maxappmag": meta.get("maxappmag", {}).get("value") if isinstance(meta.get("maxappmag"), dict) else meta.get("maxappmag", "—"),
                            "discoverdate": meta.get("discoverdate", {}).get("value") if isinstance(meta.get("discoverdate"), dict) else meta.get("discoverdate", "—"),
                            "url": f"/sne/{urllib.parse.quote(c_name)}/"
                        })
                        if len(matches) >= limit:
                            break
            resp = {
                "type": target_type,
                "count": len(matches),
                "results": matches
            }
            self._send(200, "application/json; charset=utf-8", json.dumps(resp, indent=2).encode("utf-8"))
            return

        # IVOA Simple Cone Search & Legacy OACAPI Catalog Cone Search: /api/cone, /cone, /catalog?ra=...
        has_cone_coords = ("ra" in query or "RA" in query) and ("dec" in query or "DEC" in query)
        is_cone_path = path in ("/api/cone", "/cone") or (has_cone_coords and path in ("/catalog", "/catalog.json", "/catalog.csv", "/catalog/sne", "/catalog/all", "/api/catalog"))
        if is_cone_path:
            if cone_search is not None:
                ra_raw = query.get("RA", query.get("ra", [""]))[0]
                dec_raw = query.get("DEC", query.get("dec", [""]))[0]
                ra_val = _parse_ra(ra_raw)
                dec_val = _parse_dec(dec_raw)
                if ra_val is None or dec_val is None:
                    self._send(400, "application/json; charset=utf-8", json.dumps({"error": f"Invalid RA or DEC coordinates: ra='{ra_raw}', dec='{dec_raw}'"}).encode("utf-8"))
                    return

                if "SR" in query or "sr" in query:
                    sr_val = float(query.get("SR", query.get("sr", ["0.1"]))[0])
                elif "radius_arcmin" in query:
                    sr_val = float(query.get("radius_arcmin")[0]) / 60.0
                elif "radius_arcsec" in query:
                    sr_val = float(query.get("radius_arcsec")[0]) / 3600.0
                elif "radius" in query:
                    # OACAPI specification: radius parameter is in arcseconds
                    r_val = float(query.get("radius")[0])
                    sr_val = r_val / 3600.0 if r_val > 0 else 0.1
                else:
                    sr_val = 0.1

                hits = cone_search(ra_val, dec_val, sr_val)
                req_fmt = query.get("format", ["votable" if path == "/cone" and "format" not in query else ("csv" if (path.endswith(".csv") or fmt == "csv") else "json")])[0].lower()
                if req_fmt in ("votable", "xml"):
                    body = format_votable(hits, ra_val, dec_val, sr_val).encode("utf-8")
                    self._send(200, "application/x-votable+xml; charset=utf-8", body)
                    return
                elif req_fmt in ("csv", "tsv"):
                    out_c = io.StringIO()
                    writer = csv.writer(out_c, delimiter=("\t" if req_fmt == "tsv" else ","))
                    writer.writerow(["name", "type", "ra", "dec", "separation_arcsec", "redshift", "maxappmag", "discoverdate", "host"])
                    for h in hits:
                        writer.writerow([h.get("name", ""), h.get("type", ""), h.get("ra", ""), h.get("dec", ""), h.get("separation_arcsec", ""), h.get("redshift", ""), h.get("maxappmag", ""), h.get("discoverdate", ""), h.get("host", "")])
                    self._send(200, f"text/{req_fmt}; charset=utf-8", out_c.getvalue().encode("utf-8"))
                    return
                else:
                    body = json.dumps({
                        "query": {"ra": ra_val, "dec": dec_val, "sr_deg": sr_val, "radius_arcsec": round(sr_val * 3600.0, 2)},
                        "count": len(hits),
                        "results": hits
                    }, indent=2).encode("utf-8")
                    self._send(200, "application/json; charset=utf-8", body)
                    return

        # 1. Global Catalog API endpoints (OACAPI compatible) and catalog.min.json static serve
        if path in ("/catalog", "/catalog.json", "/catalog.csv", "/catalog/sne", "/catalog/all", "/api/catalog", "/astrocats/astrocats/supernovae/output/catalog.min.json"):
            if fmt in ("csv", "tsv") or path.endswith(".csv"):
                data = _catalog_csv_bytes()
                self._send(200, "text/csv; charset=utf-8", data, {
                    "Content-Disposition": 'inline; filename="catalog.csv"'
                })
                return
            cat_file = WWW / "astrocats/astrocats/supernovae/output/catalog.min.json"
            live = _catalog_for_table()
            if live is not None:
                raw_body, gz_body = live
                accept_encoding = self.headers.get("Accept-Encoding", "")
                if "gzip" in accept_encoding:
                    self._send(200, "application/json; charset=utf-8", gz_body, {
                        "Content-Encoding": "gzip"
                    })
                else:
                    self._send(200, "application/json; charset=utf-8", raw_body)
                return
            if cat_file.is_file():
                accept_encoding = self.headers.get("Accept-Encoding", "")
                cat_gz = WWW / "astrocats/astrocats/supernovae/output/catalog.min.json.gz"
                if "gzip" in accept_encoding and cat_gz.is_file():
                    data = cat_gz.read_bytes()
                    self._send(200, "application/json; charset=utf-8", data, {
                        "Content-Encoding": "gzip"
                    })
                else:
                    data = cat_file.read_bytes()
                    self._send(200, "application/json; charset=utf-8", data)
                return
            self._send(404, "application/json", b'{"error":"catalog not found"}')
            return

        # 2. OACAPI Event Quantity Endpoints: /{event}/{quantity} or /api/{event}/{quantity}
        # e.g. /SN2023ixf/photometry, /SN2023ixf/spectra, /SN2023ixf/spectra/data, /SN2014J+SN2015F/photometry/magnitude+band
        parts = [p for p in path.strip("/").split("/") if p]
        if parts and parts[0] in ("api", "sne"):
            parts = parts[1:]

        known_quantities = {
            "photometry", "spectra", "sources", "alias", "redshift",
            "claimedtype", "ra", "dec", "discoverdate", "discoverer",
            "maxdate", "maxappmag", "maxabsmag", "lumdist", "host"
        }

        if len(parts) >= 2 and parts[1] in known_quantities:
            raw_event_str, quantity = parts[0], parts[1]
            sub_attr = parts[2] if len(parts) > 2 else None
            selected_cols = [c.strip() for c in sub_attr.split("+") if c.strip()] if (sub_attr and sub_attr != "data") else None

            raw_events = [e.strip() for e in raw_event_str.split("+") if e.strip()]
            combined_resp = {}
            combined_csv_rows = []

            for raw_event in raw_events:
                canon, fp = _find_event_file(raw_event)
                if fp and fp.is_file():
                    try:
                        ev_data = json.loads(fp.read_text(encoding="utf-8"))
                        ev_key = list(ev_data.keys())[0]
                        ev_obj = ev_data[ev_key]
                        q_data = ev_obj.get(quantity, [])

                        if selected_cols:
                            q_data = [{k: row[k] for k in selected_cols if k in row} for row in q_data]

                        combined_resp[canon or raw_event] = {quantity: q_data}

                        # Special case: spectra/data CSV
                        if quantity == "spectra" and sub_attr == "data":
                            for sp in q_data:
                                for row in sp.get("data", []):
                                    combined_csv_rows.append(",".join(map(str, row)))

                    except Exception:
                        pass

            if combined_resp:
                # Spectra data CSV
                if quantity == "spectra" and sub_attr == "data":
                    out_lines = ["wavelength,flux"] + combined_csv_rows
                    self._send(200, "text/csv; charset=utf-8", "\n".join(out_lines).encode("utf-8"))
                    return

                # Photometry CSV
                if quantity == "photometry" and (fmt in ("csv", "tsv") or path.endswith(".csv")):
                    out_csv = io.StringIO()
                    writer = csv.writer(out_csv)
                    cols = selected_cols if selected_cols else ["time", "magnitude", "e_magnitude", "band", "telescope", "instrument", "source"]
                    has_multi = len(combined_resp) > 1
                    header = (["event"] + cols) if has_multi else cols
                    writer.writerow(header)
                    for ev_k, ev_v in combined_resp.items():
                        for row in ev_v.get(quantity, []):
                            line = ([ev_k] if has_multi else []) + [row.get(c, "") for c in cols]
                            writer.writerow(line)
                    fn = f"{raw_event_str}_{quantity}.csv"
                    self._send(200, "text/csv; charset=utf-8", out_csv.getvalue().encode("utf-8"), {
                        "Content-Disposition": f'inline; filename="{fn}"'
                    })
                    return

                self._send(200, "application/json; charset=utf-8", json.dumps(combined_resp, indent=2).encode("utf-8"))
                return
            else:
                self._send(404, "application/json", json.dumps({"error": f"event(s) '{raw_event_str}' not found"}).encode())
                return

        # 3. Direct Event JSON download (e.g. /SN2023ixf.json, /sne/SN2023ixf.json, /api/SN2023ixf)
        is_json_req = path.endswith(".json") or (parts and len(parts) == 1 and path.startswith("/api/"))
        if is_json_req:
            raw = parts[0] if parts else ""
            if raw.endswith(".json"):
                raw = raw[:-5]
            if enrich_req and enrich_event is not None:
                c, _ = _resolve_event(raw)
                if c:
                    enrich_event(c, force=True)
            canon, fp = _find_event_file(raw)
            if fp and is_file_stale is not None and enrich_event is not None:
                if is_file_stale(fp):
                    # Stale-while-revalidate: spawn background thread to refresh active supernova
                    threading.Thread(target=enrich_event, args=(canon or raw,), kwargs={"force": False}, daemon=True).start()
            if fp and fp.is_file():
                data = fp.read_bytes()
                self._send(200, "application/json; charset=utf-8", data, {
                    "Content-Disposition": f'attachment; filename="{canon or raw}.json"'
                })
                return
            self._send(404, "application/json", b'{"error":"event not found"}')
            return

        # 4. Event HTML resolver (/sne/{name}, /event/{name})
        for prefix in ("/sne/", "/event/"):
            if path.startswith(prefix):
                raw = path[len(prefix) :].rstrip("/")
                if not raw:
                    break
                is_story = False
                if raw.endswith("/story") or raw.endswith("/mag"):
                    is_story = True
                    raw = re.sub(r"/(story|mag)$", "", raw)

                # Direct host cutout endpoint /sne/{event}/host.jpg
                if raw.endswith("/host.jpg") or raw.endswith("/host.png"):
                    base_ev = re.sub(r"/host\.(jpg|png)$", "", raw)
                    canon, fp = _find_event_file(base_ev)
                    if fp and fp.is_file() and extract_coords is not None:
                        try:
                            ev_d = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
                            ev_m = next(iter(ev_d.values())) if len(ev_d) == 1 else ev_d.get(canon, ev_d)
                            ra_d, dec_d, _, _ = extract_coords(ev_m)
                            if ra_d is not None and dec_d is not None:
                                tgt = f"https://www.legacysurvey.org/viewer/cutout.jpg?ra={ra_d:.6f}&dec={dec_d:.6f}&layer=ls-dr10&pixscale=0.262&size=500"
                                self._redirect(302, tgt)
                                return
                        except Exception:
                            pass
                    self._send(404, "text/plain", b"Host image coordinates not found")
                    return

                resolved, entered = _resolve_event(raw)
                if resolved and enrich_req and enrich_event is not None:
                    enrich_event(resolved, force=True)
                canon, fp = _find_event_file(raw)
                if fp and is_file_stale is not None and enrich_event is not None:
                    if is_file_stale(fp):
                        # Stale-while-revalidate: spawn background thread to refresh active supernova
                        threading.Thread(target=enrich_event, args=(resolved or canon or raw,), kwargs={"force": False}, daemon=True).start()
                if resolved:
                    if is_story and classify_event_tier is not None:
                        # Tier 3 Faint Data Record: redirect to canonical pro cockpit to protect index health
                        p_file = _find_event_json(resolved)
                        if p_file and p_file.is_file():
                            try:
                                r_raw = json.loads(p_file.read_text(encoding="utf-8", errors="replace"))
                                r_meta = next(iter(r_raw.values())) if len(r_raw) == 1 else r_raw.get(resolved, r_raw)
                                if classify_event_tier(resolved, r_meta) == 3:
                                    self._redirect(302, f"/sne/{urllib.parse.quote(resolved)}/")
                                    return
                            except Exception:
                                pass
                    code, body = _event_page(resolved, entered, is_story=is_story, fp=fp)
                    self._send(code, "text/html; charset=utf-8", body)
                else:
                    # Permissive fallback: render pro cockpit or story page directly for the requested event name
                    fallback_name = _normalize_event_name(raw)
                    code, body = _event_page(fallback_name, is_story=is_story, fp=fp)
                    self._send(code, "text/html; charset=utf-8", body)
                return

        # 5. Gzip HTML when .html empty/missing
        if path.startswith("/astrocats/") and path.endswith(".html"):
            html_path = WWW / path.lstrip("/")
            gz_path = Path(str(html_path) + ".gz")
            if (not html_path.is_file() or html_path.stat().st_size == 0) and gz_path.is_file():
                data = gz_path.read_bytes()
                self._send(200, "text/html; charset=utf-8", data, {
                    "Content-Encoding": "gzip"
                })
                return

        # 6. IA / static directory indexes (with or without trailing slash)
        rel = path.lstrip("/")
        candidate_dirs = [WWW / rel]
        for d in candidate_dirs:
            index = d / "index.html"
            if d.is_dir() and index.is_file():
                if not path.endswith("/"):
                    dest = path + "/"
                    if parsed.query:
                        dest += "?" + parsed.query
                    self._redirect(301, dest)
                    return
                data = index.read_bytes()
                self._send(200, "text/html; charset=utf-8", data)
                return

        # 7. Direct /{name} fallback resolver
        if "/" not in rel and rel:
            res, ent = _resolve_event(rel)
            if res:
                self._redirect(302, f"/sne/{rel}" + (f"?{parsed.query}" if parsed.query else ""))
                return

        static = (WWW / rel).resolve()
        try:
            static.relative_to(WWW.resolve())
        except ValueError:
            static = None
        if static is not None and static.is_file():
            ctype = mimetypes.guess_type(str(static))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "application/xml"):
                ctype += "; charset=utf-8"
            data = static.read_bytes()
            cache = "public, max-age=604800"
            if static.suffix in (".html", ".txt", ".xml"):
                cache = "public, max-age=300"
            self._send(200, ctype, data, {"Cache-Control": cache})
            return

        self._send(404, "text/plain; charset=utf-8", b"Not found\n")

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def finish(self):
        try:
            super().finish()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def handle_one_request(self):
        self._req_t0 = time.time()
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def _redirect(self, code: int, location: str):
        t0 = getattr(self, "_req_t0", None)
        dur_ms = (time.time() - t0) * 1000 if t0 else 0.0
        ip = (self.headers.get("X-Forwarded-For") or self.headers.get("X-Real-IP") or (self.client_address[0] if self.client_address else "127.0.0.1")).split(",")[0].strip()
        host = self.headers.get("Host") or "sne.space"
        ua = self.headers.get("User-Agent") or "-"
        cmd = getattr(self, "command", "GET")
        req_path = getattr(self, "path", "-")
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        is_api = host.startswith("api.") or req_path.startswith(("/api", "/sne/", "/catalog", "/cone")) or req_path.endswith((".json", ".csv"))
        tag = "[API]" if is_api else "[HTTP]"
        print(f"{tag} {now_str} | {code} | {dur_ms:>6.1f}ms | 0 B | {ip:<15} | {host} | {cmd} {req_path} -> {location} | UA: {ua}", flush=True)
        _record_api_stat(ip, host, req_path, cmd, code, 0, dur_ms, ua)
        try:
            self.send_response(code)
            self.send_header("Location", location)
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def _send(self, code: int, ctype: str, body: bytes, headers: dict | None = None):
        headers = dict(headers or {})
        accept = (self.headers.get("Accept-Encoding") or "").lower()
        compressible = (
            ctype.startswith("text/")
            or "javascript" in ctype
            or ctype.startswith("application/json")
            or ctype.startswith("application/xml")
            or "xml" in ctype
        )
        if compressible and "gzip" in accept and len(body) > 256 and "Content-Encoding" not in headers:
            body = gzip.compress(body, compresslevel=5)
            headers["Content-Encoding"] = "gzip"
            headers["Vary"] = "Accept-Encoding"
        if "Cache-Control" not in headers:
            if "text/html" in ctype:
                headers["Cache-Control"] = "public, max-age=120"

        t0 = getattr(self, "_req_t0", None)
        dur_ms = (time.time() - t0) * 1000 if t0 else 0.0
        ip = (self.headers.get("X-Forwarded-For") or self.headers.get("X-Real-IP") or (self.client_address[0] if self.client_address else "127.0.0.1")).split(",")[0].strip()
        host = self.headers.get("Host") or "sne.space"
        ua = self.headers.get("User-Agent") or "-"
        cmd = getattr(self, "command", "GET")
        req_path = getattr(self, "path", "-")
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        is_api = host.startswith("api.") or req_path.startswith(("/api", "/sne/", "/catalog", "/cone")) or req_path.endswith((".json", ".csv"))
        tag = "[API]" if is_api else "[HTTP]"
        print(f"{tag} {now_str} | {code} | {dur_ms:>6.1f}ms | {len(body):>7} B | {ip:<15} | {host} | {cmd} {req_path} | UA: {ua}", flush=True)
        _record_api_stat(ip, host, req_path, cmd, code, len(body), dur_ms, ua)

        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            if "text/html" in ctype:
                self.send_header("Link", '</.well-known/ai-catalog.json>; rel="ai-catalog"; type="application/json", </.well-known/ard.json>; rel="ard"; type="application/json", </llms.txt>; rel="describedby"')
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return


class ReusableThreadingServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def server_bind(self):
        import socket
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception:
                pass
        super().server_bind()

    def handle_error(self, request, client_address):
        exc_type, _, _ = sys.exc_info()
        if exc_type in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        super().handle_error(request, client_address)


_LIVE_CATALOG_LOCK = threading.Lock()
_LIVE_CATALOG: tuple[float, bytes, bytes] | None = None


def _catalog_for_table() -> tuple[bytes, bytes] | None:
    """March archive with post-March TNS rows prepended. Cached until that file changes."""
    global _LIVE_CATALOG
    base = WWW / "astrocats/astrocats/supernovae/output/catalog.min.json"
    base_gz = WWW / "astrocats/astrocats/supernovae/output/catalog.min.json.gz"
    recent = WWW / "assets/recent-catalog.min.json"
    if not base.is_file() and not base_gz.is_file():
        return None
    stamp = recent.stat().st_mtime if recent.is_file() else 0.0
    with _LIVE_CATALOG_LOCK:
        if _LIVE_CATALOG and _LIVE_CATALOG[0] == stamp:
            return _LIVE_CATALOG[1], _LIVE_CATALOG[2]
        raw = base.read_bytes() if base.is_file() else gzip.decompress(base_gz.read_bytes())
        raw = raw.lstrip()
        if recent.is_file() and raw.startswith(b"["):
            extra = recent.read_text(encoding="utf-8").strip()
            if extra.startswith("[") and extra.endswith("]") and len(extra) > 2:
                raw = b"[" + extra[1:-1].encode("utf-8") + b"," + raw[1:]
        packed = gzip.compress(raw, compresslevel=5)
        _LIVE_CATALOG = (stamp, raw, packed)
        return raw, packed


def _recent_tns_loop() -> None:
    """Refresh classified supernovae from the public TNS search on a fixed interval."""
    import time
    project = str(ROOT.parent)
    if project not in sys.path:
        sys.path.insert(0, project)
    while True:
        try:
            from ingest.pull_recent import pull_recent
            count = pull_recent()
            print(f"TNS recent pull stored {count} classified supernovae", flush=True)
        except Exception as exc:
            print(f"TNS recent pull failed: {exc}", flush=True)
        time.sleep(15 * 60)


def main():
    os.environ["OSC_DOCROOT"] = str(WWW)
    _ensure_catalog_files()
    # Warm names cache & spatial cone index
    _names_maps()
    if init_cone_index is not None:
        threading.Thread(target=init_cone_index, daemon=True).start()
    threading.Thread(target=_recent_tns_loop, name="tns-recent", daemon=True).start()
    httpd = ReusableThreadingServer((HOST, PORT), Handler)
    print(f"sne.space local server on http://{HOST}:{PORT}/", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
