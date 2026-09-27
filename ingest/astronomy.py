"""Astrophysical derivations and reference catalog queries.

Calculates cosmological distances, recession velocities, peak absolute magnitudes,
and queries NASA/IPAC IRSA for Galactic line-of-sight dust extinction E(B-V).
"""
import math
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

# Speed of light in km/s
CLIGHT_KM = 299792.458

# Standard Planck 2015 cosmological parameters (matching historical AstroCats cleanup.py)
# H0 = 67.8 km/s/Mpc, Om0 = 0.308, Ode0 = 0.692
H0_DEFAULT = 67.8
OM0_DEFAULT = 0.308
ODE0_DEFAULT = 1.0 - OM0_DEFAULT


def compute_cosmology(
    z: float,
    h0: float = H0_DEFAULT,
    om0: float = OM0_DEFAULT
) -> Dict[str, float]:
    """Calculate cosmological distances and recession velocity from spectroscopic redshift.
    
    Uses standard flat Lambda-CDM cosmology with Simpson's rule numerical integration.
    Returns:
        lumdist: Luminosity distance in Mpc
        comovingdist: Comoving distance in Mpc
        velocity: Relativistic recession velocity in km/s
    """
    if z <= 0.0:
        return {}

    ode0 = 1.0 - om0
    c = CLIGHT_KM

    # Relativistic velocity
    v = c * ((1.0 + z) ** 2 - 1.0) / ((1.0 + z) ** 2 + 1.0)

    # Numerical integration of 1 / E(z') from 0 to z
    n = 200
    h = z / n

    def inv_e(zp: float) -> float:
        return 1.0 / math.sqrt(om0 * (1.0 + zp) ** 3 + ode0)

    integral = inv_e(0.0) + inv_e(z)
    for i in range(1, n):
        w = 4.0 if i % 2 == 1 else 2.0
        integral += w * inv_e(i * h)
    integral *= (h / 3.0)

    dc = (c / h0) * integral
    dl = (1.0 + z) * dc

    return {
        "lumdist": round(dl, 3),
        "comovingdist": round(dc, 3),
        "velocity": round(v, 1),
    }


def mjd_to_date_str(mjd: float) -> str:
    """Convert Modified Julian Date (MJD) to Gregorian YYYY/MM/DD date string."""
    jd = mjd + 2400000.5
    z = int(jd + 0.5)
    f = (jd + 0.5) - z
    if z < 2299161:
        a = z
    else:
        alpha = int((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - int(alpha / 4)
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    day = b - d - int(30.6001 * e) + f
    if e < 14:
        month = e - 1
    else:
        month = e - 13
    if month > 2:
        year = c - 4716
    else:
        year = c - 4715
    return f"{year:04d}/{month:02d}/{int(day):02d}"


def fetch_irsa_dust(ra_deg: float, dec_deg: float, timeout: int = 6) -> Tuple[Optional[str], Optional[str]]:
    """Query NASA/IPAC IRSA dust service for Galactic line-of-sight E(B-V) reddening.
    
    Reference: Schlafly & Finkbeiner (2011, ApJ 737, 103).
    Returns (ebv_mean_str, ebv_std_str).
    """
    url = f"https://irsa.ipac.caltech.edu/cgi-bin/DUST/nph-dust?locstr={ra_deg:.6f}+{dec_deg:.6f}"
    req = urllib.request.Request(url, headers={"User-Agent": "sne.space/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            xml_text = resp.read()
        root = ET.fromstring(xml_text)
        sandf_val = root.find(".//meanValueSandF")
        sandf_std = root.find(".//stdSandF")
        if sandf_val is not None and sandf_val.text:
            val = sandf_val.text.split()[0].strip()
            err = sandf_std.text.split()[0].strip() if (sandf_std is not None and sandf_std.text) else ""
            return val, err
    except Exception:
        pass
    return None, None


def compute_peak_magnitudes(
    photometry: List[Dict[str, Any]],
    dl_mpc: Optional[float] = None,
    z: Optional[float] = None
) -> Dict[str, Any]:
    """Find peak apparent magnitude and calculate peak absolute magnitude."""
    valid_points = []
    visual_points = []
    visual_bands = {"v", "g", "r", "orange", "o", "clear", "open", "visual"}

    for p in photometry:
        if p.get("upperlimit"):
            continue
        try:
            m = float(p.get("magnitude", ""))
            t = float(p.get("time", ""))
            b = str(p.get("band", "")).strip()
            valid_points.append((m, t, b, p.get("source", "1")))
            if b.lower() in visual_bands:
                visual_points.append((m, t, b, p.get("source", "1")))
        except (ValueError, TypeError):
            continue

    if not valid_points:
        return {}

    # Peak apparent magnitude = minimum magnitude
    valid_points.sort(key=lambda x: x[0])
    peak_m, peak_t, peak_b, peak_src = valid_points[0]
    peak_date = mjd_to_date_str(peak_t)

    result: Dict[str, Any] = {
        "maxappmag": f"{peak_m:.2f}",
        "maxdate": peak_date,
        "maxband": peak_b,
        "max_source": peak_src,
    }

    # Absolute magnitude: M = m - 5*(log10(dl * 10^6) - 1) + 2.5*log10(1+z)
    if dl_mpc is not None and dl_mpc > 0:
        k_corr = 2.5 * math.log10(1.0 + z) if (z is not None and z > 0) else 0.0
        dist_mod = 5.0 * (math.log10(dl_mpc * 1.0e6) - 1.0)
        m_abs = peak_m - dist_mod + k_corr
        result["maxabsmag"] = f"{m_abs:.2f}"

    # Visual peak
    if visual_points:
        visual_points.sort(key=lambda x: x[0])
        v_m, v_t, v_b, v_src = visual_points[0]
        result["maxvisualappmag"] = f"{v_m:.2f}"
        result["maxvisualdate"] = mjd_to_date_str(v_t)
        result["maxvisualband"] = v_b
        result["maxvisual_source"] = v_src
        if dl_mpc is not None and dl_mpc > 0:
            k_corr = 2.5 * math.log10(1.0 + z) if (z is not None and z > 0) else 0.0
            dist_mod = 5.0 * (math.log10(dl_mpc * 1.0e6) - 1.0)
            m_v_abs = v_m - dist_mod + k_corr
            result["maxvisualabsmag"] = f"{m_v_abs:.2f}"

    return result
