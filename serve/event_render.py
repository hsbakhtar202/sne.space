#!/usr/bin/env python3
"""Renderer for sne.space modern Pro Cockpit and Story Mode views.

Implements Phase 1 & Phase 2 specifications from plan.md:
- Dual-Layer Host Galaxy Optical Cutouts (DESI Legacy DR10 + NASA SkyView DSS2)
- Aladin Lite v3 WebGL Interactive Crosshair Sky Viewer
- Multi-band Interactive Light Curve Engine (Plotly.js WebGL with band filtering & upper limits)
- Stacked Interactive Spectra Viewer (de-redshifting & atomic feature overlays)
- Discovery Before/After Blink Comparison Slider
- BibTeX Generation and Academic Literature Metadata
- Science-on-Schema.org Dataset JSON-LD structured data
"""
from __future__ import annotations

import json
import math
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any

try:
    from cone_search import find_closest_events
except Exception:
    try:
        from serve.cone_search import find_closest_events
    except Exception:
        find_closest_events = None

try:
    from faq_engine import (
        generate_supernova_faqs,
        build_faq_html,
        build_faq_jsonld,
        generate_story_article_html,
        build_article_jsonld,
        get_lookback_geological_era,
        calculate_solar_luminosities,
        identify_constellation,
    )
except Exception:
    try:
        from serve.faq_engine import (
            generate_supernova_faqs,
            build_faq_html,
            build_faq_jsonld,
            generate_story_article_html,
            build_article_jsonld,
            get_lookback_geological_era,
            calculate_solar_luminosities,
            identify_constellation,
        )
    except Exception:
        generate_supernova_faqs = None
        build_faq_html = None
        build_faq_jsonld = None
        generate_story_article_html = None
        build_article_jsonld = None
        get_lookback_geological_era = None
        calculate_solar_luminosities = None
        identify_constellation = None

try:
    from blockbuster_articles import get_blockbuster_article
except Exception:
    try:
        from serve.blockbuster_articles import get_blockbuster_article
    except Exception:
        get_blockbuster_article = None


def ra_to_deg(ra_str: str | None, u_val: str | None = None) -> float | None:
    """Convert Right Ascension string (sexagesimal or decimal) to decimal degrees (0..360)."""
    if not ra_str or ra_str in ("—", "-", "None"):
        return None
    ra_str = str(ra_str).strip()
    parts = re.split(r"[:\s]+", ra_str)
    try:
        if len(parts) == 3:
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return (h + m / 60.0 + s / 3600.0) * 15.0
        elif len(parts) == 2:
            h, m = float(parts[0]), float(parts[1])
            return (h + m / 60.0) * 15.0
        elif len(parts) == 1:
            val = float(parts[0])
            if u_val == "hours":
                return val * 15.0
            if val > 24.0:
                return val
            return val * 15.0 if u_val != "degrees" and val <= 24.0 else val
    except Exception:
        return None
    return None


def dec_to_deg(dec_str: str | None, u_val: str | None = None) -> float | None:
    """Convert Declination string (sexagesimal or decimal) to decimal degrees (-90..+90)."""
    if not dec_str or dec_str in ("—", "-", "None"):
        return None
    dec_str = str(dec_str).strip()
    sign = -1.0 if dec_str.startswith("-") else 1.0
    clean = dec_str.lstrip("+-")
    parts = re.split(r"[:\s]+", clean)
    try:
        if len(parts) == 3:
            d, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return sign * (d + m / 60.0 + s / 3600.0)
        elif len(parts) == 2:
            d, m = float(parts[0]), float(parts[1])
            return sign * (d + m / 60.0)
        elif len(parts) == 1:
            return float(dec_str)
    except Exception:
        return None
    return None


def extract_coords(meta: dict) -> tuple[float | None, float | None, str, str]:
    """Extract decimal degrees and original sexagesimal strings for RA and Dec."""
    ra_entry = meta.get("ra", [{}])
    dec_entry = meta.get("dec", [{}])
    ra_val = ""
    ra_u = None
    if isinstance(ra_entry, list) and ra_entry:
        first = ra_entry[0]
        if isinstance(first, dict):
            ra_val = str(first.get("value", ""))
            ra_u = first.get("u_value")
        else:
            ra_val = str(first)
    elif isinstance(ra_entry, dict):
        ra_val = str(ra_entry.get("value", ""))
        ra_u = ra_entry.get("u_value")
    elif isinstance(ra_entry, str):
        ra_val = ra_entry

    dec_val = ""
    dec_u = None
    if isinstance(dec_entry, list) and dec_entry:
        first = dec_entry[0]
        if isinstance(first, dict):
            dec_val = str(first.get("value", ""))
            dec_u = first.get("u_value")
        else:
            dec_val = str(first)
    elif isinstance(dec_entry, dict):
        dec_val = str(dec_entry.get("value", ""))
        dec_u = dec_entry.get("u_value")
    elif isinstance(dec_entry, str):
        dec_val = dec_entry

    ra_deg = ra_to_deg(ra_val, ra_u)
    dec_deg = dec_to_deg(dec_val, dec_u)
    return ra_deg, dec_deg, ra_val, dec_val


def get_val(obj: dict, key: str, default: str = "—") -> str:
    """Extract a scalar string value from an AstroCats field."""
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


def extract_host_offset(meta: dict, ra_deg: float | None, dec_deg: float | None, redshift_str: str, lumdist_str: str) -> str:
    """Calculate physical projected offset (kpc) and angular separation (arcsec) from host galaxy."""
    host_offset_ang = get_val(meta, "hostoffsetang")
    host_offset_dist = get_val(meta, "hostoffsetdist")

    # If angular offset not recorded, check if hostra / hostdec are available to compute it
    if host_offset_ang == "—":
        host_ra_raw = get_val(meta, "hostra")
        host_dec_raw = get_val(meta, "hostdec")
        if host_ra_raw != "—" and host_dec_raw != "—" and ra_deg is not None and dec_deg is not None:
            try:
                h_ra_entry = meta.get("hostra", [{}])[0] if isinstance(meta.get("hostra"), list) else meta.get("hostra", {})
                h_dec_entry = meta.get("hostdec", [{}])[0] if isinstance(meta.get("hostdec"), list) else meta.get("hostdec", {})
                h_ra_u = h_ra_entry.get("u_value") if isinstance(h_ra_entry, dict) else None
                h_dec_u = h_dec_entry.get("u_value") if isinstance(h_dec_entry, dict) else None
                h_ra_deg = ra_to_deg(host_ra_raw, h_ra_u)
                h_dec_deg = dec_to_deg(host_dec_raw, h_dec_u)
                if h_ra_deg is not None and h_dec_deg is not None:
                    r1 = math.radians(ra_deg)
                    d1 = math.radians(dec_deg)
                    r2 = math.radians(h_ra_deg)
                    d2 = math.radians(h_dec_deg)
                    cos_theta = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
                    sep_deg = math.degrees(math.acos(max(-1.0, min(1.0, cos_theta))))
                    sep_arcsec = sep_deg * 3600.0
                    host_offset_ang = f"{sep_arcsec:.2f}″"
            except Exception:
                pass
    elif not host_offset_ang.endswith("″") and not host_offset_ang.endswith("arcsec"):
        try:
            val_flt = float(host_offset_ang)
            host_offset_ang = f"{val_flt:.2f}″"
        except Exception:
            host_offset_ang += "″"

    # Compute physical projected kpc offset if not recorded but angular offset + distance are available
    if host_offset_dist == "—" and host_offset_ang != "—":
        try:
            clean_ang = float(host_offset_ang.replace("″", "").replace("arcsec", "").strip())
            z_val = float(redshift_str) if (redshift_str != "—" and re.match(r'^-?\d+(\.\d+)?$', redshift_str)) else None
            d_l_val = None
            if lumdist_str != "—":
                m = re.search(r'([\d.]+)', lumdist_str)
                if m:
                    d_l_val = float(m.group(1))
            if d_l_val and z_val is not None and z_val >= 0:
                # Angular diameter distance d_A = d_L / (1 + z)^2
                d_a_mpc = d_l_val / ((1.0 + z_val) ** 2)
                # 1 rad = 206264.806 arcsec, 1 Mpc = 1000 kpc
                kpc_val = d_a_mpc * (clean_ang / 206264.806) * 1000.0
                host_offset_dist = f"{kpc_val:.2f} kpc"
        except Exception:
            pass
    elif host_offset_dist != "—" and not host_offset_dist.endswith("kpc"):
        try:
            val_flt = float(host_offset_dist)
            host_offset_dist = f"{val_flt:.2f} kpc"
        except Exception:
            host_offset_dist += " kpc"

    if host_offset_ang != "—" and host_offset_dist != "—":
        return f"{host_offset_ang} ({host_offset_dist})"
    elif host_offset_ang != "—":
        return host_offset_ang
    elif host_offset_dist != "—":
        return host_offset_dist
    return "—"


def generate_bibtex(name: str, meta: dict) -> str:
    """Generate BibTeX entries for primary sources cited in this event."""
    entries = []
    # Primary OSC citation
    entries.append(
        f"@article{{Guillochon2017,\n"
        f"  author = {{{{Guillochon}}}}, J. and {{{{Parrent}}}}, J. and {{{{Kelley}}}}, L.~Z. and {{{{Margutti}}}}, R.}},\n"
        f'  title = "{{An Open Catalog for Supernova Data}}",\n'
        f"  journal = {{\\apj}},\n"
        f"  year = 2017,\n"
        f"  volume = 835,\n"
        f"  pages = {{64}},\n"
        f"  doi = {{10.3847/1538-4357/835/1/64}},\n"
        f"  adsurl = {{https://ui.adsabs.harvard.edu/abs/2017ApJ...835...64G}}\n"
        f"}}"
    )
    for src in meta.get("sources", []):
        bibcode = src.get("bibcode")
        if bibcode and len(bibcode) == 19:
            ref = src.get("reference") or src.get("name") or "Primary Reference"
            safe_key = re.sub(r"[^a-zA-Z0-9_]", "_", bibcode)
            entries.append(
                f"@misc{{{safe_key},\n"
                f'  title = "{{Supernova {name} Data Attribution}}",\n'
                f'  note = "{{ADS Bibcode: {bibcode} ({ref})}}",\n'
                f"  howpublished = {{\\url{{https://ui.adsabs.harvard.edu/abs/{urllib.parse.quote(bibcode)}}}}}\n"
                f"}}"
            )
    return "\n\n".join(entries)


def get_transient_lifecycle(
    meta: dict,
    tel_guidance: str = "",
    host_name: str = "",
    event_name: str = "",
    redshift: str = "",
    claimedtype: str = "",
) -> dict:
    """Analyze the observational lifecycle state and compute physical transient detectability.

    Science-based engine utilizing:
    1. Cosmological time dilation: t_rest = delta_t_obs / (1 + z)
    2. Class-specific radioactive / CSM light curve decay models:
       - Type Ia: Nickel-56 / Cobalt-56 exponential decay tail
       - Type II-P: Recombination plateau (slow ~0.005 mag/day) followed by Cobalt tail
       - Type Ib/c: Stripped envelope radioactive decay
       - Type IIn / SLSN: Circumstellar interaction / central magnetar engine
       - Kilonovae: Rapid r-process decay
    3. Instrument aperture comparison:
       Calculates m_current = m_peak + dm(t_rest, type) and determines exactly which
       ground telescopes (binoculars, 4", 8"-12", CMOS camera, 2m, 10m Keck/VLT) or space
       observatories (HST/JWST) could resolve it at peak vs. tonight.
    """
    now = datetime.now(timezone.utc)
    now_mjd = 2440587.5 + now.timestamp() / 86400.0 - 2400000.5

    disc_date = get_val(meta, "discoverdate")
    max_date = get_val(meta, "maxdate")
    maxappmag_str = get_val(meta, "maxappmag")
    ref_date = max_date if max_date != "—" else disc_date

    # Parse Redshift z
    z_val = 0.0
    if redshift and redshift != "—":
        try:
            m = re.search(r"[-+]?\d*\.?\d+", str(redshift))
            if m:
                z_val = max(0.0, float(m.group(0)))
        except Exception:
            pass

    ctype = claimedtype.lower() if claimedtype else get_val(meta, "claimedtype").lower()

    # Days since explosion / discovery
    days_since = None
    if ref_date != "—":
        try:
            parts = [int(p) for p in re.split(r"[-/]", ref_date) if p.isdigit()]
            if parts:
                y = parts[0]
                m = parts[1] if len(parts) > 1 else 1
                d = parts[2] if len(parts) > 2 else 1
                if 1 <= y <= 9999 and 1 <= m <= 12 and 1 <= d <= 31:
                    dt = datetime(y, m, d, tzinfo=timezone.utc)
                    days_since = (now - dt).days
                elif y < 1:
                    days_since = 1000000
        except Exception:
            pass

    if days_since is None:
        photo = meta.get("photometry", [])
        mjds = []
        for p in photo:
            if "time" in p:
                try:
                    mjds.append(float(p["time"]))
                except Exception:
                    pass
        if mjds:
            days_since = int(now_mjd - max(mjds))

    host_target = f"host galaxy ({host_name})" if host_name and host_name != "—" else "host galaxy"

    if days_since is None:
        return {
            "phase": "unknown",
            "days_since": None,
            "ref_date": ref_date,
            "m_current_est": None,
            "badge_html": '<span class="type-pill" style="background:#1e293b;color:#94a3b8;border:1px solid #334155;">● Epoch Uncataloged</span>',
            "cockpit_notice": (
                '<div style="margin-bottom:0.75rem;padding:0.5rem 0.75rem;background:rgba(100,116,139,0.12);'
                'border-left:3px solid #64748b;border-radius:4px;font-size:0.78rem;line-height:1.4;color:#cbd5e1;">'
                '<strong>Target Ephemeris:</strong> Plots nightly altitude and airmass for target coordinates. Verify transient brightness before observing.'
                '</div>'
            ),
            "story_guidance_html": (
                '<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);padding:1.25rem;border-radius:6px;margin:1rem 0;">'
                f'<p style="margin:0;color:var(--text-muted);line-height:1.6;">Discovery epoch unrecorded in public catalog. Peak brightness rated at magnitude {maxappmag_str}.</p>'
                '</div>'
            ),
        }

    # Rest frame days accounting for cosmological time dilation
    t_rest = max(0.0, float(days_since) / (1.0 + z_val))

    # Peak apparent magnitude
    m_peak = None
    if maxappmag_str != "—":
        try:
            m_peak = float(re.sub(r"[^\d.]", "", maxappmag_str))
        except Exception:
            pass
    if m_peak is None:
        photo = meta.get("photometry", [])
        valid_mags = []
        for p in photo:
            if "magnitude" in p and not p.get("upperlimit", False):
                try:
                    valid_mags.append(float(p["magnitude"]))
                except Exception:
                    pass
        m_peak = min(valid_mags) if valid_mags else 18.0

    # Class-dependent delta magnitude decay calculation based on standard supernova light curve physics
    if "ia" in ctype:
        # Type Ia: Phillips relation early decline + Co-56 tail
        if t_rest <= 15.0:
            dm = 0.0
        elif t_rest <= 40.0:
            dm = 0.08 * (t_rest - 15.0)
        else:
            dm = 2.0 + 0.015 * (t_rest - 40.0)
    elif "iip" in ctype or "ii-p" in ctype or ("ii" in ctype and "iin" not in ctype and "iib" not in ctype):
        # Type II-P: Hydrogen recombination plateau for ~90-100 days, then Co-56 tail
        if t_rest <= 90.0:
            dm = 0.005 * t_rest
        elif t_rest <= 120.0:
            dm = 0.45 + 0.06 * (t_rest - 90.0)
        else:
            dm = 2.25 + 0.0098 * (t_rest - 120.0)
    elif "iin" in ctype or "slsn" in ctype or "magnetar" in ctype:
        # Circumstellar medium (CSM) shock interaction or central magnetar spin-down engine
        dm = 0.006 * t_rest
    elif "ib" in ctype or "ic" in ctype or "iib" in ctype:
        # Stripped-envelope core-collapse
        if t_rest <= 15.0:
            dm = 0.0
        elif t_rest <= 45.0:
            dm = 0.07 * (t_rest - 15.0)
        else:
            dm = 2.1 + 0.016 * (t_rest - 45.0)
    elif "kilonova" in ctype or "at2017gfo" in event_name.lower():
        # Rapid radioactive r-process decay
        dm = 0.35 * t_rest
    else:
        # Generic transient decay
        if t_rest <= 20.0:
            dm = 0.04 * t_rest
        else:
            dm = 0.8 + 0.014 * (t_rest - 20.0)

    m_current = round(m_peak + dm, 2)

    # Telescope Aperture Matrix definition
    telescopes = [
        ("Naked Eye", 6.0, "Dark sky site (Bortle 1–3) with no optical aid"),
        ("Binoculars (50mm)", 9.5, "Standard 7x50 or 10x50 handheld binoculars"),
        ("Small Backyard Scope (4\" / 100mm)", 12.0, "Entry 4-inch (100mm) refractor / reflector"),
        ("Medium Amateur Scope (8\"–12\")", 14.5, "8-inch to 12-inch Dobsonian or Schmidt-Cassegrain"),
        ("Amateur CMOS Rig", 19.5, "Cooled monochrome/color CMOS camera with multi-hour stack"),
        ("2m–3m Research Telescope", 22.0, "University or regional observatory (e.g. Palomar 60\", Calar Alto)"),
        ("Giant 8m–10m Observatories", 25.0, "Keck (10m), VLT (8.2m), Gemini, Subaru optical imaging"),
        ("Space Observatories Only", 30.0, "Hubble Space Telescope (WFC3) / JWST (NIRCam deep stack)")
    ]

    # Evaluate telescope requirements
    peak_tel_needed = "Space Observatories Only"
    for t_name, limit, desc in telescopes:
        if m_peak <= limit:
            peak_tel_needed = t_name
            break

    current_tel_needed = "Extinguished from ground (requires space telescopes: HST / JWST)"
    for t_name, limit, desc in telescopes:
        if m_current <= limit:
            current_tel_needed = t_name
            break

    is_ground_detectable = m_current <= 25.0

    # Build telescope comparison HTML table
    tel_rows = []
    for t_name, limit, desc in telescopes:
        peak_ok = m_peak <= limit
        now_ok = m_current <= limit
        peak_badge = '<span style="color:#34d399;font-weight:700;">✅ Detectable</span>' if peak_ok else '<span style="color:#64748b;">❌ Below limit</span>'
        now_badge = '<span style="color:#34d399;font-weight:700;">✅ Detectable</span>' if now_ok else '<span style="color:#64748b;">❌ Below limit</span>'
        tel_rows.append(f"""
        <tr>
          <td style="padding:0.45rem 0.6rem;font-weight:600;color:#f1f5f9;border-bottom:1px solid rgba(255,255,255,0.05);">{t_name}<div style="font-size:0.75rem;color:var(--text-muted);font-weight:400;">{desc}</div></td>
          <td style="padding:0.45rem 0.6rem;text-align:center;font-family:monospace;color:var(--accent);border-bottom:1px solid rgba(255,255,255,0.05);">m &le; {limit:.1f}</td>
          <td style="padding:0.45rem 0.6rem;text-align:center;border-bottom:1px solid rgba(255,255,255,0.05);">{peak_badge}</td>
          <td style="padding:0.45rem 0.6rem;text-align:center;border-bottom:1px solid rgba(255,255,255,0.05);">{now_badge}</td>
        </tr>
        """)
    tel_table_html = f"""
    <div style="overflow-x:auto;margin:1rem 0;background:rgba(15,23,42,0.6);border:1px solid var(--border);border-radius:6px;">
      <table style="width:100%;border-collapse:collapse;font-size:0.83rem;text-align:left;">
        <thead>
          <tr style="background:rgba(255,255,255,0.04);border-bottom:1px solid var(--border);color:var(--text-muted);">
            <th style="padding:0.5rem 0.6rem;">Instrument Class &amp; Aperture</th>
            <th style="padding:0.5rem 0.6rem;text-align:center;">Sensitivity Limit</th>
            <th style="padding:0.5rem 0.6rem;text-align:center;">At Peak Maximum (m={m_peak:.2f})</th>
            <th style="padding:0.5rem 0.6rem;text-align:center;">Tonight (Est. m&approx;{m_current:.1f})</th>
          </tr>
        </thead>
        <tbody>
          {"".join(tel_rows)}
        </tbody>
      </table>
    </div>
    """

    years = days_since / 365.25
    time_str = f"{years:.1f} years ago" if years >= 1.5 else f"{days_since} days ago"

    if years >= 30:
        badge = f'<span class="type-pill" style="background:#1e1b4b;color:#c084fc;border:1px solid #4338ca;">● Remnant Era ({int(years)}y)</span>'
        cockpit_notice = (
            f'<div style="margin-bottom:0.75rem;padding:0.5rem 0.75rem;background:rgba(192,132,252,0.1);'
            f'border-left:3px solid #c084fc;border-radius:4px;font-size:0.78rem;line-height:1.4;color:#e9d5ff;">'
            f'<strong>Remnant Era Target:</strong> This supernova exploded {int(years)} years ago ({ref_date}). '
            f'The original optical transient is extinguished; telescope pointing at these coordinates observes the '
            f'expanding remnant nebula or {host_target}.'
            f'</div>'
        )
        story_guidance = (
            f'<div style="background:rgba(192,132,252,0.05);border:1px solid rgba(192,132,252,0.25);border-left:4px solid #c084fc;padding:1.25rem;border-radius:6px;margin:1rem 0;">'
            f'<h3 style="margin:0 0 0.5rem 0;color:#f3e8ff;font-size:1.05rem;">Can I see it tonight? <span style="color:#c084fc;">Only as an expanding historical remnant.</span></h3>'
            f'<p style="margin:0 0 0.75rem 0;color:var(--text-muted);line-height:1.6;">'
            f'The optical supernova exploded <strong>{int(years)} years ago</strong> ({ref_date}). The bright transient outburst has long since ceased, '
            f'leaving behind an expanding gaseous shell or pulsar wind nebula emitting in radio, X-rays, and faint nebular optical lines.'
            f'</p>'
            f'<p style="margin:0;color:var(--text-muted);line-height:1.6;">'
            f'<strong>Historical Maximum:</strong> At peak in {ref_date}, it reached magnitude {m_peak:.2f} ({peak_tel_needed}). Pointing here tonight observes the {host_target}.'
            f'</p>'
            f'{tel_table_html}'
            f'</div>'
        )
        return {
            "phase": "remnant",
            "days_since": days_since,
            "t_rest": round(t_rest, 1),
            "m_peak": m_peak,
            "m_current": m_current,
            "time_str": time_str,
            "ref_date": ref_date,
            "badge_html": badge,
            "cockpit_notice": cockpit_notice,
            "story_guidance_html": story_guidance,
            "tel_table_html": tel_table_html,
        }
    elif days_since > 180 or not is_ground_detectable:
        badge = f'<span class="type-pill" style="background:#1e293b;color:#94a3b8;border:1px solid #334155;">● Extinguished Transient (+{days_since}d)</span>'
        cockpit_notice = (
            f'<div style="margin-bottom:0.75rem;padding:0.5rem 0.75rem;background:rgba(100,116,139,0.12);'
            f'border-left:3px solid #64748b;border-radius:4px;font-size:0.78rem;line-height:1.4;color:#cbd5e1;">'
            f'⚠️ <strong>Coordinate Pointing Only:</strong> The supernova exploded {time_str} ({ref_date}, rest-frame phase +{t_rest:.1f}d). '
            f'Based on standard radioactive decay physics, it has faded to <span style="color:#f87171;font-weight:600;">m &approx; {m_current:.1f}</span> (beyond ground telescope limits). '
            f'Telescope pointing tonight observes the <strong>{host_target}</strong>, not the vanished transient.'
            f'</div>'
        )
        story_guidance = (
            f'<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-left:4px solid #64748b;padding:1.25rem;border-radius:6px;margin:1rem 0;">'
            f'<h3 style="margin:0 0 0.5rem 0;color:#f1f5f9;font-size:1.05rem;">Can I see it tonight? <span style="color:#f87171;">No — this supernova is physically extinguished.</span></h3>'
            f'<p style="margin:0 0 0.75rem 0;color:var(--text-muted);line-height:1.6;">'
            f'Supernovae are brief, explosive cosmic catastrophes. They brighten over days to weeks and then permanently fade into darkness as their radioactive '
            f'nickel-56 and cobalt-56 fuel decays. This explosion occurred <strong>{time_str}</strong> ({ref_date}). '
            f'Accounting for cosmological time dilation at redshift z = {z_val:.4f}, the rest-frame age is <strong>+{t_rest:.1f} days</strong>. '
            f'By standard radioactive decay templates, its optical brightness has decayed by &Delta;m &approx; {dm:.1f} magnitudes to an estimated <strong>magnitude {m_current:.1f}</strong>, '
            f'rendering the transient undetectable to all ground-based observatories.'
            f'</p>'
            f'<p style="margin:0;color:var(--text-muted);line-height:1.6;">'
            f'<strong>Instrument Breakdown:</strong> At its maximum brightness in {ref_date}, it reached magnitude {m_peak:.2f} ({peak_tel_needed}). '
            f'Tonight, pointing a telescope at these coordinates will reveal only the background {host_target}.'
            f'</p>'
            f'{tel_table_html}'
            f'</div>'
        )
        return {
            "phase": "extinguished",
            "days_since": days_since,
            "t_rest": round(t_rest, 1),
            "m_peak": m_peak,
            "m_current": m_current,
            "time_str": time_str,
            "ref_date": ref_date,
            "badge_html": badge,
            "cockpit_notice": cockpit_notice,
            "story_guidance_html": story_guidance,
            "tel_table_html": tel_table_html,
        }
    elif days_since >= 60:
        badge = f'<span class="type-pill" style="background:#451a03;color:#fb923c;border:1px solid #9a3412;">● Late Fading (+{days_since}d)</span>'
        cockpit_notice = (
            f'<div style="margin-bottom:0.75rem;padding:0.5rem 0.75rem;background:rgba(245,158,11,0.12);'
            f'border-left:3px solid #f59e0b;border-radius:4px;font-size:0.78rem;line-height:1.4;color:#fde68a;">'
            f'📉 <strong>Late Fading Tail:</strong> Discovered {days_since} days ago ({ref_date}, rest-frame +{t_rest:.1f}d). '
            f'Currently decaying along its radioactive tail at estimated <span style="font-weight:700;color:#fbbf24;">m &approx; {m_current:.1f}</span> '
            f'({current_tel_needed}). Check airmass window below.'
            f'</div>'
        )
        story_guidance = (
            f'<div style="background:rgba(245,158,11,0.05);border:1px solid rgba(245,158,11,0.25);border-left:4px solid #f59e0b;padding:1.25rem;border-radius:6px;margin:1rem 0;">'
            f'<h3 style="margin:0 0 0.5rem 0;color:#fde68a;font-size:1.05rem;">Can I see it tonight? <span style="color:#fbbf24;">Fading in late-time nebular phase.</span></h3>'
            f'<p style="margin:0 0 0.75rem 0;color:#e2e8f0;line-height:1.6;">'
            f'Discovered <strong>{days_since} days ago</strong> ({ref_date}), this supernova has passed peak luminosity and has decayed by &Delta;m &approx; {dm:.1f} magnitudes to an estimated <strong>magnitude {m_current:.1f}</strong>.'
            f'</p>'
            f'<p style="margin:0;color:#cbd5e1;line-height:1.6;">'
            f'<strong>Viewing Guidance:</strong> {current_tel_needed}.'
            f'</p>'
            f'{tel_table_html}'
            f'</div>'
        )
        return {
            "phase": "fading",
            "days_since": days_since,
            "t_rest": round(t_rest, 1),
            "m_peak": m_peak,
            "m_current": m_current,
            "time_str": time_str,
            "ref_date": ref_date,
            "badge_html": badge,
            "cockpit_notice": cockpit_notice,
            "story_guidance_html": story_guidance,
            "tel_table_html": tel_table_html,
        }
    else:
        badge = f'<span class="type-pill" style="background:#064e3b;color:#34d399;border:1px solid #059669;">● Active Outburst (+{days_since}d)</span>'
        cockpit_notice = (
            f'<div style="margin-bottom:0.75rem;padding:0.5rem 0.75rem;background:rgba(16,185,129,0.12);'
            f'border-left:3px solid #10b981;border-radius:4px;font-size:0.78rem;line-height:1.4;color:#a7f3d0;">'
            f'✨ <strong>Active Transient Alert:</strong> Discovered only {days_since} days ago ({ref_date}, rest-frame +{t_rest:.1f}d)! '
            f'Currently in active outburst at estimated <span style="font-weight:700;color:#34d399;">m &approx; {m_current:.1f}</span> '
            f'({current_tel_needed}). Use the window below to plan observations tonight.'
            f'</div>'
        )
        story_guidance = (
            f'<div style="background:rgba(16,185,129,0.05);border:1px solid rgba(16,185,129,0.25);border-left:4px solid #10b981;padding:1.25rem;border-radius:6px;margin:1rem 0;">'
            f'<h3 style="margin:0 0 0.5rem 0;color:#a7f3d0;font-size:1.05rem;">Can I see it tonight? <span style="color:#34d399;">Yes — this supernova is currently in active outburst!</span></h3>'
            f'<p style="margin:0 0 0.75rem 0;color:#e2e8f0;line-height:1.6;">'
            f'Discovered only <strong>{days_since} days ago</strong> ({ref_date}), this supernova is actively radiating near peak luminosity at an estimated <strong>magnitude {m_current:.1f}</strong>.'
            f'</p>'
            f'<p style="margin:0;color:#cbd5e1;line-height:1.6;">'
            f'<strong>Instrument Recommendation:</strong> {current_tel_needed}.'
            f'</p>'
            f'{tel_table_html}'
            f'</div>'
        )
        return {
            "phase": "active",
            "days_since": days_since,
            "t_rest": round(t_rest, 1),
            "m_peak": m_peak,
            "m_current": m_current,
            "time_str": time_str,
            "ref_date": ref_date,
            "badge_html": badge,
            "cockpit_notice": cockpit_notice,
            "story_guidance_html": story_guidance,
            "tel_table_html": tel_table_html,
        }


def format_cosmic_neighbors_panel(
    name: str,
    closest_data: dict[str, list[dict[str, Any]]],
    is_cockpit: bool = True
) -> str:
    """Render cosmic neighbors & contemporaries across time, space, and cosmological era."""
    path_suffix = "" if is_cockpit else "/story"

    # Format Closest in Time (Cosmic Contemporaries)
    time_items_html = ""
    if closest_data.get("time"):
        for item in closest_data["time"]:
            it_name = item.get("name", "")
            it_type = item.get("type", "Transient") or "Transient"
            it_disc = item.get("discoverdate", "—")
            it_mag = f"Mag {item.get('maxappmag')}" if item.get("maxappmag") else ""
            delta = item.get("delta_days", 0)
            if delta == 0:
                delta_label = "Exploded same day"
                delta_color = "#22c55e"
            elif delta > 0:
                delta_label = f"+{delta}d after"
                delta_color = "#38bdf8"
            else:
                delta_label = f"{abs(delta)}d before"
                delta_color = "#f59e0b"
            time_items_html += f"""
            <a href="/sne/{urllib.parse.quote(it_name)}{path_suffix}" class="neighbor-row">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                <strong style="color:#fff;font-size:0.88rem;">{it_name}</strong>
                <span style="font-size:0.68rem;padding:2px 6px;border-radius:3px;background:rgba(255,255,255,0.06);color:{delta_color};font-weight:600;">{delta_label}</span>
              </div>
              <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:var(--text-muted);">
                <span>Type {it_type}</span>
                <span>{it_disc} {f"· {it_mag}" if it_mag else ""}</span>
              </div>
            </a>"""
    else:
        time_items_html = '<div style="color:var(--text-muted);font-size:0.8rem;padding:0.5rem 0;">No contemporary transients indexed.</div>'

    # Format Closest in Sky Neighborhood
    sky_items_html = ""
    if closest_data.get("sky"):
        for item in closest_data["sky"]:
            it_name = item.get("name", "")
            it_type = item.get("type", "Transient") or "Transient"
            sep_arcmin = item.get("separation_arcmin", 0.0)
            it_disc = item.get("discoverdate", "—")
            sep_str = f"{sep_arcmin:.1f}′ away" if sep_arcmin < 60 else f"{item.get('separation_deg', 0):.2f}° away"
            sky_items_html += f"""
            <a href="/sne/{urllib.parse.quote(it_name)}{path_suffix}" class="neighbor-row">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                <strong style="color:#fff;font-size:0.88rem;">{it_name}</strong>
                <span style="font-size:0.68rem;padding:2px 6px;border-radius:3px;background:rgba(168,85,247,0.15);color:#c084fc;font-weight:600;">{sep_str}</span>
              </div>
              <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:var(--text-muted);">
                <span>Type {it_type}</span>
                <span>Discovered {it_disc}</span>
              </div>
            </a>"""
    else:
        sky_items_html = '<div style="color:var(--text-muted);font-size:0.8rem;padding:0.5rem 0;">No sky neighbors cataloged in this field.</div>'

    # Format Closest in Cosmic Distance
    cosmic_items_html = ""
    if closest_data.get("cosmic"):
        for item in closest_data["cosmic"]:
            it_name = item.get("name", "")
            it_type = item.get("type", "Transient") or "Transient"
            z_val = item.get("redshift", "")
            ly_m = item.get("est_light_years_m", "")
            cosmic_items_html += f"""
            <a href="/sne/{urllib.parse.quote(it_name)}{path_suffix}" class="neighbor-row">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                <strong style="color:#fff;font-size:0.88rem;">{it_name}</strong>
                <span style="font-size:0.68rem;padding:2px 6px;border-radius:3px;background:rgba(34,197,94,0.15);color:#4ade80;font-weight:600;">z = {z_val}</span>
              </div>
              <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:var(--text-muted);">
                <span>Type {it_type}</span>
                <span>~{ly_m} Mly lookback</span>
              </div>
            </a>"""
    else:
        cosmic_items_html = '<div style="color:var(--text-muted);font-size:0.8rem;padding:0.5rem 0;">Redshift data unavailable for cosmic distance matching.</div>'

    container_class = "panel" if is_cockpit else "dossier-card"
    container_style = 'style="margin-top:2.5rem;"' if not is_cockpit else ''

    return f"""
    <div class="{container_class}" {container_style}>
      <div class="panel-title" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem;flex-wrap:wrap;gap:0.5rem;">
        <span style="display:flex;align-items:center;gap:6px;">🌌 Cosmic Neighbors &amp; Contemporaries</span>
        <span class="cutout-tag active" style="font-size:0.7rem;border-color:rgba(56,189,248,0.4);background:rgba(56,189,248,0.12);color:#38bdf8;cursor:default;">110,222+ Transients Indexed</span>
      </div>
      <p style="color:var(--text-muted);font-size:0.85rem;margin-top:0;margin-bottom:1rem;">
        Cataloged supernovae closest to <strong>{name}</strong> in discovery time, spatial sky neighborhood, and cosmological lookback epoch:
      </p>

      <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));gap:0.85rem;">
        <!-- Closest in Time -->
        <div style="background:rgba(255,255,255,0.015);border:1px solid var(--border);border-radius:8px;padding:0.85rem;">
          <div style="font-size:0.82rem;font-weight:700;color:var(--accent);margin-bottom:0.65rem;display:flex;align-items:center;gap:5px;">
            <span>⏱️ Closest in Time</span>
          </div>
          {time_items_html}
        </div>

        <!-- Closest in Sky Neighborhood -->
        <div style="background:rgba(255,255,255,0.015);border:1px solid var(--border);border-radius:8px;padding:0.85rem;">
          <div style="font-size:0.82rem;font-weight:700;color:#c084fc;margin-bottom:0.65rem;display:flex;align-items:center;gap:5px;">
            <span>🔭 Closest on the Sky</span>
          </div>
          {sky_items_html}
        </div>

        <!-- Closest in Cosmic Distance -->
        <div style="background:rgba(255,255,255,0.015);border:1px solid var(--border);border-radius:8px;padding:0.85rem;">
          <div style="font-size:0.82rem;font-weight:700;color:#4ade80;margin-bottom:0.65rem;display:flex;align-items:center;gap:5px;">
            <span>🌌 Same Cosmic Era (Redshift)</span>
          </div>
          {cosmic_items_html}
        </div>
      </div>
    </div>"""


def render_pro_cockpit(name: str, meta: dict, entered: str | None = None, legacy_html_exists: bool = False) -> str:
    """Render the high-performance professional scientific cockpit."""
    ra_deg, dec_deg, ra_str, dec_str = extract_coords(meta)
    aliases = []
    for a in meta.get("alias", []):
        if isinstance(a, dict):
            aliases.append(str(a.get("value", "")))
        else:
            aliases.append(str(a))
    aliases = [a for a in aliases if a and a != name]

    claimedtype = get_val(meta, "claimedtype")
    discoverdate = get_val(meta, "discoverdate")
    discoverer = get_val(meta, "discoverer")
    maxdate = get_val(meta, "maxdate")
    maxappmag = get_val(meta, "maxappmag")
    maxabsmag = get_val(meta, "maxabsmag")
    redshift = get_val(meta, "redshift")
    velocity = get_val(meta, "velocity")
    if velocity != "—" and not velocity.endswith("km/s"):
        velocity += " km/s"
    lumdist = get_val(meta, "lumdist")
    if lumdist != "—" and not lumdist.endswith("Mpc"):
        lumdist += " Mpc"
    ebv = get_val(meta, "ebv")
    if ebv != "—" and not ebv.endswith("mag"):
        ebv += " mag"
    host = get_val(meta, "host")
    host_offset_str = extract_host_offset(meta, ra_deg, dec_deg, redshift, lumdist)
    lifecycle = get_transient_lifecycle(meta, host_name=host, event_name=name, redshift=redshift, claimedtype=claimedtype)

    # MOSFiT Theoretical Models & Magnetar Engine Fit
    models_data = meta.get("models", [])
    magnetar_html = ""
    if models_data and isinstance(models_data, list):
        for m in models_data:
            if not isinstance(m, dict):
                continue
            code = m.get("code", "MOSFiT")
            m_name = m.get("name", "Magnetar Engine")
            realizations = m.get("realizations", [])
            if realizations and isinstance(realizations, list):
                r0 = realizations[0]
                params = r0.get("parameters", {})
                bfield = params.get("Bfield", {}).get("value")
                pspin = params.get("Pspin", {}).get("value")
                mns = params.get("Mns", {}).get("value")
                mej = params.get("mejecta", {}).get("value")
                if bfield is not None or pspin is not None:
                    conv = m.get("convergence", [{}])[0].get("value") if m.get("convergence") else "—"
                    bf_str = f"{float(bfield):.2f}" if bfield is not None else "—"
                    ps_str = f"{float(pspin):.2f}" if pspin is not None else "—"
                    mns_str = f"{float(mns):.2f}" if mns is not None else "—"
                    mej_str = f"{float(mej):.2f}" if mej is not None else "—"
                    psrf_str = f"{float(conv):.3f}" if conv and conv != "—" else "—"
                    magnetar_html = f"""
        <div style="background:rgba(217, 70, 239, 0.08);border:1px solid rgba(217, 70, 239, 0.35);border-radius:6px;padding:0.75rem;margin-bottom:0.75rem;font-size:0.78rem;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.4rem;">
            <strong style="color:#f472b6;">🧲 Central Engine Model: MOSFiT Magnetar Fit ({m_name})</strong>
            <span style="font-family:monospace;color:#94a3b8;font-size:0.7rem;">PSRF {psrf_str}</span>
          </div>
          <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:0.4rem;font-size:0.75rem;">
            <div><span style="color:#94a3b8;">B-Field (B<sub>⊥</sub>):</span> <strong style="color:#e2e8f0;">{bf_str} × 10<sup>14</sup> G</strong></div>
            <div><span style="color:#94a3b8;">Spin Period (P<sub>spin</sub>):</span> <strong style="color:#e2e8f0;">{ps_str} ms</strong></div>
            <div><span style="color:#94a3b8;">NS Mass (M<sub>NS</sub>):</span> <strong style="color:#e2e8f0;">{mns_str} M<sub>☉</sub></strong></div>
            <div><span style="color:#94a3b8;">Ejecta Mass (M<sub>ej</sub>):</span> <strong style="color:#e2e8f0;">{mej_str} M<sub>☉</sub></strong></div>
          </div>
        </div>"""
                    break

    # Cutout URLs & Multi-Survey Options
    desi_url = ""
    panstarrs_url = ""
    dss_url = ""
    skyview_dss_url = ""
    default_layer = "desi"
    initial_cutout_url = ""
    has_coords = ra_deg is not None and dec_deg is not None
    if has_coords:
        desi_url = (
            f"https://www.legacysurvey.org/viewer/cutout.jpg?ra={ra_deg:.6f}&dec={dec_deg:.6f}"
            f"&layer=ls-dr10&pixscale=0.262&size=350"
        )
        panstarrs_url = (
            f"https://alasky.cds.unistra.fr/hips-image-services/hips2fits?hips=CDS%2FP%2FPanSTARRS%2FDR1%2Fcolor-z-zg-g"
            f"&ra={ra_deg:.6f}&dec={dec_deg:.6f}&width=350&height=350&fov=0.08&format=jpg"
        )
        dss_url = (
            f"https://alasky.cds.unistra.fr/hips-image-services/hips2fits?hips=CDS%2FP%2FDSS2%2Fcolor"
            f"&ra={ra_deg:.6f}&dec={dec_deg:.6f}&width=350&height=350&fov=0.08&format=jpg"
        )
        skyview_dss_url = (
            f"https://skyview.gsfc.nasa.gov/current/cgi/runquery.pl?survey=DSS2+Red"
            f"&position={ra_deg:.6f},{dec_deg:.6f}&pixels=350&size=0.08&return=jpeg"
        )
        # DESI DR10 covers declination <= +32 deg. For northern targets (dec > 32 deg),
        # Pan-STARRS1 DR1 provides high-resolution 0.25"/pix optical coverage:
        if dec_deg > 32.0:
            default_layer = "panstarrs"
            initial_cutout_url = panstarrs_url
        else:
            default_layer = "desi"
            initial_cutout_url = desi_url

        legacy_viewer_link = f"https://www.legacysurvey.org/viewer?ra={ra_deg:.6f}&dec={dec_deg:.6f}&layer=ls-dr10&zoom=14"
    else:
        legacy_viewer_link = "https://www.legacysurvey.org/viewer"

    # Find closest events in time, sky separation, and cosmic distance
    closest_data = {"sky": [], "time": [], "cosmic": []}
    if find_closest_events is not None and has_coords:
        try:
            closest_data = find_closest_events(name, ra_deg, dec_deg, discoverdate, redshift, limit=3)
        except Exception:
            pass

    neighbors_panel_html = format_cosmic_neighbors_panel(name, closest_data, is_cockpit=True)

    dist_ly_str = "Millions of Light-Years"
    if lumdist != "—":
        try:
            mpc = float(re.sub(r"[^0-9.]", "", lumdist))
            ly_m = mpc * 3.26156
            dist_ly_str = f"{ly_m:.1f} Million Light-Years"
        except Exception:
            pass

    cockpit_faqs = []
    if generate_supernova_faqs is not None:
        try:
            cockpit_faqs = generate_supernova_faqs(
                name=name,
                meta=meta,
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                ra_str=ra_str,
                dec_str=dec_str,
                claimedtype=claimedtype,
                discoverdate=discoverdate,
                discoverer=discoverer,
                maxappmag=maxappmag,
                maxdate=maxdate,
                maxabsmag=maxabsmag,
                lumdist=lumdist,
                redshift=redshift,
                host=host,
                host_offset_str=host_offset_str,
                dist_ly_str=dist_ly_str,
                lifecycle=lifecycle,
            )
        except Exception:
            cockpit_faqs = []

    cockpit_faq_jsonld = build_faq_jsonld(cockpit_faqs) if build_faq_jsonld and cockpit_faqs else ""
    cockpit_faq_html = build_faq_html(cockpit_faqs, name) if build_faq_html and cockpit_faqs else ""

    # Photometry processing for Plotly
    photometry = meta.get("photometry", [])
    photo_count = len(photometry)
    spectra = meta.get("spectra", [])
    spec_count = len(spectra)

    # Prepare photometry data for client-side plotting
    photo_points = []
    for p in photometry:
        t = p.get("time")
        m = p.get("magnitude")
        if t is not None and m is not None:
            try:
                t_flt = float(t)
                m_flt = float(m)
                e_m = p.get("e_magnitude")
                e_flt = float(e_m) if e_m is not None else None
                is_uplim = bool(p.get("upperlimit", False))
                band = str(p.get("band", "other"))
                photo_points.append({
                    "time": t_flt,
                    "mag": m_flt,
                    "err": e_flt,
                    "uplim": is_uplim,
                    "band": band,
                    "tel": p.get("telescope", p.get("instrument", "")),
                    "src": str(p.get("source", "")),
                })
            except Exception:
                continue

    # Prepare first few spectra for client-side plotting
    spec_samples = []
    for s in spectra[:5]:
        s_data = s.get("data", [])
        if s_data:
            pts = []
            # Subsample if extraordinarily dense (> 2000 points) to guarantee fast rendering
            step = max(1, len(s_data) // 1500)
            for row in s_data[::step]:
                try:
                    w = float(row[0])
                    f = float(row[1])
                    if not (math.isnan(w) or math.isnan(f) or math.isinf(f)):
                        pts.append([round(w, 2), float(f"{f:.4e}")])
                except Exception:
                    continue
            if pts:
                spec_samples.append({
                    "time": str(s.get("time", "")),
                    "tel": str(s.get("telescope", s.get("instrument", "Observatory"))),
                    "data": pts,
                })

    bibtex_str = generate_bibtex(name, meta)

    # Sources table
    sources_html_rows = []
    for s in meta.get("sources", []):
        s_alias = s.get("alias", "")
        s_name = s.get("name") or s.get("bibcode") or s_alias
        s_bib = s.get("bibcode")
        s_ref = s.get("reference", "")
        s_url = s.get("url")
        if not s_url and s_bib:
            s_url = f"https://ui.adsabs.harvard.edu/abs/{urllib.parse.quote(s_bib)}"
        link_str = f'<a href="{s_url}" target="_blank" rel="noopener">{s_name}</a>' if s_url else str(s_name)
        sources_html_rows.append(
            f'<tr><td class="badge">[{s_alias}]</td><td>{link_str}</td><td>{s_ref}</td>'
            f'<td><code>{s_bib or "—"}</code></td></tr>'
        )
    sources_table_html = "".join(sources_html_rows) if sources_html_rows else "<tr><td colspan='4'>No sources recorded.</td></tr>"

    legacy_btn = ""
    if legacy_html_exists:
        legacy_btn = f'<a class="btn btn-outline" href="/astrocats/astrocats/supernovae/output/html/{name.replace("/", "_")}.html" target="_blank">View 2016 Bokeh Archive</a>'

    warn_html = ""
    if entered and entered != name:
        warn_html = f'<div class="banner-warn">Resolved "{urllib.parse.unquote(entered)}" to canonical transient <strong>{name}</strong></div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name} — Open Supernova Catalog Cockpit</title>
  <meta name="description" content="Supernova {name} ({claimedtype}): Multi-band light curves, spectra, cosmology, and deep host imaging from the Open Supernova Catalog.">
  <meta property="og:title" content="{name} — Open Supernova Catalog Cockpit">
  <meta property="og:description" content="Supernova {name} ({claimedtype}): Multi-band light curves, spectra, cosmology, and deep host imaging.">
  <meta property="og:image" content="https://sne.space/sne/{urllib.parse.quote(name)}/host.jpg">
  <meta property="og:url" content="https://sne.space/sne/{urllib.parse.quote(name)}/">
  <meta property="og:type" content="website">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{name} ({claimedtype}) — Open Supernova Catalog">
  <meta name="twitter:description" content="Multi-band light curves, calibrated spectra, and deep optical host imaging from sne.space.">
  <meta name="twitter:image" content="https://sne.space/sne/{urllib.parse.quote(name)}/host.jpg">
  <link rel="stylesheet" href="/assets/ia.css">
  <link rel="ai-catalog" href="/.well-known/ai-catalog.json" type="application/ai-catalog+json">
  <link rel="ard" href="/.well-known/ard.json" type="application/json">
  <link rel="stylesheet" href="https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.css" />
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <script src="https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js"></script>
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Dataset",
    "name": "Supernova {name} Optical Photometry and Spectroscopy",
    "description": "Multi-band light curves, calibrated spectra, and derived cosmological parameters for {name} ({claimedtype}) in the Open Supernova Catalog.",
    "url": "https://sne.space/sne/{urllib.parse.quote(name)}/",
    "keywords": ["supernova", "{claimedtype}", "transient", "astrophysics", "light curve", "spectrum"],
    "creator": {{
      "@type": "Organization",
      "name": "Open Supernova Catalog",
      "url": "https://sne.space"
    }}
  }}
  </script>
{cockpit_faq_jsonld}
  <style>
    :root {{
      --bg: #0b0f19;
      --card-bg: #131b2e;
      --border: #232f48;
      --text: #e2e8f0;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-hover: #0284c7;
      --badge-bg: #1e293b;
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
    .brand-group {{
      display: flex;
      align-items: center;
      gap: 1rem;
    }}
    .brand-title {{
      font-weight: 700;
      font-size: 1.25rem;
      color: #fff;
      text-decoration: none;
    }}
    .brand-badge {{
      font-size: 0.75rem;
      background: #1e3a8a;
      color: #93c5fd;
      padding: 0.15rem 0.5rem;
      border-radius: 4px;
      font-weight: 600;
    }}
    .view-switcher {{
      display: flex;
      background: #1e293b;
      padding: 2px;
      border-radius: 6px;
      border: 1px solid var(--border);
    }}
    .view-btn {{
      padding: 0.35rem 0.75rem;
      font-size: 0.85rem;
      font-weight: 600;
      text-decoration: none;
      color: var(--text-muted);
      border-radius: 4px;
    }}
    .view-btn.active {{
      background: var(--accent);
      color: #0b0f19;
    }}
    .hdr-search-form {{
      display: flex;
      align-items: center;
      background: rgba(15, 23, 42, 0.75);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
      max-width: 320px;
      flex: 1;
      margin: 0 1rem;
      transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }}
    .hdr-search-form:focus-within {{
      border-color: #38bdf8;
      box-shadow: 0 0 12px rgba(56, 189, 248, 0.25);
    }}
    .hdr-search-form input {{
      background: transparent;
      border: none;
      outline: none;
      color: #f1f5f9;
      font-size: 0.85rem;
      padding: 0.35rem 0.65rem;
      width: 100%;
    }}
    .hdr-search-form button {{
      background: transparent;
      border: none;
      color: #94a3b8;
      padding: 0.35rem 0.6rem;
      cursor: pointer;
    }}
    .hdr-nav-links {{
      display: flex;
      align-items: center;
      gap: 0.85rem;
      margin-right: 1rem;
    }}
    .hdr-nav-links a {{
      color: var(--text-muted);
      text-decoration: none;
      font-size: 0.85rem;
      font-weight: 600;
      transition: color 0.15s ease;
    }}
    .hdr-nav-links a:hover {{
      color: #fff;
    }}
    .story-faq-accordion {{
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
      margin-top: 1rem;
    }}
    .story-faq-item {{
      background: rgba(18, 25, 41, 0.75);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
      transition: all 0.15s ease;
    }}
    .story-faq-item:hover {{
      border-color: rgba(56, 189, 248, 0.4);
    }}
    .story-faq-item summary {{
      padding: 0.85rem 1.1rem;
      font-weight: 600;
      color: #f1f5f9;
      cursor: pointer;
      user-select: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      list-style: none;
    }}
    .story-faq-item summary::-webkit-details-marker {{
      display: none;
    }}
    .story-faq-item summary::after {{
      content: "+";
      color: #38bdf8;
      font-size: 1.2rem;
      font-weight: 700;
    }}
    .story-faq-item[open] summary::after {{
      content: "−";
    }}
    .story-faq-item[open] summary {{
      border-bottom: 1px solid var(--border);
      color: #38bdf8;
      background: rgba(56, 189, 248, 0.06);
    }}
    .story-faq-badge {{
      font-size: 0.68rem;
      padding: 2px 7px;
      border-radius: 4px;
      background: rgba(56, 189, 248, 0.12);
      color: #38bdf8;
      border: 1px solid rgba(56, 189, 248, 0.25);
      font-weight: 600;
      white-space: nowrap;
      margin-left: auto;
      margin-right: 0.75rem;
    }}
    .story-faq-body {{
      padding: 0.95rem 1.1rem;
      font-size: 0.92rem;
      line-height: 1.6;
      color: #cbd5e1;
    }}
    .banner-warn {{
      background: #78350f;
      color: #fef3c7;
      padding: 0.5rem 1.5rem;
      font-size: 0.9rem;
      border-bottom: 1px solid #b45309;
    }}
    .hero-meta {{
      padding: 1.25rem 1.5rem;
      border-bottom: 1px solid var(--border);
      background: #0f172a;
    }}
    .title-row {{
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 1rem;
    }}
    .hero-title {{
      margin: 0;
      font-size: 2rem;
      font-weight: 800;
      letter-spacing: -0.02em;
    }}
    .type-pill {{
      background: #0284c7;
      color: #fff;
      padding: 0.2rem 0.65rem;
      border-radius: 9999px;
      font-size: 0.9rem;
      font-weight: 700;
    }}
    .hero-sub {{
      margin-top: 0.25rem;
      color: var(--text-muted);
      font-size: 0.95rem;
    }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-top: 1rem;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.4rem 0.8rem;
      font-size: 0.85rem;
      font-weight: 600;
      border-radius: 6px;
      text-decoration: none;
      cursor: pointer;
      border: 1px solid transparent;
      transition: all 0.15s ease;
    }}
    .btn-primary {{ background: var(--accent); color: #0b0f19; }}
    .btn-primary:hover {{ background: var(--accent-hover); color: #fff; }}
    .btn-outline {{ background: var(--card-bg); color: var(--text); border-color: var(--border); }}
    .btn-outline:hover {{ background: #1e293b; border-color: #3b82f6; }}
    .main-grid {{
      display: grid;
      grid-template-columns: minmax(320px, 420px) 1fr;
      gap: 1.5rem;
      padding: 1.5rem;
      max-width: 1600px;
      margin: 0 auto;
    }}
    @media (max-width: 1024px) {{
      .main-grid {{ grid-template-columns: 1fr; }}
    }}
    .panel {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.25rem;
      margin-bottom: 1.5rem;
    }}
    .panel-title {{
      margin: 0 0 1rem 0;
      font-size: 1.1rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.5rem;
    }}
    .meta-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }}
    .meta-table th, .meta-table td {{
      padding: 0.45rem 0;
      border-bottom: 1px solid rgba(255,255,255,0.05);
      text-align: left;
    }}
    .meta-table th {{
      color: var(--text-muted);
      width: 45%;
      font-weight: 500;
    }}
    .meta-table td {{
      color: #fff;
      font-weight: 600;
    }}
    .cutout-container {{
      position: relative;
      width: 100%;
      height: 350px;
      background: #000;
      border-radius: 6px;
      overflow: hidden;
      border: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .cutout-img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }}
    .crosshair {{
      position: absolute;
      top: 50%;
      left: 50%;
      width: 32px;
      height: 32px;
      transform: translate(-50%, -50%);
      pointer-events: none;
    }}
    .crosshair::before, .crosshair::after {{
      content: "";
      position: absolute;
      background: #ef4444;
      box-shadow: 0 0 4px #000;
    }}
    .crosshair::before {{
      top: 0; left: 15px; width: 2px; height: 32px;
    }}
    .crosshair::after {{
      top: 15px; left: 0; width: 32px; height: 2px;
    }}
    .cutout-actions {{
      display: flex;
      gap: 0.4rem;
      margin-top: 0.5rem;
      flex-wrap: wrap;
    }}
    .cutout-tag {{
      font-size: 0.75rem;
      padding: 0.2rem 0.5rem;
      border-radius: 4px;
      background: #1e293b;
      color: var(--text-muted);
      border: 1px solid var(--border);
      cursor: pointer;
    }}
    .cutout-tag.active {{
      background: #0284c7;
      color: #fff;
      border-color: #38bdf8;
    }}
    .cutout-status-badge {{
      position: absolute;
      top: 8px;
      left: 8px;
      right: 8px;
      padding: 5px 10px;
      border-radius: 4px;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.02em;
      z-index: 20;
      backdrop-filter: blur(8px);
      display: flex;
      align-items: center;
      gap: 6px;
      pointer-events: none;
      transition: all 0.2s ease;
    }}
    .cutout-status-badge.modern {{
      background: rgba(15, 23, 42, 0.9);
      color: #38bdf8;
      border: 1px solid rgba(56, 189, 248, 0.35);
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.5);
    }}
    .cutout-status-badge.archival {{
      background: rgba(41, 37, 36, 0.92);
      color: #fbbf24;
      border: 1px solid rgba(251, 191, 36, 0.4);
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.5);
    }}
    .cutout-controls-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-top: 0.5rem;
    }}
    .blink-btn.active {{
      background: #0284c7 !important;
      border-color: #38bdf8 !important;
      color: #ffffff !important;
      animation: pulse-blink 0.6s infinite alternate;
    }}
    @keyframes pulse-blink {{
      from {{ box-shadow: 0 0 4px rgba(56, 189, 248, 0.4); }}
      to {{ box-shadow: 0 0 12px rgba(56, 189, 248, 0.85); }}
    }}
    .neighbor-row {{
      display: block;
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 6px;
      padding: 0.65rem 0.75rem;
      margin-bottom: 0.5rem;
      text-decoration: none;
      transition: all 0.15s ease;
    }}
    .neighbor-row:hover {{
      background: rgba(56, 189, 248, 0.08);
      border-color: rgba(56, 189, 248, 0.3);
      transform: translateY(-1px);
    }}
    .plot-box {{
      min-height: 400px;
      width: 100%;
      margin-bottom: 1.5rem;
      border-radius: 6px;
      background: #070a12;
      border: 1px solid var(--border);
    }}
    /* Aladin Lite custom branding & overrides to match sne.space */
    .aladin-location, .aladin-fov, .aladin-projection-control, .aladin-fullScreen-control,
    .aladin-widgets-toolbar, .aladin-status-bar, .aladin-cooFrame, .aladin-reticle,
    .aladin-logo-container {{
      display: none !important;
    }}
    .aladin-container {{
      background-color: #070a13 !important;
      border: none !important;
      font-family: inherit !important;
    }}
    .aladin-custom-box {{
      position: relative;
      width: 100%;
      height: 330px;
      border-radius: 6px;
      overflow: hidden;
      border: 1px solid var(--border);
      background: #070a13;
    }}
    .aladin-hud-badge {{
      background: rgba(7, 10, 19, 0.88);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(56, 189, 248, 0.25);
      color: #38bdf8;
      font-family: monospace;
      font-size: 0.72rem;
      padding: 3px 8px;
      border-radius: 4px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.6);
    }}
    .aladin-hud-btn {{
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(6px);
      border: 1px solid rgba(148, 163, 184, 0.25);
      color: #cbd5e1;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.15s ease;
    }}
    .aladin-hud-btn:hover {{
      background: rgba(30, 41, 59, 0.95);
      color: #fff;
      border-color: #38bdf8;
    }}
    .aladin-hud-btn.active {{
      background: #0284c7;
      color: #fff;
      border-color: #38bdf8;
    }}
    /* Completely hide Aladin's default floating popup box in favor of top HUD bar */
    .aladin-popup-container,
    div.aladin-popup-container,
    .aladin-container .aladin-popup,
    div.aladin-popup {{
      display: none !important;
      visibility: hidden !important;
      pointer-events: none !important;
      opacity: 0 !important;
    }}
    @keyframes hud-slide-down {{
      from {{ opacity: 0; transform: translateY(-4px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    .aladin-container .aladin-popupTitle,
    div.aladin-popupTitle {{
      display: block !important;
      font-size: 0.85rem !important;
      font-weight: 700 !important;
      color: #ffffff !important;
      margin-bottom: 6px !important;
      padding-right: 18px !important;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
      padding-bottom: 4px !important;
    }}
    .aladin-container .aladin-popupTitle:empty,
    div.aladin-popupTitle:empty {{
      display: none !important;
    }}
    .aladin-container .aladin-popupText,
    div.aladin-popupText {{
      display: block !important;
      color: #cbd5e1 !important;
      font-size: 0.78rem !important;
      line-height: 1.4 !important;
    }}
    .aladin-container .aladin-closeBtn,
    a.aladin-closeBtn {{
      color: #94a3b8 !important;
      font-size: 18px !important;
      top: 6px !important;
      right: 8px !important;
      text-decoration: none !important;
      cursor: pointer !important;
      z-index: 10 !important;
      transition: color 0.15s ease !important;
    }}
    .aladin-container .aladin-closeBtn:hover,
    a.aladin-closeBtn:hover {{
      color: #38bdf8 !important;
    }}
    .aladin-container .aladin-popup-arrow,
    div.aladin-popup-arrow {{
      border-top-color: #0b1120 !important;
      border-bottom-color: #0b1120 !important;
      z-index: 999999 !important;
    }}
    .aladin-marker-measurement {{
      max-height: 220px !important;
      overflow-y: auto !important;
    }}
    .aladin-marker-measurement table {{
      display: table !important;
      width: 100% !important;
      border-collapse: collapse !important;
      font-size: 0.72rem !important;
      margin-top: 4px !important;
    }}
    .aladin-marker-measurement td {{
      padding: 3px 6px !important;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
      color: #94a3b8 !important;
      word-break: break-word !important;
    }}
    .aladin-marker-measurement td:first-child {{
      color: #cbd5e1 !important;
      font-weight: 600 !important;
      width: 38% !important;
    }}
    .modal {{
      display: none;
      position: fixed;
      z-index: 9999;
      left: 0; top: 0; width: 100%; height: 100%;
      background: rgba(0,0,0,0.7);
      backdrop-filter: blur(4px);
      align-items: center;
      justify-content: center;
    }}
    .modal-box {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.5rem;
      max-width: 600px;
      width: 90%;
    }}
    textarea.bib-text {{
      width: 100%;
      height: 220px;
      background: #070a12;
      border: 1px solid var(--border);
      color: #a7f3d0;
      font-family: monospace;
      font-size: 0.85rem;
      padding: 0.5rem;
      border-radius: 4px;
      resize: vertical;
      box-sizing: border-box;
    }}
    .slider-wrap {{
      margin-top: 0.5rem;
      padding: 0.5rem;
      background: #070a12;
      border-radius: 4px;
      border: 1px solid var(--border);
    }}
    .slider-wrap label {{
      font-size: 0.8rem;
      color: var(--text-muted);
      display: flex;
      justify-content: space-between;
    }}
  </style>
</head>
<body>
  <header class="cockpit-hdr">
    <div class="brand-group">
      <a class="brand-title" href="/">sne.space</a>
      <span class="brand-badge">Open Supernova Catalog</span>
    </div>
    <form class="hdr-search-form" action="/" method="GET" toolname="search_supernovae" tooldescription="Search 110,000+ supernovae by IAU designation, name, or survey alias">
      <input type="text" name="q" placeholder="Search 110,000+ transients..." autocomplete="off" toolparamdescription="Supernova name, IAU designation (e.g. SN2023ixf, SN 1987A), or alias" aria-label="Search supernovae">
      <button type="submit" aria-label="Submit Search">🔍</button>
    </form>
    <div class="hdr-nav-links">
      <a href="/radar">📡 Radar</a>
      <a href="/faq">❓ FAQs</a>
    </div>
    <div class="view-switcher">
      <a class="view-btn active" href="#">🔭 Pro Cockpit</a>
      <a class="view-btn" href="/sne/{urllib.parse.quote(name)}/story">📖 Story View</a>
    </div>
  </header>

  {warn_html}

  <section class="hero-meta">
    <div class="title-row" style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap;">
      <h1 class="hero-title" style="margin:0;">{name}</h1>
      <span class="type-pill">Type {claimedtype}</span>
      {lifecycle['badge_html']}
    </div>
    <div class="hero-sub">
      <strong>Aliases:</strong> {", ".join(aliases[:8]) if aliases else "None"} &nbsp;|&nbsp;
      <strong>Discovered:</strong> {discoverdate} by {discoverer[:60] if discoverer != "—" else "Survey Stream"}
    </div>
    <div class="toolbar">
      <a class="btn btn-primary" href="?enrich=1">⚡ Re-Enrich Data</a>
      <a class="btn btn-outline" href="/sne/{urllib.parse.quote(name)}.json" download>📥 Download JSON</a>
      <a class="btn btn-outline" href="/{urllib.parse.quote(name)}/photometry?format=csv">📊 Photometry CSV</a>
      <button class="btn btn-outline" onclick="openBibModal()">📋 Copy BibTeX</button>
      {legacy_btn}
    </div>
  </section>

  <main class="main-grid">
    <!-- LEFT COLUMN: Astrophysical Context & Imagery -->
    <div class="col-left">
      <!-- Cutout Widget: Host Optical Cutout -->
      <div class="panel" id="panel-cutout">
        <div class="panel-title" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.4rem;">
          <div style="display:flex;align-items:center;gap:0.5rem;">
            <span>Host Optical Cutout</span>
            <span style="font-size:0.75rem;padding:2px 6px;border-radius:3px;background:rgba(56,189,248,0.1);color:#38bdf8;border:1px solid rgba(56,189,248,0.25);">0.26″/pix</span>
          </div>
          <!-- Survey Layer Selection -->
          <div style="display:flex;gap:0.3rem;">
            <button class="cutout-tag {'active' if default_layer == 'desi' else ''}" id="btn-desi" onclick="switchLayer('desi')" title="DESI Legacy Survey DR10 (0.26″/pix optical)">DESI DR10</button>
            <button class="cutout-tag {'active' if default_layer == 'panstarrs' else ''}" id="btn-panstarrs" onclick="switchLayer('panstarrs')" title="Pan-STARRS1 DR1 High-Definition Optical">Pan-STARRS1</button>
            <button class="cutout-tag" id="btn-dss" onclick="switchLayer('dss')" title="Digitized Sky Survey (CDS Calibrated Optical Plates)">DSS2 Archival</button>
          </div>
        </div>

        <div class="cutout-container" id="cutout-wrap">
          {f'''
          <!-- Survey Telemetry HUD Badge -->
          <div class="cutout-status-badge modern" id="cutout-status-badge">
            <span id="cutout-status-text">{'Pan-STARRS1 DR1 Optical (0.25″/pix)' if default_layer == 'panstarrs' else 'DESI DR10 Optical (0.26″/pix)'}</span>
          </div>

          <!-- Base Sky Survey Image -->
          <img id="cutout-img" class="cutout-img" src="{initial_cutout_url}" alt="{name} cutout" onerror="handleCutoutError()">

          <!-- Central Crosshair Reticle -->
          <div class="crosshair" id="cutout-crosshair"></div>
          ''' if has_coords else '<p style="color:var(--text-muted)">Coordinates not available</p>'}
        </div>

        <!-- Controls Bar -->
        <div class="cutout-controls-bar">
          <div style="display:flex;align-items:center;gap:0.4rem;flex-wrap:wrap;">
            <button class="cutout-tag blink-btn" id="btn-blink" onclick="toggleBlink()" title="Blink back and forth between modern high-definition survey and historical DSS2 archival plates">⚡ Blink Surveys (Modern vs Archival)</button>
          </div>
          <div style="display:flex;align-items:center;gap:0.4rem;font-size:0.75rem;color:var(--text-muted);margin-left:auto;">
            <a class="cutout-tag" href="{legacy_viewer_link}" target="_blank" rel="noopener">Interactive Sky ↗</a>
          </div>
        </div>
      </div>

      <!-- Core Astrophysical Parameters -->
      <div class="panel">
        <h2 class="panel-title">Core Parameters</h2>
        <table class="meta-table">
          <tr><th>R.A. (J2000)</th><td>{ra_str} {f"({ra_deg:.5f}°)" if ra_deg else ""}</td></tr>
          <tr><th>Dec. (J2000)</th><td>{dec_str} {f"({dec_deg:.5f}°)" if dec_deg else ""}</td></tr>
          <tr><th>Spectral Type</th><td>{claimedtype}</td></tr>
          <tr><th>Redshift (z)</th><td>{redshift}</td></tr>
          <tr><th>Recession Velocity</th><td>{velocity}</td></tr>
          <tr><th>Luminosity Distance</th><td>{lumdist}</td></tr>
          <tr><th>Peak Apparent Mag</th><td>{maxappmag}</td></tr>
          <tr><th>Peak Absolute Mag</th><td>{maxabsmag}</td></tr>
          <tr><th>MW Dust E(B-V)</th><td>{ebv}</td></tr>
          <tr><th>Host Galaxy</th><td>{host}</td></tr>
          <tr><th>Host Offset</th><td>{host_offset_str}</td></tr>
          <tr><th>Observations</th><td>{photo_count} photometry, {spec_count} spectra</td></tr>
        </table>
      </div>

      <!-- Interactive Sky Map (Aladin Lite v3 Customized) -->
      <div class="panel">
        <h2 class="panel-title">
          <span>Interactive Sky Field (Aladin)</span>
          <span class="cutout-tag active" style="cursor:default;border-color:rgba(56,189,248,0.4);background:rgba(56,189,248,0.12);color:#38bdf8;font-size:0.7rem;">✨ Highest-Definition Optical (0.25″/pix)</span>
        </h2>
        <div class="aladin-custom-box">
          <div id="aladin-lite-div" style="width:100%;height:100%;"></div>

          <!-- Top HUD Header & Long Selection Telemetry Bar -->
          <div id="cockpit-top-hud" style="position:absolute;top:8px;left:8px;right:8px;display:flex;align-items:center;z-index:30;pointer-events:auto;">
            <!-- Default State: Live Coordinate & FOV HUD -->
            <div id="cockpit-hud-default" style="display:flex;align-items:center;gap:6px;">
              <span class="aladin-hud-badge">🎯 {ra_str} {dec_str}</span>
              <span class="aladin-hud-badge" id="aladin-fov-label" style="color:#94a3b8;border-color:var(--border);">FOV: 0.15°</span>
            </div>

            <!-- Selected State: Cyber Highlighted Bar with Close '×' -->
            <div id="cockpit-hud-selected" style="display:none;width:100%;align-items:center;justify-content:space-between;gap:10px;background:rgba(8,26,46,0.96);backdrop-filter:blur(12px);border:1px solid #38bdf8;border-radius:6px;padding:5px 12px;box-shadow:0 4px 20px rgba(56,189,248,0.35);color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;animation:hud-slide-down 0.2s ease-out;">
              <div id="cockpit-hud-content" style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;min-width:0;flex:1;"></div>
              <button onclick="clearCockpitSelectedTelemetry(event)" title="Deselect / Close (Esc)" aria-label="Close telemetry" style="background:none;border:none;color:#94a3b8;font-size:1.25rem;font-weight:700;cursor:pointer;padding:0 4px;line-height:1;display:flex;align-items:center;justify-content:center;transition:color 0.15s ease;" onmouseover="this.style.color='#f43f5e'" onmouseout="this.style.color='#94a3b8'">×</button>
            </div>
          </div>

          <!-- Floating Target Marker & Label Pin -->
          <div id="aladin-target-pin" onclick="showTargetTelemetry()" onkeydown="if(event.key==='Enter'||event.key===' ')showTargetTelemetry()" role="button" aria-label="Supernova Target Telemetry Pin" tabindex="0" title="Click to view supernova telemetry" style="position:absolute;top:50%;left:50%;cursor:pointer;z-index:25;pointer-events:auto;user-select:none;">
            <!-- Badge positioned safely above host galaxy & explosion reticle -->
            <div style="position:absolute;bottom:26px;left:50%;transform:translateX(-50%);background:rgba(15,23,42,0.95);border:1px solid #38bdf8;color:#fff;font-size:0.68rem;font-weight:700;padding:2px 7px;border-radius:4px;box-shadow:0 0 14px rgba(56,189,248,0.5);white-space:nowrap;display:flex;align-items:center;gap:4px;pointer-events:auto;">
              <span style="color:#38bdf8;">●</span> {name} <span style="color:#94a3b8;font-weight:400;">({claimedtype})</span>
            </div>
            <!-- Fine vertical connector line linking badge to reticle center -->
            <div style="position:absolute;bottom:12px;left:0;width:1px;height:14px;background:rgba(56,189,248,0.7);box-shadow:0 0 4px #38bdf8;"></div>
            <!-- Crosshair centered exactly at (0, 0) -->
            <div style="width:24px;height:24px;position:relative;transform:translate(-50%,-50%);pointer-events:auto;">
              <div style="position:absolute;top:0;left:11px;width:2px;height:24px;background:#38bdf8;box-shadow:0 0 6px #38bdf8;"></div>
              <div style="position:absolute;top:11px;left:0;width:24px;height:2px;background:#38bdf8;box-shadow:0 0 6px #38bdf8;"></div>
              <div style="position:absolute;top:4px;left:4px;width:16px;height:16px;border:1px solid #38bdf8;border-radius:50%;box-shadow:0 0 6px #38bdf8;"></div>
            </div>
          </div>

          <!-- Bottom-Right Controls HUD -->
          <div style="position:absolute;bottom:8px;right:8px;display:flex;gap:4px;z-index:20;">
            <button class="aladin-hud-btn active" id="btn-target-toggle" onclick="toggleTargetMarker(this)" title="Toggle target pin & crosshair to view raw optical host galaxy">🎯 Target Pin</button>
            <button class="aladin-hud-btn" id="btn-simbad-toggle" onclick="toggleSimbadOverlay(this)" title="Label nearby astronomical sources via CDS SIMBAD">🏷️ SIMBAD Labels</button>
            <button class="aladin-hud-btn" onclick="recenterAladin()" title="Recenter target">⌖ Center</button>
            <button class="aladin-hud-btn" onclick="zoomAladin(1.5)" title="Zoom in">+</button>
            <button class="aladin-hud-btn" onclick="zoomAladin(0.67)" title="Zoom out">−</button>
          </div>
        </div>
      </div>

      <!-- Tonight's Observability & Air Mass Planner -->
      <div class="panel">
        <div class="panel-title">
          <span>Coordinate Pointing &amp; Airmass</span>
          <select id="obs-site" onchange="calcObservability()" style="background:#070a12;color:var(--accent);border:1px solid var(--border);border-radius:4px;padding:2px 6px;font-size:0.75rem;cursor:pointer;">
            <option value="gps">📍 My Location (GPS)</option>
            <option value="keck" selected>Keck (Mauna Kea, HI)</option>
            <option value="paranal">VLT (Paranal, Chile)</option>
            <option value="palomar">Palomar Observatory (CA)</option>
            <option value="lapalma">La Palma (ORM, Spain)</option>
          </select>
        </div>
        {lifecycle['cockpit_notice']}
        {magnetar_html}
        <div id="obs-stats" style="display:grid;grid-template-columns:repeat(2,1fr);gap:0.4rem;margin-bottom:0.75rem;font-size:0.8rem;"></div>
        <div id="plot-airmass" style="width:100%;height:190px;"></div>
      </div>
    </div>

    <!-- RIGHT COLUMN: Interactive Visualizers -->
    <div class="col-right">
      <!-- Light Curve Plot -->
      <div class="panel">
        <div class="panel-title">
          <span>Multi-Band Light Curve</span>
          <div style="display:flex;gap:0.4rem;">
            <button class="cutout-tag active" id="btn-time-mjd" onclick="switchTimeBase('mjd')">MJD</button>
            <button class="cutout-tag" id="btn-time-rest" onclick="switchTimeBase('rest')">Days from Peak</button>
          </div>
        </div>
        <div id="plot-lc" class="plot-box"></div>
      </div>

      <!-- Spectra Viewer -->
      <div class="panel">
        <div class="panel-title">
          <span>Calibrated Spectra Viewer</span>
          <div style="display:flex;gap:0.4rem;">
            <button class="cutout-tag" id="btn-deredshift" onclick="toggleDeredshift()">De-redshift (z)</button>
            <button class="cutout-tag" id="btn-lines" onclick="toggleLines()">Atomic Features</button>
          </div>
        </div>
        <div id="plot-spec" class="plot-box"></div>
        <div class="slider-wrap">
          <label><span>Spectrum Smoothing (Filter noise)</span><span id="smooth-val">1x</span></label>
          <input type="range" min="1" max="15" value="1" step="2" style="width:100%" oninput="updateSmoothing(this.value)">
        </div>
      </div>

      <!-- Cosmic Neighbors & Contemporaries -->
      {neighbors_panel_html}

      <!-- Research Literature & Sources -->
      <div class="panel">
        <h2 class="panel-title">Literature &amp; Data Provenance</h2>
        <div style="overflow-x:auto;">
          <table class="meta-table" style="font-size:0.85rem;">
            <thead>
              <tr style="border-bottom:1px solid var(--border);color:var(--text-muted)">
                <th>ID</th><th>Source</th><th>Reference</th><th>NASA ADS Bibcode</th>
              </tr>
            </thead>
            <tbody>
              {sources_table_html}
            </tbody>
          </table>
        </div>
      </div>

      <!-- Astrophysical FAQs & Provenance -->
      {cockpit_faq_html}
    </div>
  </main>

  <!-- BibTeX Modal -->
  <div class="modal" id="bib-modal" onclick="if(event.target===this)closeBibModal()">
    <div class="modal-box">
      <h3 style="margin-top:0">BibTeX Citation Block</h3>
      <textarea class="bib-text" id="bib-content" readonly>{bibtex_str}</textarea>
      <div style="display:flex;justify-content:flex-end;gap:0.5rem;margin-top:1rem;">
        <button class="btn btn-outline" onclick="closeBibModal()">Close</button>
        <button class="btn btn-primary" onclick="copyBibTeX()">Copy to Clipboard</button>
      </div>
    </div>
  </div>

  <script>
    const RA_DEG = {ra_deg if ra_deg is not None else 'null'};
    const DEC_DEG = {dec_deg if dec_deg is not None else 'null'};
    const DESI_URL = "{desi_url}";
    const PANSTARRS_URL = "{panstarrs_url}";
    const DSS_URL = "{dss_url}";
    const SKYVIEW_DSS_URL = "{skyview_dss_url}";
    const PHOTO_DATA = {json.dumps(photo_points)};
    const SPEC_DATA = {json.dumps(spec_samples)};
    const REDSHIFT = {float(redshift) if redshift != "—" and re.match(r'^-?\d+(\.\d+)?$', redshift) else 0.0};
    const MAX_DATE = {float(maxdate) if maxdate != "—" and re.match(r'^-?\d+(\.\d+)?$', maxdate) else 'null'};

    // Cutout layer switcher & Archival Blink Comparator
    let primaryLayer = '{default_layer}';
    let currentLayer = primaryLayer;
    let blinkTimer = null;

    function getSurveyLabel(layer) {{
      if (layer === 'desi') return 'DESI DR10 Optical (0.26″/pix)';
      if (layer === 'panstarrs') return 'Pan-STARRS1 DR1 Optical (0.25″/pix)';
      if (layer === 'dss') return 'DSS2 Archival (1980s–1990s Photographic Plates)';
      return layer.toUpperCase();
    }}

    function switchLayer(layer) {{
      if (blinkTimer) {{
        clearInterval(blinkTimer);
        blinkTimer = null;
        document.getElementById('btn-blink')?.classList.remove('active');
      }}
      currentLayer = layer;
      if (layer !== 'dss') {{
        primaryLayer = layer;
      }}
      const img = document.getElementById('cutout-img');
      const badge = document.getElementById('cutout-status-badge');
      const badgeText = document.getElementById('cutout-status-text');
      if (!img) return;

      document.getElementById('btn-desi')?.classList.toggle('active', layer === 'desi');
      document.getElementById('btn-panstarrs')?.classList.toggle('active', layer === 'panstarrs');
      document.getElementById('btn-dss')?.classList.toggle('active', layer === 'dss');

      if (layer === 'desi') {{
        img.src = DESI_URL;
        if (badge) badge.className = 'cutout-status-badge modern';
      }} else if (layer === 'panstarrs') {{
        img.src = PANSTARRS_URL;
        if (badge) badge.className = 'cutout-status-badge modern';
      }} else if (layer === 'dss') {{
        img.src = DSS_URL;
        if (badge) badge.className = 'cutout-status-badge archival';
      }}
      if (badgeText) badgeText.innerText = getSurveyLabel(layer);
    }}

    function handleCutoutError() {{
      const img = document.getElementById('cutout-img');
      if (!img) return;
      // Smooth automatic survey fallback
      if (currentLayer === 'desi') {{
        primaryLayer = 'panstarrs';
        switchLayer('panstarrs');
      }} else if (currentLayer === 'panstarrs') {{
        switchLayer('dss');
      }} else if (currentLayer === 'dss' && img.src !== SKYVIEW_DSS_URL) {{
        img.src = SKYVIEW_DSS_URL;
      }}
    }}

    function toggleBlink() {{
      const btn = document.getElementById('btn-blink');
      if (blinkTimer) {{
        clearInterval(blinkTimer);
        blinkTimer = null;
        btn?.classList.remove('active');
        switchLayer(primaryLayer);
      }} else {{
        btn?.classList.add('active');
        let blinkToDss = true;
        // Blink alternates between the high-definition modern optical survey and historical DSS2 plates
        const img = document.getElementById('cutout-img');
        const badge = document.getElementById('cutout-status-badge');
        const badgeText = document.getElementById('cutout-status-text');

        if (img) img.src = DSS_URL;
        if (badge) badge.className = 'cutout-status-badge archival';
        if (badgeText) badgeText.innerText = getSurveyLabel('dss');
        document.getElementById('btn-desi')?.classList.toggle('active', false);
        document.getElementById('btn-panstarrs')?.classList.toggle('active', false);
        document.getElementById('btn-dss')?.classList.toggle('active', true);

        blinkTimer = setInterval(() => {{
          blinkToDss = !blinkToDss;
          const activeLyr = blinkToDss ? 'dss' : primaryLayer;
          if (img) img.src = blinkToDss ? DSS_URL : (primaryLayer === 'desi' ? DESI_URL : PANSTARRS_URL);
          if (badge) badge.className = 'cutout-status-badge ' + (blinkToDss ? 'archival' : 'modern');
          if (badgeText) badgeText.innerText = getSurveyLabel(activeLyr);
          document.getElementById('btn-desi')?.classList.toggle('active', activeLyr === 'desi');
          document.getElementById('btn-panstarrs')?.classList.toggle('active', activeLyr === 'panstarrs');
          document.getElementById('btn-dss')?.classList.toggle('active', activeLyr === 'dss');
        }}, 750);
      }}
    }}

    // Aladin Lite initialization & multi-survey switcher (custom sne.space UI)
    window.aladinInstance = null;
    let simbadCatalogLayer = null;
    let targetCatalogLayer = null;
    let targetVisible = true;

    function clearCockpitSelectedTelemetry(evt) {{
      if (evt) {{ evt.stopPropagation(); }}
      let defHud = document.getElementById('cockpit-hud-default');
      let selHud = document.getElementById('cockpit-hud-selected');
      if (defHud) defHud.style.display = 'flex';
      if (selHud) selHud.style.display = 'none';
      if (window.aladinInstance && window.aladinInstance.popup) {{
        window.aladinInstance.popup.hide();
      }}
    }}

    function displayTelemetryPopup(aladinObj, source, titleHtml, bodyHtml) {{
      if (aladinObj && aladinObj.popup) {{
        aladinObj.popup.hide();
      }}
      let defHud = document.getElementById('cockpit-hud-default');
      let selHud = document.getElementById('cockpit-hud-selected');
      let content = document.getElementById('cockpit-hud-content');
      if (!selHud || !content || !source) return;

      let d = source.data || {{}};
      let rawName = getSimbadVal(d, 'MAIN_ID', 'main_id', 'MATCHING_ID', 'matching_id', 'TYPED_ID', 'typed_id', 'id', 'name');
      let otype = getSimbadVal(d, 'OTYPE_S', 'otype_s', 'OTYPE', 'otype', 'OTYPE_V', 'otype_v', 'src_class', 'TYPE', 'type') || 'Object';
      let coo = getSimbadVal(d, 'COO', 'coo') || (isFinite(source.ra) && isFinite(source.dec) ? source.ra.toFixed(4) + '°, ' + source.dec.toFixed(4) + '°' : '');
      let zVal = getSimbadVal(d, 'Z_VALUE', 'z_value', 'redshift', 'z');
      let rvVal = getSimbadVal(d, 'RV_VALUE', 'rv_value', 'cz', 'vlsr', 'VLSR');
      let majAxis = getSimbadVal(d, 'GALDIM_MAJAXIS', 'galdim_majaxis', 'smajaxis');
      let minAxis = getSimbadVal(d, 'GALDIM_MINAXIS', 'galdim_minaxis', 'sminaxis');
      let bibs = getSimbadVal(d, 'NB_BIBLIO', 'nb_biblio', 'biblist', 'BIBLIST');

      let sepArcsec = null;
      if (RA_DEG !== null && DEC_DEG !== null && isFinite(source.ra) && isFinite(source.dec)) {{
        let dRa = (source.ra - RA_DEG) * Math.cos(DEC_DEG * Math.PI / 180);
        let dDec = source.dec - DEC_DEG;
        let sepDeg = Math.sqrt(dRa * dRa + dDec * dDec);
        sepArcsec = (sepDeg * 3600).toFixed(1);
      }}
      let isHost = (sepArcsec !== null && parseFloat(sepArcsec) < 15.0 && (otype.includes('G') || otype.includes('Galaxy')));
      let typeLabel = isHost ? 'Supernova Host Galaxy' : otype;

      let simbadLink = rawName ? ('https://simbad.cds.unistra.fr/simbad/sim-id?Ident=' + encodeURIComponent(rawName)) : ('https://simbad.cds.unistra.fr/simbad/sim-coo?Coord=' + encodeURIComponent(source.ra + ' ' + source.dec) + '&Radius=1&Radius.unit=arcmin');

      content.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;font-weight:700;color:#fff;font-size:0.83rem;white-space:nowrap;">
          <span style="color:#38bdf8;">●</span> ` + (rawName || 'Catalog Source') + `
          <span style="font-size:0.65rem;padding:2px 6px;border-radius:3px;background:rgba(56,189,248,0.22);color:#38bdf8;border:1px solid rgba(56,189,248,0.4);">` + typeLabel + `</span>
        </div>
        <div style="display:flex;align-items:center;gap:12px;font-size:0.75rem;color:#cbd5e1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
          <span><strong style="color:#94a3b8;">Coords:</strong> <span style="font-family:monospace;color:#f1f5f9;">` + coo + `</span></span>
          ` + (sepArcsec ? `<span><strong style="color:#94a3b8;">Sep:</strong> ` + sepArcsec + `″ from SN</span>` : '') + `
          ` + (zVal ? `<span><strong style="color:#94a3b8;">Redshift:</strong> z = ` + (parseFloat(zVal) ? parseFloat(zVal).toFixed(4) : zVal) + `</span>` : (rvVal ? `<span><strong style="color:#94a3b8;">Radial Velocity:</strong> ` + parseFloat(rvVal).toFixed(0) + ` km/s</span>` : '')) + `
          ` + (majAxis && minAxis ? `<span><strong style="color:#94a3b8;">Size:</strong> ` + majAxis + `′ × ` + minAxis + `′</span>` : '') + `
          ` + (bibs && bibs !== '0' ? `<span><strong style="color:#94a3b8;">Bib:</strong> ` + bibs + ` papers</span>` : '') + `
        </div>
        <a href="` + simbadLink + `" target="_blank" rel="noopener" style="font-size:0.72rem;font-weight:600;color:#38bdf8;text-decoration:none;padding:2px 8px;border-radius:4px;border:1px solid rgba(56,189,248,0.4);background:rgba(56,189,248,0.1);white-space:nowrap;margin-left:auto;">SIMBAD ↗</a>
      `;
      if (defHud) defHud.style.display = 'none';
      selHud.style.display = 'flex';
    }}

    function showTargetTelemetry() {{
      if (!window.aladinInstance || RA_DEG === null || DEC_DEG === null) return;
      if (window.aladinInstance.popup) window.aladinInstance.popup.hide();
      let defHud = document.getElementById('cockpit-hud-default');
      let selHud = document.getElementById('cockpit-hud-selected');
      let content = document.getElementById('cockpit-hud-content');
      if (!selHud || !content) return;

      content.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;font-weight:700;color:#fff;font-size:0.83rem;white-space:nowrap;">
          <span style="color:#38bdf8;animation:pulse-halo 2s infinite;">●</span> {name} Target
          <span style="font-size:0.65rem;padding:2px 6px;border-radius:3px;background:rgba(56,189,248,0.25);color:#38bdf8;border:1px solid rgba(56,189,248,0.5);">{claimedtype}</span>
        </div>
        <div style="display:flex;align-items:center;gap:12px;font-size:0.75rem;color:#cbd5e1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
          <span><strong style="color:#94a3b8;">Coords:</strong> <span style="font-family:monospace;color:#f1f5f9;">{ra_str} {dec_str}</span></span>
          <span><strong style="color:#94a3b8;">Peak:</strong> Mag {maxappmag}</span>
          <span><strong style="color:#94a3b8;">Host:</strong> {host if host != "—" else "Field Host (see SIMBAD)"}{f" ({host_offset_str})" if host_offset_str != "—" else ""}</span>
          <span><strong style="color:#94a3b8;">Redshift:</strong> z = {redshift}</span>
        </div>
        <a href="/sne/{urllib.parse.quote(name)}/story" style="font-size:0.72rem;font-weight:600;color:#38bdf8;text-decoration:none;padding:2px 8px;border-radius:4px;border:1px solid rgba(56,189,248,0.4);background:rgba(56,189,248,0.1);white-space:nowrap;margin-left:auto;">Story Mode ↗</a>
      `;
      if (defHud) defHud.style.display = 'none';
      selHud.style.display = 'flex';
    }}

    function getSimbadVal(d, ...keys) {{
      if (!d) return '';
      for (let k of keys) {{
        if (d[k] !== undefined && d[k] !== null && String(d[k]).trim() !== '') {{
          return String(d[k]).trim();
        }}
      }}
      let lowerMap = {{}};
      for (let k of Object.keys(d)) {{
        lowerMap[k.toLowerCase()] = d[k];
      }}
      for (let k of keys) {{
        let lk = k.toLowerCase();
        if (lowerMap[lk] !== undefined && lowerMap[lk] !== null && String(lowerMap[lk]).trim() !== '') {{
          return String(lowerMap[lk]).trim();
        }}
      }}
      return '';
    }}

    function formatSimbadData(source, targetRa, targetDec) {{
      let d = source.data || {{}};
      let rawName = getSimbadVal(d, 'MAIN_ID', 'main_id', 'MATCHING_ID', 'matching_id', 'TYPED_ID', 'typed_id', 'id', 'name');
      let otype = getSimbadVal(d, 'OTYPE_S', 'otype_s', 'OTYPE', 'otype', 'OTYPE_V', 'otype_v', 'src_class', 'TYPE', 'type') || 'Object';
      let ra = source.ra;
      let dec = source.dec;
      let coo = getSimbadVal(d, 'COO', 'coo') || (isFinite(ra) && isFinite(dec) ? ra.toFixed(5) + '°, ' + dec.toFixed(5) + '°' : '');
      let bibs = getSimbadVal(d, 'NB_BIBLIO', 'nb_biblio', 'biblist', 'BIBLIST') || '0';
      let morph = getSimbadVal(d, 'MORPH_TYPE', 'morph_type', 'morph');
      let spType = getSimbadVal(d, 'SP_TYPE', 'sp_type', 'sptype');
      let plxRaw = getSimbadVal(d, 'PLX_VALUE', 'plx_value', 'plx');
      let plx = plxRaw ? parseFloat(plxRaw) : null;
      let majAxis = getSimbadVal(d, 'GALDIM_MAJAXIS', 'galdim_majaxis', 'smajaxis');
      let minAxis = getSimbadVal(d, 'GALDIM_MINAXIS', 'galdim_minaxis', 'sminaxis');
      let zVal = getSimbadVal(d, 'Z_VALUE', 'z_value', 'redshift', 'z');
      let rvVal = getSimbadVal(d, 'RV_VALUE', 'rv_value', 'cz', 'vlsr', 'VLSR');

      // Angular distance from supernova site in arcseconds
      let sepArcsec = null;
      if (targetRa !== null && targetDec !== null && isFinite(ra) && isFinite(dec)) {{
        let dRa = (ra - targetRa) * Math.cos(targetDec * Math.PI / 180);
        let dDec = dec - targetDec;
        let sepDeg = Math.sqrt(dRa * dRa + dDec * dDec);
        sepArcsec = (sepDeg * 3600).toFixed(1);
      }}

      let isHost = (sepArcsec !== null && parseFloat(sepArcsec) < 15.0 && (otype.includes('G') || otype.includes('Galaxy')));

      // Ultra-clean concise sky label
      let skyLabel = '';
      if (isHost) {{
        skyLabel = 'Host Galaxy';
      }} else if (otype === 'Star' || otype.includes('*') || rawName.startsWith('Gaia') || rawName.startsWith('UCAC') || rawName.startsWith('2MASS') || rawName.startsWith('TYC')) {{
        skyLabel = 'Star';
      }} else if (otype.includes('Galaxy') || otype.includes('G') || rawName.startsWith('LEDA') || rawName.startsWith('2MASX') || rawName.startsWith('WISEA')) {{
        skyLabel = 'Galaxy';
      }} else if (otype.includes('QSO') || otype.includes('AGN')) {{
        skyLabel = otype;
      }} else {{
        skyLabel = otype || 'Object';
      }}
      d.sky_label = skyLabel;

      let typeLabel = otype;
      if (isHost) typeLabel = 'Supernova Host Galaxy';
      else if (otype === 'EmissionG' || otype === 'EmG') typeLabel = 'Emission-line Galaxy';
      else if (otype === 'Galaxy' || otype === 'G') typeLabel = 'Field Galaxy';
      else if (otype === 'Star' || otype === '*') typeLabel = 'Field Star';
      else if (otype === 'HighPM*' || otype === 'PM*') typeLabel = 'High Proper-Motion Star';

      let detailsHtml = '';
      if (sepArcsec !== null) {{
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Separation:</strong> ' + sepArcsec + '″ from SN site</div>';
      }}
      if (zVal) {{
        let zF = parseFloat(zVal);
        let zDisp = isFinite(zF) ? zF.toFixed(4) : zVal;
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Redshift (z):</strong> ' + zDisp + (rvVal ? ' (v ≈ ' + parseFloat(rvVal).toFixed(0) + ' km/s)' : '') + '</div>';
      }} else if (rvVal) {{
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Radial Velocity:</strong> ' + parseFloat(rvVal).toFixed(0) + ' km/s</div>';
      }}
      if (morph) {{
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Morphology:</strong> ' + morph + '</div>';
      }}
      if (spType) {{
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Spectral Type:</strong> ' + spType + '</div>';
      }}
      if (plx && plx > 0) {{
        let distPc = (1000 / plx).toFixed(0);
        let distLy = (distPc * 3.26156).toFixed(0);
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Gaia Distance:</strong> ~' + distLy + ' light-years (ϖ = ' + plx.toFixed(2) + ' mas)</div>';
      }}
      if (majAxis && minAxis) {{
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Angular Size:</strong> ' + majAxis + '′ × ' + minAxis + '′</div>';
      }}
      if (bibs && bibs !== '0') {{
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Bibliography:</strong> ' + bibs + ' NASA ADS papers</div>';
      }}

      let titleHtml = '<div style="display:flex;align-items:center;justify-content:space-between;width:100%;gap:6px;"><span style="font-weight:700;color:#fff;font-size:0.86rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:180px;">' + (rawName || skyLabel) + '</span><span style="font-size:0.65rem;font-weight:700;padding:2px 6px;border-radius:3px;background:rgba(56,189,248,0.25);color:#38bdf8;">' + (otype || 'Object') + '</span></div>';

      let simbadLink = rawName ? ('https://simbad.cds.unistra.fr/simbad/sim-id?Ident=' + encodeURIComponent(rawName)) : ('https://simbad.cds.unistra.fr/simbad/sim-coo?Coord=' + encodeURIComponent(source.ra + ' ' + source.dec) + '&Radius=1&Radius.unit=arcmin');

      let popupHtml = `
        <div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;line-height:1.45;">
          <div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;">
            <strong style="color:#cbd5e1;">Class:</strong> ` + typeLabel + `
          </div>
          <div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;">
            <strong style="color:#cbd5e1;">Coordinates:</strong> <span style="font-family:monospace;color:#f1f5f9;">` + coo + `</span>
          </div>
          ` + detailsHtml + `
          <div style="margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.1);display:flex;justify-content:space-between;align-items:center;">
            <span style="font-size:0.65rem;color:#64748b;">CDS SIMBAD Astronomical DB</span>
            <a href="` + simbadLink + `" target="_blank" rel="noopener" style="font-size:0.73rem;font-weight:600;color:#38bdf8;text-decoration:none;">View SIMBAD ↗</a>
          </div>
        </div>
      `;
      return {{ skyLabel, titleHtml, popupHtml }};
    }}

    function drawNaturalDot(source, ctx) {{
      const x = source.x;
      const y = source.y;
      if (!isFinite(x) || !isFinite(y)) return;
      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y, 4.5, 0, 2 * Math.PI);
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.45)';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(x, y, 1.8, 0, 2 * Math.PI);
      ctx.fillStyle = '#38bdf8';
      ctx.fill();
      ctx.restore();
    }}

    function toggleTargetMarker(btn) {{
      targetVisible = !targetVisible;
      const pin = document.getElementById('aladin-target-pin');
      if (pin) pin.style.display = targetVisible ? 'flex' : 'none';
      if (targetCatalogLayer) {{
        if (targetVisible) targetCatalogLayer.show();
        else targetCatalogLayer.hide();
      }}
      if (btn) {{
        if (targetVisible) {{
          btn.classList.add('active');
          btn.title = "Hide target pin & reticle to view raw optical host galaxy";
        }} else {{
          btn.classList.remove('active');
          btn.title = "Show target pin & reticle";
        }}
      }}
      if (window.aladinInstance && window.aladinInstance.view && window.aladinInstance.view.requestRedraw) {{
        window.aladinInstance.view.requestRedraw();
      }}
    }}

    function switchAladinSurvey(surveyId, btn) {{
      if (window.aladinInstance && window.aladinInstance.setImageSurvey) {{
        window.aladinInstance.setImageSurvey(surveyId);
        document.querySelectorAll('#btn-aladin-dss, #btn-aladin-ps1, #btn-aladin-2mass, #btn-aladin-wise').forEach(b => b.classList.remove('active'));
        if (btn) btn.classList.add('active');
      }}
    }}

    function toggleSimbadOverlay(btn) {{
      if (!window.aladinInstance || typeof A === 'undefined' || RA_DEG === null || DEC_DEG === null) return;
      if (simbadCatalogLayer) {{
        if (simbadCatalogLayer.isShowing) {{
          simbadCatalogLayer.hide();
          if (window.aladinInstance.popup) window.aladinInstance.popup.hide();
          if (btn) {{
            btn.classList.remove('active');
            btn.innerText = '🏷️ SIMBAD Labels';
          }}
        }} else {{
          simbadCatalogLayer.show();
          if (btn) {{
            btn.classList.add('active');
            btn.innerText = '🏷️ SIMBAD Labels';
          }}
        }}
        if (window.aladinInstance.view && window.aladinInstance.view.requestRedraw) {{
          window.aladinInstance.view.requestRedraw();
        }}
      }} else {{
        try {{
          if (btn) {{
            btn.classList.add('active');
            btn.innerText = '⏳ Loading...';
          }}
          const showSourcePopup = function(source) {{
            if (!source) return;
            let res = formatSimbadData(source, RA_DEG, DEC_DEG);
            displayTelemetryPopup(window.aladinInstance, source, res.titleHtml, res.popupHtml);
          }};

          simbadCatalogLayer = A.catalogFromSimbad(
            {{ra: RA_DEG, dec: DEC_DEG}},
            0.18,
            {{
              name: 'SIMBAD',
              color: '#38bdf8',
              sourceSize: 10,
              onClick: showSourcePopup,
              displayLabel: true
            }},
            function(cat) {{
              if (btn) {{
                btn.innerText = '🏷️ SIMBAD Labels';
                btn.classList.add('active');
              }}
              cat.onClick = showSourcePopup;
              cat.sources.forEach(s => {{
                let res = formatSimbadData(s, RA_DEG, DEC_DEG);
                s.data.sky_label = res.skyLabel;
                s.popupTitle = res.titleHtml;
                s.popupDesc = res.popupHtml;
                s.actionClicked = function() {{ showSourcePopup(s); }};
              }});
              cat.labelColumn = 'sky_label';
              cat.labelFont = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
              cat.labelColor = '#7dd3fc';
              cat.shape = drawNaturalDot;
              cat.updateShape();
              cat.displayLabel = true;
              if (window.aladinInstance.view && window.aladinInstance.view.requestRedraw) {{
                window.aladinInstance.view.requestRedraw();
              }}
            }}
          );
          window.aladinInstance.addCatalog(simbadCatalogLayer);
          window.aladinInstance.on('objectClicked', function(obj) {{
            if (!obj) return;
            showSourcePopup(obj);
          }});
        }} catch (e) {{
          console.warn('SIMBAD overlay error:', e);
          if (btn) {{
            btn.classList.remove('active');
            btn.innerText = '🏷️ SIMBAD Labels';
          }}
        }}
      }}
    }}

    function recenterAladin() {{
      if (window.aladinInstance && RA_DEG !== null && DEC_DEG !== null) {{
        window.aladinInstance.gotoRaDec(RA_DEG, DEC_DEG);
      }}
    }}

    function zoomAladin(factor) {{
      if (window.aladinInstance) {{
        if (factor > 1) window.aladinInstance.increaseZoom();
        else window.aladinInstance.decreaseZoom();
      }}
    }}

    function updateTargetPin() {{
      if (!window.aladinInstance || RA_DEG === null || DEC_DEG === null) return;
      try {{
        let pix = window.aladinInstance.world2pix(RA_DEG, DEC_DEG);
        let pin = document.getElementById('aladin-target-pin');
        if (pin && pix && isFinite(pix[0]) && isFinite(pix[1])) {{
          pin.style.left = pix[0] + 'px';
          pin.style.top = pix[1] + 'px';
        }}
        let fov = window.aladinInstance.getFov();
        let fovLbl = document.getElementById('aladin-fov-label');
        if (fovLbl && fov) {{
          fovLbl.innerText = 'FOV: ' + (fov < 1 ? (fov * 60).toFixed(1) + "'" : fov.toFixed(2) + '°');
        }}
      }} catch (e) {{}}
    }}

    if (RA_DEG !== null && DEC_DEG !== null && typeof A !== 'undefined') {{
      const initAladin = () => {{
        try {{
          // Automatically select the most HD optical survey available for this declination
          const hdSurvey = (DEC_DEG !== null && DEC_DEG >= -30.0) ? "P/PanSTARRS/DR1/color-z-zg-g" : "P/DSS2/color";
          let aladin = A.aladin('#aladin-lite-div', {{
            survey: hdSurvey,
            fov: 0.15,
            target: RA_DEG + " " + DEC_DEG,
            showReticle: false,
            showZoomControl: false,
            showLayersControl: false,
            showFullscreenControl: false,
            showSimbadPointerControl: false,
            showCooGridControl: false,
            showSettingsControl: false,
            showColorPickerControl: false,
            showShareControl: false,
            showFrame: false,
            showFov: false,
            showCooLocation: false,
            showProjectionControl: false,
            showContextMenu: false,
            showStatusBar: false,
            backgroundColor: '#070a13'
          }});
          window.aladinInstance = aladin;
          aladin.gotoRaDec(RA_DEG, DEC_DEG);
          aladin.setFov(0.15);
          let cat = A.catalog({{name: 'Target', sourceSize: 0, color: 'transparent'}});
          targetCatalogLayer = cat;
          aladin.addCatalog(cat);
          setInterval(updateTargetPin, 100);

          let alDiv = document.getElementById('aladin-lite-div');
          if (alDiv) {{
            alDiv.addEventListener('click', function(evt) {{
              if (!simbadCatalogLayer || !simbadCatalogLayer.sources || simbadCatalogLayer.sources.length === 0) return;
              let rect = alDiv.getBoundingClientRect();
              let clickX = evt.clientX - rect.left;
              let clickY = evt.clientY - rect.top;
              let bestSource = null;
              let minDist = 30;
              for (let s of simbadCatalogLayer.sources) {{
                let x = s.x, y = s.y;
                if (!isFinite(x) || !isFinite(y)) {{
                  let pix = aladin.world2pix(s.ra, s.dec);
                  if (pix && isFinite(pix[0])) {{ x = pix[0]; y = pix[1]; }}
                }}
                if (!isFinite(x) || !isFinite(y)) continue;
                let dx = x - clickX;
                let dy = y - clickY;
                let dist = Math.sqrt(dx * dx + dy * dy);
                let lDx = clickX - x;
                let lDy = Math.abs(clickY - y);
                if (lDx >= -12 && lDx <= 85 && lDy <= 16) {{
                  dist = Math.min(dist, 8);
                }}
                if (dist < minDist) {{
                  minDist = dist;
                  bestSource = s;
                }}
              }}
              if (bestSource) {{
                let res = formatSimbadData(bestSource, RA_DEG, DEC_DEG);
                displayTelemetryPopup(aladin, bestSource, res.titleHtml, res.popupHtml);
              }}
            }});
          }}
        }} catch (e) {{
          console.warn('Aladin init error:', e);
        }}
      }};
      if (A.init && typeof A.init.then === 'function') {{
        A.init.then(initAladin);
      }} else {{
        initAladin();
      }}
    }}

    document.addEventListener('keydown', function(e) {{
      if (e.key === 'Escape') {{
        clearCockpitSelectedTelemetry();
      }}
    }});

    // Plotly Multi-band Light Curve
    const BAND_COLORS = {{
      'u': '#702670', 'g': '#3b719f', 'r': '#379936', 'i': '#c23b23', 'z': '#8c1b1b',
      'c': '#00bcd4', 'cyan': '#00bcd4', 'o': '#ff9800', 'orange': '#ff9800',
      'B': '#2196f3', 'V': '#4caf50', 'R': '#e91e63', 'I': '#9c27b0'
    }};
    let currentTimeBase = 'mjd';

    function renderLightCurve() {{
      if (!PHOTO_DATA || PHOTO_DATA.length === 0) {{
        document.getElementById('plot-lc').innerHTML = '<p style="color:#94a3b8;padding:2rem;text-align:center">No calibrated photometry points available.</p>';
        return;
      }}
      // Group by band
      const bands = {{}};
      let minMjd = Infinity;
      PHOTO_DATA.forEach(p => {{
        if (p.time < minMjd && !p.uplim) minMjd = p.time;
        const b = p.band || 'other';
        if (!bands[b]) bands[b] = {{ detections: [], upperlimits: [] }};
        if (p.uplim) bands[b].upperlimits.push(p);
        else bands[b].detections.push(p);
      }});

      const peakTime = MAX_DATE !== null ? MAX_DATE : (minMjd !== Infinity ? minMjd : 0);
      const traces = [];

      Object.keys(bands).forEach(b => {{
        const color = BAND_COLORS[b] || '#94a3b8';
        const dets = bands[b].detections;
        if (dets.length > 0) {{
          traces.push({{
            name: b,
            x: dets.map(p => currentTimeBase === 'mjd' ? p.time : (p.time - peakTime) / (1 + REDSHIFT)),
            y: dets.map(p => p.mag),
            error_y: {{
              type: 'data',
              array: dets.map(p => p.err || 0),
              visible: true,
              color: color,
              thickness: 1
            }},
            mode: 'markers',
            type: 'scatter',
            marker: {{ size: 7, color: color }},
            text: dets.map(p => `${{p.tel}} (mag ${{p.mag}})`),
            hoverinfo: 'x+y+text+name'
          }});
        }}
        const uplims = bands[b].upperlimits;
        if (uplims.length > 0) {{
          traces.push({{
            name: `${{b}} (limits)`,
            x: uplims.map(p => currentTimeBase === 'mjd' ? p.time : (p.time - peakTime) / (1 + REDSHIFT)),
            y: uplims.map(p => p.mag),
            mode: 'markers',
            type: 'scatter',
            marker: {{ size: 8, color: color, symbol: 'triangle-down-open' }},
            hoverinfo: 'x+y+name'
          }});
        }}
      }});

      const layout = {{
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        margin: {{ t: 20, r: 20, b: 50, l: 60 }},
        font: {{ color: '#e2e8f0', family: 'sans-serif' }},
        xaxis: {{
          title: currentTimeBase === 'mjd' ? 'Time (MJD)' : 'Rest-Frame Days from Peak',
          gridcolor: '#1e293b',
          zerolinecolor: '#334155'
        }},
        yaxis: {{
          title: 'Apparent Magnitude',
          autorange: 'reversed',
          gridcolor: '#1e293b',
          zerolinecolor: '#334155'
        }},
        legend: {{ orientation: 'h', y: -0.2 }}
      }};

      Plotly.newPlot('plot-lc', traces, layout, {{ responsive: true, displaylogo: false }});
    }}

    function switchTimeBase(base) {{
      currentTimeBase = base;
      document.getElementById('btn-time-mjd').classList.toggle('active', base === 'mjd');
      document.getElementById('btn-time-rest').classList.toggle('active', base === 'rest');
      renderLightCurve();
    }}

    // Spectra Viewer
    let deredshift = false;
    let showLines = false;
    let smoothing = 1;

    function renderSpectra() {{
      if (!SPEC_DATA || SPEC_DATA.length === 0) {{
        document.getElementById('plot-spec').innerHTML = '<p style="color:#94a3b8;padding:2rem;text-align:center">No calibrated spectra available.</p>';
        return;
      }}
      const traces = [];
      SPEC_DATA.forEach((s, idx) => {{
        let x = s.data.map(p => deredshift && REDSHIFT > 0 ? p[0] / (1 + REDSHIFT) : p[0]);
        let rawY = s.data.map(p => p[1]);
        // Relative flux normalization (median/90th percentile = 1.0) with vertical offset for multi-epoch stacking
        let pos = rawY.filter(v => v > 0 && isFinite(v)).sort((a,b) => a - b);
        let scale = pos.length > 0 ? (pos[Math.floor(pos.length * 0.90)] || pos[Math.floor(pos.length * 0.5)]) : 1;
        if (scale <= 0) scale = 1;

        // Normalize flux and clamp negative sky-subtraction/telluric artifacts to zero
        let y = rawY.map(v => Math.max(0.0, v / scale));

        // Simple boxcar smoothing
        if (smoothing > 1) {{
          let smoothed = [];
          for (let i = 0; i < y.length; i++) {{
            let start = Math.max(0, i - Math.floor(smoothing / 2));
            let end = Math.min(y.length, i + Math.floor(smoothing / 2) + 1);
            let sum = 0;
            for (let j = start; j < end; j++) sum += y[j];
            smoothed.push(sum / (end - start));
          }}
          y = smoothed;
        }}

        let offset = idx * 1.2;
        let stackedY = y.map(v => v + offset);

        traces.push({{
          name: s.time ? `MJD ${{parseFloat(s.time).toFixed(1)}} (${{s.tel}})` : s.tel,
          x: x,
          y: stackedY,
          mode: 'lines',
          type: 'scatter',
          line: {{ width: 1.5 }}
        }});
      }});

      const shapes = [];
      const annotations = [];
      if (showLines) {{
        const lines = [
          {{ name: 'Si II λ6355', wave: 6355, color: '#f59e0b' }},
          {{ name: 'Ca II H&K', wave: 3945, color: '#ec4899' }},
          {{ name: 'Hα λ6563', wave: 6563, color: '#3b82f6' }},
          {{ name: 'Hβ λ4861', wave: 4861, color: '#06b6d4' }},
          {{ name: 'He I λ5876', wave: 5876, color: '#10b981' }}
        ];
        lines.forEach(l => {{
          shapes.push({{
            type: 'line',
            x0: l.wave, x1: l.wave,
            y0: 0, y1: 1,
            yref: 'paper',
            line: {{ color: l.color, width: 1.5, dash: 'dot' }}
          }});
          annotations.push({{
            x: l.wave,
            y: 1.02,
            yref: 'paper',
            text: l.name,
            showarrow: false,
            font: {{ size: 10, color: l.color }}
          }});
        }});
      }}

      const layout = {{
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        margin: {{ t: 30, r: 20, b: 50, l: 60 }},
        font: {{ color: '#e2e8f0', family: 'sans-serif' }},
        shapes: shapes,
        annotations: annotations,
        xaxis: {{
          title: deredshift ? 'Rest-Frame Wavelength (Å)' : 'Observed Wavelength (Å)',
          gridcolor: '#1e293b'
        }},
        yaxis: {{
          title: SPEC_DATA.length > 1 ? 'Relative Flux (+ vertical offset)' : 'Relative Normalized Flux',
          gridcolor: '#1e293b',
          rangemode: 'tozero'
        }},
        legend: {{ orientation: 'h', y: -0.2 }}
      }};

      Plotly.newPlot('plot-spec', traces, layout, {{ responsive: true, displaylogo: false }});
    }}

    function toggleDeredshift() {{
      deredshift = !deredshift;
      document.getElementById('btn-deredshift').classList.toggle('active', deredshift);
      renderSpectra();
    }}
    function toggleLines() {{
      showLines = !showLines;
      document.getElementById('btn-lines').classList.toggle('active', showLines);
      renderSpectra();
    }}
    function updateSmoothing(val) {{
      smoothing = parseInt(val, 10);
      document.getElementById('smooth-val').textContent = val + 'x';
      renderSpectra();
    }}

    // BibTeX Modal helpers
    function openBibModal() {{
      document.getElementById('bib-modal').style.display = 'flex';
    }}
    function closeBibModal() {{
      document.getElementById('bib-modal').style.display = 'none';
    }}
    function copyBibTeX() {{
      const txt = document.getElementById('bib-content');
      txt.select();
      navigator.clipboard.writeText(txt.value).then(() => {{
        alert('BibTeX copied to clipboard!');
        closeBibModal();
      }});
    }}

    // Observability & Air Mass Planner
    const SITES = {{
      keck: {{ name: 'Keck (Mauna Kea)', lat: 19.826, lon: -155.474, utcOffset: -10 }},
      paranal: {{ name: 'VLT (Paranal)', lat: -24.627, lon: -70.404, utcOffset: -4 }},
      palomar: {{ name: 'Palomar Obs.', lat: 33.356, lon: -116.865, utcOffset: -7 }},
      lapalma: {{ name: 'La Palma (ORM)', lat: 28.760, lon: -17.881, utcOffset: 0 }}
    }};

    window.__userGps = null;

    function calcObservability() {{
      const statsEl = document.getElementById('obs-stats');
      const plotEl = document.getElementById('plot-airmass');
      if (!statsEl || !plotEl) return;
      if (RA_DEG === null || DEC_DEG === null) {{
        statsEl.innerHTML = '<div style="grid-column:span 2;color:var(--text-muted);font-size:0.75rem;">Target coordinates unavailable for airmass calculation.</div>';
        return;
      }}
      const siteKey = document.getElementById('obs-site').value;
      if (siteKey === 'gps') {{
        if (window.__userGps) {{
          runCalcForSite(window.__userGps);
        }} else if (navigator.geolocation) {{
          statsEl.innerHTML = '<div style="grid-column:span 2;color:var(--accent);font-size:0.78rem;padding:0.5rem;text-align:center;">🛰️ Requesting GPS location from browser...</div>';
          navigator.geolocation.getCurrentPosition(
            pos => {{
              const tzOffset = -new Date().getTimezoneOffset() / 60;
              window.__userGps = {{
                name: `My GPS (${{pos.coords.latitude >= 0 ? '+' : ''}}${{pos.coords.latitude.toFixed(2)}}°, ${{pos.coords.longitude >= 0 ? '+' : ''}}${{pos.coords.longitude.toFixed(2)}}°)`,
                lat: pos.coords.latitude,
                lon: pos.coords.longitude,
                utcOffset: tzOffset
              }};
              runCalcForSite(window.__userGps);
            }},
            err => {{
              alert('Could not obtain GPS location (' + err.message + '). Defaulting to Keck Observatory.');
              document.getElementById('obs-site').value = 'keck';
              runCalcForSite(SITES.keck);
            }},
            {{ timeout: 8000 }}
          );
        }} else {{
          alert('Geolocation not supported by your browser. Defaulting to Keck Observatory.');
          document.getElementById('obs-site').value = 'keck';
          runCalcForSite(SITES.keck);
        }}
        return;
      }}

      const site = SITES[siteKey] || SITES.keck;
      runCalcForSite(site);
    }}

    function runCalcForSite(site) {{
      const statsEl = document.getElementById('obs-stats');
      const plotEl = document.getElementById('plot-airmass');
      if (!statsEl || !plotEl) return;

      const now = new Date();
      const nowUtcMs = now.getTime();
      const obsNow = new Date(nowUtcMs + site.utcOffset * 3600000);
      const startLocal = new Date(obsNow.getFullYear(), obsNow.getMonth(), obsNow.getDate(), 18, 0, 0);
      const startUtcMs = startLocal.getTime() - site.utcOffset * 3600000;

      const times = [];
      const airmasses = [];
      let minX = Infinity;
      let minXTime = '';
      let obsHoursCount = 0;

      for (let i = 0; i <= 24; i++) {{
        let tUtcMs = startUtcMs + i * 1800000;
        let tLocal = new Date(tUtcMs + site.utcOffset * 3600000);
        let hh = String(tLocal.getHours()).padStart(2, '0');
        let mm = String(tLocal.getMinutes()).padStart(2, '0');
        let label = `${{hh}}:${{mm}}`;

        let jd = (tUtcMs / 86400000.0) + 2440587.5;
        let gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360;
        if (gmst < 0) gmst += 360;
        let lstDeg = (gmst + site.lon) % 360;
        if (lstDeg < 0) lstDeg += 360;

        let H = lstDeg - RA_DEG;
        let latRad = site.lat * Math.PI / 180;
        let decRad = DEC_DEG * Math.PI / 180;
        let hRad = H * Math.PI / 180;
        let sinAlt = Math.sin(latRad) * Math.sin(decRad) + Math.cos(latRad) * Math.cos(decRad) * Math.cos(hRad);
        let altDeg = Math.asin(Math.max(-1, Math.min(1, sinAlt))) * 180 / Math.PI;
        let zDeg = 90 - altDeg;

        let X = null;
        if (zDeg < 88.0) {{
          let zRad = zDeg * Math.PI / 180;
          let denom = Math.cos(zRad) + 0.50572 * Math.pow(96.07995 - zDeg, -1.6364);
          if (denom > 0) {{
            X = 1.0 / denom;
            if (X > 3.0) X = null;
          }}
        }}

        times.push(label);
        airmasses.push(X);
        if (X !== null) {{
          if (X < minX) {{
            minX = X;
            minXTime = label;
          }}
          if (X <= 2.0) {{
            obsHoursCount += 0.5;
          }}
        }}
      }}

      // Real-time altitude & azimuth heading right now from observer site
      let nowJd = (nowUtcMs / 86400000.0) + 2440587.5;
      let gmstNow = (280.46061837 + 360.98564736629 * (nowJd - 2451545.0)) % 360;
      if (gmstNow < 0) gmstNow += 360;
      let lstNow = (gmstNow + site.lon) % 360;
      if (lstNow < 0) lstNow += 360;
      let hNow = (lstNow - RA_DEG) * Math.PI / 180;
      let latR = site.lat * Math.PI / 180;
      let decR = DEC_DEG * Math.PI / 180;
      let sinAltN = Math.sin(latR) * Math.sin(decR) + Math.cos(latR) * Math.cos(decR) * Math.cos(hNow);
      let altN = Math.asin(Math.max(-1, Math.min(1, sinAltN))) * 180 / Math.PI;
      let cosAz = (Math.sin(decR) - Math.sin(latR) * sinAltN) / (Math.cos(latR) * Math.cos(altN * Math.PI / 180));
      let azN = Math.acos(Math.max(-1, Math.min(1, cosAz))) * 180 / Math.PI;
      if (Math.sin(hNow) > 0) azN = 360 - azN;
      const compassDirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
      let compass = compassDirs[Math.round(azN / 22.5) % 16];
      let nowSkyStatus = altN > 0 ? `<span style="color:#22c55e;font-weight:700;">+${{altN.toFixed(0)}}° (${{compass}})</span>` : `<span style="color:#64748b;font-weight:600;">Below horizon (${{altN.toFixed(0)}}°)</span>`;

      // Moon separation
      let midUtcMs = startUtcMs + 6 * 3600000;
      let midJd = (midUtcMs / 86400000.0) + 2440587.5;
      let T = (midJd - 2451545.0) / 36525.0;
      let L0 = 218.316 + 481267.881 * T;
      let D = 297.850 + 445267.111 * T;
      let M = 357.529 + 35999.050 * T;
      let Mm = 134.963 + 477198.868 * T;
      let F = 93.272 + 483202.018 * T;
      let rD = D * Math.PI / 180, rM = M * Math.PI / 180, rMm = Mm * Math.PI / 180, rF = F * Math.PI / 180;
      let lMoon = L0 + 6.289 * Math.sin(rMm) - 1.274 * Math.sin(2 * rD - rMm) + 0.658 * Math.sin(2 * rD);
      let bMoon = 5.128 * Math.sin(rF) + 0.281 * Math.sin(rMm + rF);
      let eps = (23.43929 - 0.01300 * T) * Math.PI / 180;
      let rL = lMoon * Math.PI / 180, rB = bMoon * Math.PI / 180;
      let raMoon = Math.atan2(Math.sin(rL) * Math.cos(eps) - Math.tan(rB) * Math.sin(eps), Math.cos(rL)) * 180 / Math.PI;
      let decMoon = Math.asin(Math.sin(rB) * Math.cos(eps) + Math.cos(rB) * Math.sin(eps) * Math.sin(rL)) * 180 / Math.PI;
      let cosSep = Math.sin(DEC_DEG * Math.PI / 180) * Math.sin(decMoon * Math.PI / 180) +
                   Math.cos(DEC_DEG * Math.PI / 180) * Math.cos(decMoon * Math.PI / 180) * Math.cos((RA_DEG - raMoon) * Math.PI / 180);
      let moonSep = Math.round(Math.acos(Math.max(-1, Math.min(1, cosSep))) * 180 / Math.PI);

      const minXStr = minX !== Infinity ? `${{minX.toFixed(2)}} (${{minXTime}})` : 'Unobservable';
      const hoursStr = `${{obsHoursCount.toFixed(1)}} hrs`;
      const moonBadge = moonSep > 60 ? `<span style="color:#22c55e">${{moonSep}}° (Dark)</span>` : `<span style="color:#f59e0b">${{moonSep}}° (Bright)</span>`;

      statsEl.innerHTML = `
        <div style="background:#070a12;padding:0.4rem;border-radius:4px;border:1px solid var(--border)">
          <div style="color:var(--text-muted);font-size:0.65rem">MIN AIRMASS (TRANSIT)</div>
          <div style="font-weight:700;color:#fff">${{minXStr}}</div>
        </div>
        <div style="background:#070a12;padding:0.4rem;border-radius:4px;border:1px solid var(--border)">
          <div style="color:var(--text-muted);font-size:0.65rem">WINDOW (X &lt; 2.0)</div>
          <div style="font-weight:700;color:var(--accent)">${{hoursStr}}</div>
        </div>
        <div style="background:#070a12;padding:0.4rem;border-radius:4px;border:1px solid var(--border)">
          <div style="color:var(--text-muted);font-size:0.65rem">CURRENT SKY HEADING</div>
          <div style="font-size:0.75rem">${{nowSkyStatus}}</div>
        </div>
        <div style="background:#070a12;padding:0.4rem;border-radius:4px;border:1px solid var(--border)">
          <div style="color:var(--text-muted);font-size:0.65rem">MOON SEPARATION</div>
          <div style="font-weight:700">${{moonBadge}}</div>
        </div>
      `;

      const traces = [{{
        name: 'Air Mass X(t)',
        x: times,
        y: airmasses,
        mode: 'lines',
        type: 'scatter',
        line: {{ color: '#38bdf8', width: 2 }},
        connectgaps: false
      }}];

      const layout = {{
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        margin: {{ t: 10, r: 15, b: 35, l: 35 }},
        font: {{ color: '#94a3b8', size: 10, family: 'sans-serif' }},
        xaxis: {{
          showgrid: false,
          tickmode: 'array',
          tickvals: [times[0], times[6], times[12], times[18], times[24]],
          ticktext: [times[0], times[6], times[12], times[18], times[24]]
        }},
        yaxis: {{
          autorange: 'reversed',
          range: [2.5, 1.0],
          gridcolor: '#1e293b',
          dtick: 0.5
        }},
        shapes: [
          {{ type: 'line', x0: 0, x1: 1, xref: 'paper', y0: 1.5, y1: 1.5, line: {{ color: '#22c55e', width: 1, dash: 'dot' }} }},
          {{ type: 'line', x0: 0, x1: 1, xref: 'paper', y0: 2.0, y1: 2.0, line: {{ color: '#f59e0b', width: 1, dash: 'dot' }} }}
        ],
        showlegend: false
      }};

      Plotly.newPlot('plot-airmass', traces, layout, {{ responsive: true, displayModeBar: false }});
    }}

    // Initial plots
    renderLightCurve();
    renderSpectra();
    calcObservability();
  </script>

  <!-- WebMCP In-Browser Agentic Tools -->
  <script>
  (function() {{
    function registerWebMCP() {{
      const ctx = (window.navigator && window.navigator.modelContext) || 
                  (window.document && window.document.modelContext) || null;
      if (!ctx || typeof ctx.registerTool !== 'function') return;

      try {{
        ctx.registerTool({{
          name: "search_supernovae",
          description: "Search 110,000+ supernovae by IAU designation, name, or survey alias",
          inputSchema: {{
            type: "object",
            properties: {{
              q: {{
                type: "string",
                description: "Supernova name, IAU designation (e.g. SN2023ixf, SN 1987A), or alias"
              }}
            }},
            required: ["q"]
          }},
          execute: async function(args) {{
            if (!args || !args.q) return {{ error: "Missing query parameter 'q'" }};
            return {{ status: "success", query: args.q, url: "/sne/" + encodeURIComponent(args.q) }};
          }}
        }});
      }} catch (e) {{}}
    }}
    if (document.readyState === 'loading') {{
      document.addEventListener('DOMContentLoaded', registerWebMCP);
    }} else {{
      registerWebMCP();
    }}
  }})();
  </script>
</body>
</html>"""
    return html


TIER_1_BLOCKBUSTERS = {
    "SN1987A", "SN 1987A", "1987A",
    "SN1006", "SN 1006", "1006",
    "SN1054", "SN 1054", "1054",
    "SN1572", "SN 1572", "1572",  # Tycho's Nova
    "SN1604", "SN 1604", "1604",  # Kepler's Supernova
    "SN1885A", "SN 1885A", "1885A", # S Andromedae in Andromeda Galaxy M31
    "SN1993J", "SN 1993J", "1993J", # M81 Type IIb
    "SN1994I", "SN 1994I", "1994I", # M51 Type Ic
    "SN1998bw", "SN 1998bw", "1998bw", # GRB 980425 broad-line Ic
    "SN2005cs", "SN 2005cs", "2005cs", # M51 Type II-P
    "SN2006gy", "SN 2006gy", "2006gy", # Superluminous Supernova
    "SN2011fe", "SN 2011fe", "2011fe", # Benchmark Type Ia in Pinwheel Galaxy M101
    "SN2011dh", "SN 2011dh", "2011dh", # M51 Type IIb
    "SN2014J", "SN 2014J", "2014J",   # Benchmark Type Ia in Cigar Galaxy M82
    "SN2023ixf", "SN 2023ixf", "2023ixf", # Bright Type II in M101
    "SN2024ggi", "SN 2024ggi", "2024ggi", # Bright Type II in NGC 3621
    "SN2024nrb", "SN 2024nrb", "2024nrb",
    "SN2026ess", "SN 2026ess", "2026ess",
}


def classify_event_tier(name: str, meta: dict) -> int:
    """Classify transient into 3-tier programmatic content architecture:
    Tier 1: Blockbusters (~500 events) - Famous historic SNe, high citations, naked-eye / bright transients.
    Tier 2: Observational Dossiers (~15,000 events) - Transients with solid photometry or spectra.
    Tier 3: Faint Data Archive (~95,000 events) - Faint single-epoch survey detections.
    """
    clean_name = re.sub(r"[^A-Za-z0-9]", "", name).upper()
    for b in TIER_1_BLOCKBUSTERS:
        if clean_name == re.sub(r"[^A-Za-z0-9]", "", b).upper():
            return 1

    # Check peak brightness
    max_app = get_val(meta, "maxappmag")
    if max_app != "—":
        try:
            if float(max_app) < 13.5:
                return 1
        except Exception:
            pass

    # Check citation depth
    sources = meta.get("sources", [])
    if isinstance(sources, list) and len(sources) >= 15:
        return 1

    # Tier 2 criteria: >= 5 photometry points OR >= 1 spectrum OR confirmed claimedtype
    photo = meta.get("photometry", [])
    photo_count = len(photo) if isinstance(photo, list) else 0

    specs = meta.get("spectra", [])
    spec_count = len(specs) if isinstance(specs, list) else 0

    claimed = get_val(meta, "claimedtype")
    has_type = claimed not in ("—", "?", "", "Unknown", "Candidate", "Other")

    if photo_count >= 5 or spec_count >= 1 or has_type:
        return 2

    # Tier 3: Faint single-epoch survey detection
    return 3


def render_story_mode(name: str, meta: dict, entered: str | None = None) -> str:
    """Render the consumer-friendly Story Mode / Observer Dossier page (/sne/{event}/story)."""
    ra_deg, dec_deg, ra_str, dec_str = extract_coords(meta)
    claimedtype = get_val(meta, "claimedtype")
    discoverdate = get_val(meta, "discoverdate")
    discoverer = get_val(meta, "discoverer")
    maxappmag = get_val(meta, "maxappmag")
    maxdate = get_val(meta, "maxdate")
    lumdist = get_val(meta, "lumdist")
    redshift = get_val(meta, "redshift")
    host = get_val(meta, "host")
    host_offset_str = extract_host_offset(meta, ra_deg, dec_deg, redshift, lumdist)

    clean_u = re.sub(r"[^A-Za-z0-9]", "", name).upper()

    # Fallback dictionaries for landmark benchmarks
    HISTORIC_PEAK_MAG = {
        "SN1006": "−7.5", "SN1054": "−6.0", "SN1572": "−4.0", "SN1604": "−2.5",
        "SN1885A": "+5.8", "SN1987A": "+2.9", "SN1993J": "+10.8", "SN1994I": "+12.9",
        "SN1998BW": "+13.8", "SN2006GY": "+15.0", "SN2011FE": "+9.9", "SN2014J": "+10.5",
        "SN2023IXF": "+10.8", "SN2024GGI": "+12.0"
    }
    HISTORIC_HOSTS = {
        "SN1006": "Lupus (Milky Way Plane)",
        "SN1054": "Taurus (Milky Way / Crab Nebula)",
        "SN1572": "Cassiopeia (Milky Way)",
        "SN1604": "Ophiuchus (Milky Way)",
        "SN1885A": "Messier 31 (Andromeda Galaxy)",
        "SN1987A": "Large Magellanic Cloud (LMC)",
        "SN1993J": "Messier 81 (Bode's Galaxy)",
        "SN1994I": "Messier 51 (Whirlpool Galaxy)",
        "SN1998BW": "ESO 184-G82",
        "SN2006GY": "NGC 1260",
        "SN2011FE": "Messier 101 (Pinwheel Galaxy)",
        "SN2014J": "Messier 82 (Cigar Galaxy)",
        "SN2023IXF": "Messier 101 (Pinwheel Galaxy)",
        "SN2024GGI": "NGC 3621",
    }
    HISTORIC_DIST_LY = {
        "SN1006": "~7,200 Light-Years",
        "SN1054": "~6,500 Light-Years",
        "SN1572": "~8,500 Light-Years",
        "SN1604": "~20,000 Light-Years",
        "SN1885A": "~2.5 Million Light-Years",
        "SN1987A": "~168,000 Light-Years",
        "SN1993J": "~11.8 Million Light-Years",
        "SN1994I": "~23 Million Light-Years",
        "SN1998BW": "~125 Million Light-Years",
        "SN2006GY": "~240 Million Light-Years",
        "SN2011FE": "~21 Million Light-Years",
        "SN2014J": "~11.4 Million Light-Years",
        "SN2023IXF": "~21 Million Light-Years",
        "SN2024GGI": "~22 Million Light-Years",
    }

    if maxappmag in ("—", "", "None"):
        photo = meta.get("photometry", [])
        min_m = 99.0
        if isinstance(photo, list):
            for p in photo:
                if isinstance(p, dict):
                    m_val = p.get("magnitude") or p.get("mag")
                    if m_val:
                        try:
                            f_m = float(str(m_val))
                            if 0.0 < f_m < min_m:
                                min_m = f_m
                        except Exception:
                            pass
        if min_m < 90.0:
            maxappmag = f"{min_m:.2f}"
        elif clean_u in HISTORIC_PEAK_MAG:
            maxappmag = HISTORIC_PEAK_MAG[clean_u]

    if (host in ("—", "", "None")) and clean_u in HISTORIC_HOSTS:
        host = HISTORIC_HOSTS[clean_u]

    dist_ly_str = "Millions of Light-Years"
    if clean_u in HISTORIC_DIST_LY:
        dist_ly_str = HISTORIC_DIST_LY[clean_u]
    elif lumdist != "—":
        try:
            mpc = float(re.sub(r"[^0-9.]", "", lumdist))
            ly_m = mpc * 3.26156
            if ly_m < 0.3:
                dist_ly_str = f"{int(ly_m * 1e6):,} Light-Years"
            elif ly_m < 1.0:
                dist_ly_str = f"{ly_m * 1000:.0f} Thousand Light-Years"
            elif ly_m >= 1000:
                dist_ly_str = f"{ly_m / 1000:.2f} Billion Light-Years"
            else:
                dist_ly_str = f"{ly_m:.1f} Million Light-Years"
        except Exception:
            pass
    elif redshift != "—":
        try:
            z = float(re.sub(r"[^0-9.]", "", redshift))
            if z > 0:
                mpc = (299792.458 * z) / 70.0
                ly_m = mpc * 3.26156
                if ly_m < 1.0:
                    dist_ly_str = f"~{ly_m * 1000:.0f} Thousand Light-Years"
                elif ly_m >= 1000:
                    dist_ly_str = f"~{ly_m / 1000:.2f} Billion Light-Years"
                else:
                    dist_ly_str = f"~{ly_m:.1f} Million Light-Years"
        except Exception:
            pass

    # Telescope requirement guidance based on peak magnitude
    tel_guidance = "Visible with research-grade telescope"
    tel_guidance_short = "Research Scope"
    if maxappmag != "—":
        try:
            mag_val = float(re.sub(r"[^\d.-]", "", maxappmag))
            if mag_val < 6.0:
                tel_guidance = "Visible to the naked eye under dark skies!"
                tel_guidance_short = "Naked-Eye"
            elif mag_val < 9.5:
                tel_guidance = "Visible with standard 7x50 or 10x50 binoculars"
                tel_guidance_short = "Binoculars (7x50)"
            elif mag_val < 12.0:
                tel_guidance = "Easily visible in a small 4-inch backyard telescope"
                tel_guidance_short = "Small Scope (4-inch)"
            elif mag_val < 14.5:
                tel_guidance = "Visible in an 8-inch to 12-inch amateur telescope"
                tel_guidance_short = "Medium Scope (8-inch)"
            elif mag_val < 17.5:
                tel_guidance = "Requires long-exposure astrophotography camera (CMOS/CCD)"
                tel_guidance_short = "Astro Camera (CCD)"
            else:
                tel_guidance = "Faint transient, accessible only via large research observatories"
                tel_guidance_short = "Large Observatory"
        except Exception:
            pass

    # Solar luminosity calculation
    maxabsmag = get_val(meta, "maxabsmag")
    solar_lum = "Hundreds of Millions of Suns"
    if calculate_solar_luminosities is not None and maxabsmag != "—":
        try:
            solar_lum = calculate_solar_luminosities(maxabsmag)
        except Exception:
            pass
    elif "ia" in claimedtype.lower():
        solar_lum = "~5.0 Billion Suns"
    elif "ii" in claimedtype.lower():
        solar_lum = "~1.0 to 5.0 Billion Suns"

    # Velocity calculation
    vel_km = 10000.0
    vel_pct = 3.3
    try:
        from faq_engine import analyze_velocity
        vel_res = analyze_velocity(meta, claimedtype)
        vel_km = vel_res.get("km_s", 10000.0)
        vel_pct = vel_res.get("pct_c", 3.3)
    except Exception:
        pass

    # Constellation
    const_name, const_eng = "Deep Space", "Celestial Sphere"
    if identify_constellation is not None and ra_deg is not None and dec_deg is not None:
        try:
            const_name, const_eng = identify_constellation(ra_deg, dec_deg)
        except Exception:
            pass

    is_ia = "ia" in claimedtype.lower()
    tier = classify_event_tier(name, meta)
    schema_type = "NewsArticle" if tier == 1 else "Article"
    blockbuster_badge = '<span class="story-tag" style="background:linear-gradient(90deg, #d97706, #dc2626);color:#fff;font-weight:700;margin-left:6px;">★ Historic Landmark</span>' if tier == 1 else ""
    blockbuster_section = ""
    if tier == 1:
        blockbuster_section = f"""
    <div class="dossier-card" style="border:1px solid rgba(245, 158, 11, 0.45);background:rgba(245, 158, 11, 0.07);margin-top:1.5rem;">
      <h3 style="color:#f59e0b;display:flex;align-items:center;gap:8px;margin-top:0;font-size:1.1rem;">
        <span>★</span> Benchmark Astrophysical Landmark
      </h3>
      <p style="margin-bottom:0;font-size:0.93rem;color:#f8fafc;line-height:1.6;">
        <strong>{name}</strong> is recognized as one of the definitive benchmark supernovae in modern astrophysics. Due to its exceptional peak luminosity, favorable host galaxy orientation, and rapid multi-messenger follow-up, it was extensively observed across the electromagnetic spectrum by premier facilities—including space telescopes (HST, JWST, Swift) and global ground-based spectroscopic networks. It provides foundational empirical constraints for stellar progenitor models, ejecta dynamics, and cosmological distance calibrations.
      </p>
    </div>"""

    lifecycle = get_transient_lifecycle(meta, tel_guidance=tel_guidance, host_name=host, event_name=name, redshift=redshift, claimedtype=claimedtype)

    # Type explanation
    type_expl = (
        "A catastrophic stellar explosion marking the violent end of a star's lifecycle."
    )
    if "Ia" in claimedtype:
        type_expl = (
            "A thermonuclear detonation of a carbon-oxygen white dwarf star. In a tight binary system, "
            "the dense white dwarf siphoned matter from its companion until reaching the Chandrasekhar limit (1.4 solar masses), "
            "igniting runaway nuclear fusion that completely obliterated the star."
        )
    elif "II" in claimedtype:
        type_expl = (
            "A core-collapse explosion of a massive supergiant star (at least 8 times heavier than our Sun). "
            "Having exhausted its nuclear fuel, the iron core collapsed under gravity in a fraction of a second, "
            "rebounding into a cosmic shockwave that blew the star apart."
        )
    elif "Ib" in claimedtype or "Ic" in claimedtype:
        type_expl = (
            "A stripped-envelope core-collapse supernova. A massive star blew off its outer hydrogen (and helium) layers "
            "via ferocious stellar winds or binary interaction before its core collapsed."
        )

    has_coords = ra_deg is not None and dec_deg is not None

    # Find closest events in time, sky separation, and cosmic distance
    closest_data = {"sky": [], "time": [], "cosmic": []}
    if find_closest_events is not None and has_coords:
        try:
            closest_data = find_closest_events(name, ra_deg, dec_deg, discoverdate, redshift, limit=3)
        except Exception:
            pass

    neighbors_panel_html = format_cosmic_neighbors_panel(name, closest_data, is_cockpit=False)

    faqs = []
    if generate_supernova_faqs is not None:
        try:
            faqs = generate_supernova_faqs(
                name=name,
                meta=meta,
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                ra_str=ra_str,
                dec_str=dec_str,
                claimedtype=claimedtype,
                discoverdate=discoverdate,
                discoverer=discoverer,
                maxappmag=maxappmag,
                maxdate=maxdate,
                maxabsmag=get_val(meta, "maxabsmag"),
                lumdist=lumdist,
                redshift=redshift,
                host=host,
                host_offset_str=host_offset_str,
                dist_ly_str=dist_ly_str,
                lifecycle=lifecycle,
            )
        except Exception:
            faqs = []

    if build_faq_html is not None and faqs:
        story_faq_html = build_faq_html(faqs, name)
    else:
        story_faq_html = ""

    if build_faq_jsonld is not None and faqs:
        story_faq_jsonld = build_faq_jsonld(faqs)
    else:
        story_faq_jsonld = ""

    # Synthesize or retrieve editorial feature article
    story_article_html = ""
    if get_blockbuster_article is not None:
        try:
            story_article_html = get_blockbuster_article(
                name=name,
                meta=meta,
                claimedtype=claimedtype,
                discoverdate=discoverdate,
                discoverer=discoverer,
                maxappmag=maxappmag,
                dist_ly_str=dist_ly_str,
                host=host,
                ra_str=ra_str,
                dec_str=dec_str,
                lifecycle_html=lifecycle.get("story_guidance_html", "") if lifecycle else "",
            )
        except Exception:
            story_article_html = ""

    if not story_article_html and generate_story_article_html is not None:
        try:
            story_article_html = generate_story_article_html(
                name=name,
                meta=meta,
                claimedtype=claimedtype,
                discoverdate=discoverdate,
                discoverer=discoverer,
                maxappmag=maxappmag,
                maxdate=maxdate,
                maxabsmag=maxabsmag,
                lumdist=lumdist,
                redshift=redshift,
                host=host,
                host_offset_str=host_offset_str,
                ra_str=ra_str,
                dec_str=dec_str,
                dist_ly_str=dist_ly_str,
                lifecycle=lifecycle,
                ra_deg=ra_deg,
                dec_deg=dec_deg,
            )
        except Exception:
            story_article_html = ""

    if not story_article_html:
        story_article_html = f"""
    <div class="narrative">
      <div class="article-chapter" id="chapter-1">
        <div class="article-chapter-num">CHAPTER I &bull; MECHANISM</div>
        <h2>What Kind of Explosion Was This?</h2>
        <p class="article-lead">{type_expl}</p>
      </div>

      <div class="article-chapter" id="chapter-2">
        <div class="article-chapter-num">CHAPTER II &bull; VIEWING GUIDE</div>
        <h2>Can I See It with a Backyard Telescope?</h2>
        {lifecycle['story_guidance_html']}
      </div>

      <div class="article-chapter" id="chapter-3">
        <div class="article-chapter-num">CHAPTER III &bull; CELESTIAL LOCATION</div>
        <h2>Celestial Location &amp; Host Coordinates</h2>
        <p>In the night sky, {name} is located at Right Ascension <code>{ra_str}</code> and Declination <code>{dec_str}</code>.</p>
      </div>
    </div>"""

    # Ensure sequential anchor IDs on all chapters for jump rail
    ch_idx = 1
    while '<div class="article-chapter">' in story_article_html:
        story_article_html = story_article_html.replace('<div class="article-chapter">', f'<div class="article-chapter" id="chapter-{ch_idx}">', 1)
        ch_idx += 1

    # Extract chapters for quick-jump navigation rail
    chapter_pills = []
    ch_matches = re.findall(
        r'<div class="article-chapter"[^>]*id="([^"]+)"[^>]*>.*?(?:<div class="article-chapter-num">([^<]+)</div>)?.*?<h2>([^<]+)</h2>',
        story_article_html,
        re.DOTALL
    )
    for ch_id, ch_num, ch_title in ch_matches:
        num_clean = ch_num.strip() if ch_num else ""
        if "CHAPTER" in num_clean.upper():
            pill_label = num_clean.split("&")[0].split("•")[0].strip()
        elif num_clean:
            pill_label = num_clean.split("&")[0].split("•")[0].strip()[:14]
        else:
            pill_label = "Ch"
        title_clean = ch_title.strip()
        short_title = title_clean if len(title_clean) <= 22 else title_clean[:20] + "…"
        chapter_pills.append(
            f'<a href="#{ch_id}" class="chapter-nav-link" title="{title_clean}"><span class="ch-badge">{pill_label}</span> {short_title}</a>'
        )

    chapter_nav_html = ""
    if chapter_pills:
        chapter_nav_html = f"""
    <nav class="chapter-nav-bar" id="chapter-nav" aria-label="Story Chapters Navigation">
      <div class="chapter-nav-inner">
        <span class="chapter-nav-label">📖 Jump:</span>
        <a href="#quick-facts" class="chapter-nav-link"><span class="ch-badge">Data</span> Quick Facts</a>
        {"".join(chapter_pills)}
        <a href="#neighbors-section" class="chapter-nav-link"><span class="ch-badge">Cosmos</span> Neighbors</a>
        <a href="#faq-section" class="chapter-nav-link" style="color:#38bdf8;border-color:rgba(56,189,248,0.4);"><span class="ch-badge" style="background:rgba(56,189,248,0.2);color:#38bdf8;">Q&amp;A</span> {len(faqs)} FAQs</a>
      </div>
    </nav>"""

    # Estimated word count and reading time
    text_corpus = re.sub(r"<[^>]+>", " ", story_article_html)
    word_count = len(text_corpus.split())
    read_mins = max(5, round(word_count / 180) + 3)

    # Structured Schema.org Article / NewsArticle
    if build_article_jsonld is not None:
        try:
            story_article_jsonld = build_article_jsonld(
                name=name,
                claimedtype=claimedtype,
                host=host,
                discoverdate=discoverdate,
                dist_ly_str=dist_ly_str,
                maxappmag=maxappmag,
                schema_type=schema_type,
                ra_deg=ra_deg,
                dec_deg=dec_deg,
            )
        except Exception:
            story_article_jsonld = ""
    else:
        story_article_jsonld = ""

    if not story_article_jsonld:
        story_article_jsonld = f"""  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "{schema_type}",
    "headline": "{name}: A Cosmic Supernova Explosion in the Universe",
    "description": "Explaining supernova {name} ({claimedtype}): distance in light-years, discovery story, and telescope viewing guide.",
    "url": "https://sne.space/sne/{urllib.parse.quote(name)}/story",
    "publisher": {{
      "@type": "Organization",
      "name": "Open Supernova Catalog",
      "url": "https://sne.space"
    }}
  }}
  </script>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name}: What Happened, Distance &amp; Viewing Guide — sne.space</title>
  <meta name="description" content="The story of supernova {name} ({claimedtype}): Discovered on {discoverdate}, located {dist_ly_str} away. How to see it and the science behind the explosion.">
  <meta property="og:title" content="The Story of Supernova {name} — sne.space">
  <meta property="og:description" content="An extraordinary stellar explosion that occurred {dist_ly_str} away. Viewing guide and facts.">
  <meta property="og:image" content="https://sne.space/sne/{urllib.parse.quote(name)}/host.jpg">
  <meta property="og:url" content="https://sne.space/sne/{urllib.parse.quote(name)}/story">
  <meta property="og:type" content="article">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="The Story of Supernova {name}">
  <meta name="twitter:description" content="Stellar explosion {dist_ly_str} away. Peak mag {maxappmag}. Backyard telescope viewing guide.">
  <meta name="twitter:image" content="https://sne.space/sne/{urllib.parse.quote(name)}/host.jpg">
  <link rel="stylesheet" href="/assets/ia.css">
  <link rel="ai-catalog" href="/.well-known/ai-catalog.json" type="application/ai-catalog+json">
  <link rel="ard" href="/.well-known/ard.json" type="application/json">
  <link rel="stylesheet" href="https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.css" />
  <script src="https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js"></script>
{story_article_jsonld}
{story_faq_jsonld}
  <style>
    :root {{
      --bg: #090d16;
      --card-bg: #121929;
      --border: #1e293b;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      line-height: 1.6;
    }}
    header.cockpit-hdr {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      padding: 0.75rem 1.5rem;
      background: #050811;
      border-bottom: 1px solid var(--border);
    }}
    .brand-group {{ display: flex; align-items: center; gap: 0.75rem; }}
    .brand-title {{ font-weight: 700; font-size: 1.25rem; color: #fff; text-decoration: none; }}
    .hdr-search-form {{
      display: flex;
      align-items: center;
      background: rgba(15, 23, 42, 0.75);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
      max-width: 320px;
      flex: 1;
      margin: 0 1rem;
      transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }}
    .hdr-search-form:focus-within {{
      border-color: #38bdf8;
      box-shadow: 0 0 12px rgba(56, 189, 248, 0.25);
    }}
    .hdr-search-form input {{
      background: transparent;
      border: none;
      outline: none;
      color: #f1f5f9;
      font-size: 0.85rem;
      padding: 0.35rem 0.65rem;
      width: 100%;
    }}
    .hdr-search-form button {{
      background: transparent;
      border: none;
      color: #94a3b8;
      padding: 0.35rem 0.6rem;
      cursor: pointer;
    }}
    .hdr-nav-links {{
      display: flex;
      align-items: center;
      gap: 0.85rem;
      margin-right: 1rem;
    }}
    .hdr-nav-links a {{
      color: var(--text-muted);
      text-decoration: none;
      font-size: 0.85rem;
      font-weight: 600;
      transition: color 0.15s ease;
    }}
    .hdr-nav-links a:hover {{
      color: #fff;
    }}
    .view-switcher {{
      display: flex; background: #1e293b; padding: 2px; border-radius: 6px; border: 1px solid var(--border);
    }}
    .view-btn {{
      padding: 0.35rem 0.75rem; font-size: 0.85rem; font-weight: 600; text-decoration: none; color: var(--text-muted); border-radius: 4px;
    }}
    .view-btn.active {{ background: var(--accent); color: #0b0f19; }}
    .story-hero {{
      max-width: 800px;
      margin: 2.5rem auto 1.5rem auto;
      padding: 0 1.5rem;
      text-align: center;
    }}
    .story-tag {{
      display: inline-block;
      background: rgba(56, 189, 248, 0.1);
      color: var(--accent);
      border: 1px solid rgba(56, 189, 248, 0.3);
      padding: 0.2rem 0.75rem;
      border-radius: 9999px;
      font-size: 0.85rem;
      font-weight: 600;
      margin-bottom: 0.75rem;
    }}
    .story-hero h1 {{
      font-size: 2.5rem;
      font-weight: 800;
      line-height: 1.2;
      margin: 0 0 1rem 0;
      letter-spacing: -0.02em;
    }}
    .story-hero p.lead {{
      font-size: 1.2rem;
      color: var(--text-muted);
      margin: 0;
    }}
    .story-container {{
      max-width: 800px;
      margin: 0 auto 4rem auto;
      padding: 0 1.5rem;
    }}
    .dossier-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1.5rem;
      margin: 2rem 0;
    }}
    .stat-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 1rem;
      margin-top: 1rem;
    }}
    .stat-item {{
      background: rgba(255,255,255,0.02);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.75rem;
    }}
    .stat-label {{ font-size: 0.8rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; }}
    .stat-val {{ font-size: 1.2rem; font-weight: 700; color: #fff; margin-top: 0.25rem; }}

    /* Aladin Lite custom branding & overrides to match sne.space */
    .aladin-location, .aladin-fov, .aladin-projection-control, .aladin-fullScreen-control,
    .aladin-widgets-toolbar, .aladin-status-bar, .aladin-cooFrame, .aladin-reticle,
    .aladin-logo-container {{
      display: none !important;
    }}
    .aladin-container {{
      background-color: #070a13 !important;
      border: none !important;
    }}
    .story-aladin-box {{
      position: relative;
      height: 420px;
      background: #070a13;
      border-radius: 10px;
      overflow: hidden;
      margin: 1.5rem 0;
      border: 1px solid rgba(56, 189, 248, 0.35);
      box-shadow: 0 16px 40px rgba(0,0,0,0.8), inset 0 0 30px rgba(0,0,0,0.9);
    }}
    .story-vignette {{
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 10;
      background: radial-gradient(circle at center, transparent 65%, rgba(7, 10, 19, 0.94) 100%);
      border-radius: 10px;
    }}
    .story-aladin-btn {{
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(148, 163, 184, 0.25);
      color: #cbd5e1;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.15s ease;
    }}
    .story-aladin-btn:hover {{
      background: rgba(30, 41, 59, 0.95);
      color: #fff;
      border-color: #38bdf8;
    }}
    .story-aladin-btn.active {{
      background: #0284c7;
      color: #fff;
      border-color: #38bdf8;
    }}
    /* Completely hide Aladin's default floating popup box in favor of top HUD bar */
    .aladin-popup-container,
    div.aladin-popup-container,
    .aladin-container .aladin-popup,
    div.aladin-popup {{
      display: none !important;
      visibility: hidden !important;
      pointer-events: none !important;
      opacity: 0 !important;
    }}
    @keyframes hud-slide-down {{
      from {{ opacity: 0; transform: translateY(-4px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    .aladin-container .aladin-popupTitle,
    div.aladin-popupTitle {{
      display: block !important;
      font-size: 0.85rem !important;
      font-weight: 700 !important;
      color: #ffffff !important;
      margin-bottom: 6px !important;
      padding-right: 18px !important;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
      padding-bottom: 4px !important;
    }}
    .aladin-container .aladin-popupTitle:empty,
    div.aladin-popupTitle:empty {{
      display: none !important;
    }}
    .aladin-container .aladin-popupText,
    div.aladin-popupText {{
      display: block !important;
      color: #cbd5e1 !important;
      font-size: 0.78rem !important;
      line-height: 1.4 !important;
    }}
    .aladin-container .aladin-closeBtn,
    a.aladin-closeBtn {{
      color: #94a3b8 !important;
      font-size: 18px !important;
      top: 6px !important;
      right: 8px !important;
      text-decoration: none !important;
      cursor: pointer !important;
      z-index: 10 !important;
      transition: color 0.15s ease !important;
    }}
    .aladin-container .aladin-closeBtn:hover,
    a.aladin-closeBtn:hover {{
      color: #38bdf8 !important;
    }}
    .aladin-container .aladin-popup-arrow,
    div.aladin-popup-arrow {{
      border-top-color: #0b1120 !important;
      border-bottom-color: #0b1120 !important;
      z-index: 999999 !important;
    }}
    .aladin-marker-measurement {{
      max-height: 220px !important;
      overflow-y: auto !important;
    }}
    .aladin-marker-measurement table {{
      display: table !important;
      width: 100% !important;
      border-collapse: collapse !important;
      font-size: 0.72rem !important;
      margin-top: 4px !important;
    }}
    .aladin-marker-measurement td {{
      padding: 3px 6px !important;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
      color: #94a3b8 !important;
      word-break: break-word !important;
    }}
    .aladin-marker-measurement td:first-child {{
      color: #cbd5e1 !important;
      font-weight: 600 !important;
      width: 38% !important;
    }}
    .neighbor-row {{
      display: block;
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 6px;
      padding: 0.75rem;
      margin-bottom: 0.6rem;
      text-decoration: none;
      transition: all 0.15s ease;
    }}
    .neighbor-row:hover {{
      background: rgba(56, 189, 248, 0.08);
      border-color: rgba(56, 189, 248, 0.3);
      transform: translateY(-1px);
    }}
    @keyframes pulse-halo {{
      0% {{ transform: scale(0.8); opacity: 0.9; box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.7); }}
      50% {{ transform: scale(1.3); opacity: 0.3; box-shadow: 0 0 0 8px rgba(56, 189, 248, 0); }}
      100% {{ transform: scale(0.8); opacity: 0.9; box-shadow: 0 0 0 0 rgba(56, 189, 248, 0); }}
    }}
    .narrative, .blockbuster-narrative {{
      font-size: 1.12rem;
      line-height: 1.85;
      color: #e2e8f0;
      letter-spacing: 0.005em;
    }}
    .narrative p, .blockbuster-narrative p {{
      margin: 1.4rem 0;
      color: #cbd5e1;
    }}
    .narrative p strong, .blockbuster-narrative p strong {{
      color: #f8fafc;
      font-weight: 600;
    }}
    .narrative h2, .blockbuster-narrative h2 {{
      font-size: 1.65rem;
      font-weight: 800;
      color: #ffffff;
      line-height: 1.3;
      margin: 2.25rem 0 1rem 0;
      letter-spacing: -0.02em;
    }}
    .article-lead {{
      font-size: 1.18rem !important;
      line-height: 1.8 !important;
      color: #f1f5f9 !important;
      font-weight: 400;
    }}
    .article-lead::first-letter {{
      float: left;
      font-size: 3.4rem;
      line-height: 0.8;
      padding-top: 4px;
      padding-right: 10px;
      padding-bottom: 2px;
      color: #38bdf8;
      font-weight: 800;
      font-family: Georgia, "Times New Roman", serif;
      text-shadow: 0 0 20px rgba(56, 189, 248, 0.4);
    }}
    .blockbuster-narrative .article-lead::first-letter {{
      color: #f59e0b;
      text-shadow: 0 0 20px rgba(245, 158, 11, 0.4);
    }}
    .article-chapter {{
      margin-bottom: 3rem;
      padding-bottom: 2.5rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.07);
      scroll-margin-top: 85px;
    }}
    .article-chapter:last-child {{
      border-bottom: none;
      margin-bottom: 1rem;
      padding-bottom: 0;
    }}
    .article-chapter-num {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.74rem;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: #38bdf8;
      background: rgba(56, 189, 248, 0.08);
      border: 1px solid rgba(56, 189, 248, 0.25);
      padding: 3px 9px;
      border-radius: 4px;
      margin-bottom: 0.75rem;
    }}
    .blockbuster-narrative .article-chapter-num {{
      color: #f59e0b;
      background: rgba(245, 158, 11, 0.08);
      border-color: rgba(245, 158, 11, 0.25);
    }}
    .article-callout {{
      background: linear-gradient(135deg, rgba(15, 23, 42, 0.85) 0%, rgba(30, 41, 59, 0.5) 100%);
      border: 1px solid rgba(56, 189, 248, 0.25);
      border-left: 4px solid #38bdf8;
      border-radius: 8px;
      padding: 1.25rem 1.4rem;
      margin: 1.75rem 0;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
    }}
    .blockbuster-narrative .article-callout {{
      border-left-color: #f59e0b;
      border-color: rgba(245, 158, 11, 0.28);
    }}

    /* Reading Progress Bar */
    #story-read-progress {{
      position: fixed;
      top: 0;
      left: 0;
      height: 3px;
      background: linear-gradient(90deg, #38bdf8 0%, #818cf8 50%, #c084fc 100%);
      z-index: 99999;
      width: 0%;
      box-shadow: 0 0 10px rgba(56, 189, 248, 0.7);
      transition: width 0.08s ease-out;
    }}

    /* Floating Back to Top */
    #btn-back-to-top {{
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 99;
      background: rgba(15, 23, 42, 0.92);
      backdrop-filter: blur(10px);
      border: 1px solid rgba(56, 189, 248, 0.4);
      color: #38bdf8;
      font-size: 0.82rem;
      font-weight: 700;
      padding: 8px 14px;
      border-radius: 9999px;
      cursor: pointer;
      box-shadow: 0 4px 18px rgba(0, 0, 0, 0.6);
      opacity: 0;
      pointer-events: none;
      transform: translateY(8px);
      transition: all 0.25s ease;
      display: flex;
      align-items: center;
      gap: 5px;
    }}
    #btn-back-to-top.visible {{
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0);
    }}
    #btn-back-to-top:hover {{
      background: #0284c7;
      color: #ffffff;
      border-color: #38bdf8;
      box-shadow: 0 6px 22px rgba(56, 189, 248, 0.45);
    }}

    /* Story Hero Meta Pills */
    .story-meta-pills {{
      display: flex;
      align-items: center;
      justify-content: center;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-top: 1rem;
    }}
    .story-meta-pill {{
      font-size: 0.78rem;
      color: #cbd5e1;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 9999px;
      padding: 3px 10px;
      font-weight: 500;
    }}

    /* Sticky Chapter Jump Bar */
    .chapter-nav-bar {{
      position: sticky;
      top: 10px;
      z-index: 50;
      background: rgba(8, 14, 26, 0.94);
      backdrop-filter: blur(14px);
      border: 1px solid rgba(56, 189, 248, 0.3);
      border-radius: 10px;
      padding: 0.5rem 0.75rem;
      margin: 2rem 0;
      box-shadow: 0 8px 30px rgba(0, 0, 0, 0.6);
    }}
    .chapter-nav-inner {{
      display: flex;
      align-items: center;
      gap: 0.45rem;
      overflow-x: auto;
      white-space: nowrap;
      scrollbar-width: thin;
      padding-bottom: 2px;
    }}
    .chapter-nav-inner::-webkit-scrollbar {{
      height: 4px;
    }}
    .chapter-nav-inner::-webkit-scrollbar-thumb {{
      background: rgba(56, 189, 248, 0.3);
      border-radius: 4px;
    }}
    .chapter-nav-label {{
      font-size: 0.74rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #38bdf8;
      margin-right: 0.35rem;
      display: flex;
      align-items: center;
      gap: 4px;
      flex-shrink: 0;
    }}
    .chapter-nav-link {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: 0.78rem;
      font-weight: 600;
      color: #cbd5e1;
      text-decoration: none;
      padding: 4px 10px;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.07);
      transition: all 0.15s ease;
      flex-shrink: 0;
    }}
    .chapter-nav-link:hover {{
      background: rgba(56, 189, 248, 0.12);
      border-color: rgba(56, 189, 248, 0.4);
      color: #fff;
    }}
    .chapter-nav-link.active {{
      background: #0284c7;
      border-color: #38bdf8;
      color: #fff;
      box-shadow: 0 0 10px rgba(56, 189, 248, 0.3);
    }}
    .ch-badge {{
      font-size: 0.66rem;
      text-transform: uppercase;
      font-weight: 700;
      letter-spacing: 0.05em;
      background: rgba(255, 255, 255, 0.07);
      padding: 1px 5px;
      border-radius: 3px;
      color: #94a3b8;
    }}
    .chapter-nav-link.active .ch-badge {{
      background: rgba(255, 255, 255, 0.2);
      color: #fff;
    }}

    /* 8-Stat Quick Observer Facts */
    .stat-grid-8 {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 0.75rem;
      margin-top: 1rem;
    }}
    @media (max-width: 820px) {{
      .stat-grid-8 {{
        grid-template-columns: repeat(2, 1fr);
      }}
    }}
    @media (max-width: 460px) {{
      .stat-grid-8 {{
        grid-template-columns: 1fr;
      }}
    }}
    .stat-card-mini {{
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid rgba(255, 255, 255, 0.07);
      border-radius: 8px;
      padding: 0.85rem 0.95rem;
      transition: all 0.2s ease;
      position: relative;
      overflow: hidden;
    }}
    .stat-card-mini:hover {{
      background: rgba(56, 189, 248, 0.04);
      border-color: rgba(56, 189, 248, 0.3);
      transform: translateY(-1px);
    }}
    .stat-mini-hdr {{
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 0.72rem;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .stat-mini-val {{
      font-size: 1.15rem;
      font-weight: 700;
      color: #f8fafc;
      margin-top: 0.35rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .stat-mini-sub {{
      font-size: 0.74rem;
      color: #94a3b8;
      margin-top: 0.2rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    /* FAQ Toolbar & Search */
    .faq-toolbar {{
      margin: 1.25rem 0 1.5rem 0;
      display: flex;
      flex-direction: column;
      gap: 0.85rem;
    }}
    .faq-search-row {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      flex-wrap: wrap;
    }}
    .faq-search-box {{
      flex: 1;
      min-width: 260px;
      display: flex;
      align-items: center;
      gap: 8px;
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.5rem 0.85rem;
      transition: border-color 0.2s, box-shadow 0.2s;
    }}
    .faq-search-box:focus-within {{
      border-color: #38bdf8;
      box-shadow: 0 0 12px rgba(56, 189, 248, 0.2);
    }}
    .faq-search-box input {{
      background: transparent;
      border: none;
      outline: none;
      color: #f1f5f9;
      font-size: 0.88rem;
      width: 100%;
    }}
    .faq-match-badge {{
      font-size: 0.75rem;
      color: var(--text-muted);
      white-space: nowrap;
      margin-left: auto;
    }}
    .faq-expand-btns {{
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }}
    .faq-action-btn {{
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--border);
      color: #94a3b8;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 5px 10px;
      border-radius: 5px;
      cursor: pointer;
      transition: all 0.15s ease;
      white-space: nowrap;
    }}
    .faq-action-btn:hover {{
      background: rgba(255, 255, 255, 0.08);
      color: #f1f5f9;
      border-color: #38bdf8;
    }}
    .faq-pills-scroll {{
      display: flex;
      gap: 6px;
      overflow-x: auto;
      white-space: nowrap;
      padding-bottom: 4px;
      scrollbar-width: thin;
    }}
    .faq-filter-pill {{
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.08);
      color: #94a3b8;
      font-size: 0.78rem;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 9999px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: all 0.15s ease;
      user-select: none;
    }}
    .faq-filter-pill:hover {{
      background: rgba(255, 255, 255, 0.07);
      color: #cbd5e1;
    }}
    .faq-filter-pill.active {{
      background: rgba(56, 189, 248, 0.18);
      border-color: rgba(56, 189, 248, 0.5);
      color: #38bdf8;
    }}
    .pill-cnt {{
      font-size: 0.68rem;
      background: rgba(255, 255, 255, 0.08);
      padding: 1px 5px;
      border-radius: 9999px;
      color: inherit;
    }}

    /* FAQ Items */
    .story-faq-accordion {{
      display: flex;
      flex-direction: column;
      gap: 0.65rem;
      margin-top: 0.5rem;
    }}
    .story-faq-item {{
      background: rgba(18, 25, 41, 0.65);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      transition: all 0.15s ease;
    }}
    .story-faq-item:hover {{
      border-color: rgba(56, 189, 248, 0.35);
      background: rgba(18, 25, 41, 0.85);
    }}
    .story-faq-item[open] {{
      border-color: rgba(56, 189, 248, 0.45);
      background: rgba(18, 25, 41, 0.95);
      box-shadow: 0 4px 18px rgba(0, 0, 0, 0.35);
    }}
    .story-faq-item summary {{
      padding: 0.95rem 1.15rem;
      font-weight: 600;
      font-size: 0.96rem;
      color: #f1f5f9;
      cursor: pointer;
      user-select: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      list-style: none;
    }}
    .story-faq-item summary::-webkit-details-marker {{
      display: none;
    }}
    .story-faq-item summary::after {{
      content: "+";
      color: #38bdf8;
      font-size: 1.25rem;
      font-weight: 700;
      flex-shrink: 0;
      transition: transform 0.2s ease;
    }}
    .story-faq-item[open] summary::after {{
      content: "−";
      transform: rotate(180deg);
    }}
    .story-faq-item[open] summary {{
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      color: #38bdf8;
      background: rgba(56, 189, 248, 0.06);
    }}
    .story-faq-q {{
      flex: 1;
      line-height: 1.45;
    }}
    .story-faq-badge {{
      font-size: 0.68rem;
      padding: 2px 8px;
      border-radius: 9999px;
      background: rgba(56, 189, 248, 0.12);
      color: #38bdf8;
      border: 1px solid rgba(56, 189, 248, 0.25);
      font-weight: 600;
      white-space: nowrap;
      flex-shrink: 0;
    }}
    .story-faq-body {{
      padding: 1.1rem 1.25rem 1.25rem 1.25rem;
      font-size: 0.94rem;
      line-height: 1.8;
      color: #cbd5e1;
    }}
    .story-faq-body code {{
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid rgba(255, 255, 255, 0.1);
      padding: 2px 5px;
      border-radius: 4px;
      color: #7dd3fc;
    }}

    .btn-return {{
      display: inline-block;
      margin-top: 2rem;
      padding: 0.6rem 1.25rem;
      background: var(--accent);
      color: #090d16;
      border-radius: 6px;
      font-weight: 700;
      text-decoration: none;
    }}
  </style>
</head>
<body>
  <div id="story-read-progress"></div>

  <header class="cockpit-hdr">
    <div class="brand-group">
      <a class="brand-title" href="/">sne.space</a>
    </div>
    <form class="hdr-search-form" action="/" method="GET" toolname="search_supernovae" tooldescription="Search 110,000+ supernovae by IAU designation, name, or survey alias">
      <input type="text" name="q" placeholder="Search 110,000+ transients..." autocomplete="off" toolparamdescription="Supernova name, IAU designation (e.g. SN2023ixf, SN 1987A), or alias" aria-label="Search supernovae">
      <button type="submit" aria-label="Submit Search">🔍</button>
    </form>
    <div class="hdr-nav-links">
      <a href="/radar">📡 Radar</a>
      <a href="/faq">❓ FAQs</a>
    </div>
    <div class="view-switcher">
      <a class="view-btn" href="/sne/{urllib.parse.quote(name)}/">🔭 Pro Cockpit</a>
      <a class="view-btn active" href="#">📖 Story View</a>
    </div>
  </header>

  <div class="story-hero">
    <div style="display:inline-flex;align-items:center;flex-wrap:wrap;justify-content:center;gap:6px;margin-bottom:0.6rem;">
      <span class="story-tag">Type {claimedtype} Supernova</span>
      {blockbuster_badge}
    </div>
    <h1>The Story of Supernova {name}</h1>
    <p class="lead">An extraordinary stellar explosion that occurred {dist_ly_str} away in deep space.</p>
    <div class="story-meta-pills">
      <span class="story-meta-pill">⏱️ ~{read_mins} min deep read</span>
      <span class="story-meta-pill">🔬 {len(faqs)} Astrophysical Q&amp;As</span>
      <span class="story-meta-pill">🔭 Viewing Guide Included</span>
      <span class="story-meta-pill">🪐 Constellation {const_name}</span>
    </div>
  </div>

  <main class="story-container">
    <!-- Sexy Zoomed-In Interactive Sky Viewport -->
    <div class="story-aladin-box">
      <div id="story-aladin-div" style="width:100%;height:100%;"></div>
      <div class="story-vignette"></div>

      <!-- Top HUD Header & Long Selection Telemetry Bar -->
      <div id="story-top-hud" style="position:absolute;top:10px;left:10px;right:10px;display:flex;align-items:center;z-index:30;pointer-events:auto;">
        <!-- Default State: Deep Field info -->
        <div id="story-hud-default" style="display:flex;align-items:center;background:rgba(7,10,19,0.85);backdrop-filter:blur(8px);border:1px solid rgba(56,189,248,0.3);color:#38bdf8;font-family:monospace;font-size:0.75rem;padding:5px 12px;border-radius:6px;box-shadow:0 2px 10px rgba(0,0,0,0.5);">
          <span>🔭 Deep Field (~2.1′ FOV) · Highest-Definition Optical Field (0.25″/pix)</span>
        </div>

        <!-- Selected State: Replaces default, highlighted cyan background with close '×' -->
        <div id="story-hud-selected" style="display:none;width:100%;align-items:center;justify-content:space-between;gap:10px;background:rgba(8,26,46,0.96);backdrop-filter:blur(12px);border:1px solid #38bdf8;border-radius:6px;padding:6px 14px;box-shadow:0 4px 22px rgba(56,189,248,0.35);color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;animation:hud-slide-down 0.2s ease-out;">
          <div id="story-hud-content" style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;min-width:0;flex:1;"></div>
          <button onclick="clearStorySelectedTelemetry(event)" title="Deselect / Close (Esc)" aria-label="Close telemetry" style="background:none;border:none;color:#94a3b8;font-size:1.25rem;font-weight:700;cursor:pointer;padding:0 4px;line-height:1;display:flex;align-items:center;justify-content:center;transition:color 0.15s ease;" onmouseover="this.style.color='#f43f5e'" onmouseout="this.style.color='#94a3b8'">×</button>
        </div>
      </div>

      <!-- Floating Target Marker & Pulsing Explosion Reticle -->
      <div id="story-target-pin" onclick="showStoryTargetTelemetry()" onkeydown="if(event.key==='Enter'||event.key===' ')showStoryTargetTelemetry()" role="button" aria-label="Supernova Explosion Target Telemetry Pin" tabindex="0" title="Click to view supernova telemetry" style="position:absolute;top:50%;left:50%;cursor:pointer;z-index:25;pointer-events:auto;user-select:none;">
        <!-- Badge floating safely above explosion site & host galaxy -->
        <div style="position:absolute;bottom:28px;left:50%;transform:translateX(-50%);background:rgba(15,23,42,0.95);border:1px solid #38bdf8;color:#fff;font-size:0.75rem;font-weight:700;padding:3px 8px;border-radius:4px;box-shadow:0 0 16px rgba(56,189,248,0.6);white-space:nowrap;display:flex;align-items:center;gap:5px;pointer-events:auto;">
          <span style="color:#38bdf8;animation:pulse-halo 2s infinite;">●</span> {name} Explosion Site
        </div>
        <!-- Vertical connector line linking badge to reticle center -->
        <div style="position:absolute;bottom:13px;left:0;width:1px;height:15px;background:rgba(56,189,248,0.7);box-shadow:0 0 4px #38bdf8;"></div>
        <!-- Crosshair centered exactly on explosion site -->
        <div style="width:26px;height:26px;position:relative;transform:translate(-50%,-50%);pointer-events:auto;">
          <div style="position:absolute;top:0;left:12px;width:2px;height:26px;background:#38bdf8;box-shadow:0 0 8px #38bdf8;"></div>
          <div style="position:absolute;top:12px;left:0;width:26px;height:2px;background:#38bdf8;box-shadow:0 0 8px #38bdf8;"></div>
          <div style="position:absolute;top:5px;left:5px;width:16px;height:16px;border:1px solid #38bdf8;border-radius:50%;box-shadow:0 0 8px #38bdf8;animation:pulse-halo 2s infinite;"></div>
        </div>
      </div>

      <!-- Bottom-Right Controls HUD -->
      <div style="position:absolute;bottom:10px;right:10px;display:flex;gap:5px;z-index:20;">
        <button class="story-aladin-btn active" id="btn-story-target" onclick="toggleStoryTargetMarker(this)" title="Toggle target pin & halo to view raw host galaxy">🎯 Target Pin</button>
        <button class="story-aladin-btn" id="btn-story-simbad" onclick="toggleStorySimbad(this)" title="Label nearby astronomical sources via CDS SIMBAD">🏷️ SIMBAD Labels</button>
        <button class="story-aladin-btn" onclick="recenterStoryAladin()" title="Recenter explosion site">⌖ Center</button>
        <button class="story-aladin-btn" onclick="zoomStoryAladin(1.5)" title="Zoom in">+</button>
        <button class="story-aladin-btn" onclick="zoomStoryAladin(0.67)" title="Zoom out">−</button>
      </div>
    </div>
    <p style="text-align:center;font-size:0.85rem;color:var(--text-muted);margin-top:-0.5rem;margin-bottom:1.5rem;">
      High-magnification deep optical view into {name}'s host environment. Pan and scroll to explore the cosmic neighborhood where this star exploded.
    </p>

    {chapter_nav_html}

    {blockbuster_section}

    <!-- Quick Observer Facts 8-Stat Grid -->
    <div class="dossier-card" id="quick-facts">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.5rem;">
        <h3 style="margin:0;display:flex;align-items:center;gap:8px;font-size:1.2rem;color:#f8fafc;">
          <span>⚡</span> Quick Observer Facts &amp; Telemetry
        </h3>
        <span style="font-size:0.75rem;color:var(--text-muted);font-family:monospace;">IAU Transients DB</span>
      </div>
      <div class="stat-grid-8">
        <div class="stat-card-mini">
          <div class="stat-mini-hdr"><span>🌐</span> Distance to Earth</div>
          <div class="stat-mini-val" title="{dist_ly_str}">{dist_ly_str}</div>
          <div class="stat-mini-sub">Lookback Cosmic Time</div>
        </div>
        <div class="stat-card-mini">
          <div class="stat-mini-hdr"><span>✨</span> Peak Brightness</div>
          <div class="stat-mini-val">Mag {maxappmag}</div>
          <div class="stat-mini-sub">{tel_guidance_short}</div>
        </div>
        <div class="stat-card-mini">
          <div class="stat-mini-hdr"><span>☀️</span> Peak Radiance</div>
          <div class="stat-mini-val" title="{solar_lum}">{solar_lum}</div>
          <div class="stat-mini-sub">Combined Stellar Energy</div>
        </div>
        <div class="stat-card-mini">
          <div class="stat-mini-hdr"><span>🚀</span> Shock Velocity</div>
          <div class="stat-mini-val">~{vel_km:,.0f} km/s</div>
          <div class="stat-mini-sub">~{vel_pct:.1f}% Speed of Light</div>
        </div>
        <div class="stat-card-mini">
          <div class="stat-mini-hdr"><span>🌌</span> Host Galaxy</div>
          <div class="stat-mini-val" title="{host}">{host if host != "—" else "Field Transient Host"}</div>
          <div class="stat-mini-sub">{f"Offset: {host_offset_str}" if host_offset_str != "—" else "Center Coincident"}</div>
        </div>
        <div class="stat-card-mini">
          <div class="stat-mini-hdr"><span>🧭</span> Constellation</div>
          <div class="stat-mini-val" title="{const_name}">{const_name}</div>
          <div class="stat-mini-sub">{const_eng}</div>
        </div>
        <div class="stat-card-mini">
          <div class="stat-mini-hdr"><span>💥</span> Explosion Physics</div>
          <div class="stat-mini-val" title="Type {claimedtype}">Type {claimedtype}</div>
          <div class="stat-mini-sub">{"Thermonuclear White Dwarf" if is_ia else "Core-Collapse Supergiant"}</div>
        </div>
        <div class="stat-card-mini">
          <div class="stat-mini-hdr"><span>📅</span> Discovered On</div>
          <div class="stat-mini-val">{discoverdate}</div>
          <div class="stat-mini-sub" title="{discoverer}">{discoverer if discoverer != "—" else "Robotic Alert Network"}</div>
        </div>
      </div>
    </div>

    <!-- Deep Editorial Feature Article / Story Narrative -->
    <div class="story-article-wrapper">
      {story_article_html}
    </div>

    <!-- Cosmic Neighbors & Contemporaries -->
    <div id="neighbors-section">
      {neighbors_panel_html}
    </div>

    <!-- Frequently Asked Questions -->
    {story_faq_html}

    <div style="text-align:center;margin-top:3rem;">
      <a class="btn-return" href="/sne/{urllib.parse.quote(name)}/">View Full Scientific Data &amp; Plots in Pro Cockpit →</a>
    </div>
  </main>

  <script>
    const STORY_RA = {ra_deg if ra_deg is not None else 'null'};
    const STORY_DEC = {dec_deg if dec_deg is not None else 'null'};
    window.storyAladinInstance = null;
    let storySimbadLayer = null;
    let storyTargetCatalogLayer = null;
    let storyTargetVisible = true;

    function clearStorySelectedTelemetry(evt) {{
      if (evt) {{ evt.stopPropagation(); }}
      let defHud = document.getElementById('story-hud-default');
      let selHud = document.getElementById('story-hud-selected');
      if (defHud) defHud.style.display = 'flex';
      if (selHud) selHud.style.display = 'none';
      if (window.storyAladinInstance && window.storyAladinInstance.popup) {{
        window.storyAladinInstance.popup.hide();
      }}
    }}

    function displayStoryTelemetryPopup(aladinObj, source, titleHtml, bodyHtml) {{
      if (aladinObj && aladinObj.popup) {{
        aladinObj.popup.hide();
      }}
      let defHud = document.getElementById('story-hud-default');
      let selHud = document.getElementById('story-hud-selected');
      let content = document.getElementById('story-hud-content');
      if (!selHud || !content || !source) return;

      let d = source.data || {{}};
      let rawName = getStorySimbadVal(d, 'MAIN_ID', 'main_id', 'MATCHING_ID', 'matching_id', 'TYPED_ID', 'typed_id', 'id', 'name');
      let otype = getStorySimbadVal(d, 'OTYPE_S', 'otype_s', 'OTYPE', 'otype', 'OTYPE_V', 'otype_v', 'src_class', 'TYPE', 'type') || 'Object';
      let coo = getStorySimbadVal(d, 'COO', 'coo') || (isFinite(source.ra) && isFinite(source.dec) ? source.ra.toFixed(4) + '°, ' + source.dec.toFixed(4) + '°' : '');
      let zVal = getStorySimbadVal(d, 'Z_VALUE', 'z_value', 'redshift', 'z');
      let rvVal = getStorySimbadVal(d, 'RV_VALUE', 'rv_value', 'cz', 'vlsr', 'VLSR');
      let majAxis = getStorySimbadVal(d, 'GALDIM_MAJAXIS', 'galdim_majaxis', 'smajaxis');
      let minAxis = getStorySimbadVal(d, 'GALDIM_MINAXIS', 'galdim_minaxis', 'sminaxis');
      let bibs = getStorySimbadVal(d, 'NB_BIBLIO', 'nb_biblio', 'biblist', 'BIBLIST');

      let sepArcsec = null;
      if (STORY_RA !== null && STORY_DEC !== null && isFinite(source.ra) && isFinite(source.dec)) {{
        let dRa = (source.ra - STORY_RA) * Math.cos(STORY_DEC * Math.PI / 180);
        let dDec = source.dec - STORY_DEC;
        let sepDeg = Math.sqrt(dRa * dRa + dDec * dDec);
        sepArcsec = (sepDeg * 3600).toFixed(1);
      }}
      let isHost = (sepArcsec !== null && parseFloat(sepArcsec) < 15.0 && (otype.includes('G') || otype.includes('Galaxy')));
      let typeLabel = isHost ? 'Supernova Host Galaxy' : otype;

      let simbadLink = rawName ? ('https://simbad.cds.unistra.fr/simbad/sim-id?Ident=' + encodeURIComponent(rawName)) : ('https://simbad.cds.unistra.fr/simbad/sim-coo?Coord=' + encodeURIComponent(source.ra + ' ' + source.dec) + '&Radius=1&Radius.unit=arcmin');

      content.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;font-weight:700;color:#fff;font-size:0.83rem;white-space:nowrap;">
          <span style="color:#38bdf8;">●</span> ` + (rawName || 'Catalog Source') + `
          <span style="font-size:0.65rem;padding:2px 6px;border-radius:3px;background:rgba(56,189,248,0.22);color:#38bdf8;border:1px solid rgba(56,189,248,0.4);">` + typeLabel + `</span>
        </div>
        <div style="display:flex;align-items:center;gap:12px;font-size:0.75rem;color:#cbd5e1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
          <span><strong style="color:#94a3b8;">Coords:</strong> <span style="font-family:monospace;color:#f1f5f9;">` + coo + `</span></span>
          ` + (sepArcsec ? `<span><strong style="color:#94a3b8;">Sep:</strong> ` + sepArcsec + `″ from SN</span>` : '') + `
          ` + (zVal ? `<span><strong style="color:#94a3b8;">Redshift:</strong> z = ` + (parseFloat(zVal) ? parseFloat(zVal).toFixed(4) : zVal) + `</span>` : (rvVal ? `<span><strong style="color:#94a3b8;">Radial Velocity:</strong> ` + parseFloat(rvVal).toFixed(0) + ` km/s</span>` : '')) + `
          ` + (majAxis && minAxis ? `<span><strong style="color:#94a3b8;">Size:</strong> ` + majAxis + `′ × ` + minAxis + `′</span>` : '') + `
          ` + (bibs && bibs !== '0' ? `<span><strong style="color:#94a3b8;">Bib:</strong> ` + bibs + ` papers</span>` : '') + `
        </div>
        <a href="` + simbadLink + `" target="_blank" rel="noopener" style="font-size:0.72rem;font-weight:600;color:#38bdf8;text-decoration:none;padding:2px 8px;border-radius:4px;border:1px solid rgba(56,189,248,0.4);background:rgba(56,189,248,0.1);white-space:nowrap;margin-left:auto;">SIMBAD ↗</a>
      `;
      if (defHud) defHud.style.display = 'none';
      selHud.style.display = 'flex';
    }}

    function showStoryTargetTelemetry() {{
      if (!window.storyAladinInstance || STORY_RA === null || STORY_DEC === null) return;
      if (window.storyAladinInstance.popup) window.storyAladinInstance.popup.hide();
      let defHud = document.getElementById('story-hud-default');
      let selHud = document.getElementById('story-hud-selected');
      let content = document.getElementById('story-hud-content');
      if (!selHud || !content) return;

      content.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;font-weight:700;color:#fff;font-size:0.83rem;white-space:nowrap;">
          <span style="color:#38bdf8;animation:pulse-halo 2s infinite;">●</span> {name} Explosion Site
          <span style="font-size:0.65rem;padding:2px 6px;border-radius:3px;background:rgba(56,189,248,0.25);color:#38bdf8;border:1px solid rgba(56,189,248,0.5);">{claimedtype}</span>
        </div>
        <div style="display:flex;align-items:center;gap:12px;font-size:0.75rem;color:#cbd5e1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
          <span><strong style="color:#94a3b8;">Coords:</strong> <span style="font-family:monospace;color:#f1f5f9;">{ra_str} {dec_str}</span></span>
          <span><strong style="color:#94a3b8;">Peak:</strong> Mag {maxappmag}</span>
          <span><strong style="color:#94a3b8;">Distance:</strong> {dist_ly_str}</span>
          <span><strong style="color:#94a3b8;">Host:</strong> {host if host != "—" else "Field Host (see SIMBAD)"}{f" ({host_offset_str})" if host_offset_str != "—" else ""}</span>
        </div>
        <span style="font-size:0.7rem;color:#38bdf8;background:rgba(56,189,248,0.1);padding:2px 7px;border-radius:4px;white-space:nowrap;margin-left:auto;">Target Selected</span>
      `;
      if (defHud) defHud.style.display = 'none';
      selHud.style.display = 'flex';
    }}

    function getStorySimbadVal(d, ...keys) {{
      if (!d) return '';
      for (let k of keys) {{
        if (d[k] !== undefined && d[k] !== null && String(d[k]).trim() !== '') {{
          return String(d[k]).trim();
        }}
      }}
      let lowerMap = {{}};
      for (let k of Object.keys(d)) {{
        lowerMap[k.toLowerCase()] = d[k];
      }}
      for (let k of keys) {{
        let lk = k.toLowerCase();
        if (lowerMap[lk] !== undefined && lowerMap[lk] !== null && String(lowerMap[lk]).trim() !== '') {{
          return String(lowerMap[lk]).trim();
        }}
      }}
      return '';
    }}

    function formatStorySimbadData(source, targetRa, targetDec) {{
      let d = source.data || {{}};
      let rawName = getStorySimbadVal(d, 'MAIN_ID', 'main_id', 'MATCHING_ID', 'matching_id', 'TYPED_ID', 'typed_id', 'id', 'name');
      let otype = getStorySimbadVal(d, 'OTYPE_S', 'otype_s', 'OTYPE', 'otype', 'OTYPE_V', 'otype_v', 'src_class', 'TYPE', 'type') || 'Object';
      let ra = source.ra;
      let dec = source.dec;
      let coo = getStorySimbadVal(d, 'COO', 'coo') || (isFinite(ra) && isFinite(dec) ? ra.toFixed(5) + '°, ' + dec.toFixed(5) + '°' : '');
      let bibs = getStorySimbadVal(d, 'NB_BIBLIO', 'nb_biblio', 'biblist', 'BIBLIST') || '0';
      let morph = getStorySimbadVal(d, 'MORPH_TYPE', 'morph_type', 'morph');
      let spType = getStorySimbadVal(d, 'SP_TYPE', 'sp_type', 'sptype');
      let plxRaw = getStorySimbadVal(d, 'PLX_VALUE', 'plx_value', 'plx');
      let plx = plxRaw ? parseFloat(plxRaw) : null;
      let majAxis = getStorySimbadVal(d, 'GALDIM_MAJAXIS', 'galdim_majaxis', 'smajaxis');
      let minAxis = getStorySimbadVal(d, 'GALDIM_MINAXIS', 'galdim_minaxis', 'sminaxis');
      let zVal = getStorySimbadVal(d, 'Z_VALUE', 'z_value', 'redshift', 'z');
      let rvVal = getStorySimbadVal(d, 'RV_VALUE', 'rv_value', 'cz', 'vlsr', 'VLSR');

      // Angular distance from supernova site in arcseconds
      let sepArcsec = null;
      if (targetRa !== null && targetDec !== null && isFinite(ra) && isFinite(dec)) {{
        let dRa = (ra - targetRa) * Math.cos(targetDec * Math.PI / 180);
        let dDec = dec - targetDec;
        let sepDeg = Math.sqrt(dRa * dRa + dDec * dDec);
        sepArcsec = (sepDeg * 3600).toFixed(1);
      }}

      let isHost = (sepArcsec !== null && parseFloat(sepArcsec) < 15.0 && (otype.includes('G') || otype.includes('Galaxy')));

      // Ultra-clean concise sky label
      let skyLabel = '';
      if (isHost) {{
        skyLabel = 'Host Galaxy';
      }} else if (otype === 'Star' || otype.includes('*') || rawName.startsWith('Gaia') || rawName.startsWith('UCAC') || rawName.startsWith('2MASS') || rawName.startsWith('TYC')) {{
        skyLabel = 'Star';
      }} else if (otype.includes('Galaxy') || otype.includes('G') || rawName.startsWith('LEDA') || rawName.startsWith('2MASX') || rawName.startsWith('WISEA')) {{
        skyLabel = 'Galaxy';
      }} else if (otype.includes('QSO') || otype.includes('AGN')) {{
        skyLabel = otype;
      }} else {{
        skyLabel = otype || 'Object';
      }}
      d.sky_label = skyLabel;

      let typeLabel = otype;
      if (isHost) typeLabel = 'Supernova Host Galaxy';
      else if (otype === 'EmissionG' || otype === 'EmG') typeLabel = 'Emission-line Galaxy';
      else if (otype === 'Galaxy' || otype === 'G') typeLabel = 'Field Galaxy';
      else if (otype === 'Star' || otype === '*') typeLabel = 'Field Star';
      else if (otype === 'HighPM*' || otype === 'PM*') typeLabel = 'High Proper-Motion Star';

      let detailsHtml = '';
      if (sepArcsec !== null) {{
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Separation:</strong> ' + sepArcsec + '″ from SN site</div>';
      }}
      if (zVal) {{
        let zF = parseFloat(zVal);
        let zDisp = isFinite(zF) ? zF.toFixed(4) : zVal;
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Redshift (z):</strong> ' + zDisp + (rvVal ? ' (v ≈ ' + parseFloat(rvVal).toFixed(0) + ' km/s)' : '') + '</div>';
      }} else if (rvVal) {{
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Radial Velocity:</strong> ' + parseFloat(rvVal).toFixed(0) + ' km/s</div>';
      }}
      if (morph) {{
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Morphology:</strong> ' + morph + '</div>';
      }}
      if (spType) {{
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Spectral Type:</strong> ' + spType + '</div>';
      }}
      if (plx && plx > 0) {{
        let distPc = (1000 / plx).toFixed(0);
        let distLy = (distPc * 3.26156).toFixed(0);
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Gaia Distance:</strong> ~' + distLy + ' light-years (ϖ = ' + plx.toFixed(2) + ' mas)</div>';
      }}
      if (majAxis && minAxis) {{
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Angular Size:</strong> ' + majAxis + '′ × ' + minAxis + '′</div>';
      }}
      if (bibs && bibs !== '0') {{
        detailsHtml += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;"><strong style="color:#cbd5e1;">Bibliography:</strong> ' + bibs + ' NASA ADS papers</div>';
      }}

      let titleHtml = '<div style="display:flex;align-items:center;justify-content:space-between;width:100%;gap:6px;"><span style="font-weight:700;color:#fff;font-size:0.86rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:180px;">' + (rawName || skyLabel) + '</span><span style="font-size:0.65rem;font-weight:700;padding:2px 6px;border-radius:3px;background:rgba(56,189,248,0.25);color:#38bdf8;">' + (otype || 'Object') + '</span></div>';

      let simbadLink = rawName ? ('https://simbad.cds.unistra.fr/simbad/sim-id?Ident=' + encodeURIComponent(rawName)) : ('https://simbad.cds.unistra.fr/simbad/sim-coo?Coord=' + encodeURIComponent(source.ra + ' ' + source.dec) + '&Radius=1&Radius.unit=arcmin');

      let popupHtml = `
        <div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;line-height:1.45;">
          <div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;">
            <strong style="color:#cbd5e1;">Class:</strong> ` + typeLabel + `
          </div>
          <div style="font-size:0.73rem;color:#94a3b8;margin-bottom:3px;">
            <strong style="color:#cbd5e1;">Coordinates:</strong> <span style="font-family:monospace;color:#f1f5f9;">` + coo + `</span>
          </div>
          ` + detailsHtml + `
          <div style="margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.1);display:flex;justify-content:space-between;align-items:center;">
            <span style="font-size:0.65rem;color:#64748b;">CDS SIMBAD Astronomical DB</span>
            <a href="` + simbadLink + `" target="_blank" rel="noopener" style="font-size:0.73rem;font-weight:600;color:#38bdf8;text-decoration:none;">View SIMBAD ↗</a>
          </div>
        </div>
      `;
      return {{ skyLabel, titleHtml, popupHtml }};
    }}

    function drawStoryNaturalDot(source, ctx) {{
      const x = source.x;
      const y = source.y;
      if (!isFinite(x) || !isFinite(y)) return;
      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y, 4.5, 0, 2 * Math.PI);
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.45)';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(x, y, 1.8, 0, 2 * Math.PI);
      ctx.fillStyle = '#38bdf8';
      ctx.fill();
      ctx.restore();
    }}

    function toggleStoryTargetMarker(btn) {{
      storyTargetVisible = !storyTargetVisible;
      const pin = document.getElementById('story-target-pin');
      if (pin) pin.style.display = storyTargetVisible ? 'flex' : 'none';
      if (storyTargetCatalogLayer) {{
        if (storyTargetVisible) storyTargetCatalogLayer.show();
        else storyTargetCatalogLayer.hide();
      }}
      if (btn) {{
        if (storyTargetVisible) {{
          btn.classList.add('active');
          btn.title = "Hide target pin & halo to view raw host galaxy";
        }} else {{
          btn.classList.remove('active');
          btn.title = "Show target pin & halo";
        }}
      }}
      if (window.storyAladinInstance && window.storyAladinInstance.view && window.storyAladinInstance.view.requestRedraw) {{
        window.storyAladinInstance.view.requestRedraw();
      }}
    }}

    function toggleStorySimbad(btn) {{
      if (!window.storyAladinInstance || typeof A === 'undefined' || STORY_RA === null || STORY_DEC === null) return;
      if (storySimbadLayer) {{
        if (storySimbadLayer.isShowing) {{
          storySimbadLayer.hide();
          if (window.storyAladinInstance.popup) window.storyAladinInstance.popup.hide();
          if (btn) {{
            btn.classList.remove('active');
            btn.innerText = '🏷️ SIMBAD Labels';
          }}
        }} else {{
          storySimbadLayer.show();
          if (btn) {{
            btn.classList.add('active');
            btn.innerText = '🏷️ SIMBAD Labels';
          }}
        }}
        if (window.storyAladinInstance.view && window.storyAladinInstance.view.requestRedraw) {{
          window.storyAladinInstance.view.requestRedraw();
        }}
      }} else {{
        try {{
          if (btn) {{
            btn.classList.add('active');
            btn.innerText = '⏳ Loading...';
          }}
          const showStorySourcePopup = function(source) {{
            if (!source) return;
            let res = formatStorySimbadData(source, STORY_RA, STORY_DEC);
            displayStoryTelemetryPopup(window.storyAladinInstance, source, res.titleHtml, res.popupHtml);
          }};

          storySimbadLayer = A.catalogFromSimbad(
            {{ra: STORY_RA, dec: STORY_DEC}},
            0.18,
            {{
              name: 'SIMBAD',
              color: '#38bdf8',
              sourceSize: 10,
              onClick: showStorySourcePopup,
              displayLabel: true
            }},
            function(cat) {{
              if (btn) {{
                btn.innerText = '🏷️ SIMBAD Labels';
                btn.classList.add('active');
              }}
              cat.onClick = showStorySourcePopup;
              cat.sources.forEach(s => {{
                let res = formatStorySimbadData(s, STORY_RA, STORY_DEC);
                s.data.sky_label = res.skyLabel;
                s.popupTitle = res.titleHtml;
                s.popupDesc = res.popupHtml;
                s.actionClicked = function() {{ showStorySourcePopup(s); }};
              }});
              cat.labelColumn = 'sky_label';
              cat.labelFont = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
              cat.labelColor = '#7dd3fc';
              cat.shape = drawStoryNaturalDot;
              cat.updateShape();
              cat.displayLabel = true;
              if (window.storyAladinInstance.view && window.storyAladinInstance.view.requestRedraw) {{
                window.storyAladinInstance.view.requestRedraw();
              }}
            }}
          );
          window.storyAladinInstance.addCatalog(storySimbadLayer);
          window.storyAladinInstance.on('objectClicked', function(obj) {{
            if (!obj) return;
            showStorySourcePopup(obj);
          }});
        }} catch (e) {{
          console.warn('SIMBAD overlay error:', e);
          if (btn) {{
            btn.classList.remove('active');
            btn.innerText = '🏷️ SIMBAD Labels';
          }}
        }}
      }}
    }}

    function recenterStoryAladin() {{
      if (window.storyAladinInstance && STORY_RA !== null && STORY_DEC !== null) {{
        window.storyAladinInstance.gotoRaDec(STORY_RA, STORY_DEC);
      }}
    }}

    function zoomStoryAladin(factor) {{
      if (window.storyAladinInstance) {{
        if (factor > 1) window.storyAladinInstance.increaseZoom();
        else window.storyAladinInstance.decreaseZoom();
      }}
    }}

    function updateStoryPin() {{
      if (!window.storyAladinInstance || STORY_RA === null || STORY_DEC === null) return;
      try {{
        let pix = window.storyAladinInstance.world2pix(STORY_RA, STORY_DEC);
        let pin = document.getElementById('story-target-pin');
        if (pin && pix && isFinite(pix[0]) && isFinite(pix[1])) {{
          pin.style.left = pix[0] + 'px';
          pin.style.top = pix[1] + 'px';
        }}
      }} catch (e) {{}}
    }}

    if (STORY_RA !== null && STORY_DEC !== null && typeof A !== 'undefined') {{
      const initStoryAladin = () => {{
        try {{
          // Highest-definition optical survey (Pan-STARRS DR1 color north of Dec -30°, DSS2 color fallback)
          const bestHdSurvey = STORY_DEC >= -30.0 ? "P/PanSTARRS/DR1/color-z-zg-g" : "P/DSS2/color";
          let aladin = A.aladin('#story-aladin-div', {{
            survey: bestHdSurvey,
            fov: 0.035, // High zoom ~2.1 arcmin into host galaxy
            target: STORY_RA + " " + STORY_DEC,
            showReticle: false,
            showZoomControl: false,
            showLayersControl: false,
            showFullscreenControl: false,
            showSimbadPointerControl: false,
            showCooGridControl: false,
            showSettingsControl: false,
            showColorPickerControl: false,
            showShareControl: false,
            showFrame: false,
            showFov: false,
            showCooLocation: false,
            showProjectionControl: false,
            showContextMenu: false,
            showStatusBar: false,
            backgroundColor: '#070a13'
          }});
          window.storyAladinInstance = aladin;
          aladin.gotoRaDec(STORY_RA, STORY_DEC);
          aladin.setFov(0.035);
          let cat = A.catalog({{name: 'Target', sourceSize: 0, color: 'transparent'}});
          storyTargetCatalogLayer = cat;
          aladin.addCatalog(cat);
          setInterval(updateStoryPin, 100);

          let sDiv = document.getElementById('story-aladin-div');
          if (sDiv) {{
            sDiv.addEventListener('click', function(evt) {{
              if (!storySimbadLayer || !storySimbadLayer.sources || storySimbadLayer.sources.length === 0) return;
              let rect = sDiv.getBoundingClientRect();
              let clickX = evt.clientX - rect.left;
              let clickY = evt.clientY - rect.top;
              let bestSource = null;
              let minDist = 30;
              for (let s of storySimbadLayer.sources) {{
                let x = s.x, y = s.y;
                if (!isFinite(x) || !isFinite(y)) {{
                  let pix = aladin.world2pix(s.ra, s.dec);
                  if (pix && isFinite(pix[0])) {{ x = pix[0]; y = pix[1]; }}
                }}
                if (!isFinite(x) || !isFinite(y)) continue;
                let dx = x - clickX;
                let dy = y - clickY;
                let dist = Math.sqrt(dx * dx + dy * dy);
                let lDx = clickX - x;
                let lDy = Math.abs(clickY - y);
                if (lDx >= -12 && lDx <= 85 && lDy <= 16) {{
                  dist = Math.min(dist, 8);
                }}
                if (dist < minDist) {{
                  minDist = dist;
                  bestSource = s;
                }}
              }}
              if (bestSource) {{
                let res = formatStorySimbadData(bestSource, STORY_RA, STORY_DEC);
                displayStoryTelemetryPopup(aladin, bestSource, res.titleHtml, res.popupHtml);
              }}
            }});
          }}
        }} catch (e) {{
          console.warn('Story Aladin init error:', e);
        }}
      }};
      if (A.init && typeof A.init.then === 'function') {{
        A.init.then(initStoryAladin);
      }} else {{
        initStoryAladin();
      }}
    }}

    document.addEventListener('keydown', function(e) {{
      if (e.key === 'Escape') {{
        clearStorySelectedTelemetry();
      }}
    }});

    // Reading Progress & Back To Top
    window.addEventListener('scroll', function() {{
      const docHeight = document.documentElement.scrollHeight - window.innerHeight;
      const progress = docHeight > 0 ? (window.scrollY / docHeight) * 100 : 0;
      const bar = document.getElementById('story-read-progress');
      if (bar) bar.style.width = Math.min(100, Math.max(0, progress)) + '%';

      const btt = document.getElementById('btn-back-to-top');
      if (btt) {{
        if (window.scrollY > 450) btt.classList.add('visible');
        else btt.classList.remove('visible');
      }}

      // Highlight active chapter in nav rail
      const navLinks = document.querySelectorAll('.chapter-nav-link');
      if (navLinks.length > 0) {{
        const scrollPos = window.scrollY + 130;
        let currentLink = null;
        navLinks.forEach(link => {{
          const href = link.getAttribute('href');
          if (href && href.startsWith('#')) {{
            const target = document.getElementById(href.substring(1));
            if (target && target.offsetTop <= scrollPos) {{
              currentLink = link;
            }}
          }}
        }});
        if (currentLink) {{
          navLinks.forEach(l => l.classList.remove('active'));
          currentLink.classList.add('active');
        }}
      }}
    }}, {{ passive: true }});

    // FAQ Interactive Filtering & Search
    let currentFaqCat = 'all';
    let currentFaqQuery = '';

    window.filterFaqCat = function(btn, cat) {{
      currentFaqCat = cat;
      document.querySelectorAll('.faq-filter-pill').forEach(b => b.classList.remove('active'));
      if (btn) btn.classList.add('active');
      applyFaqFilters();
    }};

    window.filterFaqQuery = function(query) {{
      currentFaqQuery = (query || '').toLowerCase().trim();
      applyFaqFilters();
    }};

    window.clearFaqSearch = function() {{
      currentFaqCat = 'all';
      currentFaqQuery = '';
      const input = document.getElementById('faq-search-input');
      if (input) input.value = '';
      document.querySelectorAll('.faq-filter-pill').forEach(b => {{
        if (b.textContent.trim().startsWith('All')) b.classList.add('active');
        else b.classList.remove('active');
      }});
      applyFaqFilters();
    }};

    window.applyFaqFilters = function() {{
      const items = document.querySelectorAll('.story-faq-item');
      let visibleCount = 0;
      items.forEach(el => {{
        const itemCat = el.getAttribute('data-cat') || '';
        const itemSearch = el.getAttribute('data-search') || '';
        const matchesCat = (currentFaqCat === 'all' || itemCat === currentFaqCat);
        const matchesQuery = (!currentFaqQuery || itemSearch.includes(currentFaqQuery));
        if (matchesCat && matchesQuery) {{
          el.style.display = '';
          visibleCount++;
        }} else {{
          el.style.display = 'none';
        }}
      }});
      const countBadge = document.getElementById('faq-match-count');
      if (countBadge) {{
        countBadge.textContent = visibleCount + ' of ' + items.length;
      }}
      const emptyMsg = document.getElementById('faq-empty-state');
      if (emptyMsg) {{
        emptyMsg.style.display = (visibleCount === 0) ? 'block' : 'none';
      }}
    }};

    window.toggleFaqs = function(openState) {{
      const items = document.querySelectorAll('.story-faq-item');
      items.forEach(el => {{
        if (el.style.display !== 'none') {{
          el.open = openState;
        }}
      }});
    }};
  </script>
  <button id="btn-back-to-top" onclick="window.scrollTo({{top: 0, behavior: 'smooth'}})" aria-label="Back to top" title="Scroll to top">
    ↑ Top
  </button>
</body>
</html>"""
    return html
