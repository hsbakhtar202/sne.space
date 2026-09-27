"""Sitemap Generator and Sharding Engine for sne.space.

Respects Google's 50,000 URLs per sitemap hard limit by sharding 110,000+ supernovae
into chronological epochs, plus a dedicated story/magazine sitemap index.
"""
from __future__ import annotations

import datetime
import json
import logging
import threading
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://sne.space"
CATALOG_PATH = Path("serve/www/astrocats/astrocats/supernovae/output/catalog.min.json")

# In-memory byte cache for generated sitemaps
_CACHE: Dict[str, bytes] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TIMESTAMP: Optional[datetime.date] = None


def _get_catalog_events() -> List[Dict]:
    """Load lightweight event summaries from catalog.min.json."""
    if not CATALOG_PATH.is_file():
        # Fallback to local relative check
        alt = Path("vendor/astrocats/astrocats/supernovae/output/catalog.min.json")
        if alt.is_file():
            return json.loads(alt.read_text(encoding="utf-8"))
        return []
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Failed to read catalog.min.json for sitemaps: %s", e)
        return []


def _extract_year(event: Dict) -> int:
    """Extract discovery year from event dict."""
    d = event.get("discoverdate", [{}])
    val = ""
    if isinstance(d, list) and d:
        val = d[0].get("value", "") if isinstance(d[0], dict) else str(d[0])
    elif isinstance(d, str):
        val = d
    if val:
        try:
            return int(val.replace("-", "/").split("/")[0].split(".")[0])
        except (ValueError, IndexError):
            pass
    # Fallback: extract year from name if standard IAU pattern SNYYYY... or ATYYYY...
    name = event.get("name", "")
    if isinstance(name, list) and name:
        name = name[0].get("value", "") if isinstance(name[0], dict) else str(name[0])
    if name.startswith(("SN", "AT")) and len(name) >= 6 and name[2:6].isdigit():
        return int(name[2:6])
    return 0


def build_sitemaps() -> Dict[str, bytes]:
    """Generate all sitemap shards and the sitemap index."""
    today_str = datetime.date.today().isoformat()
    events = _get_catalog_events()

    # Buckets:
    # 1. historical_1: < 2015 (~27k)
    # 2. historical_2: 2015-2019 (~27k)
    # 3. modern_1: 2020-2022 (~28k)
    # 4. modern_2: 2023-2024 (~24k)
    # 5. current: 2025-2029+ (~3k, daily updates)
    # 6. stories: high-value consumer dossiers (Tier 1 & Tier 2)

    buckets: Dict[str, List[str]] = {
        "historical_1": [],
        "historical_2": [],
        "modern_1": [],
        "modern_2": [],
        "current": [],
        "stories": [],
    }

    for ev in events:
        name = ev.get("name")
        if isinstance(name, list) and name:
            name = name[0].get("value") if isinstance(name[0], dict) else str(name[0])
        if not name:
            continue

        safe_name = urllib.parse.quote(str(name))
        year = _extract_year(ev)

        if year < 2015:
            buckets["historical_1"].append(safe_name)
        elif year <= 2019:
            buckets["historical_2"].append(safe_name)
        elif year <= 2022:
            buckets["modern_1"].append(safe_name)
        elif year <= 2024:
            buckets["modern_2"].append(safe_name)
        else:
            buckets["current"].append(safe_name)

        # High-interest transients get Story Mode indexing
        photo_count = 0
        p = ev.get("photometry")
        if isinstance(p, list):
            photo_count = len(p)
        elif isinstance(p, int):
            photo_count = p

        claimed = ev.get("claimedtype", [{}])
        c_type = claimed[0].get("value", "") if isinstance(claimed, list) and claimed else ""

        if year >= 2020 or photo_count >= 10 or (c_type and c_type != "?"):
            # Sample stories to keep stories sitemap lean and top-tier
            if len(buckets["stories"]) < 45000:
                buckets["stories"].append(safe_name)

    results: Dict[str, bytes] = {}

    # Build individual urlsets
    for shard_name, names in buckets.items():
        xml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]
        is_current = shard_name == "current"
        is_story = shard_name == "stories"
        freq = "daily" if is_current else "monthly"
        prio = "0.9" if is_current else ("0.8" if is_story else "0.6")

        for n in names:
            loc = f"{BASE_URL}/sne/{n}/story" if is_story else f"{BASE_URL}/sne/{n}/"
            xml_lines.append(
                f"  <url><loc>{loc}</loc><changefreq>{freq}</changefreq><priority>{prio}</priority></url>"
            )
        xml_lines.append("</urlset>")
        results[f"sitemap_{shard_name}.xml"] = "\n".join(xml_lines).encode("utf-8")

    # Build root sitemapindex
    index_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    shard_order = [
        "sitemap_current.xml",
        "sitemap_stories.xml",
        "sitemap_modern_2.xml",
        "sitemap_modern_1.xml",
        "sitemap_historical_2.xml",
        "sitemap_historical_1.xml",
    ]
    for s in shard_order:
        index_lines.append(
            f"  <sitemap><loc>{BASE_URL}/{s}</loc><lastmod>{today_str}</lastmod></sitemap>"
        )
    index_lines.append("</sitemapindex>")
    results["sitemap.xml"] = "\n".join(index_lines).encode("utf-8")

    return results


def get_sitemap(filename: str) -> Optional[bytes]:
    """Retrieve sitemap bytes from memory cache, refreshing daily."""
    global _CACHE, _CACHE_TIMESTAMP
    today = datetime.date.today()
    with _CACHE_LOCK:
        if not _CACHE or _CACHE_TIMESTAMP != today:
            _CACHE = build_sitemaps()
            _CACHE_TIMESTAMP = today
        return _CACHE.get(filename)
