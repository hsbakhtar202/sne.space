"""Coordinate and astronomical time conversion utilities for transients."""
from datetime import datetime
from typing import Tuple, Optional


def deg_to_ra_dec(ra_deg: float, dec_deg: float) -> Tuple[str, str]:
    """Convert RA and Dec in decimal degrees to sexagesimal strings.
    
    RA is converted to hours, minutes, seconds: HH:MM:SS.sss
    Dec is converted to degrees, arcminutes, arcseconds: ±DD:MM:SS.ss
    """
    # RA: 360 degrees = 24 hours (1 hour = 15 degrees)
    hours = (ra_deg % 360.0) / 15.0
    h = int(hours)
    m = int((hours - h) * 60.0)
    s = (hours - h - m / 60.0) * 3600.0
    # Handle rounding edge cases where seconds rounds to 60.0
    if round(s, 3) >= 60.0:
        s = 0.0
        m += 1
        if m >= 60:
            m = 0
            h = (h + 1) % 24
    ra_str = f"{h:02d}:{m:02d}:{s:06.3f}"

    # Dec: -90 to +90 degrees
    sign = "+" if dec_deg >= 0 else "-"
    d_abs = abs(dec_deg)
    d = int(d_abs)
    dm = int((d_abs - d) * 60.0)
    ds = (d_abs - d - dm / 60.0) * 3600.0
    if round(ds, 2) >= 60.0:
        ds = 0.0
        dm += 1
        if dm >= 60:
            dm = 0
            d += 1
    dec_str = f"{sign}{d:02d}:{dm:02d}:{ds:05.2f}"

    return ra_str, dec_str


def ra_dec_to_deg(ra_str: str, dec_str: str) -> Tuple[float, float]:
    """Convert sexagesimal RA (HH:MM:SS) and Dec (±DD:MM:SS) to decimal degrees."""
    ra_parts = [float(p) for p in ra_str.strip().split(":")]
    ra_deg = (ra_parts[0] + ra_parts[1] / 60.0 + ra_parts[2] / 3600.0) * 15.0

    dec_clean = dec_str.strip()
    dec_sign = -1.0 if dec_clean.startswith("-") else 1.0
    dec_parts = [float(p) for p in dec_clean.lstrip("+-").split(":")]
    dec_deg = dec_sign * (dec_parts[0] + dec_parts[1] / 60.0 + dec_parts[2] / 3600.0)

    return ra_deg, dec_deg


def parse_float_safe(val: str | None) -> Optional[float]:
    """Safely parse float from string."""
    if val is None:
        return None
    val_str = str(val).strip()
    if not val_str:
        return None
    try:
        return float(val_str)
    except ValueError:
        return None


def datetime_to_mjd(dt: datetime) -> float:
    """Compute Modified Julian Date (MJD) from standard UTC datetime."""
    year = dt.year
    month = dt.month
    day = dt.day + (dt.hour + dt.minute / 60.0 + dt.second / 3600.0 + dt.microsecond / 1e6) / 24.0
    if month <= 2:
        year -= 1
        month += 12
    a = int(year / 100)
    b = 2 - a + int(a / 4)
    jd = int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + b - 1524.5
    return jd - 2400000.5


def parse_iso_datetime(date_str: str) -> Optional[Tuple[datetime, float, str]]:
    """Parse TNS/ISO date string and return (datetime, MJD, formatted_date_str)."""
    if not date_str:
        return None
    s = date_str.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            mjd = datetime_to_mjd(dt)
            # Astrocats date format is YYYY/MM/DD
            cat_date = dt.strftime("%Y/%m/%d")
            return dt, mjd, cat_date
        except ValueError:
            continue
    return None

