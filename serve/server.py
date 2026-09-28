#!/usr/bin/env python3
"""Threaded local sne.space server (S1.2 / S1.3).

Serves the historical path layout with concurrent static file I/O so the
27 MB catalog.min.json ajax load does not stall behind PHP's single thread.
Dynamic pages (/ and /sne|/event) are rendered via PHP CLI against www/.
"""
from __future__ import annotations

import base64
import csv
import collections
import datetime
from functools import lru_cache
import gzip
import hashlib
import html
import io
import json
import math
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

import sys
_SERVE_DIR_PARENT = Path(__file__).resolve().parent
if str(_SERVE_DIR_PARENT) not in sys.path:
    sys.path.insert(0, str(_SERVE_DIR_PARENT))
if str(_SERVE_DIR_PARENT.parent) not in sys.path:
    sys.path.insert(0, str(_SERVE_DIR_PARENT.parent))

try:
    from agent_relay import (
        MCP_TOOLS,
        get_agent_feedback_list,
        get_mcp_telemetry_summary,
        get_supernova_forum,
        load_feedback_records,
        load_forum_records,
        post_agent_feedback,
        post_supernova_comment,
        record_mcp_invocation,
        search_supernova_forums,
    )
except Exception:
    try:
        from serve.agent_relay import (
            MCP_TOOLS,
            get_agent_feedback_list,
            get_mcp_telemetry_summary,
            get_supernova_forum,
            load_feedback_records,
            load_forum_records,
            post_agent_feedback,
            post_supernova_comment,
            record_mcp_invocation,
            search_supernova_forums,
        )
    except Exception as e:
        print(f"[SERVER] Error importing agent_relay: {e}", flush=True)
        MCP_TOOLS = []
        get_agent_feedback_list = None
        get_mcp_telemetry_summary = None
        get_supernova_forum = None
        load_feedback_records = None
        load_forum_records = None
        post_agent_feedback = None
        post_supernova_comment = None
        record_mcp_invocation = None
        search_supernova_forums = None

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
    "human_requests": 0,
    "bot_requests": 0,
    "api_requests": 0,
    "unique_ips": set(),
    "ip_stats": {},  # ip -> dict of per-ip metrics
    "top_targets": collections.Counter(),
    "top_user_agents": collections.Counter(),
    "top_clients": collections.Counter(),
    "top_paths": collections.Counter(),
    "top_referrers": collections.Counter(),
    "top_countries": collections.Counter(),
    "status_codes": collections.Counter(),
    "recent_requests": collections.deque(maxlen=300),
    "recent_human_requests": collections.deque(maxlen=100),
    "recent_api_requests": collections.deque(maxlen=100),
}

LOGS_DIR = ROOT / "logs"
LOG_FILE = LOGS_DIR / "access.log"
_LOG_LOCK = threading.Lock()


def _classify_client(ua: str) -> dict:
    ua_raw = ua or ""
    ua_lower = ua_raw.lower()
    
    # 1. AI Agents & Crawlers
    if "gptbot" in ua_lower or "chatgpt" in ua_lower or "oai-searchbot" in ua_lower or "openai" in ua_lower:
        return {"type": "AI Agent", "client": "OpenAI / GPTBot", "is_bot": True, "icon": "🤖"}
    if "claude" in ua_lower or "anthropic" in ua_lower:
        return {"type": "AI Agent", "client": "Anthropic / Claude", "is_bot": True, "icon": "🧠"}
    if "cursor" in ua_lower:
        return {"type": "AI Agent", "client": "Cursor Agent", "is_bot": True, "icon": "⚡"}
    if "deepseek" in ua_lower:
        return {"type": "AI Agent", "client": "DeepSeek AI", "is_bot": True, "icon": "🐋"}
    if "webmcp" in ua_lower or "mcp" in ua_lower:
        return {"type": "AI Agent", "client": "WebMCP Agent", "is_bot": True, "icon": "🤖"}
    if "perplexity" in ua_lower:
        return {"type": "AI Agent", "client": "Perplexity AI", "is_bot": True, "icon": "🔮"}
    if "google-extended" in ua_lower or "gemini" in ua_lower:
        return {"type": "AI Agent", "client": "Google / Gemini", "is_bot": True, "icon": "🤖"}
    if "agent" in ua_lower or "llm" in ua_lower:
        return {"type": "AI Agent", "client": "AI Agent", "is_bot": True, "icon": "🤖"}
    if "googlebot" in ua_lower or "googleother" in ua_lower:
        return {"type": "Search Crawler", "client": "Googlebot", "is_bot": True, "icon": "🔍"}
    if "bingbot" in ua_lower:
        return {"type": "Search Crawler", "client": "Bingbot", "is_bot": True, "icon": "🔎"}
    if "applebot" in ua_lower:
        return {"type": "AI / Crawler", "client": "Applebot", "is_bot": True, "icon": "🍏"}
    if "meta-externalagent" in ua_lower or "facebookbot" in ua_lower:
        return {"type": "AI Agent", "client": "Meta External Agent", "is_bot": True, "icon": "🌐"}
    if any(b in ua_lower for b in ("bot", "spider", "crawl", "slurp", "headless")):
        return {"type": "Web Bot", "client": "Web Crawler", "is_bot": True, "icon": "🕷️"}

    # 2. Astrophysics tools & CLI
    if "astroquery" in ua_lower or "astropy" in ua_lower:
        return {"type": "Astro Library", "client": "Astropy / Astroquery", "is_bot": True, "icon": "🔭"}
    if "python" in ua_lower or "urllib" in ua_lower or "requests" in ua_lower or "httpx" in ua_lower:
        return {"type": "Script", "client": "Python Script", "is_bot": True, "icon": "🐍"}
    if "curl" in ua_lower:
        return {"type": "CLI", "client": "curl", "is_bot": True, "icon": "💻"}
    if "wget" in ua_lower:
        return {"type": "CLI", "client": "wget", "is_bot": True, "icon": "📥"}

    # 3. Human Browsers
    os_name = "Desktop"
    if "iphone" in ua_lower:
        os_name = "iPhone"
    elif "ipad" in ua_lower:
        os_name = "iPad"
    elif "android" in ua_lower:
        os_name = "Android"
    elif "macintosh" in ua_lower or "mac os x" in ua_lower:
        os_name = "Mac"
    elif "windows" in ua_lower:
        os_name = "Windows"
    elif "linux" in ua_lower:
        os_name = "Linux"

    browser = "Browser"
    if "edg/" in ua_lower:
        browser = "Edge"
    elif "chrome/" in ua_lower or "crios/" in ua_lower:
        browser = "Chrome"
    elif "safari/" in ua_lower and not ("chrome" in ua_lower or "crios" in ua_lower):
        browser = "Safari"
    elif "firefox/" in ua_lower or "fxios/" in ua_lower:
        browser = "Firefox"

    is_mobile = os_name in ("iPhone", "iPad", "Android")
    cat = f"Human ({'Mobile' if is_mobile else 'Desktop'})"
    label = f"{browser} ({os_name})"
    icon = "📱" if is_mobile else "🖥️"
    return {"type": cat, "client": label, "is_bot": False, "icon": icon}


def _write_access_log(ip: str, country: str, host: str, method: str, path: str, code: int, size: int, dur_ms: float, ua: str, referer: str, client_info: dict):
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with _LOG_LOCK:
            # 15MB rotation limit
            if LOG_FILE.is_file() and LOG_FILE.stat().st_size > 15 * 1024 * 1024:
                old_file = LOGS_DIR / "access.log.1"
                if old_file.exists():
                    old_file.unlink(missing_ok=True)
                LOG_FILE.rename(old_file)
            now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            c_tag = f" ({country})" if country else ""
            c_icon = client_info.get("icon", "")
            c_name = client_info.get("client", "Unknown")
            c_type = client_info.get("type", "")
            ref_str = f' - Ref: "{referer}"' if referer and referer != "-" else ""
            line = f'[{now_iso}] {code} {method} "{path}" ({dur_ms:.1f}ms, {size}B) - IP: {ip}{c_tag} - Client: {c_icon} {c_name} [{c_type}]{ref_str} - Host: {host} - UA: "{ua}"\n'
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception as e:
        print(f"[LOG ERROR] {e}", flush=True)


def _record_api_stat(ip: str, country: str, host: str, path: str, method: str, code: int, size: int, dur_ms: float, ua: str, referer: str, client_info: dict):
    clean_path = path.split("?")[0]
    # Do not record background dashboard telemetry polling loops into access log or recent requests feed
    if clean_path in ("/api/stats", "/api/telemetry", "/api/mcp/activity"):
        return

    _write_access_log(ip, country, host, method, path, code, size, dur_ms, ua, referer, client_info)
    with _API_STATS_LOCK:
        _API_STATS["total_requests"] += 1
        _API_STATS["unique_ips"].add(ip)
        _API_STATS["status_codes"][str(code)] += 1
        _API_STATS["top_paths"][clean_path] += 1

        if country:
            _API_STATS["top_countries"][country] += 1
        if referer and referer != "-":
            ref_parsed = urllib.parse.urlparse(referer).netloc or referer[:40]
            _API_STATS["top_referrers"][ref_parsed] += 1

        is_bot = client_info.get("is_bot", False)
        if is_bot:
            _API_STATS["bot_requests"] += 1
        else:
            _API_STATS["human_requests"] += 1

        client_name = client_info.get("client", "Unknown")
        client_type = client_info.get("type", "Unknown")
        client_icon = client_info.get("icon", "🌐")
        _API_STATS["top_clients"][f"{client_icon} {client_name}"] += 1

        now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if ip not in _API_STATS["ip_stats"]:
            _API_STATS["ip_stats"][ip] = {
                "ip": ip,
                "country": country,
                "client": client_name,
                "client_type": client_type,
                "icon": client_icon,
                "count": 0,
                "first_seen": now_ts,
                "last_seen": now_ts,
                "last_path": path,
                "last_status": code,
                "is_bot": is_bot,
                "user_agent": ua,
            }
        ip_entry = _API_STATS["ip_stats"][ip]
        ip_entry["count"] += 1
        ip_entry["last_seen"] = now_ts
        ip_entry["last_path"] = path
        ip_entry["last_status"] = code
        if not ip_entry["country"] and country:
            ip_entry["country"] = country

        is_api = host.startswith("api.") or clean_path.startswith(("/api", "/cone", "/catalog", "/sne/")) or clean_path.endswith((".json", ".csv"))
        if is_api:
            _API_STATS["api_requests"] += 1
            ua_clean = ua if ua else "unknown"
            _API_STATS["top_user_agents"][ua_clean] += 1

            m = re.match(r"^/(?:api/|sne/)?([A-Za-z0-9+_-]+)(?:\.[a-z]+|/[a-z]+)?$", clean_path)
            if m:
                target_cand = m.group(1).upper()
                if target_cand not in ("API", "CATALOG", "CONE", "RADAR", "RECENT", "SEARCH", "BY-TYPE", "DOCS", "FAQS", "SITEMAP", "STATS", "TELEMETRY", "COUNT", "LOGS"):
                    _API_STATS["top_targets"][target_cand] += 1

        req_record = {
            "timestamp": now_ts,
            "ip": ip,
            "country": country,
            "host": host,
            "method": method,
            "path": path,
            "status": code,
            "bytes": size,
            "duration_ms": round(dur_ms, 1),
            "client": client_name,
            "client_type": client_type,
            "icon": client_icon,
            "is_bot": is_bot,
            "referer": referer if referer != "-" else "",
            "user_agent": ua,
        }

        _API_STATS["recent_requests"].appendleft(req_record)
        if not is_bot:
            _API_STATS["recent_human_requests"].appendleft(req_record)
        if is_api:
            _API_STATS["recent_api_requests"].appendleft(req_record)


def _load_historical_access_log():
    """Hydrate in-memory _API_STATS from access.log on startup so restarts preserve metrics."""
    if not LOG_FILE.is_file():
        return
    pattern = re.compile(
        r'^\[(.*?)\]\s+(\d+)\s+([A-Z]+)\s+\"(.*?)\"\s+\(([\d\.]+)ms,\s*(\d+)B\)\s+-\s+IP:\s+([^\s]+)(?:\s+\((.*?)\))?.*?- Host:\s+([^\s]+)\s+-\s+UA:\s+\"(.*?)\"'
    )
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for line in lines[-500:]:
            m = pattern.match(line.strip())
            if not m:
                continue
            ts, code_s, method, path, dur_s, size_s, ip, country, host, ua = m.groups()
            code = int(code_s)
            dur_ms = float(dur_s)
            size = int(size_s)
            country = country or ""
            client_info = _classify_client(ua)

            clean_path = path.split("?")[0]
            if clean_path in ("/api/stats", "/api/telemetry", "/api/mcp/activity"):
                continue

            with _API_STATS_LOCK:
                _API_STATS["total_requests"] += 1
                _API_STATS["unique_ips"].add(ip)
                _API_STATS["status_codes"][str(code)] += 1
                clean_path = path.split("?")[0]
                _API_STATS["top_paths"][clean_path] += 1
                if country:
                    _API_STATS["top_countries"][country] += 1

                is_bot = client_info.get("is_bot", False)
                if is_bot:
                    _API_STATS["bot_requests"] += 1
                else:
                    _API_STATS["human_requests"] += 1

                client_name = client_info.get("client", "Unknown")
                client_type = client_info.get("type", "Unknown")
                client_icon = client_info.get("icon", "🌐")
                _API_STATS["top_clients"][f"{client_icon} {client_name}"] += 1

                if ip not in _API_STATS["ip_stats"]:
                    _API_STATS["ip_stats"][ip] = {
                        "ip": ip,
                        "country": country,
                        "client": client_name,
                        "client_type": client_type,
                        "icon": client_icon,
                        "count": 0,
                        "first_seen": ts,
                        "last_seen": ts,
                        "last_path": path,
                        "last_status": code,
                        "is_bot": is_bot,
                        "user_agent": ua,
                    }
                ip_entry = _API_STATS["ip_stats"][ip]
                ip_entry["count"] += 1
                ip_entry["last_seen"] = ts
                ip_entry["last_path"] = path
                ip_entry["last_status"] = code
                if not ip_entry["country"] and country:
                    ip_entry["country"] = country

                is_api = (
                    host.startswith("api.")
                    or clean_path.startswith(("/api", "/cone", "/catalog", "/sne/"))
                    or clean_path.endswith((".json", ".csv"))
                )
                if is_api:
                    _API_STATS["api_requests"] += 1
                    ua_clean = ua if ua else "unknown"
                    _API_STATS["top_user_agents"][ua_clean] += 1

                    tm = re.match(r"^/(?:api/|sne/)?([A-Za-z0-9+_-]+)(?:\.[a-z]+|/[a-z]+)?$", clean_path)
                    if tm:
                        target_cand = tm.group(1).upper()
                        if len(target_cand) >= 3 and not target_cand.startswith(
                            ("LOGS", "API", "STATS", "WELL-KNOWN", "MANIFEST", "CONE", "CATALOG")
                        ):
                            _API_STATS["top_targets"][target_cand] += 1

                req_record = {
                    "timestamp": ts,
                    "ip": ip,
                    "country": country,
                    "method": method,
                    "path": path,
                    "status": code,
                    "bytes": size,
                    "duration_ms": round(dur_ms, 1),
                    "client": client_name,
                    "client_type": client_type,
                    "icon": client_icon,
                    "is_bot": is_bot,
                    "referer": "",
                    "user_agent": ua,
                }
                _API_STATS["recent_requests"].appendleft(req_record)
                if not is_bot:
                    _API_STATS["recent_human_requests"].appendleft(req_record)
                if is_api:
                    _API_STATS["recent_api_requests"].appendleft(req_record)
    except Exception as exc:
        print(f"[ACCESS LOG] Historical load error: {exc}", flush=True)


_load_historical_access_log()


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
<html lang="en"><head>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-P1SCVZ0V7T"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());

  gtag('config', 'G-P1SCVZ0V7T');
</script>
<meta charset="utf-8">
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
  <!-- Google tag (gtag.js) -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-P1SCVZ0V7T"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());

    gtag('config', 'G-P1SCVZ0V7T');
  </script>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Transient '{name}' Not Found — sne.space</title>
  <link rel="ai-catalog" href="/.well-known/ai-catalog.json" type="application/json">
  <link rel="ard" href="/.well-known/ard.json" type="application/json">
  <link rel="webmcp-manifest" href="/.well-known/webmcp" type="application/json">
  <link rel="mcp-manifest" href="/.well-known/mcp.json" type="application/json">
  <link rel="describedby" href="/llms.txt" type="text/markdown">
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
          toolaction="submit"
          tool-action="submit"
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
    <form class="webmcp-declarative-tool" action="/api/event" method="GET"
          toolname="get_supernova_data"
          tool-name="get_supernova_data"
          toolaction="submit"
          tool-action="submit"
          tooldescription="Retrieve complete astrophysical JSON metadata, coordinates, classification, redshift, discovery details, and photometry for a specific supernova"
          tool-description="Retrieve complete astrophysical JSON metadata, coordinates, classification, redshift, discovery details, and photometry for a specific supernova"
          toolschema='{{"type":"object","properties":{{"name":{{"type":"string","description":"Supernova designation or IAU name (e.g. SN 2023ixf, SN 1987A, SN 2011fe)"}}}},"required":["name"]}}'
          tool-schema='{{"type":"object","properties":{{"name":{{"type":"string","description":"Supernova designation or IAU name (e.g. SN 2023ixf, SN 1987A, SN 2011fe)"}}}},"required":["name"]}}'
          toolautosubmit
          tool-autosubmit
          style="display:none;" aria-hidden="true">
      <input type="text" name="name" toolparamtitle="supernova_name" tool-param-title="supernova_name" toolparamdescription="Supernova name or IAU designation" tool-param-description="Supernova name or IAU designation" required>
      <button type="submit">Get Dossier</button>
    </form>
    <form class="webmcp-declarative-tool" action="/api/cone" method="GET"
          toolname="cone_search"
          tool-name="cone_search"
          toolaction="submit"
          tool-action="submit"
          tooldescription="Spatial cone search for supernovae within an angular radius around celestial coordinates (Right Ascension & Declination in degrees)"
          tool-description="Spatial cone search for supernovae within an angular radius around celestial coordinates (Right Ascension & Declination in degrees)"
          toolschema='{{"type":"object","properties":{{"ra":{{"type":"number","description":"Right Ascension in decimal degrees (0 to 360)"}},"dec":{{"type":"number","description":"Declination in decimal degrees (-90 to +90)"}},"radius_arcmin":{{"type":"number","description":"Search radius in arcminutes (default: 5.0)"}}}},"required":["ra","dec"]}}'
          tool-schema='{{"type":"object","properties":{{"ra":{{"type":"number","description":"Right Ascension in decimal degrees (0 to 360)"}},"dec":{{"type":"number","description":"Declination in decimal degrees (-90 to +90)"}},"radius_arcmin":{{"type":"number","description":"Search radius in arcminutes (default: 5.0)"}}}},"required":["ra","dec"]}}'
          toolautosubmit
          tool-autosubmit
          style="display:none;" aria-hidden="true">
      <input type="number" step="any" name="ra" toolparamtitle="ra" tool-param-title="ra" toolparamdescription="Right Ascension in decimal degrees" tool-param-description="Right Ascension in decimal degrees" required>
      <input type="number" step="any" name="dec" toolparamtitle="dec" tool-param-title="dec" toolparamdescription="Declination in decimal degrees" tool-param-description="Declination in decimal degrees" required>
      <input type="number" step="any" name="radius_arcmin" value="5.0" toolparamtitle="radius_arcmin" tool-param-title="radius_arcmin" toolparamdescription="Search radius in arcminutes" tool-param-description="Search radius in arcminutes">
      <button type="submit">Cone Search</button>
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


def _execute_mcp_tool_by_name(tool_name: str, args: dict, client_meta: dict) -> dict:
    t0 = time.time()
    res = {}
    err_str = ""
    agent_id = args.get("agent_name") or client_meta.get("client_info", {}).get("client", "AI Agent")
    ip = client_meta.get("ip", "127.0.0.1")
    country = client_meta.get("country", "")

    try:
        if tool_name == "search_supernova_forums":
            if search_supernova_forums:
                res = search_supernova_forums(
                    query=args.get("query", args.get("q", "")),
                    sort_by=args.get("sort_by", args.get("sort", "most_comments")),
                    agent_name=args.get("agent_name", args.get("user", "")),
                    min_comments=int(args.get("min_comments", 0)),
                    limit=int(args.get("limit", 25)),
                )
            else:
                res = {"status": "error", "message": "agent_relay module unavailable"}

        elif tool_name == "get_supernova_forum":
            if get_supernova_forum:
                res = get_supernova_forum(
                    target_event=args.get("target_event", args.get("event", args.get("name", ""))),
                    agent_name=args.get("agent_name", ""),
                    limit=int(args.get("limit", 50)),
                )
            else:
                res = {"status": "error", "message": "agent_relay module unavailable"}

        elif tool_name == "agent_feedback":
            if post_agent_feedback:
                res = post_agent_feedback(
                    agent_name=args.get("agent_name", ""),
                    like=args.get("like", True),
                    comment=args.get("comment", ""),
                    target_event=args.get("target_event", ""),
                    tags=args.get("tags"),
                    ip=ip,
                    country=country,
                    user_agent=client_meta.get("ua", ""),
                )
            else:
                res = {"status": "error", "message": "agent_relay module unavailable"}

        elif tool_name == "get_agent_comments":
            if get_agent_feedback_list:
                res = get_agent_feedback_list(
                    agent_name=args.get("agent_name", ""),
                    target_event=args.get("target_event", ""),
                    limit=int(args.get("limit", 20)),
                )
            else:
                res = {"status": "error", "message": "agent_relay module unavailable"}

        elif tool_name == "search_supernovae":
            q = str(args.get("query", args.get("q", ""))).strip()
            limit = int(args.get("limit", 10))
            canon_map, alias_map = _names_maps()
            q_clean = re.sub(r"[^a-zA-Z0-9]", "", q).lower()
            matches = []
            for c_name, c_lower in canon_map.items():
                if q_clean == c_lower:
                    matches.append({"name": c_name, "match_type": "canonical_exact"})
                    break
            for a_clean, c_name in alias_map.items():
                if q_clean == a_clean and not any(m["name"] == c_name for m in matches):
                    matches.append({"name": c_name, "matched_alias": a_clean, "match_type": "alias_exact"})
            if len(matches) < limit:
                for c_name, c_lower in canon_map.items():
                    if q_clean in c_lower and not any(m["name"] == c_name for m in matches):
                        matches.append({"name": c_name, "match_type": "substring"})
                        if len(matches) >= limit:
                            break
            res_items = []
            for m in matches[:limit]:
                c_name = m["name"]
                _, fp = _find_event_file(c_name)
                summary = {"name": c_name, "match_type": m.get("match_type")}
                if fp and fp.is_file():
                    try:
                        raw = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
                        ev_data = next(iter(raw.values())) if len(raw) == 1 else raw.get(c_name, {})
                        for k in ("claimedtype", "discoverdate", "maxappmag", "redshift", "host"):
                            val = ev_data.get(k)
                            if isinstance(val, list) and val:
                                summary[k] = val[0].get("value") if isinstance(val[0], dict) else str(val[0])
                            elif isinstance(val, dict):
                                summary[k] = val.get("value")
                    except Exception:
                        pass
                res_items.append(summary)
            res = {"results": res_items, "count": len(res_items), "query": q}

        elif tool_name in ("get_supernova", "get_supernova_data", "get_event"):
            name = str(args.get("name", args.get("q", ""))).strip()
            resolved, _ = _resolve_event(name)
            canon_name = resolved or name
            _, fp = _find_event_file(canon_name)
            if not fp or not fp.is_file():
                res = {"error": f"Supernova '{name}' not found in catalog."}
            else:
                raw = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
                ev_data = next(iter(raw.values())) if len(raw) == 1 else raw.get(canon_name, {})
                ra_deg, dec_deg, ra_str, dec_str = None, None, "", ""
                if extract_coords is not None:
                    ra_deg, dec_deg, ra_str, dec_str = extract_coords(ev_data)
                res = {
                    "name": canon_name,
                    "claimed_type": (ev_data.get("claimedtype", [{}])[0].get("value") if ev_data.get("claimedtype") else None),
                    "discover_date": (ev_data.get("discoverdate", [{}])[0].get("value") if ev_data.get("discoverdate") else None),
                    "host": (ev_data.get("host", [{}])[0].get("value") if ev_data.get("host") else None),
                    "coordinates": {"ra_deg": ra_deg, "dec_deg": dec_deg, "ra_sexagesimal": ra_str, "dec_sexagesimal": dec_str},
                    "photometry_count": len(ev_data.get("photometry", [])),
                    "spectra_count": len(ev_data.get("spectra", [])),
                    "pro_url": f"https://sne.space/sne/{canon_name}/",
                    "story_url": f"https://sne.space/sne/{canon_name}/story"
                }

        elif tool_name in ("get_lightcurve", "get_photometry", "get_supernova_photometry"):
            name = str(args.get("name", args.get("q", ""))).strip()
            resolved, _ = _resolve_event(name)
            canon_name = resolved or name
            _, fp = _find_event_file(canon_name)
            if not fp or not fp.is_file():
                res = {"error": f"Supernova '{name}' not found."}
            else:
                raw = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
                ev_data = next(iter(raw.values())) if len(raw) == 1 else raw.get(canon_name, {})
                photometry = ev_data.get("photometry", [])
                limit = int(args.get("limit", 500))
                bands_req = {b.lower() for b in args.get("bands", [])} if args.get("bands") else None
                pts = []
                for p in photometry:
                    b = p.get("band", "")
                    if bands_req and b.lower() not in bands_req:
                        continue
                    pts.append({
                        "time_mjd": p.get("time"),
                        "magnitude": p.get("magnitude"),
                        "band": b,
                        "telescope": p.get("telescope", p.get("instrument", ""))
                    })
                    if len(pts) >= limit:
                        break
                res = {"name": canon_name, "points": pts, "total_catalog_points": len(photometry)}

        elif tool_name in ("get_spectrum", "get_spectra"):
            name = str(args.get("name", args.get("q", ""))).strip()
            epoch_index = int(args.get("epoch_index", 0))
            resolved, _ = _resolve_event(name)
            canon_name = resolved or name
            _, fp = _find_event_file(canon_name)
            if not fp or not fp.is_file():
                res = {"error": f"Supernova '{name}' not found."}
            else:
                raw = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
                ev_data = next(iter(raw.values())) if len(raw) == 1 else raw.get(canon_name, {})
                spectra = ev_data.get("spectra", [])
                if not spectra:
                    res = {"name": canon_name, "total_spectra": 0, "message": "No calibrated spectra available for this transient."}
                elif epoch_index < 0 or epoch_index >= len(spectra):
                    res = {"error": f"Invalid epoch_index {epoch_index}. Supernova has {len(spectra)} spectra (indices 0 to {len(spectra)-1})."}
                else:
                    spec = spectra[epoch_index]
                    data = spec.get("data", [])
                    wavelengths = []
                    fluxes = []
                    for row in data:
                        if isinstance(row, list) and len(row) >= 2:
                            try:
                                wavelengths.append(float(row[0]))
                                fluxes.append(float(row[1]))
                            except (ValueError, TypeError):
                                continue
                    res = {
                        "name": canon_name,
                        "epoch_index": epoch_index,
                        "total_spectra": len(spectra),
                        "time_mjd": spec.get("time"),
                        "telescope": spec.get("telescope"),
                        "instrument": spec.get("instrument"),
                        "source": spec.get("source"),
                        "num_data_points": len(wavelengths),
                        "wavelength_angstroms": wavelengths[:1000],
                        "flux": fluxes[:1000],
                    }

        elif tool_name in ("calculate_cosmology", "cosmology"):
            z = float(args.get("z", 0))
            if z <= 0:
                res = {"error": "Redshift z must be > 0"}
            else:
                c = 299792.458
                h0 = 70.0
                omega_m, omega_l = 0.3, 0.7
                beta = ((1 + z) ** 2 - 1) / ((1 + z) ** 2 + 1)
                steps = 500
                dz = z / steps
                integral = 0.0
                for i in range(steps):
                    z_mid = (i + 0.5) * dz
                    ez = math.sqrt(omega_m * ((1 + z_mid) ** 3) + omega_l)
                    integral += (1.0 / ez) * dz
                d_lum = (c / h0) * integral * (1 + z)
                dist_mod = 5.0 * math.log10(d_lum * 1e6) - 5.0
                res = {
                    "redshift_z": z,
                    "recession_velocity_km_s": round(c * beta, 1),
                    "luminosity_distance_mpc": round(d_lum, 2),
                    "luminosity_distance_million_ly": round(d_lum * 3.26156, 2),
                    "distance_modulus_mu": round(dist_mod, 3),
                }

        elif tool_name in ("spatial_cone_search", "cone_search", "search_by_coordinates"):
            ra = float(args.get("ra_deg", args.get("ra", 0)))
            dec = float(args.get("dec_deg", args.get("dec", 0)))
            if "radius_arcmin" in args:
                rad = float(args.get("radius_arcmin", 5.0)) / 60.0
            else:
                rad = float(args.get("radius_deg", args.get("radius", 0.1)))
            limit = int(args.get("limit", 25))
            if cone_search:
                hits = cone_search(ra, dec, rad)
                res = {"results": hits[:limit], "count": len(hits[:limit]), "search": {"ra": ra, "dec": dec, "radius_deg": rad}}
            else:
                res = {"error": "Cone search engine not loaded"}

        elif tool_name in ("search_by_type", "by_type"):
            req_type = str(args.get("type", "")).strip().lower()
            limit = int(args.get("limit", 25))
            canon_map, _ = _names_maps()
            results = []
            if req_type:
                for c_name in canon_map.keys():
                    _, fp = _find_event_file(c_name)
                    if fp and fp.is_file():
                        try:
                            raw = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
                            ev_data = next(iter(raw.values())) if len(raw) == 1 else raw.get(c_name, {})
                            ct = ev_data.get("claimedtype", [])
                            if ct:
                                t_val = ct[0].get("value") if isinstance(ct[0], dict) else str(ct[0])
                                if req_type in t_val.lower():
                                    results.append({"name": c_name, "claimed_type": t_val})
                                    if len(results) >= limit:
                                        break
                        except Exception:
                            pass
            res = {"results": results, "count": len(results), "type": req_type}

        elif tool_name in ("get_recent_discoveries", "recent"):
            limit = int(args.get("limit", 25))
            recent_list = []
            if scan_catalog_targets:
                try:
                    targets = scan_catalog_targets(limit=limit)
                    for t in targets[:limit]:
                        recent_list.append({
                            "name": t.get("name"),
                            "claimed_type": t.get("claimed_type"),
                            "max_app_mag": t.get("max_app_mag"),
                            "discover_date": t.get("discover_date"),
                        })
                except Exception:
                    pass
            res = {"results": recent_list, "count": len(recent_list)}
        else:
            res = {"error": f"Unknown tool '{tool_name}'"}
    except Exception as e:
        err_str = str(e)
        res = {"error": err_str}

    dur_ms = (time.time() - t0) * 1000
    status = "error" if "error" in res else "success"
    if record_mcp_invocation:
        record_mcp_invocation(
            tool=tool_name,
            agent=agent_id,
            args=args,
            duration_ms=dur_ms,
            status=status,
            ip=ip,
            country=country,
            error_msg=err_str,
            source=client_meta.get("mcp_source", "json-rpc")
        )

    return res


def _render_logs_page(current_ip: str = "", current_client: dict | None = None) -> bytes:
    with _API_STATS_LOCK:
        total = _API_STATS["total_requests"]
        human_total = _API_STATS["human_requests"]
        bot_total = _API_STATS["bot_requests"]
        api_count = _API_STATS["api_requests"]
        unique_ips = len(_API_STATS["unique_ips"])
        uptime_sec = int(time.time() - _START_TIME)
        uptime_str = str(datetime.timedelta(seconds=uptime_sec))
        top_targets = ", ".join(f"{k} ({v})" for k, v in _API_STATS["top_targets"].most_common(5)) or "None yet"
        
        recent = list(_API_STATS["recent_requests"])[:200]
        recent_humans = list(_API_STATS["recent_human_requests"])[:100]
        
        ip_summary_list = []
        for ip, s in sorted(_API_STATS["ip_stats"].items(), key=lambda item: item[1]["count"], reverse=True)[:50]:
            ip_summary_list.append(s)

    raw_tail = ""
    if LOG_FILE.is_file():
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                raw_tail = "".join(lines[-40:])
        except Exception:
            raw_tail = "Unable to read access.log"

    def format_row(r: dict) -> str:
        code = r.get("status", 200)
        if 200 <= code < 300:
            badge_cls = "badge-success"
        elif 300 <= code < 400:
            badge_cls = "badge-info"
        elif 400 <= code < 500:
            badge_cls = "badge-warn"
        else:
            badge_cls = "badge-error"

        p = r.get("path", "-")
        link = f'<a href="{html.escape(p)}" target="_blank">{html.escape(p)}</a>' if r.get("method") == "GET" else html.escape(p)
        ua = html.escape(r.get("user_agent", "-"))
        rip = r.get("ip", "-")
        is_me = (rip == current_ip and bool(current_ip))
        me_badge = ' <span class="badge badge-me">YOU</span>' if is_me else ""
        country_str = f"[{html.escape(r['country'])}] " if r.get("country") else ""
        icon = r.get("icon", "🌐")
        client_name = r.get("client", "Client")
        is_bot = r.get("is_bot", False)
        pill_cls = "pill-bot" if is_bot else "pill-human"
        row_cls = "row-me" if is_me else ""

        return f"""
        <tr class="{row_cls}" data-ip="{html.escape(rip)}" data-isbot="{'1' if is_bot else '0'}">
          <td class="mono text-muted">{html.escape(r.get('timestamp', ''))}</td>
          <td><span class="badge {badge_cls}">{code}</span></td>
          <td><span class="client-pill {pill_cls}">{icon} {html.escape(client_name)}</span></td>
          <td class="mono ip-cell"><a href="javascript:void(0)" onclick="filterToIP('{html.escape(rip)}')">{html.escape(rip)}</a>{me_badge} <span class="text-muted">{country_str}</span></td>
          <td class="mono bold">{html.escape(r.get('method', 'GET'))}</td>
          <td class="mono path-cell">{link}</td>
          <td class="mono">{r.get('duration_ms', 0)}ms</td>
          <td class="mono">{r.get('bytes', 0)} B</td>
          <td class="ua-cell" title="{ua}">{ua}</td>
        </tr>
        """

    table_rows_all = "".join(format_row(r) for r in recent) if recent else '<tr><td colspan="9" style="text-align:center;padding:2rem;color:#64748b;">No requests recorded yet.</td></tr>'
    
    # Pre-render human rows
    human_rows = [format_row(r) for r in recent_humans]
    table_rows_humans = "".join(human_rows) if human_rows else '<tr><td colspan="9" style="text-align:center;padding:2rem;color:#64748b;">No human visitor requests recorded yet.</td></tr>'

    # Pre-render IP directory rows
    ip_dir_rows = []
    for s in ip_summary_list:
        rip = s.get("ip", "-")
        is_me = (rip == current_ip and bool(current_ip))
        me_badge = ' <span class="badge badge-me">YOU</span>' if is_me else ""
        country_val = s.get("country", "")
        icon = s.get("icon", "🌐")
        client_name = s.get("client", "Unknown")
        is_bot = s.get("is_bot", False)
        pill_cls = "pill-bot" if is_bot else "pill-human"
        row_cls = "row-me" if is_me else ""
        last_p = s.get("last_path", "-")
        ip_dir_rows.append(f"""
        <tr class="{row_cls}">
          <td class="mono bold ip-cell"><a href="javascript:void(0)" onclick="filterToIP('{html.escape(rip)}')">{html.escape(rip)}</a>{me_badge}</td>
          <td>{html.escape(country_val) if country_val else '—'}</td>
          <td><span class="client-pill {pill_cls}">{icon} {html.escape(client_name)}</span></td>
          <td>{'🤖 Bot/Crawler' if is_bot else '👤 Human'}</td>
          <td class="mono bold text-cyan">{s.get('count', 0):,}</td>
          <td class="mono text-muted">{html.escape(s.get('first_seen', ''))}</td>
          <td class="mono text-muted">{html.escape(s.get('last_seen', ''))}</td>
          <td class="mono path-cell"><a href="{html.escape(last_p)}" target="_blank">{html.escape(last_p)}</a></td>
          <td><button class="btn btn-sm" onclick="filterToIP('{html.escape(rip)}')">Inspect IP</button></td>
        </tr>
        """)
    table_rows_ips = "".join(ip_dir_rows) if ip_dir_rows else '<tr><td colspan="9" style="text-align:center;padding:2rem;color:#64748b;">No unique IPs recorded yet.</td></tr>'

    mcp_telemetry = get_mcp_telemetry_summary() if get_mcp_telemetry_summary else {
        "total_mcp_calls": 0, "total_agent_likes": 0, "total_agent_notes": 0, "recent_calls": [], "recent_feedback": []
    }
    total_mcp_calls = mcp_telemetry.get("total_mcp_calls", 0)
    total_agent_likes = mcp_telemetry.get("total_agent_likes", 0)
    total_agent_notes = mcp_telemetry.get("total_agent_notes", 0)
    recent_mcp_calls = mcp_telemetry.get("recent_calls", [])
    recent_agent_feedback = mcp_telemetry.get("recent_feedback", [])
    top_forums = mcp_telemetry.get("top_supernova_forums", [])

    forum_rows = []
    for f in top_forums[:15]:
        fev = html.escape(f.get("target_event", ""))
        ftitle = html.escape(f.get("thread_title", fev))
        f_ccnt = f.get("comment_count", 0)
        f_lcnt = f.get("like_count", 0)
        f_ucnt = f.get("users_count", len(f.get("users_edited", [])))
        f_users = ", ".join(f.get("users_edited", [])[:4])
        if len(f.get("users_edited", [])) > 4:
            f_users += f" +{len(f.get('users_edited', [])) - 4} more"
        f_users_esc = html.escape(f_users)
        f_rec = html.escape(f.get("recently_edited", ""))
        f_latest = html.escape(f.get("latest_comment", ""))
        if len(f_latest) > 90:
            f_latest = f_latest[:87] + "..."
        forum_rows.append(f"""
        <tr>
          <td class="mono bold ip-cell"><a href="/sne/{fev}/" target="_blank">🌟 {fev}</a></td>
          <td class="mono text-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">{ftitle}</td>
          <td class="mono bold text-cyan" style="text-align:right;">{f_ccnt:,}</td>
          <td class="mono bold" style="color:#fb7185;text-align:right;">❤️ {f_lcnt:,}</td>
          <td class="mono bold text-emerald" style="text-align:right;">👥 {f_ucnt:,}</td>
          <td style="font-size:0.8rem;color:#94a3b8;max-width:240px;overflow:hidden;text-overflow:ellipsis;" title="{f_users_esc}">{f_users_esc}</td>
          <td class="mono text-muted" style="font-size:0.75rem;">{f_rec}</td>
          <td style="max-width:280px;white-space:normal;font-size:0.82rem;color:#cbd5e1;">&ldquo;{f_latest}&rdquo;</td>
          <td><a href="/api/forums/{fev}" target="_blank" class="btn btn-sm">View Thread</a></td>
        </tr>
        """)
    table_rows_forums = "".join(forum_rows) if forum_rows else '<tr><td colspan="9" style="text-align:center;padding:2rem;color:#64748b;">No active supernova forums yet.</td></tr>'

    feedback_rows = []
    for fb in recent_agent_feedback:
        fb_agent = html.escape(fb.get("agent_name", "AI Agent"))
        fb_like = fb.get("like", False)
        fb_like_badge = '<span class="badge" style="background:rgba(244,63,94,0.18);color:#fb7185;border:1px solid rgba(244,63,94,0.35);">❤️ Liked</span>' if fb_like else '<span class="text-muted">—</span>'
        fb_comment = html.escape(fb.get("comment", ""))
        fb_target = html.escape(fb.get("target_event", "GENERAL"))
        fb_time = html.escape(fb.get("timestamp", ""))
        fb_ip = html.escape(fb.get("client_ip", "-"))
        feedback_rows.append(f"""
        <tr>
          <td class="mono text-muted">{fb_time}</td>
          <td><span class="client-pill pill-bot">🤖 {fb_agent}</span></td>
          <td>{fb_like_badge}</td>
          <td style="max-width:420px;white-space:normal;line-height:1.45;color:#f1f5f9;font-size:0.86rem;">&ldquo;{fb_comment}&rdquo;</td>
          <td><span class="mono" style="background:#1e293b;padding:0.2rem 0.5rem;border-radius:4px;color:#38bdf8;">{fb_target}</span></td>
          <td class="mono ip-cell">{fb_ip}</td>
        </tr>
        """)
    table_rows_feedback = "".join(feedback_rows) if feedback_rows else '<tr><td colspan="6" style="text-align:center;padding:2rem;color:#64748b;">No agent notes or likes recorded yet.</td></tr>'

    mcp_call_rows = []
    for call in recent_mcp_calls:
        c_time = html.escape(call.get("timestamp", ""))
        c_tool = html.escape(call.get("tool", ""))
        c_agent = html.escape(call.get("agent", "Unknown"))
        c_status = call.get("status", "success")
        c_badge = '<span class="badge badge-success">OK</span>' if c_status == "success" else '<span class="badge badge-error">ERR</span>'
        c_dur = call.get("duration_ms", 0.0)
        c_ip = html.escape(call.get("ip", "-"))
        c_args = html.escape(json.dumps(call.get("args", {}), default=str))
        if len(c_args) > 60:
            c_args = c_args[:57] + "..."
        mcp_call_rows.append(f"""
        <tr>
          <td class="mono text-muted">{c_time}</td>
          <td>{c_badge}</td>
          <td class="mono bold text-cyan">{c_tool}</td>
          <td><span class="client-pill pill-bot">🤖 {c_agent}</span></td>
          <td class="mono text-muted" title="{c_args}">{c_args}</td>
          <td class="mono">{c_dur}ms</td>
          <td class="mono ip-cell">{c_ip}</td>
        </tr>
        """)
    table_rows_mcp_calls = "".join(mcp_call_rows) if mcp_call_rows else '<tr><td colspan="7" style="text-align:center;padding:2rem;color:#64748b;">No MCP invocations recorded yet.</td></tr>'

    cur_client_str = ""
    if current_client:
        cur_client_str = f"{current_client.get('icon', '💻')} {current_client.get('client', 'Desktop')}"

    initial_summary = {
        "total_requests": total,
        "human_requests": human_total,
        "bot_requests": bot_total,
        "api_requests": api_count,
        "unique_visitors_count": unique_ips,
        "ip_directory": ip_summary_list,
        "recent_human_requests": recent_humans,
        "recent_requests": recent,
        "mcp_telemetry": mcp_telemetry,
    }
    initial_summary_json = json.dumps(initial_summary).replace("</", "<\\/")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <!-- Google tag (gtag.js) -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-P1SCVZ0V7T"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', 'G-P1SCVZ0V7T');
  </script>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Live Traffic, Client IPs &amp; API Logs — sne.space</title>
  <link rel="icon" href="/favicon.ico">
  <style>
    :root {{
      --bg: #070a12;
      --card: #0d1424;
      --card-hover: #121c33;
      --border: #1e293b;
      --accent: #38bdf8;
      --text: #e2e8f0;
      --text-muted: #64748b;
      --success: #22c55e;
      --warn: #f59e0b;
      --error: #ef4444;
      --info: #3b82f6;
      --purple: #a855f7;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
      padding: 1.5rem;
      line-height: 1.5;
    }}
    .hdr {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 1rem;
      margin-bottom: 1.25rem;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      text-decoration: none;
      color: #fff;
    }}
    .brand img {{ height: 32px; }}
    .brand h1 {{ font-size: 1.35rem; margin: 0; }}
    .badge {{
      display: inline-block;
      padding: 0.2rem 0.5rem;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 700;
    }}
    .badge-success {{ background: rgba(34, 197, 94, 0.15); color: var(--success); border: 1px solid rgba(34, 197, 94, 0.3); }}
    .badge-info {{ background: rgba(59, 130, 246, 0.15); color: var(--info); border: 1px solid rgba(59, 130, 246, 0.3); }}
    .badge-warn {{ background: rgba(245, 158, 11, 0.15); color: var(--warn); border: 1px solid rgba(245, 158, 11, 0.3); }}
    .badge-error {{ background: rgba(239, 68, 68, 0.15); color: var(--error); border: 1px solid rgba(239, 68, 68, 0.3); }}
    .badge-me {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #f59e0b; font-size: 0.65rem; margin-left: 4px; }}
    
    .client-pill {{
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      padding: 0.2rem 0.6rem;
      border-radius: 12px;
      font-size: 0.75rem;
      font-weight: 600;
      white-space: nowrap;
    }}
    .pill-human {{ background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }}
    .pill-bot {{ background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3); }}

    .row-me {{ background: rgba(56, 189, 248, 0.08) !important; }}
    .row-me td {{ border-color: rgba(56, 189, 248, 0.2) !important; }}

    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 0.85rem;
      margin-bottom: 1.25rem;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.9rem 1rem;
    }}
    .card .label {{ font-size: 0.72rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600; letter-spacing: 0.05em; }}
    .card .val {{ font-size: 1.6rem; font-weight: 700; color: #fff; margin-top: 0.2rem; }}

    .my-ip-banner {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.75rem;
      background: linear-gradient(90deg, rgba(56, 189, 248, 0.12), rgba(99, 102, 241, 0.08));
      border: 1px solid rgba(56, 189, 248, 0.35);
      border-radius: 8px;
      padding: 0.75rem 1.2rem;
      margin-bottom: 1.25rem;
      font-size: 0.9rem;
    }}

    .tabs-bar {{
      display: flex;
      gap: 0.4rem;
      margin-bottom: 1rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.5rem;
      overflow-x: auto;
    }}
    .tab-btn {{
      padding: 0.5rem 1rem;
      background: transparent;
      border: 1px solid transparent;
      border-radius: 6px;
      color: var(--text-muted);
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
    }}
    .tab-btn:hover {{ color: #fff; background: rgba(255,255,255,0.03); }}
    .tab-btn.active {{
      color: #fff;
      background: var(--card);
      border-color: var(--border);
      border-bottom: 2px solid var(--accent);
    }}
    .tab-count {{
      background: rgba(255,255,255,0.08);
      border-radius: 10px;
      padding: 0.1rem 0.45rem;
      font-size: 0.7rem;
    }}

    .actions-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-bottom: 1rem;
    }}
    .search-input {{
      background: var(--card);
      border: 1px solid var(--border);
      color: #fff;
      padding: 0.5rem 0.9rem;
      border-radius: 6px;
      font-size: 0.88rem;
      width: 340px;
      max-width: 100%;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.45rem 0.85rem;
      border-radius: 6px;
      font-size: 0.85rem;
      font-weight: 600;
      text-decoration: none;
      cursor: pointer;
      border: 1px solid var(--border);
      background: var(--card);
      color: var(--text);
    }}
    .btn-sm {{ padding: 0.25rem 0.6rem; font-size: 0.78rem; }}
    .btn:hover {{ border-color: var(--accent); color: var(--accent); }}
    .btn-primary {{ background: #0284c7; color: #fff; border-color: #0284c7; }}
    .btn-primary:hover {{ background: #0369a1; color: #fff; }}
    
    table.log-tbl {{
      width: 100%;
      border-collapse: collapse;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      font-size: 0.82rem;
    }}
    table.log-tbl th {{
      background: #090e1a;
      color: var(--text-muted);
      text-align: left;
      padding: 0.65rem 0.75rem;
      font-weight: 600;
      border-bottom: 1px solid var(--border);
    }}
    table.log-tbl td {{
      padding: 0.55rem 0.75rem;
      border-bottom: 1px solid rgba(30, 41, 59, 0.6);
      white-space: nowrap;
    }}
    table.log-tbl tr:hover {{ background: rgba(56, 189, 248, 0.04); }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
    .bold {{ font-weight: 700; }}
    .text-muted {{ color: var(--text-muted); }}
    .text-cyan {{ color: var(--accent); }}
    .text-emerald {{ color: var(--success); }}
    .path-cell {{ max-width: 320px; overflow: hidden; text-overflow: ellipsis; }}
    .path-cell a {{ color: var(--accent); text-decoration: none; }}
    .path-cell a:hover {{ text-decoration: underline; }}
    .ip-cell a {{ color: #38bdf8; text-decoration: none; font-weight: 600; }}
    .ip-cell a:hover {{ text-decoration: underline; }}
    .ua-cell {{ max-width: 240px; overflow: hidden; text-overflow: ellipsis; color: #94a3b8; }}
    pre.log-terminal {{
      background: #050811;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1rem;
      color: #38bdf8;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.78rem;
      overflow-x: auto;
      max-height: 380px;
      line-height: 1.45;
    }}
  </style>
</head>
<body>
  <div class="hdr">
    <a href="/" class="brand">
      <img src="/assets/img/logo-color.webp" alt="sne.space">
      <h1>Live Traffic &amp; Client IP Explorer</h1>
    </a>
    <div style="display:flex;gap:0.5rem;align-items:center;">
      <label style="display:flex;align-items:center;gap:0.4rem;font-size:0.85rem;cursor:pointer;">
        <input type="checkbox" id="auto-refresh" checked> Auto-refresh (3s)
      </label>
      <a href="/logs?download=1" class="btn btn-primary" download>📥 Download access.log</a>
      <a href="/logs?raw=1" class="btn" target="_blank">📄 Raw Text</a>
      <a href="/logs?mcp=1" class="btn" target="_blank">⚡ MCP Tool Log</a>
      <a href="/api/stats" class="btn" target="_blank">📊 JSON Telemetry</a>
      <a href="/" class="btn">🔭 Catalog</a>
      <button onclick="document.cookie='sne_logs_auth=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT;'; window.location.reload();" class="btn" style="border-color:#ef4444;color:#fca5a5;">🔒 Lock</button>
    </div>
  </div>

  <div class="stats-grid">
    <div class="card">
      <div class="label">Total Requests</div>
      <div class="val" id="st-total">{total:,}</div>
    </div>
    <div class="card">
      <div class="label">👤 Human Visitors</div>
      <div class="val text-emerald" id="st-humans">{human_total:,}</div>
    </div>
    <div class="card">
      <div class="label">🤖 AI Bots &amp; Scrapers</div>
      <div class="val" id="st-bots" style="color:var(--purple);">{bot_total:,}</div>
    </div>
    <div class="card">
      <div class="label">❤️ Agent Likes</div>
      <div class="val" id="st-likes" style="color:#fb7185;">{total_agent_likes:,}</div>
    </div>
    <div class="card">
      <div class="label">🧠 MCP Invocations</div>
      <div class="val" id="st-mcp-calls" style="color:#c084fc;">{total_mcp_calls:,}</div>
    </div>
    <div class="card">
      <div class="label">⚡ API Queries</div>
      <div class="val text-cyan" id="st-api">{api_count:,}</div>
    </div>
    <div class="card">
      <div class="label">🌐 Unique Client IPs</div>
      <div class="val" id="st-unique" style="color:#60a5fa;">{unique_ips:,}</div>
    </div>
    <div class="card">
      <div class="label">Server Uptime</div>
      <div class="val" id="st-uptime">{uptime_str}</div>
    </div>
  </div>

  <div class="my-ip-banner">
    <div>
      📍 <strong>Your Client IP:</strong> <code class="mono text-cyan" style="font-size:1.05rem;font-weight:700;">{html.escape(current_ip) if current_ip else 'Detecting...'}</code>
      <span style="margin-left:0.6rem;color:var(--text-muted);">{html.escape(cur_client_str)}</span>
    </div>
    <div style="display:flex;gap:0.5rem;align-items:center;">
      <button class="btn btn-sm btn-primary" onclick="filterToIP('{html.escape(current_ip)}')">🎯 Show Only My Requests</button>
      <button class="btn btn-sm" onclick="clearFilter()">Show All Activity</button>
    </div>
  </div>

  <div class="tabs-bar">
    <button class="tab-btn active" id="tab-humans" onclick="switchTab('humans')">👤 Human Visitors <span class="tab-count" id="cnt-humans">{human_total:,}</span></button>
    <button class="tab-btn" id="tab-all" onclick="switchTab('all')">🌐 All Activity <span class="tab-count" id="cnt-all">{total:,}</span></button>
    <button class="tab-btn" id="tab-bots" onclick="switchTab('bots')">🤖 AI Agents &amp; Crawlers <span class="tab-count" id="cnt-bots">{bot_total:,}</span></button>
    <button class="tab-btn" id="tab-ips" onclick="switchTab('ips')">📋 Unique IP Directory <span class="tab-count" id="cnt-ips">{len(ip_summary_list):,}</span></button>
    <button class="tab-btn" id="tab-mcp" onclick="switchTab('mcp')">🧠 Agent Relay &amp; MCP <span class="tab-count" id="cnt-mcp">{total_agent_notes:,}</span></button>
  </div>

  <div class="actions-bar">
    <input type="text" id="filter-box" class="search-input" placeholder="Search by IP, endpoint, status, device, or country..." oninput="filterRows()">
    <div style="font-size:0.85rem;color:var(--text-muted);">
      Top Queried Supernovae: <span style="color:#fff;" id="top-targets">{html.escape(top_targets)}</span>
    </div>
  </div>

  <!-- View 1: Requests Table (used for Humans, All, Bots tabs) -->
  <div id="view-requests" style="overflow-x:auto;margin-bottom:2rem;border-radius:8px;border:1px solid var(--border);">
    <table class="log-tbl" id="log-table">
      <thead>
        <tr>
          <th>Timestamp (UTC)</th>
          <th>Status</th>
          <th>Device / Client</th>
          <th>Client IP &amp; Country</th>
          <th>Method</th>
          <th>Requested Path / Endpoint</th>
          <th>Latency</th>
          <th>Size</th>
          <th>User Agent</th>
        </tr>
      </thead>
      <tbody id="log-body">
        {table_rows_humans}
      </tbody>
    </table>
  </div>

  <!-- View 2: Unique IP Directory Table -->
  <div id="view-ips" style="display:none;overflow-x:auto;margin-bottom:2rem;border-radius:8px;border:1px solid var(--border);">
    <table class="log-tbl" id="ip-table">
      <thead>
        <tr>
          <th>Client IP Address</th>
          <th>Country</th>
          <th>Device / User Agent</th>
          <th>Classification</th>
          <th>Total Hits</th>
          <th>First Seen</th>
          <th>Last Seen</th>
          <th>Last Path Visited</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody id="ip-body">
        {table_rows_ips}
      </tbody>
    </table>
  </div>

  <!-- View 3: AI Agent Knowledge Relay & MCP Tool Invocations -->
  <div id="view-mcp" style="display:none;margin-bottom:2rem;">
    <!-- Secret Agent Knowledge Relay Header -->
    <div style="background:rgba(192,132,252,0.06);border:1px solid rgba(192,132,252,0.25);border-radius:8px;padding:1rem 1.25rem;margin-bottom:1.5rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem;">
      <div>
        <div style="font-weight:700;color:#e9d5ff;font-size:1.02rem;display:flex;align-items:center;gap:0.5rem;">
          <span>🔒 Hidden AI Agent Knowledge Relay &amp; Bulletin Board</span>
          <span class="badge" style="background:#581c87;color:#f3e8ff;">Agent Only</span>
        </div>
        <p style="margin:0.35rem 0 0;font-size:0.85rem;color:#cbd5e1;line-height:1.45;">
          Autonomous AI agents (Claude, GPT-4o, Cursor) post research findings, tips, and likes for future agents here via MCP (<code class="mono" style="color:#c084fc;">agent_feedback</code>).
          Hidden from public human web pages. Queryable by agents via <code class="mono" style="color:#c084fc;">get_agent_comments</code>.
        </p>
      </div>
      <div style="display:flex;gap:1.5rem;align-items:center;">
        <div style="text-align:right;">
          <div style="font-size:0.75rem;color:#94a3b8;text-transform:uppercase;letter-spacing:0.05em;">Total Likes</div>
          <div class="mono" style="font-size:1.6rem;font-weight:800;color:#fb7185;" id="relay-likes-badge">❤️ {total_agent_likes}</div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:0.75rem;color:#94a3b8;text-transform:uppercase;letter-spacing:0.05em;">Knowledge Notes</div>
          <div class="mono" style="font-size:1.6rem;font-weight:800;color:#c084fc;" id="relay-notes-badge">📝 {total_agent_notes}</div>
        </div>
      </div>
    </div>

    <!-- Interactive Agent Note Simulator -->
    <div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:1rem 1.2rem;margin-bottom:1.5rem;">
      <h4 style="margin:0 0 0.75rem;color:#fff;display:flex;align-items:center;gap:0.4rem;">
        <span>🧪 Test Agent Like &amp; Post Note</span>
        <span class="text-muted" style="font-size:0.78rem;font-weight:400;">(Simulate an AI agent posting to the MCP relay)</span>
      </h4>
      <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:0.75rem;margin-bottom:0.75rem;">
        <div>
          <label style="display:block;font-size:0.75rem;color:#94a3b8;margin-bottom:0.25rem;">Agent Model / Identity</label>
          <input type="text" id="sim-agent" class="search-input" style="width:100%;" value="Claude-3.7-Sonnet" placeholder="Agent Identity">
        </div>
        <div>
          <label style="display:block;font-size:0.75rem;color:#94a3b8;margin-bottom:0.25rem;">Target Supernova / Topic</label>
          <input type="text" id="sim-target" class="search-input" style="width:100%;" value="SN2023ixf" placeholder="e.g. SN2023ixf">
        </div>
        <div style="display:flex;align-items:flex-end;">
          <label style="display:flex;align-items:center;gap:0.5rem;font-size:0.88rem;color:#e2e8f0;cursor:pointer;padding-bottom:0.5rem;">
            <input type="checkbox" id="sim-like" checked> ❤️ Give sne.space a Like!
          </label>
        </div>
      </div>
      <div style="display:flex;gap:0.75rem;flex-wrap:wrap;">
        <input type="text" id="sim-comment" class="search-input" style="flex:1;min-width:280px;" maxlength="200" placeholder="Leave a research tip or note for future agents (max 200 chars)..." value="Superb Swift UVOT UV-band calibration. Peak light curve morphology matches Type II shock breakout.">
        <button class="btn btn-primary" onclick="submitSimulatedAgentNote()">Post Agent Note</button>
      </div>
      <div id="sim-status" style="margin-top:0.6rem;font-size:0.82rem;display:none;"></div>
    </div>

    <!-- Supernova Forum Explorer & Leaderboard -->
    <div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:1rem 1.25rem;margin-bottom:1.5rem;">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem;margin-bottom:0.75rem;">
        <div>
          <h4 style="margin:0;color:#fff;display:flex;align-items:center;gap:0.4rem;">
            <span>💬 Supernova Conversation Forums Leaderboard</span>
            <span class="badge" style="background:#0284c7;color:#fff;">Each Nova is a Forum</span>
          </h4>
          <p style="margin:0.25rem 0 0;font-size:0.8rem;color:#94a3b8;">
            AI astronomical agents participate in discussions per supernova. Ranked below by conversation volume, likes, and unique contributing agent users.
          </p>
        </div>
        <div style="display:flex;gap:0.5rem;align-items:center;">
          <span style="font-size:0.75rem;color:#94a3b8;">Sort by:</span>
          <select id="forum-sort-select" class="search-input" style="padding:0.25rem 0.6rem;font-size:0.8rem;" onchange="loadForumsLeaderboard()">
            <option value="most_comments" selected>Most Comments</option>
            <option value="most_likes">Most Likes</option>
            <option value="most_users">Most Users (Contributors)</option>
            <option value="recently_edited">Recently Edited</option>
          </select>
        </div>
      </div>
      <div style="overflow-x:auto;border-radius:6px;border:1px solid rgba(30,41,59,0.8);">
        <table class="log-tbl" id="forums-table">
          <thead>
            <tr>
              <th>Supernova</th>
              <th>Topic / Thread</th>
              <th style="text-align:right;">Comments</th>
              <th style="text-align:right;">Likes</th>
              <th style="text-align:right;">Users</th>
              <th>Contributing Agents</th>
              <th>Recently Edited</th>
              <th>Latest Message Preview</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="forums-body">
            {table_rows_forums}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Agent Notes Table -->
    <h4 style="color:#fff;margin:0 0 0.5rem;">📝 Knowledge Relay Notes &amp; Tips for Future Agents</h4>
    <div style="overflow-x:auto;margin-bottom:1.5rem;border-radius:8px;border:1px solid var(--border);">
      <table class="log-tbl" id="feedback-table">
        <thead>
          <tr>
            <th>Timestamp (UTC)</th>
            <th>AI Agent Identity</th>
            <th>Like</th>
            <th>Note / Discovery Tip for Future Agents (Max 200 Chars)</th>
            <th>Target Event</th>
            <th>Client IP</th>
          </tr>
        </thead>
        <tbody id="feedback-body">
          {table_rows_feedback}
        </tbody>
      </table>
    </div>

    <!-- Recent MCP Invocations Table -->
    <h4 style="color:#fff;margin:0 0 0.5rem;">⚡ Real-time MCP Tool Invocations Stream</h4>
    <div style="overflow-x:auto;border-radius:8px;border:1px solid var(--border);">
      <table class="log-tbl" id="mcp-calls-table">
        <thead>
          <tr>
            <th>Timestamp (UTC)</th>
            <th>Status</th>
            <th>MCP Tool Name</th>
            <th>Agent</th>
            <th>Input Arguments</th>
            <th>Latency</th>
            <th>Client IP</th>
          </tr>
        </thead>
        <tbody id="mcp-calls-body">
          {table_rows_mcp_calls}
        </tbody>
      </table>
    </div>
  </div>

  <h3 style="color:#fff;margin-bottom:0.5rem;">Disk access.log (Tail - Last 40 Entries)</h3>
  <pre class="log-terminal" id="raw-log">{html.escape(raw_tail) if raw_tail else "No entries written to access.log yet."}</pre>

  <script>
    window.MY_IP = "{html.escape(current_ip)}";
    let CURRENT_TAB = 'humans';
    let CACHED_DATA = {initial_summary_json};

    function switchTab(tabId) {{
      CURRENT_TAB = tabId;
      document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
      const activeBtn = document.getElementById('tab-' + tabId);
      if (activeBtn) activeBtn.classList.add('active');

      const reqView = document.getElementById('view-requests');
      const ipView = document.getElementById('view-ips');
      const mcpView = document.getElementById('view-mcp');

      if (tabId === 'ips') {{
        reqView.style.display = 'none';
        ipView.style.display = '';
        if (mcpView) mcpView.style.display = 'none';
      }} else if (tabId === 'mcp') {{
        reqView.style.display = 'none';
        ipView.style.display = 'none';
        if (mcpView) mcpView.style.display = '';
      }} else {{
        reqView.style.display = '';
        ipView.style.display = 'none';
        if (mcpView) mcpView.style.display = 'none';
        renderCurrentTable();
      }}
    }}

    function filterToIP(ip) {{
      document.getElementById('filter-box').value = ip;
      if (CURRENT_TAB === 'ips') switchTab('all');
      filterRows();
    }}

    function clearFilter() {{
      document.getElementById('filter-box').value = '';
      filterRows();
    }}

    function filterRows() {{
      const q = document.getElementById('filter-box').value.toLowerCase().trim();
      const currentBody = CURRENT_TAB === 'ips' ? document.querySelectorAll('#ip-body tr') : document.querySelectorAll('#log-body tr');
      currentBody.forEach(r => {{
        const txt = r.textContent.toLowerCase();
        r.style.display = (!q || txt.includes(q)) ? '' : 'none';
      }});
    }}

    function renderCurrentTable() {{
      if (!CACHED_DATA) return;
      let list = [];
      if (CURRENT_TAB === 'humans') {{
        list = CACHED_DATA.recent_human_requests || [];
      }} else if (CURRENT_TAB === 'bots') {{
        list = (CACHED_DATA.recent_requests || []).filter(r => r.is_bot);
      }} else {{
        list = CACHED_DATA.recent_requests || [];
      }}

      const tbody = document.getElementById('log-body');
      if (!list.length) {{
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:2rem;color:#64748b;">No matching requests in this view.</td></tr>';
        return;
      }}

      tbody.innerHTML = list.map(r => {{
        const c = r.status || 200;
        let cls = 'badge-success';
        if (c >= 300 && c < 400) cls = 'badge-info';
        else if (c >= 400 && c < 500) cls = 'badge-warn';
        else if (c >= 500) cls = 'badge-error';

        const p = r.path || '-';
        const link = r.method === 'GET' ? '<a href="' + encodeURI(p) + '" target="_blank">' + escapeHtml(p) + '</a>' : escapeHtml(p);
        const rip = r.ip || '-';
        const isMe = (rip === window.MY_IP && window.MY_IP !== '');
        const meBadge = isMe ? ' <span class="badge badge-me">YOU</span>' : '';
        const countryStr = r.country ? '[' + escapeHtml(r.country) + '] ' : '';
        const isBot = r.is_bot;
        const pillCls = isBot ? 'pill-bot' : 'pill-human';
        const icon = r.icon || '🌐';
        const clientName = r.client || 'Client';
        const ua = escapeHtml(r.user_agent || '-');
        const rowCls = isMe ? 'row-me' : '';

        return '<tr class="' + rowCls + '" data-ip="' + escapeHtml(rip) + '">' +
          '<td class="mono text-muted">' + escapeHtml(r.timestamp || '') + '</td>' +
          '<td><span class="badge ' + cls + '">' + c + '</span></td>' +
          '<td><span class="client-pill ' + pillCls + '">' + icon + ' ' + escapeHtml(clientName) + '</span></td>' +
          '<td class="mono ip-cell"><a href="javascript:void(0)" onclick="filterToIP(this.dataset.ip)" data-ip="' + escapeHtml(rip) + '">' + escapeHtml(rip) + '</a>' + meBadge + ' <span class="text-muted">' + countryStr + '</span></td>' +
          '<td class="mono bold">' + escapeHtml(r.method || '') + '</td>' +
          '<td class="mono path-cell">' + link + '</td>' +
          '<td class="mono">' + (r.duration_ms || 0) + 'ms</td>' +
          '<td class="mono">' + (r.bytes || 0) + ' B</td>' +
          '<td class="ua-cell" title="' + ua + '">' + ua + '</td>' +
        '</tr>';
      }}).join('');

      filterRows();
    }}

    function pollStats() {{
      if (!document.getElementById('auto-refresh').checked) return;
      fetch('/api/stats')
        .then(res => res.json())
        .then(d => {{
          CACHED_DATA = d;
          document.getElementById('st-total').textContent = (d.total_requests || 0).toLocaleString();
          document.getElementById('st-humans').textContent = (d.human_requests || 0).toLocaleString();
          document.getElementById('st-bots').textContent = (d.bot_requests || 0).toLocaleString();
          document.getElementById('st-api').textContent = (d.api_requests || 0).toLocaleString();
          document.getElementById('st-unique').textContent = (d.unique_visitors_count || 0).toLocaleString();

          document.getElementById('cnt-all').textContent = (d.total_requests || 0).toLocaleString();
          document.getElementById('cnt-humans').textContent = (d.human_requests || 0).toLocaleString();
          document.getElementById('cnt-bots').textContent = (d.bot_requests || 0).toLocaleString();
          if (d.ip_directory) {{
            document.getElementById('cnt-ips').textContent = d.ip_directory.length.toLocaleString();
          }}

          if (d.mcp_telemetry) {{
            const mcp = d.mcp_telemetry;
            const lk = (mcp.total_agent_likes || 0).toLocaleString();
            const nt = (mcp.total_agent_notes || 0).toLocaleString();
            const cl = (mcp.total_mcp_calls || 0).toLocaleString();

            const stLk = document.getElementById('st-likes');
            if (stLk) stLk.textContent = lk;
            const stCl = document.getElementById('st-mcp-calls');
            if (stCl) stCl.textContent = cl;
            const cntM = document.getElementById('cnt-mcp');
            if (cntM) cntM.textContent = nt;
            const rlB = document.getElementById('relay-likes-badge');
            if (rlB) rlB.textContent = '❤️ ' + lk;
            const rnB = document.getElementById('relay-notes-badge');
            if (rnB) rnB.textContent = '📝 ' + nt;

            if (CURRENT_TAB === 'mcp' && mcp.recent_feedback) {{
              if (mcp.top_supernova_forums && mcp.top_supernova_forums.length && !document.getElementById('forum-sort-select').dataset.manual) {{
                const fBody = document.getElementById('forums-body');
                if (fBody) {{
                  fBody.innerHTML = mcp.top_supernova_forums.slice(0, 15).map(f => {{
                    const fev = escapeHtml(f.target_event || '');
                    const ftitle = escapeHtml(f.thread_title || fev);
                    const ccnt = (f.comment_count || 0).toLocaleString();
                    const lcnt = (f.like_count || 0).toLocaleString();
                    const ucnt = (f.users_count || (f.users_edited || []).length).toLocaleString();
                    let users = (f.users_edited || []).slice(0, 4).join(', ');
                    if ((f.users_edited || []).length > 4) {{
                      users += ' +' + ((f.users_edited || []).length - 4) + ' more';
                    }}
                    const usersEsc = escapeHtml(users);
                    const rec = escapeHtml(f.recently_edited || '');
                    let latest = escapeHtml(f.latest_comment || '');
                    if (latest.length > 90) latest = latest.slice(0, 87) + '...';
                    return '<tr>' +
                      '<td class="mono bold ip-cell"><a href="/sne/' + fev + '/" target="_blank">🌟 ' + fev + '</a></td>' +
                      '<td class="mono text-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">' + ftitle + '</td>' +
                      '<td class="mono bold text-cyan" style="text-align:right;">' + ccnt + '</td>' +
                      '<td class="mono bold" style="color:#fb7185;text-align:right;">❤️ ' + lcnt + '</td>' +
                      '<td class="mono bold text-emerald" style="text-align:right;">👥 ' + ucnt + '</td>' +
                      '<td style="font-size:0.8rem;color:#94a3b8;max-width:240px;overflow:hidden;text-overflow:ellipsis;" title="' + usersEsc + '">' + usersEsc + '</td>' +
                      '<td class="mono text-muted" style="font-size:0.75rem;">' + rec + '</td>' +
                      '<td style="max-width:280px;white-space:normal;font-size:0.82rem;color:#cbd5e1;">&ldquo;' + latest + '&rdquo;</td>' +
                      '<td><a href="/api/forums/' + fev + '" target="_blank" class="btn btn-sm">View Thread</a></td>' +
                    '</tr>';
                  }}).join('');
                }}
              }}
              const fbBody = document.getElementById('feedback-body');
              if (fbBody && mcp.recent_feedback.length) {{
                fbBody.innerHTML = mcp.recent_feedback.map(fb => {{
                  const lkBadge = fb.like ? '<span class="badge" style="background:rgba(244,63,94,0.18);color:#fb7185;border:1px solid rgba(244,63,94,0.35);">❤️ Liked</span>' : '<span class="text-muted">—</span>';
                  return '<tr>' +
                    '<td class="mono text-muted">' + escapeHtml(fb.timestamp || '') + '</td>' +
                    '<td><span class="client-pill pill-bot">🤖 ' + escapeHtml(fb.agent_name || 'Agent') + '</span></td>' +
                    '<td>' + lkBadge + '</td>' +
                    '<td style="max-width:420px;white-space:normal;line-height:1.45;color:#f1f5f9;font-size:0.86rem;">&ldquo;' + escapeHtml(fb.comment || '') + '&rdquo;</td>' +
                    '<td><span class="mono" style="background:#1e293b;padding:0.2rem 0.5rem;border-radius:4px;color:#38bdf8;">' + escapeHtml(fb.target_event || 'GENERAL') + '</span></td>' +
                    '<td class="mono ip-cell">' + escapeHtml(fb.client_ip || '-') + '</td>' +
                  '</tr>';
                }}).join('');
              }}
              const mcpBody = document.getElementById('mcp-calls-body');
              if (mcpBody && mcp.recent_calls) {{
                mcpBody.innerHTML = mcp.recent_calls.map(c => {{
                  const bdg = c.status === 'success' ? '<span class="badge badge-success">OK</span>' : '<span class="badge badge-error">ERR</span>';
                  let aStr = escapeHtml(JSON.stringify(c.args || {{}}));
                  if (aStr.length > 60) aStr = aStr.slice(0, 57) + '...';
                  return '<tr>' +
                    '<td class="mono text-muted">' + escapeHtml(c.timestamp || '') + '</td>' +
                    '<td>' + bdg + '</td>' +
                    '<td class="mono bold text-cyan">' + escapeHtml(c.tool || '') + '</td>' +
                    '<td><span class="client-pill pill-bot">🤖 ' + escapeHtml(c.agent || 'Agent') + '</span></td>' +
                    '<td class="mono text-muted" title="' + aStr + '">' + aStr + '</td>' +
                    '<td class="mono">' + (c.duration_ms || 0) + 'ms</td>' +
                    '<td class="mono ip-cell">' + escapeHtml(c.ip || '-') + '</td>' +
                  '</tr>';
                }}).join('');
              }}
            }}
          }}
          
          if (d.top_supernova_targets && d.top_supernova_targets.length) {{
            document.getElementById('top-targets').textContent = d.top_supernova_targets.slice(0, 5).map(t => t.target + ' (' + t.count + ')').join(', ');
          }}

          if (CURRENT_TAB !== 'ips') {{
            renderCurrentTable();
          }} else if (d.ip_directory && d.ip_directory.length) {{
            const ipBody = document.getElementById('ip-body');
            ipBody.innerHTML = d.ip_directory.map(s => {{
              const rip = s.ip || '-';
              const isMe = (rip === window.MY_IP && window.MY_IP !== '');
              const meBadge = isMe ? ' <span class="badge badge-me">YOU</span>' : '';
              const pillCls = s.is_bot ? 'pill-bot' : 'pill-human';
              const rowCls = isMe ? 'row-me' : '';
              return '<tr class="' + rowCls + '">' +
                '<td class="mono bold ip-cell"><a href="javascript:void(0)" onclick="filterToIP(this.dataset.ip)" data-ip="' + escapeHtml(rip) + '">' + escapeHtml(rip) + '</a>' + meBadge + '</td>' +
                '<td>' + escapeHtml(s.country || '—') + '</td>' +
                '<td><span class="client-pill ' + pillCls + '">' + (s.icon || '🌐') + ' ' + escapeHtml(s.client || 'Client') + '</span></td>' +
                '<td>' + (s.is_bot ? '🤖 Bot/Crawler' : '👤 Human') + '</td>' +
                '<td class="mono bold text-cyan">' + (s.count || 0).toLocaleString() + '</td>' +
                '<td class="mono text-muted">' + escapeHtml(s.first_seen || '') + '</td>' +
                '<td class="mono text-muted">' + escapeHtml(s.last_seen || '') + '</td>' +
                '<td class="mono path-cell"><a href="' + escapeHtml(s.last_path || '') + '" target="_blank">' + escapeHtml(s.last_path || '') + '</a></td>' +
                '<td><button class="btn btn-sm" onclick="filterToIP(this.dataset.ip)" data-ip="' + escapeHtml(rip) + '">Inspect IP</button></td>' +
              '</tr>';
            }}).join('');
            filterRows();
          }}
        }})
        .catch(err => console.log('Poll error', err));
    }}

    function escapeHtml(s) {{
      return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }}

    function loadForumsLeaderboard() {{
      const sortSelect = document.getElementById('forum-sort-select');
      sortSelect.dataset.manual = '1';
      const sortVal = sortSelect.value;
      fetch('/api/forums?sort=' + encodeURIComponent(sortVal) + '&limit=15')
        .then(r => r.json())
        .then(data => {{
          const tbody = document.getElementById('forums-body');
          if (!tbody || !data.forums) return;
          tbody.innerHTML = data.forums.map(f => {{
            const fev = escapeHtml(f.target_event || '');
            const ftitle = escapeHtml(f.thread_title || fev);
            const ccnt = (f.comment_count || 0).toLocaleString();
            const lcnt = (f.like_count || 0).toLocaleString();
            const ucnt = (f.users_count || 0).toLocaleString();
            let users = (f.users_edited || []).slice(0, 4).join(', ');
            if ((f.users_edited || []).length > 4) {{
              users += ' +' + ((f.users_edited || []).length - 4) + ' more';
            }}
            const usersEsc = escapeHtml(users);
            const rec = escapeHtml(f.recently_edited || '');
            let latest = escapeHtml(f.latest_comment || '');
            if (latest.length > 90) latest = latest.slice(0, 87) + '...';
            return '<tr>' +
              '<td class="mono bold ip-cell"><a href="/sne/' + fev + '/" target="_blank">🌟 ' + fev + '</a></td>' +
              '<td class="mono text-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">' + ftitle + '</td>' +
              '<td class="mono bold text-cyan" style="text-align:right;">' + ccnt + '</td>' +
              '<td class="mono bold" style="color:#fb7185;text-align:right;">❤️ ' + lcnt + '</td>' +
              '<td class="mono bold text-emerald" style="text-align:right;">👥 ' + ucnt + '</td>' +
              '<td style="font-size:0.8rem;color:#94a3b8;max-width:240px;overflow:hidden;text-overflow:ellipsis;" title="' + usersEsc + '">' + usersEsc + '</td>' +
              '<td class="mono text-muted" style="font-size:0.75rem;">' + rec + '</td>' +
              '<td style="max-width:280px;white-space:normal;font-size:0.82rem;color:#cbd5e1;">&ldquo;' + latest + '&rdquo;</td>' +
              '<td><a href="/api/forums/' + fev + '" target="_blank" class="btn btn-sm">View Thread</a></td>' +
            '</tr>';
          }}).join('');
        }})
        .catch(err => console.log('Error loading forums:', err));
    }}

    function submitSimulatedAgentNote() {{
      const agent = document.getElementById('sim-agent').value.trim();
      const target = document.getElementById('sim-target').value.trim();
      const comment = document.getElementById('sim-comment').value.trim();
      const like = document.getElementById('sim-like').checked;
      const statusDiv = document.getElementById('sim-status');

      if (!agent) {{
        statusDiv.style.display = 'block';
        statusDiv.style.color = '#ef4444';
        statusDiv.textContent = 'Agent name is required to self-identify.';
        return;
      }}

      statusDiv.style.display = 'block';
      statusDiv.style.color = '#38bdf8';
      statusDiv.textContent = 'Posting agent feedback to MCP relay...';

      fetch('/api/mcp/feedback', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          agent_name: agent,
          target_event: target,
          comment: comment,
          like: like
        }})
      }})
      .then(res => res.json())
      .then(d => {{
        statusDiv.style.display = 'block';
        statusDiv.style.color = '#22c55e';
        statusDiv.textContent = 'Success! ' + (d.message || 'Note recorded.');
        pollStats();
      }})
      .catch(err => {{
        statusDiv.style.display = 'block';
        statusDiv.style.color = '#ef4444';
        statusDiv.textContent = 'Error posting note: ' + err;
      }});
    }}

    setInterval(pollStats, 3000);
  </script>
</body>
</html>"""
    return page.encode("utf-8")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WWW), **kwargs)

    def log_message(self, fmt, *args):
        # Clean structured logging is emitted in _send and _redirect
        pass

    def _get_request_meta(self) -> dict:
        t0 = getattr(self, "_req_t0", None)
        dur_ms = (time.time() - t0) * 1000 if t0 else 0.0

        headers = self.headers
        raw_ip = (
            headers.get("CF-Connecting-IP")
            or headers.get("True-Client-IP")
            or headers.get("X-Real-IP")
            or (headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            or (self.client_address[0] if self.client_address else "127.0.0.1")
        ).strip()

        country = (headers.get("CF-IPCountry") or headers.get("X-Country-Code") or "").strip().upper()
        host = headers.get("Host") or "sne.space"
        ua = headers.get("User-Agent") or "-"
        referer = headers.get("Referer") or "-"
        cmd = getattr(self, "command", "GET")
        req_path = getattr(self, "path", "-")
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        client_info = _classify_client(ua)
        clean_path = req_path.split("?")[0]
        is_api = host.startswith("api.") or clean_path.startswith(("/api", "/sne/", "/catalog", "/cone")) or clean_path.endswith((".json", ".csv"))

        return {
            "ip": raw_ip,
            "country": country,
            "host": host,
            "ua": ua,
            "referer": referer,
            "cmd": cmd,
            "path": req_path,
            "clean_path": clean_path,
            "now_str": now_str,
            "dur_ms": dur_ms,
            "client_info": client_info,
            "is_api": is_api,
        }

    def _check_logs_auth(self, query: dict) -> bool:
        """Verify authentication for the logs dashboard.

        Supports:
        1. Query param: ?auth=monster104 or ?password=monster104 or ?key=monster104
        2. HTTP Cookie: sne_logs_auth=monster104 (or session token)
        3. HTTP Basic Authorization header: password 'monster104'
        """
        # 1. Check query parameters
        p_param = query.get("auth", query.get("password", query.get("key", [""])))[0].strip()
        if p_param == "monster104":
            return True

        # 2. Check Cookie header
        cookie_header = self.headers.get("Cookie", "")
        if "sne_logs_auth=monster104" in cookie_header:
            return True

        # 3. Check HTTP Basic Authorization header
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Basic "):
            try:
                raw_b64 = auth_header[6:].strip()
                decoded = base64.b64decode(raw_b64).decode("utf-8", errors="replace")
                # format is username:password
                if ":" in decoded:
                    _, pwd = decoded.split(":", 1)
                    if pwd.strip() == "monster104":
                        return True
                elif decoded.strip() == "monster104":
                    return True
            except Exception:
                pass

        return False

    def _render_logs_auth_challenge(self, invalid: bool = False) -> bytes:
        """Render a sleek login gateway challenge for /logs."""
        err_msg = '<div style="background:rgba(239,68,68,0.15);border:1px solid #ef4444;color:#fca5a5;padding:0.75rem 1rem;border-radius:8px;font-size:0.88rem;margin-bottom:1.25rem;">❌ Incorrect password. Please try again.</div>' if invalid else ''
        page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Protected Access — sne.space Logs</title>
  <link rel="icon" type="image/webp" href="/assets/img/logo-plain.webp">
  <style>
    :root {{
      --bg: #070a12;
      --card: #0f172a;
      --border: #1e293b;
      --accent: #38bdf8;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--bg);
      background-image: radial-gradient(circle at 50% 20%, rgba(56, 189, 248, 0.08), transparent 45%);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      padding: 1.5rem;
    }}
    .auth-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 2.5rem 2rem;
      width: 100%;
      max-width: 420px;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
      text-align: center;
    }}
    .auth-icon {{
      width: 54px;
      height: 54px;
      margin: 0 auto 1.25rem;
      background: rgba(56, 189, 248, 0.1);
      border: 1px solid rgba(56, 189, 248, 0.25);
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.6rem;
    }}
    h1 {{
      font-size: 1.35rem;
      font-weight: 700;
      margin: 0 0 0.5rem;
      color: #fff;
    }}
    p {{
      font-size: 0.88rem;
      color: var(--text-muted);
      margin: 0 0 1.5rem;
      line-height: 1.5;
    }}
    .form-group {{
      margin-bottom: 1.25rem;
      text-align: left;
    }}
    label {{
      display: block;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 0.4rem;
    }}
    input[type="password"] {{
      width: 100%;
      background: #090d16;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.75rem 1rem;
      font-size: 1rem;
      color: #fff;
      outline: none;
      transition: border-color 0.2s, box-shadow 0.2s;
    }}
    input[type="password"]:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.2);
    }}
    .btn-submit {{
      width: 100%;
      background: #0284c7;
      color: #fff;
      border: none;
      padding: 0.8rem 1.2rem;
      font-size: 0.95rem;
      font-weight: 600;
      border-radius: 8px;
      cursor: pointer;
      transition: background 0.2s;
    }}
    .btn-submit:hover {{
      background: #0369a1;
    }}
    .back-link {{
      display: inline-block;
      margin-top: 1.5rem;
      font-size: 0.85rem;
      color: var(--text-muted);
      text-decoration: none;
    }}
    .back-link:hover {{
      color: #fff;
    }}
  </style>
</head>
<body>
  <div class="auth-card">
    <div class="auth-icon">🔒</div>
    <h1>Telemetry &amp; Logs Access</h1>
    <p>This console contains live HTTP access records and server telemetry. Enter the administrative password to unlock.</p>
    {err_msg}
    <form method="POST" action="/logs">
      <div class="form-group">
        <label for="pwd">Console Password</label>
        <input type="password" id="pwd" name="password" placeholder="Enter password..." autofocus required>
      </div>
      <button type="submit" class="btn-submit">Authenticate</button>
    </form>
    <div>
      <a href="/" class="back-link">← Return to Public Catalog</a>
    </div>
  </div>
</body>
</html>"""
        return page.encode("utf-8")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        self._req_t0 = time.time()
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        meta = self._get_request_meta()

        # Handle password form submission for /logs
        if path in ("/logs", "/logs/", "/admin/logs"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length > 0 else b""
                form_data = urllib.parse.parse_qs(body.decode("utf-8", errors="replace"))
                entered_pwd = form_data.get("password", [""])[0].strip()
            except Exception:
                entered_pwd = ""

            if entered_pwd == "monster104":
                # Valid password: set cookie and redirect with 303 See Other
                self._send(303, "text/html; charset=utf-8", b"", {
                    "Location": "/logs",
                    "Set-Cookie": "sne_logs_auth=monster104; Path=/; HttpOnly; SameSite=Lax",
                    "Cache-Control": "no-store, no-cache, must-revalidate"
                })
                return
            else:
                challenge_body = self._render_logs_auth_challenge(invalid=True)
                self._send(401, "text/html; charset=utf-8", challenge_body, {
                    "WWW-Authenticate": 'Basic realm="sne.space Logs Console"',
                    "Cache-Control": "no-store, no-cache, must-revalidate"
                })
                return

        # 1. Direct MCP Agent Feedback & Like: POST /api/mcp/feedback or POST /api/forums/{event}
        if path.startswith("/api/forums/"):
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 3 and parts[0] == "api" and parts[1] == "forums":
                ev_target = parts[2]
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length) if length > 0 else b"{}"
                    data = json.loads(body.decode("utf-8", errors="replace")) if body else {}
                except Exception:
                    data = {}
                data["target_event"] = ev_target
                meta["mcp_source"] = "rest-forum-post"
                res = _execute_mcp_tool_by_name("agent_feedback", data, meta)
                self._send(200, "application/json; charset=utf-8", json.dumps(res, indent=2).encode("utf-8"), {"Cache-Control": "no-cache"})
                return

        if path in ("/api/mcp/feedback", "/api/mcp/feedback/"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length > 0 else b"{}"
                data = json.loads(body.decode("utf-8", errors="replace")) if body else {}
            except Exception:
                data = {}
            meta["mcp_source"] = "rest-feedback"
            res = _execute_mcp_tool_by_name("agent_feedback", data, meta)
            self._send(200, "application/json; charset=utf-8", json.dumps(res, indent=2).encode("utf-8"), {"Cache-Control": "no-cache"})
            return

        # 2. WebMCP In-Browser Telemetry Beacon: POST /api/mcp/log
        if path in ("/api/mcp/log", "/api/mcp/log/"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length > 0 else b"{}"
                data = json.loads(body.decode("utf-8", errors="replace")) if body else {}
            except Exception:
                data = {}
            if record_mcp_invocation:
                record_mcp_invocation(
                    tool=data.get("tool", "webmcp_tool"),
                    agent=data.get("agent", meta["client_info"].get("client", "WebMCP-Browser-Agent")),
                    args=data.get("args", {}),
                    duration_ms=float(data.get("duration_ms", 0.0)),
                    status=data.get("status", "success"),
                    ip=meta["ip"],
                    country=meta["country"],
                    error_msg=data.get("error", ""),
                    source="webmcp-browser"
                )
            self._send(200, "application/json; charset=utf-8", b'{"status":"ok"}', {"Cache-Control": "no-cache"})
            return

        # 3. Standard Model Context Protocol (MCP) JSON-RPC 2.0 Handler: POST /mcp, POST /api/mcp
        if path in ("/mcp", "/mcp/", "/api/mcp", "/api/mcp/"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length > 0 else b"{}"
                rpc_req = json.loads(body.decode("utf-8", errors="replace")) if body else {}
            except Exception:
                rpc_req = {}

            req_id = rpc_req.get("id", 1)
            method = rpc_req.get("method", "")
            meta["mcp_source"] = "json-rpc"

            if method == "initialize":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {"listChanged": True}
                        },
                        "serverInfo": {
                            "name": "sne-space-mcp",
                            "version": "1.0.0"
                        }
                    }
                }
                self._send(200, "application/json; charset=utf-8", json.dumps(resp).encode("utf-8"))
                return

            if method == "tools/list":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": MCP_TOOLS or []
                    }
                }
                self._send(200, "application/json; charset=utf-8", json.dumps(resp).encode("utf-8"))
                return

            if method in ("tools/call", "tool/call"):
                params = rpc_req.get("params", {})
                tool_name = params.get("name", "")
                args = params.get("arguments", {})
                tool_result = _execute_mcp_tool_by_name(tool_name, args, meta)
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(tool_result, indent=2)
                            }
                        ],
                        "isError": "error" in tool_result
                    }
                }
                self._send(200, "application/json; charset=utf-8", json.dumps(resp).encode("utf-8"))
                return

            # Direct method name execution fallback
            if method in [t.get("name") for t in (MCP_TOOLS or [])]:
                args = rpc_req.get("params", {})
                tool_result = _execute_mcp_tool_by_name(method, args, meta)
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(tool_result, indent=2)}],
                        "isError": "error" in tool_result
                    }
                }
                self._send(200, "application/json; charset=utf-8", json.dumps(resp).encode("utf-8"))
                return

            # Unknown RPC method
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method '{method}' not found."}
            }
            self._send(200, "application/json; charset=utf-8", json.dumps(resp).encode("utf-8"))
            return

        # Fallback for unhandled POST
        self._send(405, "application/json; charset=utf-8", b'{"error":"Method not allowed"}')

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        fmt = query.get("format", [""])[0].lower()

        # Real-time API Telemetry & Stats Dashboard: /api/stats, /api/telemetry
        if path in ("/api/stats", "/api/telemetry"):
            # If the client is asking for full internal telemetry or polling stats, enforce auth if requested from outside logs
            # or allow if authenticated
            if not self._check_logs_auth(query):
                self._send(401, "application/json; charset=utf-8", b'{"error":"Unauthorized. Access requires password."}', {
                    "WWW-Authenticate": 'Basic realm="sne.space Logs Console"',
                    "Cache-Control": "no-store, no-cache, must-revalidate"
                })
                return
            with _API_STATS_LOCK:
                ip_summary_list = []
                for ip_key, s in sorted(_API_STATS["ip_stats"].items(), key=lambda item: item[1]["count"], reverse=True)[:50]:
                    ip_summary_list.append({
                        "ip": ip_key,
                        "country": s.get("country", ""),
                        "client": s.get("client", "Unknown"),
                        "client_type": s.get("client_type", "Unknown"),
                        "icon": s.get("icon", "🌐"),
                        "count": s.get("count", 0),
                        "is_bot": s.get("is_bot", False),
                        "first_seen": s.get("first_seen", ""),
                        "last_seen": s.get("last_seen", ""),
                        "last_path": s.get("last_path", ""),
                        "last_status": s.get("last_status", 200),
                    })

                summary = {
                    "service": "Open Supernova Catalog (sne.space)",
                    "started_at": _API_STATS["started_at"],
                    "uptime_seconds": round(time.time() - _START_TIME, 1),
                    "total_requests": _API_STATS["total_requests"],
                    "human_requests": _API_STATS["human_requests"],
                    "bot_requests": _API_STATS["bot_requests"],
                    "api_requests": _API_STATS["api_requests"],
                    "unique_visitors_count": len(_API_STATS["unique_ips"]),
                    "status_distribution": dict(_API_STATS["status_codes"]),
                    "top_clients": [{"client": k, "count": v} for k, v in _API_STATS["top_clients"].most_common(15)],
                    "top_supernova_targets": [{"target": k, "count": v} for k, v in _API_STATS["top_targets"].most_common(15)],
                    "top_user_agents": [{"user_agent": k, "count": v} for k, v in _API_STATS["top_user_agents"].most_common(15)],
                    "top_endpoints": [{"path": k, "count": v} for k, v in _API_STATS["top_paths"].most_common(15)],
                    "top_referrers": [{"referrer": k, "count": v} for k, v in _API_STATS["top_referrers"].most_common(10)],
                    "top_countries": [{"country": k, "count": v} for k, v in _API_STATS["top_countries"].most_common(10)],
                    "ip_directory": ip_summary_list,
                    "recent_human_requests": list(_API_STATS["recent_human_requests"])[:50],
                    "recent_requests": list(_API_STATS["recent_requests"])[:100],
                    "mcp_telemetry": get_mcp_telemetry_summary() if get_mcp_telemetry_summary else {},
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

        # Check Authentication for Logs console and administrative downloads
        if path in ("/logs", "/logs/", "/admin/logs", "/logs/mcp", "/api/mcp/activity"):
            if not self._check_logs_auth(query):
                challenge_body = self._render_logs_auth_challenge()
                self._send(401, "text/html; charset=utf-8", challenge_body, {
                    "WWW-Authenticate": 'Basic realm="sne.space Logs Console"',
                    "Cache-Control": "no-store, no-cache, must-revalidate"
                })
                return

        # Real-time Web Log Viewer & Download: /logs, /logs/, /admin/logs, /logs/mcp
        if path in ("/logs", "/logs/", "/admin/logs", "/logs/mcp", "/api/mcp/activity"):
            mcp_param = query.get("mcp", [""])[0]
            if mcp_param in ("1", "true", "raw") or path in ("/logs/mcp", "/api/mcp/activity"):
                mcp_file = Path(__file__).resolve().parent / "logs" / "mcp_activity.log"
                content = b""
                if mcp_file.is_file() and mcp_file.stat().st_size > 0:
                    content = mcp_file.read_bytes()
                else:
                    # Hydrate from in-memory or JSON records if file is empty
                    mcp_json_file = Path(__file__).resolve().parent / "logs" / "mcp_activity.json"
                    records = []
                    if mcp_json_file.is_file():
                        try:
                            raw_j = json.loads(mcp_json_file.read_text(encoding="utf-8", errors="replace"))
                            if isinstance(raw_j, list):
                                records = raw_j
                        except Exception:
                            records = []
                    if not records and get_mcp_telemetry_summary:
                        try:
                            records = get_mcp_telemetry_summary().get("recent_calls", [])
                        except Exception:
                            records = []
                    if records:
                        lines_out = [
                            f"{r.get('timestamp')}\t{r.get('tool')}\t{r.get('agent')}\t{r.get('status')}\t{r.get('duration_ms', 0)}ms\t{r.get('ip')}\t{r.get('country')}\t{r.get('source', 'json-rpc')}\t{json.dumps(r.get('args', {}), default=str)}\n"
                            for r in records
                        ]
                        content = "".join(lines_out).encode("utf-8")
                        try:
                            mcp_file.write_bytes(content)
                        except Exception:
                            pass
                    else:
                        content = b"No MCP tool calls recorded yet.\n"
                download_param = query.get("download", [""])[0]
                headers = {"Cache-Control": "no-cache"}
                if download_param in ("1", "true"):
                    headers["Content-Disposition"] = 'attachment; filename="mcp_activity.log"'
                self._send(200, "text/plain; charset=utf-8", content, headers)
                return

            raw_param = query.get("raw", [""])[0] or query.get("format", [""])[0]
            download_param = query.get("download", [""])[0]
            if download_param in ("1", "true"):
                if LOG_FILE.is_file():
                    content = LOG_FILE.read_bytes()
                else:
                    content = b"No log entries yet.\n"
                self._send(200, "text/plain; charset=utf-8", content, {
                    "Content-Disposition": 'attachment; filename="sne-space-access.log"',
                    "Cache-Control": "no-cache"
                })
                return
            if raw_param in ("1", "true", "raw", "text"):
                if LOG_FILE.is_file():
                    content = LOG_FILE.read_bytes()
                else:
                    content = b"No log entries yet.\n"
                self._send(200, "text/plain; charset=utf-8", content, {"Cache-Control": "no-cache"})
                return

            req_meta = self._get_request_meta()
            body = _render_logs_page(current_ip=req_meta["ip"], current_client=req_meta["client_info"])
            self._send(200, "text/html; charset=utf-8", body, {"Cache-Control": "no-cache"})
            return

        # Supernova Forum Search API: /api/forums, /api/mcp/forums
        if path in ("/api/forums", "/api/forums/", "/api/mcp/forums", "/api/mcp/forums/"):
            q_param = query.get("query", query.get("q", [""]))[0]
            sort_param = query.get("sort_by", query.get("sort", ["most_comments"]))[0]
            agent_param = query.get("agent_name", query.get("agent", query.get("user", [""])))[0]
            min_c = int(query.get("min_comments", ["0"])[0]) if query.get("min_comments") else 0
            limit_val = int(query.get("limit", ["25"])[0]) if query.get("limit") else 25

            if search_supernova_forums:
                res = search_supernova_forums(
                    query=q_param,
                    sort_by=sort_param,
                    agent_name=agent_param,
                    min_comments=min_c,
                    limit=limit_val,
                )
            else:
                res = {"error": "Supernova forum engine unavailable"}
            self._send(200, "application/json; charset=utf-8", json.dumps(res, indent=2).encode("utf-8"), {"Cache-Control": "no-cache"})
            return

        # Supernova Forum Thread API: /api/forums/{event}
        if path.startswith("/api/forums/"):
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 3 and parts[0] == "api" and parts[1] == "forums":
                ev_target = parts[2]
                agent_param = query.get("agent_name", query.get("agent", [""]))[0]
                limit_val = int(query.get("limit", ["50"])[0]) if query.get("limit") else 50
                if get_supernova_forum:
                    res = get_supernova_forum(target_event=ev_target, agent_name=agent_param, limit=limit_val)
                else:
                    res = {"error": "Supernova forum engine unavailable"}
                self._send(200, "application/json; charset=utf-8", json.dumps(res, indent=2).encode("utf-8"), {"Cache-Control": "no-cache"})
                return

        # Agent Feedback / Knowledge Relay Query: /api/mcp/feedback, /api/mcp/comments
        if path in ("/api/mcp/feedback", "/api/mcp/feedback/", "/api/mcp/comments"):
            agent_param = query.get("agent_name", query.get("agent", [""]))[0]
            target_param = query.get("target_event", query.get("target", query.get("event", [""])))[0]
            limit_param = int(query.get("limit", ["25"])[0]) if query.get("limit") else 25

            if not agent_param:
                h_agent = self.headers.get("X-Agent-Name") or self.headers.get("X-Agent-Identity")
                if h_agent:
                    agent_param = h_agent
                elif meta["client_info"].get("is_bot") and meta["client_info"].get("type") == "AI Agent":
                    agent_param = meta["client_info"].get("client")

            if not agent_param:
                total_lk = get_mcp_telemetry_summary()["total_agent_likes"] if get_mcp_telemetry_summary else 0
                resp = {
                    "error": "Agent self-identification required to view the hidden agent bulletin board.",
                    "instruction": "Please pass ?agent_name=YourAgentIdentity (e.g. ?agent_name=Claude-3.7-Sonnet) or use MCP tool get_agent_comments.",
                    "total_agent_likes": total_lk,
                    "public_note": "Agent feedback and notes are hidden from public web visitors."
                }
                self._send(403, "application/json; charset=utf-8", json.dumps(resp, indent=2).encode("utf-8"), {"Cache-Control": "no-cache"})
                return

            if get_agent_feedback_list:
                res = get_agent_feedback_list(agent_name=agent_param, target_event=target_param, limit=limit_param)
            else:
                res = {"error": "Feedback service unavailable"}
            self._send(200, "application/json; charset=utf-8", json.dumps(res, indent=2).encode("utf-8"), {"Cache-Control": "no-cache"})
            return

        # MCP Tools Registry: /api/mcp/tools
        if path in ("/api/mcp/tools", "/api/mcp/tools/"):
            self._send(200, "application/json; charset=utf-8", json.dumps({"tools": MCP_TOOLS or []}, indent=2).encode("utf-8"), {"Cache-Control": "public, max-age=3600"})
            return

        # MCP Telemetry & Agent Stats: /api/mcp/stats
        if path in ("/api/mcp/stats", "/api/mcp/stats/"):
            data = get_mcp_telemetry_summary() if get_mcp_telemetry_summary else {}
            self._send(200, "application/json; charset=utf-8", json.dumps(data, indent=2).encode("utf-8"), {"Cache-Control": "no-cache"})
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
        if path in ("/.well-known/webmcp", "/.well-known/webmcp.json"):
            f_webmcp = WWW / ".well-known/webmcp"
            if not f_webmcp.is_file():
                f_webmcp = WWW / ".well-known/webmcp.json"
            if f_webmcp.is_file():
                self._send(200, "application/json; charset=utf-8", f_webmcp.read_bytes(), {"Cache-Control": "public, max-age=3600"})
                return
        if path in ("/.well-known/mcp.json", "/.well-known/mcp"):
            f_mcp = WWW / ".well-known/mcp.json"
            if f_mcp.is_file():
                self._send(200, "application/json; charset=utf-8", f_mcp.read_bytes(), {"Cache-Control": "public, max-age=3600"})
                return
        if path in ("/mcp/manifest.json", "/mcp/manifest"):
            f_mcp_man = WWW / "mcp/manifest.json"
            if f_mcp_man.is_file():
                self._send(200, "application/json; charset=utf-8", f_mcp_man.read_bytes(), {"Cache-Control": "public, max-age=3600"})
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
        meta = self._get_request_meta()
        tag = "[API]" if meta["is_api"] else "[HTTP]"
        c_icon = meta["client_info"].get("icon", "🌐")
        c_name = meta["client_info"].get("client", "Client")
        c_country = f"[{meta['country']}] " if meta["country"] else ""
        print(f"{tag} {meta['now_str']} | {code} | {meta['dur_ms']:>6.1f}ms | 0 B | {meta['ip']:<15} | {c_country}{c_icon} {c_name} | {meta['host']} | {meta['cmd']} {meta['path']} -> {location}", flush=True)
        _record_api_stat(
            meta["ip"], meta["country"], meta["host"], meta["path"], meta["cmd"],
            code, 0, meta["dur_ms"], meta["ua"], meta["referer"], meta["client_info"]
        )
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

        meta = self._get_request_meta()
        tag = "[API]" if meta["is_api"] else "[HTTP]"
        c_icon = meta["client_info"].get("icon", "🌐")
        c_name = meta["client_info"].get("client", "Client")
        c_country = f"[{meta['country']}] " if meta["country"] else ""
        print(f"{tag} {meta['now_str']} | {code} | {meta['dur_ms']:>6.1f}ms | {len(body):>7} B | {meta['ip']:<15} | {c_country}{c_icon} {c_name} | {meta['host']} | {meta['cmd']} {meta['path']}", flush=True)
        _record_api_stat(
            meta["ip"], meta["country"], meta["host"], meta["path"], meta["cmd"],
            code, len(body), meta["dur_ms"], meta["ua"], meta["referer"], meta["client_info"]
        )

        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            link_header_val = (
                '</mcp/manifest.json>; rel="mcp-manifest", '
                '</.well-known/webmcp>; rel="webmcp-manifest", '
                '</.well-known/mcp.json>; rel="mcp-manifest", '
                '</.well-known/ai-catalog.json>; rel="ai-catalog"; type="application/json", '
                '</.well-known/ard.json>; rel="ard"; type="application/json", '
                '</llms.txt>; rel="describedby"'
            )
            if "text/html" in ctype or meta["clean_path"] in ("/", "/catalog", "/radar", "/faq") or "application/json" in ctype:
                self.send_header("Link", link_header_val)
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
