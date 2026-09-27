"""Open Supernova Catalog Model Context Protocol (MCP) Server.

Provides tools for AI assistants (Claude, Cursor, LLM agents) to query
110,000+ supernovae, light curves, spectra, cosmology, and sky observability.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

# Ensure serve is in sys.path
SERVE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVE_DIR.parent
if str(SERVE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVE_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cone_search import cone_search as do_cone_search
from event_render import extract_coords, get_val
from server import _find_event_file, _names_maps, _resolve_event

# Initialize FastMCP app
mcp = FastMCP(
    "sne-space-mcp",
    instructions="Open Supernova Catalog (sne.space) - Query 110,000+ supernovae, photometry, and spectra",
)


@mcp.tool()
def search_supernovae(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search for supernovae by name, IAU designation, or alias (e.g., '2023ixf', 'SN 1987A', 'ZTF20acvjqoo').

    Args:
        query: Name, partial name, or survey alias to search for.
        limit: Maximum number of search results to return (default 10).
    """
    canon_map, alias_map = _names_maps()
    q_clean = re.sub(r"[^a-zA-Z0-9]", "", query).lower()
    matches = []

    # Exact canonical check
    for c_name, c_lower in canon_map.items():
        if q_clean == c_lower:
            matches.append({"name": c_name, "match_type": "canonical_exact"})
            break

    # Alias check
    for a_clean, c_name in alias_map.items():
        if q_clean == a_clean and not any(m["name"] == c_name for m in matches):
            matches.append({"name": c_name, "matched_alias": a_clean, "match_type": "alias_exact"})

    # Partial substring match if under limit
    if len(matches) < limit:
        for c_name, c_lower in canon_map.items():
            if q_clean in c_lower and not any(m["name"] == c_name for m in matches):
                matches.append({"name": c_name, "match_type": "substring"})
                if len(matches) >= limit:
                    break

    # Gather quick metadata for results
    results = []
    for m in matches[:limit]:
        c_name = m["name"]
        _, fp = _find_event_file(c_name)
        meta_summary = {"name": c_name, "match_type": m.get("match_type")}
        if fp and fp.is_file():
            try:
                raw = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
                ev_data = next(iter(raw.values())) if len(raw) == 1 else raw.get(c_name, {})
                meta_summary["claimedtype"] = get_val(ev_data, "claimedtype")
                meta_summary["discoverdate"] = get_val(ev_data, "discoverdate")
                meta_summary["maxappmag"] = get_val(ev_data, "maxappmag")
                meta_summary["redshift"] = get_val(ev_data, "redshift")
                meta_summary["host"] = get_val(ev_data, "host")
            except Exception:
                pass
        results.append(meta_summary)

    return results


@mcp.tool()
def get_supernova(name: str) -> Dict[str, Any]:
    """Retrieve full astrophysical metadata for a specific supernova.

    Args:
        name: Name of the supernova (e.g., 'SN2023ixf', 'SN 1987A', 'AT2024nrb').
    """
    resolved, _ = _resolve_event(name)
    canon_name = resolved or name
    _, fp = _find_event_file(canon_name)

    if not fp or not fp.is_file():
        return {"error": f"Supernova '{name}' not found in catalog."}

    raw = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
    ev_data = next(iter(raw.values())) if len(raw) == 1 else raw.get(canon_name, {})

    ra_deg, dec_deg, ra_str, dec_str = extract_coords(ev_data)

    aliases = [a.get("value") if isinstance(a, dict) else str(a) for a in ev_data.get("alias", [])]
    photo_count = len(ev_data.get("photometry", []))
    spec_count = len(ev_data.get("spectra", []))

    return {
        "name": canon_name,
        "aliases": aliases,
        "claimed_type": get_val(ev_data, "claimedtype"),
        "discovery_date": get_val(ev_data, "discoverdate"),
        "discoverer": get_val(ev_data, "discoverer"),
        "host_galaxy": get_val(ev_data, "host"),
        "coordinates": {
            "ra_deg": ra_deg,
            "dec_deg": dec_deg,
            "ra_sexagesimal": ra_str,
            "dec_sexagesimal": dec_str,
        },
        "redshift": get_val(ev_data, "redshift"),
        "luminosity_distance_mpc": get_val(ev_data, "lumdist"),
        "max_apparent_mag": get_val(ev_data, "maxappmag"),
        "max_abs_mag": get_val(ev_data, "maxabsmag"),
        "photometry_points_count": photo_count,
        "spectra_count": spec_count,
        "pro_url": f"https://sne.space/sne/{canon_name}/",
        "story_url": f"https://sne.space/sne/{canon_name}/story",
    }


@mcp.tool()
def get_lightcurve(name: str, bands: Optional[List[str]] = None, limit: int = 500) -> Dict[str, Any]:
    """Retrieve calibrated multi-band photometric light curve observations for a supernova.

    Args:
        name: Name of the supernova (e.g., 'SN2023ixf', 'SN2024ggi').
        bands: Optional list of photometric passbands to filter by (e.g., ['g', 'r', 'V']).
        limit: Maximum number of photometric points to return (default 500).
    """
    resolved, _ = _resolve_event(name)
    canon_name = resolved or name
    _, fp = _find_event_file(canon_name)

    if not fp or not fp.is_file():
        return {"error": f"Supernova '{name}' not found."}

    raw = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
    ev_data = next(iter(raw.values())) if len(raw) == 1 else raw.get(canon_name, {})

    photometry = ev_data.get("photometry", [])
    if not photometry:
        return {"name": canon_name, "photometry": [], "message": "No photometry available for this event."}

    bands_filter = {b.lower() for b in bands} if bands else None

    points = []
    for p in photometry:
        band = p.get("band", "")
        if bands_filter and band.lower() not in bands_filter:
            continue

        pt = {
            "time_mjd": float(p["time"]) if "time" in p and str(p["time"]).replace(".", "", 1).isdigit() else p.get("time"),
            "magnitude": float(p["magnitude"]) if "magnitude" in p and str(p["magnitude"]).replace(".", "", 1).isdigit() else p.get("magnitude"),
            "e_magnitude": float(p["e_magnitude"]) if "e_magnitude" in p and str(p["e_magnitude"]).replace(".", "", 1).isdigit() else p.get("e_magnitude"),
            "band": band,
            "telescope": p.get("telescope", p.get("instrument", "")),
            "upperlimit": p.get("upperlimit", False),
        }
        points.append(pt)
        if len(points) >= limit:
            break

    return {
        "name": canon_name,
        "total_catalog_points": len(photometry),
        "returned_points": len(points),
        "photometry": points,
    }


@mcp.tool()
def get_spectrum(name: str, epoch_index: int = 0) -> Dict[str, Any]:
    """Retrieve calibrated 1D optical spectrum (wavelengths in Angstroms, flux values) for a supernova.

    Args:
        name: Name of the supernova.
        epoch_index: Index of the spectrum to fetch (0 = earliest/classification epoch).
    """
    resolved, _ = _resolve_event(name)
    canon_name = resolved or name
    _, fp = _find_event_file(canon_name)

    if not fp or not fp.is_file():
        return {"error": f"Supernova '{name}' not found."}

    raw = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
    ev_data = next(iter(raw.values())) if len(raw) == 1 else raw.get(canon_name, {})

    spectra = ev_data.get("spectra", [])
    if not spectra:
        return {"name": canon_name, "spectra_available": 0, "message": "No calibrated spectra available."}

    if epoch_index >= len(spectra):
        return {"error": f"Invalid epoch_index {epoch_index}. Supernova has {len(spectra)} spectra."}

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

    return {
        "name": canon_name,
        "epoch_index": epoch_index,
        "total_spectra": len(spectra),
        "time_mjd": spec.get("time"),
        "telescope": spec.get("telescope"),
        "instrument": spec.get("instrument"),
        "source": spec.get("source"),
        "num_data_points": len(wavelengths),
        "wavelength_angstroms": wavelengths[:1000],  # capped for network payload
        "flux": fluxes[:1000],
    }


@mcp.tool()
def calculate_cosmology(z: float) -> Dict[str, Any]:
    """Calculate cosmological distance parameters (recession velocity, luminosity distance, lookback time) under standard Flat Lambda-CDM cosmology (H0=70 km/s/Mpc, Omega_M=0.3, Omega_Lambda=0.7).

    Args:
        z: Spectroscopic or photometric redshift.
    """
    if z <= 0:
        return {"error": "Redshift z must be greater than 0."}

    c = 299792.458  # speed of light in km/s
    h0 = 70.0
    omega_m = 0.3
    omega_l = 0.7

    # Relativistic recession velocity
    beta = ((1 + z) ** 2 - 1) / ((1 + z) ** 2 + 1)
    v_recession_km_s = c * beta

    # Numeric integration for comoving distance
    steps = 1000
    dz = z / steps
    integral = 0.0
    lookback_integral = 0.0
    for i in range(steps):
        z_mid = (i + 0.5) * dz
        ez = math.sqrt(omega_m * ((1 + z_mid) ** 3) + omega_l)
        integral += (1.0 / ez) * dz
        lookback_integral += (1.0 / ((1 + z_mid) * ez)) * dz

    d_comoving_mpc = (c / h0) * integral
    d_lum_mpc = d_comoving_mpc * (1 + z)
    dist_modulus = 5.0 * math.log10(d_lum_mpc * 1e6) - 5.0
    dist_ly_millions = d_lum_mpc * 3.26156

    # Lookback time in Gyr
    # 1/H0 in Gyr = 977.8 / h0
    thub_gyr = 977.8 / h0
    lookback_time_gyr = thub_gyr * lookback_integral

    return {
        "redshift_z": z,
        "recession_velocity_km_s": round(v_recession_km_s, 1),
        "luminosity_distance_mpc": round(d_lum_mpc, 2),
        "luminosity_distance_million_ly": round(dist_ly_millions, 2),
        "distance_modulus_mu": round(dist_modulus, 3),
        "lookback_time_gyr": round(lookback_time_gyr, 3),
        "hubble_constant_km_s_mpc": h0,
    }


@mcp.tool()
def spatial_cone_search(ra_deg: float, dec_deg: float, radius_deg: float = 0.1, limit: int = 25) -> List[Dict[str, Any]]:
    """Perform high-speed 3D Cartesian cone search across all 110,000+ catalog supernovae.

    Args:
        ra_deg: Right Ascension in decimal degrees (0 to 360).
        dec_deg: Declination in decimal degrees (-90 to +90).
        radius_deg: Search radius in decimal degrees (default 0.1 deg = 6 arcmin).
        limit: Maximum results to return (default 25).
    """
    hits = do_cone_search(ra_deg, dec_deg, radius_deg)
    return hits[:limit]


if __name__ == "__main__":
    mcp.run()
