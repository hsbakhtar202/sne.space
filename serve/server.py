#!/usr/bin/env python3
"""Threaded local sne.space server (S1.2 / S1.3).

Serves the historical path layout with concurrent static file I/O so the
27 MB catalog.min.json ajax load does not stall behind PHP's single thread.
Dynamic pages (/ and /sne|/event) are rendered via PHP CLI against www/.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import mimetypes
import os
import re
import subprocess
import threading
import urllib.parse
import urllib.request
from functools import lru_cache
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

    match = re.search(r'\b(19\d{2}|20\d{2})\b', clean)
    year = int(match.group(1)) if match else 2025
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

    dest_dir = output_dir / epoch
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{clean}.json"

    # 1. Try raw GitHub from historical archive repos
    repos_to_try = [
        epoch,
        "sne-2020-2024",
        "sne-2015-2019",
        "sne-2010-2014",
        "sne-2005-2009",
        "sne-2000-2004",
        "sne-1990-1999",
        "sne-pre-1990",
        "sne-boneyard",
    ]
    seen = set()
    repos_ordered = [r for r in repos_to_try if not (r in seen or seen.add(r))]

    for r in repos_ordered:
        for branch in ("master", "main"):
            for cand_name in (clean, clean.replace("SN", "AT"), clean.replace("AT", "SN")):
                url = f"https://raw.githubusercontent.com/astrocatalogs/{r}/{branch}/{cand_name}.json"
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "sne.space/1.0"})
                    with urllib.request.urlopen(req, timeout=4) as resp:
                        if resp.status == 200:
                            data = resp.read()
                            if data and len(data) > 10:
                                dest_file.write_bytes(data)
                                return clean, dest_file
                except Exception:
                    pass

    # 2. Try live ingest/enrichment from TNS / ALeRCE / WISeREP if modern
    if enrich_event is not None:
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

    # 3. Levenshtein fallback for typos
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
                try:
                    lev = _levenshtein(alias, eventname)
                except Exception:
                    lev = 100
                if lev < min_lev:
                    min_lev = lev
            levs[name] = min_lev

    if levs and min(levs.values()) < 4:
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


def _photometry_to_csv(photo_list: list[dict]) -> bytes:
    cols = ["time", "magnitude", "e_magnitude", "band", "telescope", "instrument", "source"]
    out = io.StringIO()
    writer = csv.writer(out)
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
  <a class="brand" href="/" title="sne.space — The Open Supernova Catalog"><img src="/assets/img/logo-plain.png" alt="sne.space" class="brand-logo-ia"><span>Open Supernova Catalog</span></a>
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


def _event_page(name: str, entered: str | None = None, is_story: bool = False) -> bytes:
    fn = name.replace("/", "_")
    legacy_exists = _html_exists(fn)
    path = _find_event_json(name)
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
    else:
        # If no JSON exists on disk or remotely, build fallback metadata from name
        meta = {"name": [{"value": name}]}
    if is_story and render_story_mode is not None:
        return render_story_mode(name, meta, entered).encode("utf-8")
    if render_pro_cockpit is not None:
        return render_pro_cockpit(name, meta, entered, legacy_html_exists=legacy_exists).encode("utf-8")
    return _fallback_event_page(name, entered)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WWW), **kwargs)

    def log_message(self, fmt, *args):
        # Quieter: only log errors / dynamic
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

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
        if path == "/.well-known/ai-catalog.json":
            f_cat = WWW / ".well-known/ai-catalog.json"
            if f_cat.is_file():
                self._send(200, "application/ai-catalog+json; charset=utf-8", f_cat.read_bytes())
                return
        if path == "/.well-known/ard.json":
            f_ard = WWW / ".well-known/ard.json"
            if f_ard.is_file():
                self._send(200, "application/json; charset=utf-8", f_ard.read_bytes())
                return
        if path == "/.well-known/mcp/server-card.json":
            f_sc = WWW / ".well-known/mcp/server-card.json"
            if f_sc.is_file():
                self._send(200, "application/json; charset=utf-8", f_sc.read_bytes())
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

                self.send_response(302)
                self.send_header("Location", dest_url)
                self.end_headers()
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

        # IVOA Simple Cone Search: /api/cone, /cone
        if path in ("/api/cone", "/cone"):
            if cone_search is not None:
                try:
                    ra_val = float(query.get("RA", query.get("ra", [""]))[0])
                    dec_val = float(query.get("DEC", query.get("dec", [""]))[0])
                    sr_val = float(query.get("SR", query.get("sr", ["0.1"]))[0])
                except (ValueError, IndexError):
                    self._send(400, "text/plain", b"Error: Missing or invalid RA, DEC, or SR parameters. Example: /api/cone?RA=210.77&DEC=54.27&SR=0.2")
                    return

                hits = cone_search(ra_val, dec_val, sr_val)
                req_fmt = query.get("format", ["votable" if "format" not in query else "json"])[0].lower()
                if req_fmt in ("votable", "xml"):
                    body = format_votable(hits, ra_val, dec_val, sr_val).encode("utf-8")
                    self._send(200, "application/x-votable+xml; charset=utf-8", body)
                    return
                else:
                    body = json.dumps({
                        "query": {"ra": ra_val, "dec": dec_val, "sr_deg": sr_val},
                        "count": len(hits),
                        "results": hits
                    }, indent=2).encode("utf-8")
                    self._send(200, "application/json; charset=utf-8", body)
                    return

        # 1. Global Catalog API endpoints (OACAPI compatible) and catalog.min.json static serve
        if path in ("/catalog", "/catalog.json", "/catalog.csv", "/api/catalog", "/astrocats/astrocats/supernovae/output/catalog.min.json"):
            if fmt in ("csv", "tsv") or path.endswith(".csv"):
                data = _catalog_csv_bytes()
                self._send(200, "text/csv; charset=utf-8", data, {
                    "Content-Disposition": 'inline; filename="catalog.csv"'
                })
                return
            cat_file = WWW / "astrocats/astrocats/supernovae/output/catalog.min.json"
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
        # e.g. /SN2023ixf/photometry, /SN2023ixf/spectra, /SN2023ixf/spectra/data
        parts = [p for p in path.strip("/").split("/") if p]
        if parts and parts[0] in ("api", "sne"):
            parts = parts[1:]

        known_quantities = {
            "photometry", "spectra", "sources", "alias", "redshift",
            "claimedtype", "ra", "dec", "discoverdate", "discoverer",
            "maxdate", "maxappmag", "maxabsmag", "lumdist", "host"
        }

        if len(parts) >= 2 and parts[1] in known_quantities:
            raw_event, quantity = parts[0], parts[1]
            sub_attr = parts[2] if len(parts) > 2 else None
            canon, fp = _find_event_file(raw_event)
            if fp and fp.is_file():
                try:
                    ev_data = json.loads(fp.read_text(encoding="utf-8"))
                    ev_key = list(ev_data.keys())[0]
                    ev_obj = ev_data[ev_key]
                    q_data = ev_obj.get(quantity, [])

                    # Special case: spectra/data CSV
                    if quantity == "spectra" and sub_attr == "data":
                        out_lines = ["wavelength,flux"]
                        for sp in q_data:
                            for row in sp.get("data", []):
                                out_lines.append(",".join(map(str, row)))
                        data_csv = "\n".join(out_lines).encode("utf-8")
                        self._send(200, "text/csv; charset=utf-8", data_csv)
                        return

                    # Photometry CSV
                    if quantity == "photometry" and (fmt in ("csv", "tsv") or path.endswith(".csv")):
                        csv_data = _photometry_to_csv(q_data)
                        self._send(200, "text/csv; charset=utf-8", csv_data, {
                            "Content-Disposition": f'inline; filename="{canon}_{quantity}.csv"'
                        })
                        return

                    resp = json.dumps({canon: {quantity: q_data}}, indent=2).encode("utf-8")
                    self._send(200, "application/json; charset=utf-8", resp)
                    return
                except Exception as e:
                    self._send(500, "application/json", json.dumps({"error": str(e)}).encode())
                    return
            else:
                self._send(404, "application/json", json.dumps({"error": f"event '{raw_event}' not found"}).encode())
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
                                self.send_response(302)
                                self.send_header("Location", tgt)
                                self.end_headers()
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
                                    self.send_response(302)
                                    self.send_header("Location", f"/sne/{urllib.parse.quote(resolved)}/")
                                    self.end_headers()
                                    return
                            except Exception:
                                pass
                    self._send(200, "text/html; charset=utf-8", _event_page(resolved, entered, is_story=is_story))
                else:
                    # Permissive fallback: render pro cockpit or story page directly for the requested event name
                    fallback_name = _normalize_event_name(raw)
                    self._send(200, "text/html; charset=utf-8", _event_page(fallback_name, is_story=is_story))
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
                    self.send_response(301)
                    self.send_header("Location", dest)
                    self.end_headers()
                    return
                data = index.read_bytes()
                self._send(200, "text/html; charset=utf-8", data)
                return

        # 7. Direct /{name} fallback resolver
        if "/" not in rel and rel:
            res, ent = _resolve_event(rel)
            if res:
                self.send_response(302)
                self.send_header("Location", f"/sne/{rel}" + (f"?{parsed.query}" if parsed.query else ""))
                self.end_headers()
                return

        return super().do_GET()

    def _send(self, code: int, ctype: str, body: bytes, headers: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        if "text/html" in ctype:
            self.send_header("Link", '</.well-known/ai-catalog.json>; rel="ai-catalog", </.well-known/ard.json>; rel="ard"')
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


class ReusableThreadingServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def server_bind(self):
        import socket
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception:
                pass
        super().server_bind()


def main():
    os.environ["OSC_DOCROOT"] = str(WWW)
    _ensure_catalog_files()
    # Warm names cache & spatial cone index
    _names_maps()
    if init_cone_index is not None:
        import threading
        threading.Thread(target=init_cone_index, daemon=True).start()
    httpd = ReusableThreadingServer((HOST, PORT), Handler)
    print(f"sne.space local server on http://{HOST}:{PORT}/", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
