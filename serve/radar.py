"""
sne.space — Observers Radar & Real-Time Transient Feed Engine
Identifies active supernovae rising tonight (dm/dt < 0) and bright unclassified targets (m < 18.5)
for amateur and professional observational follow-up.
"""

from __future__ import annotations

import glob
import json
import math
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    from event_render import ra_to_deg, dec_to_deg, extract_coords
except Exception:
    from serve.event_render import ra_to_deg, dec_to_deg, extract_coords

ROOT = Path(__file__).resolve().parent.parent
SNE_DIRS = [
    ROOT / "serve/www/astrocats/astrocats/supernovae/output/sne-2025-2029",
    ROOT / "serve/www/astrocats/astrocats/supernovae/output/sne-2020-2024",
]

# Observatory presets
OBSERVATORIES = {
    "keck": {"name": "Keck Observatory (Mauna Kea, HI)", "lat": 19.826, "lon": -155.474, "tz": -10},
    "paranal": {"name": "VLT (Paranal, Chile)", "lat": -24.627, "lon": -70.404, "tz": -4},
    "palomar": {"name": "Palomar Observatory (CA)", "lat": 33.356, "lon": -116.865, "tz": -7},
    "lapalma": {"name": "Roque de los Muchachos (La Palma)", "lat": 28.760, "lon": -17.881, "tz": 0},
}

_RADAR_CACHE: list[dict[str, Any]] = []
_LAST_SCAN_TIME: float = 0.0


def scan_catalog_targets(limit: int = 1500) -> list[dict[str, Any]]:
    """Scan recent supernova catalogs and build lightweight radar records."""
    global _RADAR_CACHE, _LAST_SCAN_TIME

    now = time.time()
    if _RADAR_CACHE and (now - _LAST_SCAN_TIME) < 300:
        return _RADAR_CACHE

    records = []
    now_mjd = 40587.0 + now / 86400.0

    for sne_dir in SNE_DIRS:
        if not sne_dir.is_dir():
            continue
        for f in sne_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
                name = next(iter(data.keys()))
                ev = data[name]

                ra_deg, dec_deg, ra_str, dec_str = extract_coords(ev)
                if ra_deg is None or dec_deg is None:
                    continue

                ctype = "Candidate"
                if ev.get("claimedtype"):
                    first_ct = ev["claimedtype"][0]
                    ctype = first_ct.get("value", "Candidate") if isinstance(first_ct, dict) else str(first_ct)

                disc_date = "—"
                days_since_disc = 9999
                if ev.get("discoverdate"):
                    first_dd = ev["discoverdate"][0]
                    disc_date = first_dd.get("value", "—") if isinstance(first_dd, dict) else str(first_dd)
                    try:
                        clean_dd = disc_date.replace("/", "-").strip()
                        parts = clean_dd.split("-")
                        if len(parts) >= 3:
                            d_obj = datetime(int(parts[0]), int(parts[1]), int(parts[2]), tzinfo=timezone.utc)
                            days_since_disc = max(0, int((now - d_obj.timestamp()) / 86400.0))
                    except Exception:
                        pass

                # Process photometry
                photo = ev.get("photometry", [])
                valid_pts = []
                for p in photo:
                    if "time" in p and "magnitude" in p and not p.get("upperlimit", False):
                        try:
                            valid_pts.append({
                                "mjd": float(p["time"]),
                                "mag": float(p["magnitude"]),
                                "band": str(p.get("band", "other")),
                                "tel": str(p.get("telescope", ""))
                            })
                        except Exception:
                            continue

                if not valid_pts:
                    continue

                valid_pts.sort(key=lambda x: x["mjd"])
                min_mag = min(p["mag"] for p in valid_pts)
                latest_pt = valid_pts[-1]
                latest_mag = latest_pt["mag"]
                latest_mjd = latest_pt["mjd"]

                days_since_obs = max(0, int(now_mjd - latest_mjd))
                effective_age = min(days_since_obs, days_since_disc)

                # Rate of change dm/dt
                trend = "stable"
                rate = 0.0
                if len(valid_pts) >= 2:
                    prev_pt = valid_pts[-2]
                    dt = latest_mjd - prev_pt["mjd"]
                    if 0.1 <= dt <= 60.0:
                        dm = latest_mag - prev_pt["mag"]
                        rate = dm / dt
                        if rate < -0.02 and effective_age <= 60:
                            trend = "rising"
                        elif rate > 0.02 and effective_age <= 180:
                            trend = "fading"

                if effective_age <= 14:
                    lifecycle = "active"
                    if trend == "stable":
                        trend = "new"
                elif effective_age <= 60:
                    lifecycle = "active"
                elif effective_age <= 180:
                    lifecycle = "fading"
                else:
                    lifecycle = "extinguished"

                is_unclassified = (
                    not ctype or
                    ctype.lower() in ("candidate", "at", "other", "unknown", "") or
                    name.startswith("AT")
                )

                records.append({
                    "name": name,
                    "ra_deg": round(ra_deg, 5),
                    "dec_deg": round(dec_deg, 5),
                    "ra_str": ra_str,
                    "dec_str": dec_str,
                    "type": ctype,
                    "is_unclassified": is_unclassified,
                    "min_mag": round(min_mag, 2),
                    "latest_mag": round(latest_mag, 2),
                    "band": latest_pt["band"],
                    "trend": trend,
                    "lifecycle": lifecycle,
                    "days_since_obs": effective_age,
                    "rate_mag_day": round(rate, 3),
                    "discoverdate": disc_date,
                    "photo_count": len(valid_pts)
                })
            except Exception:
                continue

    # Sort so active recent discoveries are at the top
    def _sort_key(t):
        life_tier = 0 if t["lifecycle"] == "active" else (1 if t["lifecycle"] == "fading" else 2)
        return (life_tier, t["days_since_obs"], t["latest_mag"])

    records.sort(key=_sort_key)
    _RADAR_CACHE = records[:limit]
    _LAST_SCAN_TIME = now
    return _RADAR_CACHE


def compute_observability_for_targets(
    targets: list[dict[str, Any]],
    obs_key: str = "keck"
) -> list[dict[str, Any]]:
    """Calculate tonight's airmass and observability metrics for a list of targets."""
    site = OBSERVATORIES.get(obs_key, OBSERVATORIES["keck"])
    lat_deg = site["lat"]
    lon_deg = site["lon"]
    tz_offset = site["tz"]

    now = datetime.now(timezone.utc)
    now_utc_ts = now.timestamp()
    obs_local_now = datetime.fromtimestamp(now_utc_ts + tz_offset * 3600, tz=timezone.utc)

    # If currently in the morning (local < 12:00), the observing night started yesterday at 18:00
    if obs_local_now.hour < 12:
        start_local = (obs_local_now - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    else:
        start_local = obs_local_now.replace(hour=18, minute=0, second=0, microsecond=0)
    start_utc_ts = start_local.timestamp() - tz_offset * 3600

    # Precalculate sidereal time across 25 time steps (every 30 min from 18:00 to 06:00)
    time_steps = []
    for step in range(25):
        t_ts = start_utc_ts + step * 1800
        jd = (t_ts / 86400.0) + 2440587.5
        gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360.0
        if gmst < 0:
            gmst += 360.0
        lst_deg = (gmst + lon_deg) % 360.0
        if lst_deg < 0:
            lst_deg += 360.0
        time_steps.append((t_ts, lst_deg))

    lat_rad = math.radians(lat_deg)
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)

    enriched = []
    for t in targets:
        ra = t["ra_deg"]
        dec = t["dec_deg"]
        dec_rad = math.radians(dec)
        sin_dec = math.sin(dec_rad)
        cos_dec = math.cos(dec_rad)

        min_x = 999.0
        obs_hours = 0.0

        for _, lst_deg in time_steps:
            h_deg = lst_deg - ra
            h_rad = math.radians(h_deg)
            sin_alt = sin_lat * sin_dec + cos_lat * cos_dec * math.cos(h_rad)
            alt_rad = math.asin(max(-1.0, min(1.0, sin_alt)))
            alt_deg = math.degrees(alt_rad)
            z_deg = 90.0 - alt_deg

            if z_deg < 88.0:
                z_rad = math.radians(z_deg)
                denom = math.cos(z_rad) + 0.50572 * math.pow(96.07995 - z_deg, -1.6364)
                if denom > 0:
                    x = 1.0 / denom
                    if x < min_x:
                        min_x = x
                    if x <= 2.0:
                        obs_hours += 0.5

        t_copy = dict(t)
        t_copy["min_airmass"] = round(min_x, 2) if min_x < 5.0 else None
        t_copy["observable_hours"] = round(obs_hours, 1)
        t_copy["is_observable_tonight"] = obs_hours >= 1.0
        enriched.append(t_copy)

    return enriched


def render_radar_page(obs_key: str = "keck", filter_mode: str = "active") -> str:
    """Render the high-performance Observers Radar dashboard."""
    all_targets = scan_catalog_targets()
    enriched = compute_observability_for_targets(all_targets, obs_key=obs_key)

    site = OBSERVATORIES.get(obs_key, OBSERVATORIES["keck"])
    site_options_html = "".join(
        f'<option value="{k}" {"selected" if k == obs_key else ""}>{v["name"]}</option>'
        for k, v in OBSERVATORIES.items()
    )

    # Counts for tab badges
    count_active = len([t for t in enriched if t["lifecycle"] == "active" and t["is_observable_tonight"]])
    count_fresh = len([t for t in enriched if t.get("days_since_obs", 9999) <= 30 and t["is_observable_tonight"]])
    count_bright = len([t for t in enriched if t["latest_mag"] < 18.5 and t["is_observable_tonight"]])
    count_unclass = len([t for t in enriched if t["is_unclassified"] and t["is_observable_tonight"]])
    count_all = len([t for t in enriched if t["is_observable_tonight"]])

    # Filter targets
    if filter_mode in ("active", "rising"):
        filtered = [t for t in enriched if t["is_observable_tonight"] and t["lifecycle"] == "active"]
        if not filtered:
            filtered = [t for t in enriched if t["lifecycle"] == "active"]
        if not filtered:
            filtered = [t for t in enriched if t["is_observable_tonight"] and t.get("days_since_obs", 9999) <= 120]
        filtered.sort(key=lambda x: (x.get("days_since_obs", 9999), x.get("latest_mag", 99)))
    elif filter_mode == "discoveries":
        filtered = [t for t in enriched if t["is_observable_tonight"] and t.get("days_since_obs", 9999) <= 30]
        if not filtered:
            filtered = [t for t in enriched if t.get("days_since_obs", 9999) <= 30]
        filtered.sort(key=lambda x: (x.get("days_since_obs", 9999), x.get("latest_mag", 99)))
    elif filter_mode == "bright":
        filtered = [t for t in enriched if t["is_observable_tonight"] and t["latest_mag"] < 18.5]
        filtered.sort(key=lambda x: x["latest_mag"])
    elif filter_mode == "unclassified":
        filtered = [t for t in enriched if t["is_unclassified"] and t["is_observable_tonight"]]
        filtered.sort(key=lambda x: (x.get("days_since_obs", 9999), x.get("latest_mag", 99)))
    else:  # all observable
        filtered = [t for t in enriched if t["is_observable_tonight"]]
        filtered.sort(key=lambda x: (0 if x["lifecycle"] == "active" else 1, x.get("days_since_obs", 9999), x["latest_mag"]))

    # Table rows
    rows_html = []
    for t in filtered[:100]:
        t_name = t["name"]
        days = t.get("days_since_obs", 0)
        lifecycle = t.get("lifecycle", "extinguished")
        trend = t.get("trend", "stable")

        if lifecycle == "active":
            if trend == "new":
                trend_badge = f'<span class="badge badge-green">▲ New Discovery (+{days}d)</span>'
            elif trend == "rising":
                trend_badge = f'<span class="badge badge-green">▲ Rising (+{days}d)</span>'
            else:
                trend_badge = f'<span class="badge badge-green">● Active Outburst (+{days}d)</span>'
        elif lifecycle == "fading":
            trend_badge = f'<span class="badge badge-orange">▼ Late Fading (+{days}d)</span>'
        else:
            years = days / 365.25
            age_str = f"{years:.1f}y" if years >= 1.5 else f"{days}d"
            trend_badge = f'<span class="badge badge-gray">● Extinguished (+{age_str})</span>'

        type_badge = f'<span class="badge badge-blue">{t["type"]}</span>'
        if t["is_unclassified"]:
            type_badge = f'<span class="badge badge-orange">{t["type"] or "Unclassified"}</span>'

        airmass_str = f"{t['min_airmass']:.2f}" if t['min_airmass'] else "Below Horiz."
        win_str = f"{t['observable_hours']:.1f} hrs" if t['observable_hours'] > 0 else "0.0 hrs"

        target_note = (
            '<div style="font-size:0.7rem;color:#94a3b8">Host Galaxy Pointing</div>'
            if lifecycle == "extinguished"
            else '<div style="font-size:0.7rem;color:#34d399;font-weight:600">Active Transient</div>'
        )

        rows_html.append(f"""
        <tr>
          <td>
            <a href="/sne/{t_name}/" class="target-link"><strong>{t_name}</strong></a>
            <div style="font-size:0.75rem;color:var(--text-muted)">Discovered {t['discoverdate']}</div>
          </td>
          <td>{type_badge}</td>
          <td>
            <strong>{t['latest_mag']:.2f}</strong> <span style="font-size:0.75rem;color:var(--accent)">({t['band']})</span>
            <div style="margin-top:2px">{trend_badge}</div>
          </td>
          <td style="font-family:monospace;font-size:0.8rem">{t['ra_str']}<br>{t['dec_str']}</td>
          <td>
            <div style="font-weight:700;color:{'#22c55e' if t['observable_hours'] >= 2.0 else '#f59e0b'}">{win_str}</div>
            <div style="font-size:0.75rem;color:var(--text-muted)">Min Airmass: {airmass_str}</div>
            {target_note}
          </td>
          <td style="text-align:right">
            <a class="btn-sm" href="/sne/{t_name}/">Cockpit</a>
            <a class="btn-sm btn-outline" href="/sne/{t_name}/story">Story</a>
          </td>
        </tr>
        """)

    table_body = "".join(rows_html) if rows_html else "<tr><td colspan='6' style='text-align:center;padding:2rem'>No targets match the current filter.</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Observers Radar &amp; Target Feed — sne.space</title>
  <meta name="description" content="Live transient tracking feed for active supernovae, rising light curves, and unclassified targets observable tonight.">
  <link rel="ai-catalog" href="/.well-known/ai-catalog.json" type="application/json">
  <link rel="ard" href="/.well-known/ard.json" type="application/json">
  <link rel="webmcp-manifest" href="/.well-known/webmcp" type="application/json">
  <link rel="mcp-manifest" href="/.well-known/mcp.json" type="application/json">
  <link rel="describedby" href="/llms.txt" type="text/markdown">
  <style>
    :root {{
      --bg: #070a12;
      --card-bg: #131b2e;
      --border: #232f48;
      --text: #e2e8f0;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --tag-green: #22c55e;
      --tag-orange: #f97316;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      line-height: 1.5;
    }}
    header.cockpit-hdr {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      padding: 0.75rem 1.5rem;
      background: #070a12;
      border-bottom: 1px solid var(--border);
    }}
    .brand-title {{ font-weight: 700; font-size: 1.25rem; color: #fff; text-decoration: none; }}
    .radar-container {{
      max-width: 1200px;
      margin: 2rem auto;
      padding: 0 1.5rem;
    }}
    .radar-hero {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      flex-wrap: wrap;
      gap: 1.5rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 1.5rem;
      margin-bottom: 1.5rem;
    }}
    .radar-title h1 {{ font-size: 2rem; margin: 0; color: #fff; }}
    .radar-title p {{ margin: 0.25rem 0 0 0; color: var(--text-muted); font-size: 1rem; }}
    .radar-tabs {{
      display: flex;
      gap: 0.5rem;
      margin-bottom: 1rem;
      flex-wrap: wrap;
    }}
    .radar-tab {{
      padding: 0.5rem 1rem;
      background: var(--card-bg);
      border: 1px solid var(--border);
      color: var(--text-muted);
      border-radius: 6px;
      text-decoration: none;
      font-weight: 600;
      font-size: 0.9rem;
      cursor: pointer;
    }}
    .radar-tab.active {{
      background: #0284c7;
      color: #fff;
      border-color: #38bdf8;
    }}
    .controls-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.75rem 1rem;
      margin-bottom: 1.5rem;
      flex-wrap: wrap;
      gap: 1rem;
    }}
    .site-select {{
      background: #070a12;
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 0.4rem 0.8rem;
      font-size: 0.9rem;
    }}
    table.radar-table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }}
    table.radar-table th {{
      background: #0e1526;
      color: var(--text-muted);
      font-size: 0.75rem;
      text-transform: uppercase;
      padding: 0.75rem 1rem;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    table.radar-table td {{
      padding: 0.85rem 1rem;
      border-bottom: 1px solid rgba(255,255,255,0.05);
      vertical-align: middle;
    }}
    .badge {{
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 600;
    }}
    .badge-blue {{ background: #1e3a8a; color: #93c5fd; }}
    .badge-orange {{ background: #7c2d12; color: #fdba74; }}
    .badge-green {{ background: #064e3b; color: #6ee7b7; }}
    .badge-red {{ background: #7f1d1d; color: #fca5a5; }}
    .badge-gray {{ background: #1e293b; color: #94a3b8; }}
    .target-link {{ color: #fff; text-decoration: none; font-size: 1.05rem; }}
    .target-link:hover {{ color: var(--accent); }}
    .btn-sm {{
      display: inline-block;
      padding: 0.3rem 0.6rem;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 600;
      background: var(--accent);
      color: #070a12;
      text-decoration: none;
      margin-left: 0.25rem;
    }}
    .btn-sm.btn-outline {{
      background: transparent;
      color: var(--text);
      border: 1px solid var(--border);
    }}
  </style>
</head>
<body>
  <header class="cockpit-hdr">
    <a class="brand-title" href="/" title="sne.space — The Open Supernova Catalog" style="display:inline-flex;align-items:center;text-decoration:none;">
      <img src="/assets/img/logo-color.webp" alt="sne.space" style="height:38px;width:auto;vertical-align:middle;filter:drop-shadow(0 0 10px rgba(56,189,248,0.4));">
    </a>
    <form class="hdr-search-form" action="/" method="GET" 
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
          style="display:inline-flex;align-items:center;background:#0d1527;border:1px solid #1e293b;border-radius:20px;padding:3px 10px;"
          onsubmit="event.preventDefault(); var q=this.q.value.trim(); if(q) window.location.href='/sne/'+encodeURIComponent(q)+'/';">
      <input type="search" name="q" placeholder="Search 110k+ supernovae..." autocomplete="off" 
             toolparamtitle="supernova_query" 
             tool-param-title="supernova_query" 
             toolparamdescription="Supernova IAU designation, catalog name, or survey alias" 
             tool-param-description="Supernova IAU designation, catalog name, or survey alias" 
             aria-label="Search supernovae" 
             style="background:transparent;border:none;color:#fff;outline:none;font-size:0.85rem;width:220px;" required>
      <button type="submit" aria-label="Submit search" style="background:transparent;border:none;cursor:pointer;font-size:0.85rem;">🔍</button>
    </form>
    <div style="font-size:0.85rem;color:var(--text-muted)">
      Live Alert Feeds: <span style="color:#22c55e">● TNS / ZTF / ATLAS Online</span>
    </div>
  </header>

  <main class="radar-container">
    <div class="radar-hero">
      <div class="radar-title">
        <h1>Observers Radar &amp; Target Feed</h1>
        <p>Live transient tracking for active supernovae, rising light curves, and unclassified targets observable tonight.</p>
      </div>
      <div>
        <a href="/api/radar.json?obs={obs_key}" class="btn-sm btn-outline" download="radar_targets.json">📥 Export JSON</a>
        <a href="/api/radar.json?format=csv&obs={obs_key}" class="btn-sm btn-outline" download="radar_targets.csv">📊 Export CSV</a>
      </div>
    </div>

    <div style="margin-bottom:1.25rem;padding:0.75rem 1rem;background:rgba(56,189,248,0.06);border:1px solid rgba(56,189,248,0.25);border-radius:8px;font-size:0.83rem;line-height:1.5;color:#cbd5e1;">
      <strong>🔭 Astronomical Ephemeris vs. Physical Transience:</strong>
      The pointing window shows when celestial coordinates rise above airmass <em>X &lt; 2.0</em> from the chosen observatory tonight.
      Fresh, physically radiating transients in outburst are highlighted with <span class="badge badge-green" style="font-size:0.7rem">● Active Outburst</span> or <span class="badge badge-green" style="font-size:0.7rem">▲ New Discovery</span>, while older targets are marked <span class="badge badge-orange" style="font-size:0.7rem">▼ Late Fading</span> or <span class="badge badge-gray" style="font-size:0.7rem">● Extinguished</span>.
    </div>

    <div class="controls-bar">
      <div class="radar-tabs">
        <a class="radar-tab {'active' if filter_mode in ('active', 'rising') else ''}" href="?filter=active&obs={obs_key}">⚡ Active Supernovae ({count_active})</a>
        <a class="radar-tab {'active' if filter_mode == 'discoveries' else ''}" href="?filter=discoveries&obs={obs_key}">🎯 Fresh Discoveries (&lt;30d) ({count_fresh})</a>
        <a class="radar-tab {'active' if filter_mode == 'bright' else ''}" href="?filter=bright&obs={obs_key}">🌟 Bright Transients (m&lt;18.5) ({count_bright})</a>
        <a class="radar-tab {'active' if filter_mode == 'all' else ''}" href="?filter=all&obs={obs_key}">🔭 All Observable Tonight ({count_all})</a>
      </div>
      <div>
        <label style="font-size:0.85rem;color:var(--text-muted);margin-right:0.5rem">Observatory Site:</label>
        <select class="site-select" onchange="window.location.search = '?filter={filter_mode}&obs=' + this.value">
          {site_options_html}
        </select>
      </div>
    </div>

    <table class="radar-table">
      <thead>
        <tr>
          <th>Target</th>
          <th>Classification</th>
          <th>Catalog Mag (Epoch)</th>
          <th>Coordinates (J2000)</th>
          <th>Pointing Window ({site['name'].split(' ')[0]})</th>
          <th style="text-align:right">Actions</th>
        </tr>
      </thead>
      <tbody>
        {table_body}
      </tbody>
    </table>
  </main>
  <!-- WebMCP In-Browser Agentic Tools -->
  <script src="/assets/webmcp.js"></script>
</body>
</html>"""
    return html
