"""Dynamic Astrophysical FAQ Generation & Article Synthesis Engine for sne.space.

Transforms all available astrophysical parameters (type, progenitor physics,
distance, lookback era, host offset, nucleosynthesis, remnant fate, peak solar
luminosity, multi-band photometry, spectroscopy, ejecta velocity, visibility,
and celestial coordinates) into rich, educational Q&A pairs for both consumer
pages, Schema.org FAQPage / Article structured data, and in-depth story articles.
"""
from __future__ import annotations

import json
import math
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

# Constellation centers for celestial locator (88 IAU constellations)
_CONSTELLATION_CENTERS = [
    ("And", "Andromeda", "The Chained Maiden", 15.0, 38.0),
    ("Ant", "Antlia", "The Air Pump", 150.0, -35.0),
    ("Aps", "Apus", "The Bird of Paradise", 240.0, -75.0),
    ("Aqr", "Aquarius", "The Water Bearer", 335.0, -10.0),
    ("Aql", "Aquila", "The Eagle", 295.0, 3.0),
    ("Ara", "Ara", "The Altar", 260.0, -55.0),
    ("Ari", "Aries", "The Ram", 40.0, 20.0),
    ("Aur", "Auriga", "The Charioteer", 90.0, 42.0),
    ("Boo", "Boötes", "The Herdsman", 215.0, 30.0),
    ("Cae", "Caelum", "The Chisel", 70.0, -38.0),
    ("Cam", "Camelopardalis", "The Giraffe", 90.0, 70.0),
    ("Cnc", "Cancer", "The Crab", 130.0, 20.0),
    ("CVn", "Canes Venatici", "The Hunting Dogs", 195.0, 40.0),
    ("CMa", "Canis Major", "The Greater Dog", 105.0, -22.0),
    ("CMi", "Canis Minor", "The Lesser Dog", 115.0, 6.0),
    ("Cap", "Capricornus", "The Sea Goat", 315.0, -20.0),
    ("Car", "Carina", "The Keel", 135.0, -63.0),
    ("Cas", "Cassiopeia", "The Queen", 15.0, 60.0),
    ("Cen", "Centaurus", "The Centaur", 200.0, -47.0),
    ("Cep", "Cepheus", "The King", 335.0, 70.0),
    ("Cet", "Cetus", "The Sea Monster", 25.0, -10.0),
    ("Cha", "Chamaeleon", "The Chameleon", 165.0, -79.0),
    ("Cir", "Circinus", "The Compasses", 220.0, -63.0),
    ("Col", "Columba", "The Dove", 85.0, -35.0),
    ("Com", "Coma Berenices", "Berenice's Hair", 190.0, 23.0),
    ("CrA", "Corona Australis", "The Southern Crown", 285.0, -40.0),
    ("CrB", "Corona Borealis", "The Northern Crown", 235.0, 30.0),
    ("Crv", "Corvus", "The Crow", 185.0, -18.0),
    ("Crt", "Crater", "The Cup", 170.0, -15.0),
    ("Cru", "Crux", "The Southern Cross", 185.0, -60.0),
    ("Cyg", "Cygnus", "The Swan", 310.0, 43.0),
    ("Del", "Delphinus", "The Dolphin", 310.0, 12.0),
    ("Dor", "Dorado", "The Swordfish / Dolphinfish", 80.0, -60.0),
    ("Dra", "Draco", "The Dragon", 260.0, 65.0),
    ("Equ", "Equuleus", "The Little Horse", 320.0, 8.0),
    ("Eri", "Eridanus", "The River", 55.0, -30.0),
    ("For", "Fornax", "The Furnace", 40.0, -30.0),
    ("Gem", "Gemini", "The Twins", 105.0, 22.0),
    ("Gru", "Grus", "The Crane", 335.0, -47.0),
    ("Her", "Hercules", "Hercules", 255.0, 27.0),
    ("Hor", "Horologium", "The Clock", 45.0, -50.0),
    ("Hya", "Hydra", "The Water Snake", 160.0, -20.0),
    ("Hyi", "Hydrus", "The Lesser Water Snake", 30.0, -70.0),
    ("Ind", "Indus", "The Indian", 315.0, -55.0),
    ("Lac", "Lacerta", "The Lizard", 335.0, 45.0),
    ("Leo", "Leo", "The Lion", 160.0, 15.0),
    ("LMi", "Leo Minor", "The Lesser Lion", 155.0, 35.0),
    ("Lep", "Lepus", "The Hare", 80.0, -20.0),
    ("Lib", "Libra", "The Scales", 225.0, -15.0),
    ("Lup", "Lupus", "The Wolf", 230.0, -42.0),
    ("Lyn", "Lynx", "The Lynx", 120.0, 45.0),
    ("Lyr", "Lyra", "The Lyre", 285.0, 36.0),
    ("Men", "Mensa", "The Table Mountain", 85.0, -77.0),
    ("Mic", "Microscopium", "The Microscope", 315.0, -36.0),
    ("Mon", "Monoceros", "The Unicorn", 105.0, 0.0),
    ("Mus", "Musca", "The Fly", 185.0, -70.0),
    ("Nor", "Norma", "The Carpenter's Square", 235.0, -52.0),
    ("Oct", "Octans", "The Octant", 330.0, -85.0),
    ("Oph", "Ophiuchus", "The Serpent Bearer", 260.0, -5.0),
    ("Ori", "Orion", "The Hunter", 85.0, 5.0),
    ("Pav", "Pavo", "The Peacock", 295.0, -65.0),
    ("Peg", "Pegasus", "The Winged Horse", 340.0, 20.0),
    ("Per", "Perseus", "The Hero", 45.0, 42.0),
    ("Phe", "Phoenix", "The Phoenix", 5.0, -45.0),
    ("Pic", "Pictor", "The Painter's Easel", 85.0, -53.0),
    ("Psc", "Pisces", "The Fishes", 10.0, 15.0),
    ("PsA", "Piscis Austrinus", "The Southern Fish", 335.0, -30.0),
    ("Pup", "Puppis", "The Stern", 115.0, -32.0),
    ("Pyx", "Pyxis", "The Compass", 135.0, -30.0),
    ("Ret", "Reticulum", "The Reticle", 60.0, -60.0),
    ("Sge", "Sagitta", "The Arrow", 295.0, 18.0),
    ("Sgr", "Sagittarius", "The Archer", 285.0, -25.0),
    ("Sco", "Scorpius", "The Scorpion", 250.0, -30.0),
    ("Scl", "Sculptor", "The Sculptor", 5.0, -32.0),
    ("Sct", "Scutum", "The Shield", 280.0, -10.0),
    ("Ser", "Serpens", "The Serpent", 240.0, 5.0),
    ("Sex", "Sextans", "The Sextant", 152.0, 0.0),
    ("Tau", "Taurus", "The Bull", 65.0, 18.0),
    ("Tel", "Telescopium", "The Telescope", 285.0, -50.0),
    ("Tri", "Triangulum", "The Triangle", 35.0, 32.0),
    ("TrA", "Triangulum Australe", "The Southern Triangle", 240.0, -65.0),
    ("Tuc", "Tucana", "The Toucan", 0.0, -65.0),
    ("UMa", "Ursa Major", "The Great Bear", 165.0, 55.0),
    ("UMi", "Ursa Minor", "The Little Bear", 230.0, 78.0),
    ("Vel", "Vela", "The Sails", 140.0, -47.0),
    ("Vir", "Virgo", "The Maiden", 195.0, -5.0),
    ("Vol", "Volans", "The Flying Fish", 115.0, -70.0),
    ("Vul", "Vulpecula", "The Fox", 305.0, 25.0),
]


def identify_constellation(ra_deg: Optional[float], dec_deg: Optional[float]) -> Tuple[str, str]:
    """Return (Constellation Name, English Label) for celestial coordinates."""
    if ra_deg is None or dec_deg is None:
        return ("the deep sky", "deep space")
    ra_rad = math.radians(ra_deg)
    dec_rad = math.radians(dec_deg)
    x0 = math.cos(dec_rad) * math.cos(ra_rad)
    y0 = math.cos(dec_rad) * math.sin(ra_rad)
    z0 = math.sin(dec_rad)

    best_name = "Ursa Major"
    best_english = "The Great Bear"
    min_dist = 999.0

    for code, name, eng, ra_c, dec_c in _CONSTELLATION_CENTERS:
        rc_rad = math.radians(ra_c)
        dc_rad = math.radians(dec_c)
        xc = math.cos(dc_rad) * math.cos(rc_rad)
        yc = math.cos(dc_rad) * math.sin(rc_rad)
        zc = math.sin(dc_rad)
        dist = (x0 - xc) ** 2 + (y0 - yc) ** 2 + (z0 - zc) ** 2
        if dist < min_dist:
            min_dist = dist
            best_name = name
            best_english = eng

    return (best_name, best_english)


def get_lookback_geological_era(ly_millions: Optional[float]) -> str:
    """Return historical / geological context of when the light set out from the explosion."""
    if ly_millions is None or ly_millions <= 0:
        return "deep cosmic time"
    if ly_millions < 0.2:
        return f"{int(ly_millions * 1e6):,} years ago during the human Stone Age, as early Homo sapiens first inhabited Africa"
    elif ly_millions < 3.0:
        return f"{ly_millions:.1f} million years ago during the Pleistocene epoch when early hominins first fashioned stone tools on Earth"
    elif ly_millions < 25.0:
        return f"{ly_millions:.1f} million years ago during the Miocene epoch as mammalian lineages and grasslands flourished"
    elif ly_millions < 66.0:
        return f"{ly_millions:.1f} million years ago during the early Cenozoic era, following the extinction of the non-avian dinosaurs"
    elif ly_millions < 145.0:
        return f"{ly_millions:.1f} million years ago during the Cretaceous period when Tyrannosaurus rex and Triceratops walked the planet"
    elif ly_millions < 201.0:
        return f"{ly_millions:.1f} million years ago during the Jurassic period when giant sauropod dinosaurs dominated the continents"
    elif ly_millions < 252.0:
        return f"{ly_millions:.1f} million years ago during the Triassic period as the earliest dinosaurs and mammals were just evolving"
    elif ly_millions < 541.0:
        return f"{ly_millions:.1f} million years ago during the Paleozoic era, long before the first dinosaurs appeared on Earth"
    elif ly_millions < 1000.0:
        return f"{ly_millions:.1f} million years ago during the Neoproterozoic, hundreds of millions of years before complex animal life diversified"
    else:
        return f"{ly_millions:.1f} million years ago in deep Precambrian time, well before multicellular animals dominated Earth"


def calculate_solar_luminosities(max_abs_mag: str) -> str | None:
    """Convert peak absolute magnitude into equivalent solar luminosities.

    Returns None when the absolute magnitude is unavailable. The previous fallback
    returned the string "hundreds of millions of Suns", which read as a measurement
    in rendered prose despite being a placeholder. Callers must handle None.
    """
    try:
        m_abs = float(re.sub(r"[^\d.-]", "", str(max_abs_mag)))
        l_suns = 10 ** (-0.4 * (m_abs - 4.83))
        if l_suns >= 1e9:
            return f"{l_suns / 1e9:.1f} billion Suns"
        elif l_suns >= 1e6:
            return f"{l_suns / 1e6:.1f} million Suns"
        else:
            return f"{l_suns:,.0f} Suns"
    except Exception:
        return None


def analyze_photometry(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Extract quantitative photometric statistics from event metadata."""
    photo = meta.get("photometry", [])
    if not isinstance(photo, list):
        photo = []

    count = len(photo)
    bands = sorted(list(set(str(p.get("band", "")).strip() for p in photo if isinstance(p, dict) and p.get("band"))))
    telescopes = sorted(list(set(str(p.get("telescope", "")).strip() for p in photo if isinstance(p, dict) and p.get("telescope"))))
    instruments = sorted(list(set(str(p.get("instrument", "")).strip() for p in photo if isinstance(p, dict) and p.get("instrument"))))

    times: List[float] = []
    mags: List[float] = []
    for p in photo:
        if isinstance(p, dict):
            t = p.get("time")
            if t is not None:
                try:
                    times.append(float(t))
                except (ValueError, TypeError):
                    pass
            m = p.get("magnitude")
            if m is not None:
                try:
                    mags.append(float(m))
                except (ValueError, TypeError):
                    pass

    timespan_days = None
    if times and len(times) > 1:
        timespan_days = round(max(times) - min(times), 1)

    brightest_mag = min(mags) if mags else None
    faintest_mag = max(mags) if mags else None

    return {
        "count": count,
        "bands": bands,
        "telescopes": telescopes,
        "instruments": instruments,
        "timespan_days": timespan_days,
        "brightest_mag": brightest_mag,
        "faintest_mag": faintest_mag,
    }


def analyze_spectra(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Extract quantitative spectroscopic statistics from event metadata."""
    specs = meta.get("spectra", [])
    if not isinstance(specs, list):
        specs = []

    count = len(specs)
    telescopes = sorted(list(set(str(s.get("telescope", "")).strip() for s in specs if isinstance(s, dict) and s.get("telescope"))))
    instruments = sorted(list(set(str(s.get("instrument", "")).strip() for s in specs if isinstance(s, dict) and s.get("instrument"))))

    all_w: List[float] = []
    for s in specs:
        if isinstance(s, dict):
            data = s.get("data", [])
            if isinstance(data, list):
                for row in data:
                    if isinstance(row, list) and len(row) > 0:
                        try:
                            all_w.append(float(row[0]))
                        except (ValueError, TypeError):
                            pass

    w_min = round(min(all_w), 1) if all_w else None
    w_max = round(max(all_w), 1) if all_w else None

    return {
        "count": count,
        "telescopes": telescopes,
        "instruments": instruments,
        "w_min": w_min,
        "w_max": w_max,
    }


def analyze_velocity(meta: Dict[str, Any], claimedtype: str) -> Dict[str, Any]:
    """Return measured ejecta velocity only — never cosmological recession velocity.

    ``meta["velocity"]`` may hold a derived redshift Doppler-equivalent speed
    written by enrichment (kind=redshift_doppler_equivalent / recession /
    heliocentric / derived). That is unrelated to blast-wave ejecta speed, which
    must come from Doppler-shifted spectral lines. Class-typical means are not
    returned as object measurements.
    """
    _empty = {
        "is_measured": False,
        "km_s": None,
        "pct_c": None,
        "earths_per_sec": None,
        "mach": None,
        "class_typical_kms": None,
    }
    _cosmo_kinds = {
        "heliocentric",
        "recession",
        "redshift_doppler_equivalent",
        "cosmological",
        "hubble",
        "cmb",
    }

    vel_raw = meta.get("velocity", [])
    vel_val = None
    if isinstance(vel_raw, list) and vel_raw:
        first = vel_raw[0]
        if isinstance(first, dict):
            kind = str(first.get("kind") or "").lower().strip()
            if first.get("derived") or kind in _cosmo_kinds:
                vel_val = None
            else:
                v_str = first.get("value", "")
                try:
                    vel_val = float(re.sub(r"[^\d.-]", "", str(v_str)))
                except Exception:
                    vel_val = None
        else:
            try:
                vel_val = float(re.sub(r"[^\d.-]", "", str(first)))
            except Exception:
                vel_val = None
    elif isinstance(vel_raw, (int, float)):
        vel_val = float(vel_raw)
    elif isinstance(vel_raw, str) and vel_raw.strip():
        try:
            vel_val = float(re.sub(r"[^\d.-]", "", vel_raw))
        except Exception:
            vel_val = None

    is_measured = vel_val is not None and vel_val > 0
    if not is_measured:
        # Optional class-typical scale for prose context only — never as a measurement.
        c_low = (claimedtype or "").lower().strip()
        class_typical = None
        if "ia" in c_low and "ii" not in c_low:
            class_typical = 11000.0
        elif "ic-bl" in c_low or "broad" in c_low:
            class_typical = 22000.0
        elif "ib" in c_low or "ic" in c_low:
            class_typical = 12500.0
        elif "slsn" in c_low:
            class_typical = 15000.0
        elif "ii" in c_low:
            class_typical = 8500.0
        out = dict(_empty)
        out["class_typical_kms"] = class_typical
        return out

    c_light = 299792.458  # km/s
    return {
        "is_measured": True,
        "km_s": vel_val,
        "pct_c": (vel_val / c_light) * 100.0,
        "earths_per_sec": vel_val / 12742.0,
        "mach": vel_val / 0.343,
        "class_typical_kms": None,
    }


def analyze_sources(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Extract citation depth and archival publications."""
    sources = meta.get("sources", [])
    if not isinstance(sources, list):
        sources = []
    count = len(sources)
    names: List[str] = []
    bibcodes: List[str] = []
    for s in sources:
        if isinstance(s, dict):
            name = s.get("name") or s.get("reference") or ""
            if name:
                names.append(str(name))
            if s.get("bibcode"):
                bibcodes.append(str(s.get("bibcode")))
    return {
        "count": count,
        "names": names[:6],
        "bibcodes": bibcodes[:4],
    }


def analyze_cosmology(redshift_str: str, lumdist_str: str) -> Dict[str, Any]:
    """Compute recession velocity, luminosity distance, and lookback time separately.

    Luminosity distance (converted to Mly) is *not* light-travel time. Lookback
    time comes from flat ΛCDM integration and is reported independently.
    Recession velocity uses the same relativistic Doppler-equivalent convention
    as ``astro_engine.calc_cosmology`` (not bare ``c*z``).
    """
    z = None
    if redshift_str != "—":
        try:
            z = float(re.sub(r"[^\d.-]", "", redshift_str))
        except Exception:
            pass

    recession_km_s = None
    lookback_myr = None
    if z is not None and z > 0:
        try:
            try:
                from astro_engine import calc_cosmology
            except ImportError:
                from serve.astro_engine import calc_cosmology
            cos = calc_cosmology(z)
            recession_km_s = cos.get("velocity_kms")
            lookback_myr = cos.get("lookback_myr")
        except Exception:
            # Fallback: relativistic Doppler-equivalent velocity only.
            opz = 1.0 + z
            recession_km_s = round(299792.458 * (opz * opz - 1.0) / (opz * opz + 1.0), 1)

    mpc = None
    ly_millions = None  # luminosity-distance Mly — not lookback
    if lumdist_str != "—":
        try:
            mpc = float(re.sub(r"[^\d.]", "", lumdist_str))
            ly_millions = mpc * 3.26156
        except Exception:
            pass

    return {
        "z": z,
        "recession_km_s": recession_km_s,
        "mpc": mpc,
        "ly_millions": ly_millions,
        "lookback_myr": lookback_myr,
    }


def generate_supernova_faqs(
    name: str,
    meta: Dict[str, Any],
    ra_deg: Optional[float] = None,
    dec_deg: Optional[float] = None,
    ra_str: str = "—",
    dec_str: str = "—",
    claimedtype: str = "—",
    discoverdate: str = "—",
    discoverer: str = "—",
    maxappmag: str = "—",
    maxdate: str = "—",
    maxabsmag: str = "—",
    lumdist: str = "—",
    redshift: str = "—",
    host: str = "—",
    host_offset_str: str = "—",
    dist_ly_str: str = "Millions of Light-Years",
    lifecycle: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Synthesize complete, mathematically verified FAQs from event metadata."""
    faqs: List[Dict[str, str]] = []

    # Quantitative analyses
    cosmo = analyze_cosmology(redshift, lumdist)
    photo_info = analyze_photometry(meta)
    spec_info = analyze_spectra(meta)
    vel_info = analyze_velocity(meta, claimedtype)
    src_info = analyze_sources(meta)
    const_name, const_eng = identify_constellation(ra_deg, dec_deg)
    # Geological era uses lookback time (Myr), never luminosity-distance Mly.
    era_context = get_lookback_geological_era(
        cosmo.get("lookback_myr") if cosmo.get("lookback_myr") is not None else None
    )
    solar_lum = calculate_solar_luminosities(maxabsmag)

    # Aliases
    raw_aliases = meta.get("alias", [])
    aliases = []
    for a in raw_aliases:
        val = a.get("value", "") if isinstance(a, dict) else str(a)
        if val and val != name:
            aliases.append(val)

    # Foreground dust — preserve provenance from enrichment when present
    ebv_val = "—"
    ebv_source = None
    ebv_raw = meta.get("ebv", [])
    if isinstance(ebv_raw, list) and ebv_raw:
        first_ebv = ebv_raw[0]
        if isinstance(first_ebv, dict):
            ebv_val = str(first_ebv.get("value", "—"))
            ebv_source = first_ebv.get("source_name") or first_ebv.get("source")
        else:
            ebv_val = str(first_ebv)
    elif isinstance(ebv_raw, str):
        ebv_val = ebv_raw

    c_lower = claimedtype.lower()
    host_identified = host not in ("—", "", "none", "None", None)
    host_name = host if host_identified else None
    disc_who = discoverer if discoverer != "—" else "an automated robotic transient sky survey"

    # =========================================================================
    # CATEGORY 1: ASTROPHYSICS & PROGENITOR STAR
    # =========================================================================

    # 1. Type & Progenitor Physics
    if "ia" in c_lower and "ii" not in c_lower:
        type_ans = (
            f"{name} is spectroscopically classified as a <strong>Type Ia supernova</strong>, consistent with a thermonuclear "
            f"explosion involving a carbon-oxygen white dwarf. Type Ia events are used as distance indicators via empirical "
            f"relations such as the Phillips relation, but that cosmological utility does not identify which binary channel "
            f"(single-degenerate accretion, double-degenerate merger, or sub-Chandrasekhar detonation) produced "
            f"<em>this</em> object."
        )
    elif "tde" in c_lower or "tidal" in c_lower:
        type_ans = (
            f"{name} is classified as a <strong>tidal disruption event (TDE)</strong>: a star was torn apart by a "
            f"supermassive black hole's tidal field. This is not a stellar core-collapse or thermonuclear supernova; "
            f"radioactive ⁵⁶Ni-powered light-curve models for supernovae do not apply by default."
        )
    elif "slsn" in c_lower or "superluminous" in c_lower:
        type_ans = (
            f"{name} is classified as a <strong>superluminous supernova (SLSN)</strong>. Proposed power sources include "
            f"magnetar spin-down and ejecta–CSM interaction; which engine applies to this object is not established from "
            f"the classification label alone."
        )
    elif "iip" in c_lower or "ii-p" in c_lower or ("ii" in c_lower and "iin" not in c_lower and "iib" not in c_lower):
        type_ans = (
            f"{name} is classified as a <strong>Type II supernova</strong>, consistent with core collapse of a massive star "
            f"that retained hydrogen in its outer envelope. Typical progenitor mass ranges quoted for the class are "
            f"model expectations, not a measured mass for this star."
        )
    elif "ib" in c_lower or "ic" in c_lower or "iib" in c_lower:
        type_ans = (
            f"{name} is a <strong>stripped-envelope supernova (Type {claimedtype})</strong>, consistent with core collapse "
            f"after loss of the outer hydrogen (and for Ic, helium) envelope. The specific progenitor channel for this "
            f"object is not uniquely determined by the spectral type alone."
        )
    elif c_lower and c_lower not in ("unclassified", "unknown", "—", "none", "at", "other", "candidate"):
        type_ans = (
            f"{name} is cataloged as a <strong>Type {claimedtype} transient</strong>. Mechanism-specific claims "
            f"(progenitor mass, nickel yield, remnant type) require more than this label and are not asserted here as "
            f"object-specific measurements."
        )
    else:
        # Unclassified / unknown. Asserting a physical mechanism here would state a
        # classification the data does not contain: "AT..." names are *transients*,
        # not confirmed supernovae, and the type may never be resolved. Say what is
        # known and stop, rather than narrating a core-collapse that may not have
        # happened.
        type_ans = (
            f"<strong>{name} has not been spectroscopically classified.</strong> It was reported as an astronomical transient, "
            f"which means an object was detected changing in brightness, but its nature is not yet established. "
            f"Classification requires a spectrum: the presence or absence of hydrogen lines separates Type II from Type I, "
            f"and Type Ia is identified by silicon absorption near 6150 Å combined with the absence of hydrogen. "
            f"Until such a spectrum is published, claims about the progenitor star or explosion mechanism would be speculation. "
            f"Check the sources below for follow-up spectroscopy."
        )
    faqs.append({
        "category": "Astrophysics & Progenitor",
        "question": f"What type of supernova is {name} and what kind of star exploded?",
        "answer": type_ans,
    })

    # 2. Pre-Explosion Evolutionary History — competing models, not object biography
    if "ia" in c_lower:
        pre_ans = (
            f"<strong>No unique progenitor history is established for {name}.</strong> "
            f"Type Ia spectral classification is consistent with a thermonuclear explosion of a carbon-oxygen white dwarf, "
            f"but it does not identify which binary pathway produced this event. Leading models include "
            f"single-degenerate accretion toward the Chandrasekhar mass, double-degenerate white-dwarf mergers, "
            f"and sub-Chandrasekhar helium-shell detonations. Distinguishing these requires population statistics, "
            f"early-time spectra, or remnant searches that are not established for this individual object. "
            f"Claims that this white dwarf accreted for millions of years, or that it approached 1.4 solar masses, "
            f"are general theory—not documented facts about {name}."
        )
    elif c_lower and c_lower not in ("unclassified", "unknown", "—", "none", "at", "other", "candidate"):
        pre_ans = (
            f"<strong>The specific progenitor of {name} has not been observed.</strong> "
            f"Events of this spectroscopic class are generally associated with massive-star core collapse after "
            f"successive nuclear burning stages (hydrogen → helium → carbon → neon → oxygen → silicon → iron). "
            f"Typical lifetimes of such progenitors are tens of millions of years, but that is a class expectation—"
            f"not a measured age or evolutionary track for this star. No pre-explosion imaging identification is "
            f"cited in the available record for {name}."
        )
    else:
        pre_ans = (
            f"The progenitor of {name} cannot be identified without a classification. Stellar evolutionary history depends entirely on the "
            f"explosion type: a Type Ia event would require a carbon-oxygen white dwarf in a binary system, "
            f"whereas a core-collapse event would require a massive star exhausting its fuel within tens of millions of years. "
            f"These are mutually exclusive histories that produce different spectra and light curves. No progenitor or precursor has been "
            f"reported for this transient in the available literature."
        )
    faqs.append({
        "category": "Astrophysics & Progenitor",
        "question": f"What was the progenitor star doing in the millions of years leading up to {name}?",
        "answer": pre_ans,
    })

    # =========================================================================
    # CATEGORY 2: COSMIC DISTANCE & LOOKBACK TIME
    # =========================================================================

    # 3. Cosmic Distance & Lookback Time
    # Luminosity distance ≠ light-travel distance; keep them separate.
    if redshift != "—" or lumdist != "—":
        lb = cosmo.get("lookback_myr")
        if lb is not None and era_context and era_context != "deep cosmic time":
            lookback_clause = (
                f" Under a flat ΛCDM cosmology (H₀≈70 km/s/Mpc, Ωₘ≈0.3), the corresponding "
                f"<strong>lookback time is ≈{lb:.0f} Myr</strong> — when the light set out "
                f"<strong>{era_context}</strong>. Luminosity distance is larger than the light-travel "
                f"distance because cosmic expansion stretches the path; the two must not be equated."
            )
        elif lb is not None:
            lookback_clause = (
                f" The cosmological lookback time at this redshift is ≈<strong>{lb:.0f} Myr</strong> "
                f"(flat ΛCDM); that elapsed travel time is not equal to the luminosity-distance figure in light-years."
            )
        else:
            lookback_clause = (
                f" A lookback time is not computed here without a usable redshift; "
                f"do not interpret the luminosity-distance light-year figure as travel time."
            )
        dist_ans = (
            f"{name} has a luminosity distance of approximately <strong>{dist_ly_str}</strong>"
            + (f" (redshift z = {redshift}, d_L = {lumdist})" if redshift != "—" else "")
            + f".{lookback_clause}"
        )
    else:
        # No redshift and no luminosity distance -> the distance is simply unknown.
        # "Millions of Light-Years" was a default string, not a measurement, and it
        # propagated into the lookback-time and Earth-safety answers too.
        dist_ans = (
            f"<strong>The distance to {name} has not been measured.</strong> No spectroscopic redshift or luminosity distance "
            f"is published for this transient, so neither its distance from Earth nor its lookback time can be stated. "
            f"A redshift requires a spectrum, and a photometric redshift requires multi-band imaging that has not been reported. "
            f"Without a distance, its intrinsic luminosity and total energy release are also undetermined. "
            f"Check the sources below for follow-up spectroscopy or host-galaxy identification."
        )
    faqs.append({
        "category": "Cosmic Distance & Time",
        "question": f"How far away is {name} from Earth and how old is the light reaching us?",
        "answer": dist_ans,
    })

    # 4. Redshift & Hubble Expansion
    if cosmo["recession_km_s"] is not None:
        z_val = cosmo["z"]
        rec_val = cosmo["recession_km_s"]
        red_ans = (
            f"{name} exhibits a measured spectroscopic redshift of <strong>z = {z_val:.4f}</strong>. "
            f"The cockpit reports a user-facing <strong>recession velocity</strong> of "
            f"<strong>{rec_val:,.1f} km/s</strong>, computed as the "
            f"<em>redshift Doppler-equivalent</em> "
            f"v = c·((1+z)²−1)/((1+z)²+1). "
            f"Cosmological redshift is not generally equivalent to special-relativistic motion through space; "
            f"this number is a convenient velocity label for z, not a measured peculiar velocity and "
            f"<strong>not</strong> supernova ejecta speed. "
            f"Bare c·z (≈{z_val * 299792.458:,.0f} km/s) is a different low-z approximation and is not mixed here."
        )
    else:
        red_ans = (
            f"<strong>No spectroscopic redshift has been measured for {name}.</strong> "
            f"Without a published z, its place in the Hubble flow, recession velocity, and lookback time cannot be stated. "
            f"A redshift requires a spectrum (or a well-calibrated photometric redshift from multi-band imaging). "
            f"Check the sources below for follow-up spectroscopy."
        )
    faqs.append({
        "category": "Cosmic Distance & Time",
        "question": f"What does the cosmological redshift of {name} tell us about the expansion of space?",
        "answer": red_ans,
    })

    # =========================================================================
    # CATEGORY 3: EXPLOSION ENERGETICS & BLAST KINEMATICS
    # =========================================================================

    # 5. Peak Brightness & Solar Equivalents
    _peak_confirmed = bool(lifecycle and lifecycle.get("peak_confirmed"))
    _single_epoch = bool(
        (lifecycle and lifecycle.get("magnitude_kind") == "observed_single_epoch")
        or (photo_info.get("count") == 1 and not _peak_confirmed)
    )
    if maxappmag != "—" and _single_epoch:
        bright_ans = (
            f"<strong>Observed (single-epoch)</strong> magnitude of {name} is <strong>{maxappmag}</strong>"
            + (f" on {maxdate}" if maxdate != "—" else "")
            + ". A single calibrated detection is not evidence of a peak; no rise, decline, or light curve can be established from one point."
            + (
                f" An absolute magnitude of <strong>{maxabsmag}</strong> can be quoted only if distance is independently known."
                if maxabsmag != "—"
                else ""
            )
        )
    elif maxappmag != "—":
        bright_ans = (
            f"At peak brightness, {name} achieved an apparent magnitude of <strong>{maxappmag}</strong>"
            + (f" around {maxdate}" if maxdate != "—" else "")
            + (f". Corrected for cosmic distance and foreground interstellar dust, its intrinsic absolute magnitude was <strong>{maxabsmag}</strong>" if maxabsmag != "—" else "")
            + (
                f". At this peak, the exploding star radiated with the incandescent brilliance of approximately <strong>{solar_lum} combined</strong>, "
                f"briefly outshining the cumulative starlight of entire dwarf galaxies!"
                if solar_lum
                else "."
            )
        )
    else:
        bright_ans = (
            f"<strong>The peak brightness of {name} is not recorded.</strong> No peak apparent magnitude and no calibrated "
            f"photometry are published for this transient, so neither its apparent brightness nor its intrinsic luminosity "
            f"can be stated. Any figure quoted here would be an estimate from a template rather than a measurement of this object. "
            f"Follow-up photometry would establish the light curve and the peak."
        )
    faqs.append({
        "category": "Explosion Energetics",
        "question": f"How bright did {name} become at its peak, and how many Suns does that equal?",
        "answer": bright_ans,
    })

    # 6. Total Energy Release & Neutrino Flash
    _unclass = c_lower in ("", "—", "none", "unknown", "unclassified", "at", "other", "candidate")
    _is_tde = "tde" in c_lower or "tidal" in c_lower
    _is_slsn = "slsn" in c_lower or "superluminous" in c_lower
    if _unclass:
        energy_ans = (
            f"<strong>The total energy released by {name} is unknown.</strong> "
            f"Energy budgets differ by orders of magnitude depending on mechanism: a thermonuclear Type Ia liberates "
            f"~10⁵¹ ergs mostly as kinetic energy, while a core-collapse event liberates ~10⁵³ ergs of which ~99% escapes "
            f"as neutrinos. Without a spectroscopic classification, neither figure applies to this transient."
        )
    elif _is_tde:
        energy_ans = (
            f"<strong>No object-specific energy budget is published for {name}.</strong> "
            f"Tidal disruption events are powered by accretion onto a supermassive black hole, not by the neutrino burst "
            f"or ⁵⁶Ni decay that dominate supernova energy discussions. Class-scale estimates must not be quoted as "
            f"measurements of this event."
        )
    elif "ia" in c_lower and "ii" not in c_lower:
        energy_ans = (
            f"Type Ia events are typically associated with a kinetic energy scale of order <strong>10⁵¹ ergs</strong>, "
            f"with little neutrino emission compared to core-collapse. That is a class expectation—"
            f"<strong>not a calorimetry measurement for {name}</strong>."
        )
    elif _is_slsn:
        energy_ans = (
            f"SLSN radiated energies can exceed ordinary supernovae by large factors, but the power source "
            f"(magnetar, CSM interaction, or other) is model-dependent. "
            f"<strong>No object-specific energy release is published for {name}</strong>."
        )
    else:
        energy_ans = (
            f"Core-collapse events of this broad class are often discussed with a ~10⁵³ erg gravitational binding "
            f"energy of which ~99% may escape as neutrinos—again a class scale, "
            f"<strong>not a measured budget for {name}</strong>."
        )
    faqs.append({
        "category": "Explosion Energetics",
        "question": f"How much total energy was released by {name}, and where did that energy go?",
        "answer": energy_ans,
    })

    # 7. Expansion Velocity & Blast Kinematics
    # Never reuse cosmological recession velocity as ejecta speed.
    v_km = vel_info.get("km_s")
    class_typ = vel_info.get("class_typical_kms")
    if v_km is None:
        typical_note = (
            f" Type {claimedtype} events typically show ejecta speeds of order "
            f"~{class_typ:,.0f} km/s near maximum, but that class scale is not a measurement of {name}."
            if class_typ
            else ""
        )
        vel_ans = (
            f"<strong>No ejecta velocity is measured for {name}.</strong> "
            f"Blast-wave speed is obtained from Doppler shifts of spectral absorption features "
            f"(e.g. Si II λ6355 for Type Ia), not from cosmological redshift. "
            f"Any recession velocity derived from z describes Hubble flow, not the explosion debris."
            f"{typical_note}"
        )
    else:
        v_pct = vel_info["pct_c"]
        vel_ans = (
            f"Spectroscopic line blueshifts imply an ejecta velocity of approximately "
            f"<strong>{v_km:,.0f} km/s</strong> (~{v_pct:.1f}% of c) for {name}. "
            f"This is distinct from cosmological recession velocity inferred from redshift."
        )
    faqs.append({
        "category": "Explosion Energetics",
        "question": f"How fast are the supernova ejecta and shockwave of {name} expanding through space?",
        "answer": vel_ans,
    })

    # =========================================================================
    # CATEGORY 4: RADIOACTIVE ENGINE & LIGHT CURVE MORPHOLOGY
    # =========================================================================

    # 8. Radioactive Decay Engine
    if _unclass:
        engine_ans = (
            f"<strong>The power source sustaining {name} cannot be identified without a classification.</strong> "
            f"Classified supernovae are typically powered after peak by the radioactive decay of ⁵⁶Ni → ⁵⁶Co → ⁵⁶Fe, "
            f"but nickel yields and whether a shock-breakout flash occurred depend on the explosion mechanism. "
            f"No spectrum is published for this transient, so no ⁵⁶Ni mass or decay-powered light-curve narrative applies."
        )
    elif _is_tde:
        engine_ans = (
            f"<strong>Radioactive ⁵⁶Ni decay is not the default power source for {name}.</strong> "
            f"As a tidal disruption event, the optical light curve is generally discussed in terms of accretion and "
            f"circularization physics, not the supernova ⁵⁶Ni → ⁵⁶Co → ⁵⁶Fe chain. "
            f"No object-specific nickel mass applies."
        )
    elif "ia" in c_lower and "ii" not in c_lower:
        engine_ans = (
            f"After peak, Type Ia light curves are generally powered by the radioactive chain "
            f"<strong>⁵⁶Ni → ⁵⁶Co → ⁵⁶Fe</strong> (half-lives ≈6.1 d and ≈77.2 d). "
            f"Typical Type Ia events synthesize of order half a solar mass of freshly made "
            f"<strong>Nickel-56</strong> (which later decays into Iron-56); that is a class expectation, "
            f"<strong>not a measured nickel mass for {name}</strong>. Estimating M(⁵⁶Ni) for this object "
            f"requires a bolometric light-curve fit that is not published here."
        )
    elif _is_slsn:
        engine_ans = (
            f"SLSN light curves may be powered by magnetar spin-down, CSM interaction, or (in some models) "
            f"large ⁵⁶Ni masses. <strong>Which engine powers {name} is not established here</strong>, and no "
            f"object-specific nickel mass is published."
        )
    else:
        engine_ans = (
            f"Classified core-collapse light curves are often sustained after peak by radioactive "
            f"<strong>⁵⁶Ni → ⁵⁶Co → ⁵⁶Fe</strong> decay, with typical nickel yields of order "
            f"0.05–0.15 solar masses—again a class scale, <strong>not a measured yield for {name}</strong>. "
            f"Shock-breakout heating may dominate the earliest optical flash; without a published "
            f"bolometric fit, neither nickel mass nor the dominant power source is established for this event."
        )
    faqs.append({
        "category": "Radioactive Engine",
        "question": f"What powers the prolonged glow of {name} weeks and months after detonation?",
        "answer": engine_ans,
    })

    # =========================================================================
    # CATEGORY 5: COSMIC NUCLEOSYNTHESIS & CHEMICAL YIELDS
    # =========================================================================

    # 9. Chemical Elements Synthesized
    if "ia" in c_lower and "ii" not in c_lower:
        elements_ans = (
            f"Type Ia explosions are efficient producers of <strong>iron-peak elements</strong> via thermonuclear burning. "
            f"Models typically yield substantial <strong>⁵⁶Ni</strong> (which decays to stable <strong>⁵⁶Fe</strong>), "
            f"plus silicon, sulfur, calcium, and related species—consistent with the Si II features used in classification. "
            f"<strong>No object-specific nucleosynthetic yield has been published for {name}</strong>; "
            f"asserting that this event synthesized half a solar mass of iron would overstate the evidence."
        )
    elif _is_tde:
        elements_ans = (
            f"<strong>{name} is a TDE, not a nucleosynthesis factory in the supernova sense.</strong> "
            f"Observed abundances reflect debris from the disrupted star and accretion-flow physics; "
            f"no supernova-style elemental yield is published for this object."
        )
    elif "ii" in c_lower or "ib" in c_lower or "ic" in c_lower or _is_slsn:
        elements_ans = (
            f"Events of {name}'s broad spectroscopic class are discussed in galactic chemical evolution as sources of "
            f"oxygen-group and intermediate-mass elements (and, for some channels, iron-peak material). "
            f"<strong>No measured elemental yields are published for {name}</strong>."
        )
    else:
        elements_ans = (
            f"<strong>The nucleosynthetic products of {name} are unknown because its type is unresolved.</strong> "
            f"Element yields depend directly on the explosion mechanism: a thermonuclear Type Ia produces mostly iron-peak elements "
            f"such as <sup>56</sup>Ni and <sup>56</sup>Fe, whereas a core-collapse event produces large quantities of oxygen, neon, "
            f"magnesium and silicon from successive burning shells. No spectrum has been published for this transient, so which of "
            f"these occurred is not established."
        )
    faqs.append({
        "category": "Nucleosynthesis & Elements",
        "question": f"What chemical elements did {name} create and disperse into the universe?",
        "answer": elements_ans,
    })

    # =========================================================================
    # CATEGORY 6: COSMIC REMNANT & STELLAR FATE
    # =========================================================================

    # 10. Stellar Remnant Fate
    if _unclass:
        remnant_ans = (
            f"<strong>Whether {name} left a remnant is unknown.</strong> "
            f"A thermonuclear Type Ia leaves no compact remnant (the white dwarf is fully disrupted), whereas a core-collapse event "
            f"leaves a neutron star or black hole depending on progenitor mass. Without a spectroscopic classification, "
            f"none of these outcomes can be asserted for this transient."
        )
    elif "ia" in c_lower:
        remnant_ans = (
            f"<strong>Nothing remains at the center.</strong> Because a Type Ia supernova involves the total thermonuclear disruption of the progenitor "
            f"white dwarf, the entire star was incinerated and flung into space. There is no central neutron star, pulsar, or black hole left behind. "
            f"The star's entire mass now exists as an expanding gaseous shell traveling through the host galaxy."
        )
    else:
        remnant_ans = (
            f"A core-collapse explosion associated with {name}'s class forges an ultra-dense compact stellar remnant at the center of the detonation. "
            f"If the progenitor had an initial mass under ~20 solar masses, it left behind a <strong>neutron star (pulsar)</strong>—packing the mass of our entire Sun "
            f"into a city-sized sphere barely 20 kilometers wide, spinning dozens or hundreds of times per second. If the progenitor exceeded ~25–30 solar masses, "
            f"gravity overcame neutron degeneracy pressure, creating a permanent <strong>stellar-mass black hole</strong>."
        )
    faqs.append({
        "category": "Cosmic Remnant",
        "question": f"Did {name} leave behind a black hole, a neutron star, or nothing at all?",
        "answer": remnant_ans,
    })

    # 11. Remnant Evolution Across Millennia
    rem_future_ans = (
        f"Supernova remnants in general evolve through free-expansion, Sedov–Taylor, and radiative phases over centuries to millennia, "
        f"sometimes becoming bright X-ray shells and occasionally compressing nearby molecular clouds. "
        f"<strong>These are standard remnant-evolution models, not forecasts measured for {name}</strong>. "
        f"Whether this site will trigger star formation, reach particular X-ray temperatures, or match Cassiopeia A depends on "
        f"local density and magnetic field—none of which are constrained by the data shown here."
    )
    faqs.append({
        "category": "Cosmic Remnant",
        "question": f"What will {name}'s explosion site look like in 1,000 to 10,000 years?",
        "answer": rem_future_ans,
    })

    # =========================================================================
    # CATEGORY 7: GALACTIC ENVIRONMENT & HOST COORDINATES
    # =========================================================================

    # 12. Host Galaxy & Galactic Offset
    if host_identified and host_offset_str != "—":
        host_ans = (
            f"{name} is associated with cataloged host <strong>{host_name}</strong> at an angular/physical offset of "
            f"<strong>{host_offset_str}</strong> from the reported galactic center. "
            f"That offset places the transient in the host's projected light distribution; it does not by itself "
            f"prove which stellar population produced the progenitor."
        )
    elif host_identified:
        host_ans = (
            f"{name} is cataloged with host galaxy <strong>{host_name}</strong>. "
            f"No secure nuclear offset is published in this record."
        )
    else:
        host_ans = (
            f"<strong>No host galaxy is identified for {name} in this catalog record.</strong> "
            f"A blank host field means the association is unresolved here—it does not establish that the host is "
            f"uncataloged, resolved in imaging, or securely linked by astrometry. "
            f"Possible states (unidentified, hostless candidate, imaging detection without a catalog name, "
            f"or a securely matched cataloged galaxy) require separate evidence that is not present in this field."
        )
    faqs.append({
        "category": "Galactic Environment",
        "question": f"In which galaxy did {name} explode, and where is it located relative to the galactic center?",
        "answer": host_ans,
    })

    # 13. Sky Coordinates & Constellation
    loc_ans = (
        f"In the celestial sphere, {name} is located at Right Ascension <strong>{ra_str}</strong> and Declination <strong>{dec_str}</strong>, "
        f"situated in the constellation <strong>{const_name} ({const_eng})</strong>. "
        + (f"Because its declination is {dec_str}, it is primarily placed in the Northern celestial hemisphere." if (dec_deg or 0) > 0 else f"Because its declination is {dec_str}, it is favorably placed for Southern Hemisphere observatories.")
    )
    faqs.append({
        "category": "Sky Coordinates",
        "question": f"Where is {name} located in the night sky and which constellation is it in?",
        "answer": loc_ans,
    })

    # 14. Milky Way Dust Extinction
    if ebv_val != "—":
        try:
            ebv_num = float(re.sub(r"[^\d.]", "", ebv_val))
            av_num = ebv_num * 3.1
            src_label = str(ebv_source) if ebv_source else "published extinction estimate"
            # Do not attribute analytical disk models as Schlafly & Finkbeiner maps.
            dust_ans = (
                f"Along this line of sight, the catalog records a Milky Way foreground color excess of "
                f"<strong>E(B−V) = {ebv_num:.4f} mag</strong> "
                f"(source: <em>{src_label}</em>), corresponding to roughly "
                f"<strong>A_V ≈ {av_num:.2f} mag</strong> for R_V = 3.1. "
                f"Band-specific corrections (e.g. A_r) differ from A_V and should be applied when available. "
                f"Map-based values (IRSA / Schlafly & Finkbeiner 2011) must not be claimed unless that map was actually queried."
            )
        except Exception:
            dust_ans = f"Milky Way foreground interstellar dust along this line of sight introduces an extinction of E(B-V) = {ebv_val}."
        faqs.append({
            "category": "Interstellar Dust",
            "question": f"How much Milky Way interstellar dust obscures our view of {name}?",
            "answer": dust_ans,
        })

    # =========================================================================
    # CATEGORY 8: OBSERVATIONAL ASTRONOMY & SPECTROSCOPY
    # =========================================================================

    # 15. Photometric Filter Passbands & Monitoring
    p_cnt = photo_info["count"]
    p_bnds = photo_info["bands"]
    p_tels = photo_info["telescopes"]
    p_days = photo_info["timespan_days"]
    if p_cnt >= 2:
        bnd_str = ", ".join(f"<code>{b}</code>" for b in p_bnds[:8]) if p_bnds else "optical filters"
        tel_str = ", ".join(p_tels[:4]) if p_tels else "global optical observatories"
        span_str = f" across a baseline of <strong>{p_days} days</strong>" if p_days else ""
        photo_ans = (
            f"{name} was tracked across <strong>{p_cnt} photometric observations</strong>{span_str} utilizing filter bands including {bnd_str}. "
            f"Data were captured by observatories and survey networks including {tel_str}. "
            f"Multi-color photometry tracks the temperature evolution of the fireball, verifying the rise time to peak and the rate of radioactive decline."
        )
    elif p_cnt == 1:
        bnd_str = ", ".join(f"<code>{b}</code>" for b in p_bnds[:8]) if p_bnds else "an optical filter"
        tel_str = ", ".join(p_tels[:4]) if p_tels else "the reporting survey"
        photo_ans = (
            f"{name} has <strong>1 calibrated photometric detection</strong> on record"
            + (f" in {bnd_str}" if p_bnds else "")
            + (f" from {tel_str}" if p_tels else "")
            + ". A single point is not a light curve: no rise, peak, or decline rate can be measured until additional epochs are published."
        )
    else:
        photo_ans = (
            f"<strong>No calibrated photometry is published for {name}.</strong> "
            f"Without multi-epoch flux measurements, neither a light curve nor a peak magnitude can be established. "
            f"Follow-up imaging from survey alert streams would be required to map its brightness evolution."
        )
    faqs.append({
        "category": "Astronomical Observations",
        "question": f"Across which photometric filter bands was {name} monitored?",
        "answer": photo_ans,
    })

    # 16. Spectroscopic Fingerprinting & Diagnostic Lines
    s_cnt = spec_info["count"]
    s_wmin = spec_info["w_min"]
    s_wmax = spec_info["w_max"]
    s_tels = spec_info["telescopes"]
    if s_cnt > 0:
        w_range_str = f" from {s_wmin} Å to {s_wmax} Å" if s_wmin and s_wmax else ""
        tel_spec_str = f" by facilities including {', '.join(s_tels[:3])}" if s_tels else ""
        spec_ans = (
            f"Astronomers obtained <strong>{s_cnt} spectroscopic epochs</strong> for {name}{w_range_str}{tel_spec_str}. "
            f"Optical spectroscopy provides the definitive physical fingerprint of the transient: P-Cygni line profiles reveal the expansion speed "
            f"of the ejecta, while characteristic absorption features (such as hydrogen Balmer lines Hα/Hβ in Type II, or Si II λ6355 in Type Ia) "
            f"identify the stellar composition and physical mechanism of the explosion."
        )
    else:
        spec_ans = (
            f"<strong>No spectrum has been published for {name}.</strong> "
            f"Without spectroscopy, its chemical composition, expansion velocity, and physical classification cannot be established. "
            f"Classification spectra from follow-up observatories would be required to identify diagnostic absorption and emission lines."
        )
    faqs.append({
        "category": "Astronomical Observations",
        "question": f"What did astronomical spectroscopy reveal about {name}'s chemical makeup?",
        "answer": spec_ans,
    })

    # 17. Discovery & Initial Detection
    disc_ans = (
        f"{name} was officially reported on <strong>{discoverdate}</strong> by <strong>{disc_who}</strong>. "
        f"Discoveries are typically flagged by high-cadence robotic survey telescopes (such as ATLAS, ZTF, Pan-STARRS, ASAS-SN, or Gaia) "
        f"and worldwide amateur astronomers scanning the night sky, followed by rapid spectroscopic classification by international observatories."
    )
    faqs.append({
        "category": "Discovery & History",
        "question": f"Who discovered {name} and how was it first detected?",
        "answer": disc_ans,
    })

    # 18. Scientific Literature & Archival Citations
    src_cnt = src_info["count"]
    src_names = src_info["names"]
    if src_cnt > 0:
        cites_str = ", ".join(src_names[:4])
        lit_ans = (
            f"{name} is documented across <strong>{src_cnt} scientific references and archival data sources</strong> in the Open Supernova Catalog. "
            f"These include discovery circulars and research datasets from {cites_str}. "
            f"All raw photometry and spectroscopy points are cross-indexed to their original bibliographic records for peer-reviewed verification."
        )
    else:
        lit_ans = (
            f"Data for {name} are compiled from international astronomical notices, the IAU Transient Name Server (TNS), "
            f"and peer-reviewed astrophysical journals."
        )
    faqs.append({
        "category": "Scientific Research",
        "question": f"How many scientific publications and observatories have contributed data to {name}?",
        "answer": lit_ans,
    })

    # 19. Survey Aliases & Cross-IDs
    if aliases:
        alias_str = ", ".join(f"<code>{a}</code>" for a in aliases[:10])
        alias_ans = (
            f"Throughout global alert streams and survey databases, {name} has also been designated as: {alias_str}. "
            f"These cross-matched identifiers allow astronomers to cross-reference observations across the Zwicky Transient Facility (ZTF), "
            f"the Asteroid Terrestrial-impact Last Alert System (ATLAS), Pan-STARRS, Gaia Photometric Science Alerts, and the IAU Transient Name Server (TNS)."
        )
        faqs.append({
            "category": "Cross-Identifications",
            "question": f"What other names and survey identifiers exist for {name}?",
            "answer": alias_ans,
        })

    # =========================================================================
    # CATEGORY 9: COSMOLOGY & MULTI-MESSENGER ASTRONOMY
    # =========================================================================

    # 20. Cosmological Distance Ladder & Standard Candles
    if "ia" in c_lower:
        cosmo_ans = (
            f"Because {name} is a Type Ia supernova, it serves as an indispensable rung on the <strong>Cosmic Distance Ladder</strong>. "
            f"Astrophysicists utilize the Phillips relation—a tight empirical correlation between peak absolute magnitude and light curve decline rate (Δm₁₅)—to "
            f"standardize its luminosity. By comparing this calibrated intrinsic brightness with observed apparent magnitude, researchers calculate precise geometric "
            f"distances across the universe, providing key empirical tests of the Hubble constant (H₀) and dark energy."
        )
    elif "ii" in c_lower or "ib" in c_lower or "ic" in c_lower:
        cosmo_ans = (
            f"As a core-collapse supernova, {name} provides independent cosmological distance calibrations via the <strong>Expanding Photosphere Method (EPM)</strong> "
            f"and the Standard Candle Method for Type II supernovae (SCM-II). By correlating the physical expansion speed of the photosphere (measured via spectroscopic "
            f"Doppler shifts) with its photometric color temperature, astronomers determine direct geometric distances independent of secondary distance ladders."
        )
    else:
        cosmo_ans = (
            f"{name} cannot currently be used for cosmological distance work because its classification is unresolved. "
            f"The distance ladder relies on type-specific techniques: Type Ia supernovae use the Phillips relation between peak absolute "
            f"magnitude and decline rate, while Type II events use the Expanding Photosphere Method or SCM-II. An unclassified transient "
            f"fits neither, so no Hubble-constant constraint can be derived from it until a spectrum establishes its type."
        )
    faqs.append({
        "category": "Cosmology & Distance Ladder",
        "question": f"How does {name} contribute to measuring the Hubble Constant and the scale of the cosmos?",
        "answer": cosmo_ans,
    })

    # 21. Multi-Messenger Astronomy (Neutrinos & Gravitational Waves)
    if "ia" in c_lower:
        mm_ans = (
            f"For thermonuclear explosions like {name}, gravitational wave and neutrino emissions are negligible compared to core-collapse events. "
            f"However, multi-messenger radio and X-ray observations are crucial: detecting synchrotron radio emission would reveal circumstellar gas "
            f"shed by a companion star, helping settle the century-old debate between single-degenerate and double-degenerate white dwarf progenitor channels."
        )
    elif "ii" in c_lower or "ib" in c_lower or "ic" in c_lower:
        mm_ans = (
            f"Core-collapse supernovae like {name} are premier targets for multi-messenger astrophysics! During the collapse of the iron core, an intense "
            f"burst of 10⁵⁸ neutrinos escaped into space hours before the shock broke out through the stellar surface (as famously seen in SN 1987A). "
            f"Furthermore, violent core asymmetries and non-axisymmetric core bounce can emit high-frequency gravitational waves detectable by advanced "
            f"interferometers (LIGO, Virgo, KAGRA) for events within the Milky Way and Local Group."
        )
    else:
        mm_ans = (
            f"No neutrino or gravitational-wave counterpart has been reported for {name}, and none is expected to be identifiable "
            f"without a classification. The multi-messenger signature differs sharply by type: core-collapse events emit a neutrino "
            f"burst at shock breakout (detected once, for SN 1987A), while thermonuclear Type Ia events produce negligible neutrinos and "
            f"gravitational waves. Searching for a counterpart before knowing which mechanism applies would be unfocused."
        )
    faqs.append({
        "category": "Multi-Messenger Astronomy",
        "question": f"Could gravitational waves or neutrinos from {name} be detected on Earth?",
        "answer": mm_ans,
    })

    # 22. Historical Supernova Comparison
    _placeholder_dist = str(dist_ly_str or "").strip().lower() in {
        "millions of light-years", "—", "", "none", "unknown",
    }
    _known_dist = (redshift != "—" or lumdist != "—") and not _placeholder_dist
    if _unclass:
        _dist_clause = (
            f"the distance to {name} is not established for a historical comparison "
            f"(unclassified; "
            + (f"redshift z = {redshift} is published but no luminosity distance is derived). "
               if redshift != "—" else
               "no redshift or luminosity distance is published). ")
        )
    elif _known_dist:
        _dist_clause = f"{name} occurred at a distance of <strong>{dist_ly_str}</strong>. "
    else:
        _dist_clause = f"the distance to {name} is not measured, so no such comparison can be drawn. "
    hist_ans = (
        f"Compared to historical landmarks like <strong>SN 1987A</strong> in the Large Magellanic Cloud (168,000 light-years away, naked-eye peak m = 2.9) "
        f"or the <strong>Crab Supernova of 1054</strong> (6,500 light-years away), "
        + _dist_clause
        + f"While historical naked-eye supernovae occurred within our Milky Way or its immediate satellites, modern discoveries like {name} allow astrophysicists "
        f"to probe diverse galactic environments, metallicities, and stellar populations across the broader universe."
    )
    faqs.append({
        "category": "Historical Comparison",
        "question": f"How does {name} compare to famous historical supernovae like SN 1987A or the Crab Supernova?",
        "answer": hist_ans,
    })

    # =========================================================================
    # CATEGORY 10: BACKYARD OBSERVATION & PLANETARY SAFETY
    # =========================================================================

    # 23. Tonight's Observation & Telescope Guidance
    if lifecycle:
        phase = lifecycle.get("phase", "fading")
        days_since = lifecycle.get("days_since", 0)
        m_current = lifecycle.get("m_current")
        time_str = lifecycle.get("time_str", "")

        # A missing magnitude must never be rendered as a number. The old default of
        # 20.0 meant an unmeasured transient was quoted to one decimal place.
        if m_current is None:
            obs_ans = (
                f"<strong>Unknown \u2014 no measured brightness.</strong> {name} was discovered {days_since} days ago ({discoverdate}), "
                f"but no calibrated photometry is published for it, so its current apparent magnitude cannot be stated. "
                f"Without a magnitude there is no basis for a telescope-aperture recommendation. "
                f"Use the coordinates and airmass chart above to plan a follow-up observation and report what you measure."
            )
        elif phase == "extinguished":
            obs_ans = (
                f"{name} exploded <strong>{time_str}</strong> ({discoverdate}). Optical transient emission has completely faded along its radioactive "
                f"decay curve. Today, pointing a telescope at these coordinates reveals the expanding remnant nebula"
                f"{f' or {host_name}' if host_name else ''}; "
                f"the original optical transient is no longer detectable with amateur backyard equipment."
            )
        elif phase in ("active", "peak", "recent_unconfirmed"):
            _n = lifecycle.get("measured_points")
            _trend_note = (
                "The light curve shows more than one detection, so an ongoing outburst is supported by the data."
                if phase == "active"
                else "Only one detection is on record, so its brightness trend is not established."
            )
            obs_ans = (
                f"Discovered <strong>{days_since} days ago</strong> ({discoverdate}), {name} has a <strong>measured</strong> apparent magnitude "
                f"of <strong>m \u2248 {m_current:.1f}</strong>. {_trend_note} "
                f"Backyard astronomers with appropriate telescope aperture can attempt imaging under dark skies."
            )
        else:
            obs_ans = (
                f"Discovered <strong>{days_since} days ago</strong> ({discoverdate}), {name} has passed peak maximum and is fading along its radioactive "
                f"Co-56 decay tail at an estimated apparent magnitude of <strong>m \u2248 {m_current:.1f}</strong>. "
                f"It is accessible with sensitive amateur astrophotography rigs or larger research telescopes, depending on local sky darkness."
            )
    else:
        obs_ans = (
            f"Visibility depends on telescope aperture and time elapsed since discovery ({discoverdate}). "
            f"Check the interactive light curve and tonight's airmass visibility chart above to plan observations."
        )
    faqs.append({
        "category": "Backyard Observation",
        "question": f"Can I see {name} tonight with a backyard telescope or binoculars?",
        "answer": obs_ans,
    })

    # 24. Earth Safety & Planetary Impact
    if redshift != "—" or lumdist != "—":
        earth_ans = (
            f"<strong>No, Earth is in zero danger.</strong> Supernovae are violent events emitting powerful gamma rays, X-rays, and cosmic rays; "
            f"however, the astrophysical 'lethal kill zone' for our planet's protective ozone layer is estimated at 50 to 100 light-years. "
            f"At a distance of <strong>{dist_ly_str}</strong>, the inverse-square law dilutes the radiation by quintillions of times, making "
            f"{name} completely harmless to our biosphere and purely a fascinating spectacle for human exploration."
        )
    else:
        earth_ans = (
            f"<strong>Earth is in no danger from {name}.</strong> The astrophysical 'lethal kill zone' for a supernova to damage our ozone layer "
            f"is roughly 50 to 100 light-years. This transient is far outside the solar neighbourhood: it was discovered by a wide-field survey "
            f"at a magnitude only reachable for an extragalactic object, and any transient in our own galaxy within that radius would have appeared "
            f"far brighter than the ~18th magnitude reported here. Its exact distance is unmeasured, but the detection brightness alone rules out "
            f"any nearby threat."
        )
    faqs.append({
        "category": "Planetary Safety",
        "question": f"Does the radiation or shockwave from {name} pose any threat to Earth?",
        "answer": earth_ans,
    })

    return faqs


def build_faq_html(faqs: List[Dict[str, str]], name: str) -> str:
    """Render the master FAQ accordion component with instant category filtering, live search, and expand/collapse controls."""
    cat_counts: Dict[str, int] = {}
    for f in faqs:
        c = f.get("category", "General")
        cat_counts[c] = cat_counts.get(c, 0) + 1

    pills = [f'<button type="button" class="faq-filter-pill active" onclick="filterFaqCat(this, \'all\')">All <span class="pill-cnt">{len(faqs)}</span></button>']
    for cat, cnt in cat_counts.items():
        safe_c = re.sub(r"[^a-zA-Z0-9]", "-", cat).lower()
        pills.append(f'<button type="button" class="faq-filter-pill" onclick="filterFaqCat(this, \'{safe_c}\')">{cat} <span class="pill-cnt">{cnt}</span></button>')

    pills_html = "".join(pills)

    item_blocks = []
    for i, f in enumerate(faqs):
        cat = f.get("category", "General")
        safe_c = re.sub(r"[^a-zA-Z0-9]", "-", cat).lower()
        q = f.get("question", "")
        a = f.get("answer", "")
        clean_search = re.sub(r"<[^>]+>", " ", f"{q} {a} {cat}").lower().replace('"', "")
        item_blocks.append(f"""
        <details class="story-faq-item" data-cat="{safe_c}" data-search="{clean_search}">
          <summary>
            <span class="story-faq-q">{q}</span>
            <span class="story-faq-badge">{cat}</span>
          </summary>
          <div class="story-faq-body">{a}</div>
        </details>
        """)

    html = f"""
    <div class="dossier-card" id="faq-section" style="margin-top:2.5rem;border-color:rgba(56,189,248,0.25);">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:0.75rem;margin-bottom:1rem;border-bottom:1px solid var(--border);padding-bottom:0.85rem;">
        <div>
          <h3 style="margin:0 0 0.25rem 0;display:flex;align-items:center;gap:8px;font-size:1.3rem;color:#f1f5f9;">
            <span style="color:#38bdf8;">❓</span> Frequently Asked Questions About {name}
          </h3>
          <div style="font-size:0.82rem;color:var(--text-muted);">
            Scientific &amp; observational Q&amp;As indexed from astronomical databases &amp; the Open Supernova Catalog
          </div>
        </div>
        <div class="faq-expand-btns">
          <button type="button" class="faq-action-btn" onclick="toggleFaqs(true)" title="Expand all visible questions">Expand All</button>
          <button type="button" class="faq-action-btn" onclick="toggleFaqs(false)" title="Collapse all questions">Collapse All</button>
        </div>
      </div>

      <!-- FAQ Search & Filter Toolbar -->
      <div class="faq-toolbar">
        <div class="faq-search-row">
          <div class="faq-search-box">
            <span style="color:#94a3b8;font-size:0.9rem;">🔍</span>
            <input type="text" id="faq-search-input" oninput="filterFaqQuery(this.value)" placeholder="Search {len(faqs)} questions &amp; answers (e.g. 'black hole', 'redshift', 'telescope', 'light curve')..." aria-label="Search FAQs" />
            <span id="faq-match-count" class="faq-match-badge">{len(faqs)} of {len(faqs)}</span>
          </div>
        </div>
        <div class="faq-pills-scroll">
          {pills_html}
        </div>
      </div>

      <div class="story-faq-accordion" id="story-faq-accordion">
        {"".join(item_blocks)}
      </div>

      <div id="faq-empty-state" style="display:none;padding:2rem;text-align:center;background:rgba(255,255,255,0.02);border:1px dashed var(--border);border-radius:8px;margin-top:1rem;">
        <div style="font-size:1.5rem;margin-bottom:0.5rem;">🔍</div>
        <div style="font-weight:600;color:#f1f5f9;margin-bottom:0.25rem;">No matching questions found</div>
        <div style="font-size:0.85rem;color:var(--text-muted);margin-bottom:1rem;">Try different keywords or clear your search query.</div>
        <button type="button" class="faq-action-btn" onclick="clearFaqSearch()">Reset FAQ Filters</button>
      </div>

      <div style="margin-top:1.5rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem;border-top:1px solid rgba(255,255,255,0.06);padding-top:1rem;">
        <span style="font-size:0.8rem;color:var(--text-muted);">
          Data sourced from IAU TNS, ALeRCE, WISeREP, and the Open Supernova Catalog.
        </span>
        <a href="/faq" style="font-size:0.85rem;color:var(--accent);text-decoration:none;font-weight:600;">View All General Astrophysics FAQs &rarr;</a>
      </div>
    </div>"""
    return html


def build_faq_jsonld(faqs: List[Dict[str, str]]) -> str:
    """Render the complete Schema.org FAQPage JSON-LD snippet."""
    entities = []
    for f in faqs:
        q_raw = f.get("question", "")
        a_raw = f.get("answer", "")
        # Clean HTML tags from answers for schema compliance
        clean_q = re.sub(r"<[^>]+>", "", q_raw).replace('"', '\\"').replace("\n", " ").strip()
        clean_a = re.sub(r"<[^>]+>", "", a_raw).replace('"', '\\"').replace("\n", " ").strip()
        entities.append(f"""      {{
        "@type": "Question",
        "name": "{clean_q}",
        "acceptedAnswer": {{
          "@type": "Answer",
          "text": "{clean_a}"
        }}
      }}""")

    entities_joined = ",\n".join(entities)
    jsonld = f"""  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "FAQPage",
    "mainEntity": [
{entities_joined}
    ]
  }}
  </script>"""
    return jsonld


def generate_story_article_html(
    name: str,
    meta: Dict[str, Any],
    claimedtype: str,
    discoverdate: str,
    discoverer: str,
    maxappmag: str,
    maxdate: str,
    maxabsmag: str,
    lumdist: str,
    redshift: str,
    host: str,
    host_offset_str: str,
    ra_str: str,
    dec_str: str,
    dist_ly_str: str,
    lifecycle: Optional[Dict[str, Any]] = None,
    ra_deg: Optional[float] = None,
    dec_deg: Optional[float] = None,
) -> str:
    """Synthesize a multi-chapter, long-form editorial feature article for Story Mode."""
    cosmo = analyze_cosmology(redshift, lumdist)
    photo_info = analyze_photometry(meta)
    spec_info = analyze_spectra(meta)
    vel_info = analyze_velocity(meta, claimedtype)
    const_name, const_eng = identify_constellation(ra_deg, dec_deg)
    era_context = get_lookback_geological_era(
        cosmo.get("lookback_myr") if cosmo.get("lookback_myr") is not None else None
    )
    solar_lum = calculate_solar_luminosities(maxabsmag)

    c_low = claimedtype.lower()
    is_ia = "ia" in c_low
    host_identified = host not in ("—", "", "none", "None", None)
    host_name = host if host_identified else None
    host_phrase = f"<strong>{host_name}</strong>" if host_name else "an unidentified host environment"
    disc_who = discoverer if discoverer != "—" else "an automated sky survey"

    # Progenitor narrative — models, not object biography
    _story_unclass = c_low in {"", "—", "none", "unknown", "unclassified", "at", "other", "candidate"}
    if is_ia:
        progenitor_title = "A Type Ia Thermonuclear Explosion"
        progenitor_p1 = (
            f"<strong>{name}</strong> is spectroscopically classified as Type Ia, consistent with a thermonuclear "
            f"white-dwarf explosion in {host_phrase}. Competing progenitor channels (single-degenerate accretion, "
            f"double-degenerate merger, sub-Chandrasekhar detonations) remain open; an individual accretion history "
            f"toward the Chandrasekhar mass is <em>not</em> established for this event."
        )
    elif _story_unclass:
        progenitor_title = "An Unclassified Astronomical Transient"
        progenitor_p1 = (
            f"<strong>{name}</strong> was reported as a changing source"
            f"{f' associated with {host_phrase}' if host_name else ''}, but it has not been "
            f"spectroscopically classified. Without a spectrum, the progenitor cannot be identified: a thermonuclear white-dwarf detonation and "
            f"a core-collapse of a massive star are mutually exclusive histories that produce different spectra and light curves. "
            f"No progenitor, explosion mechanism, or remnant outcome is established for this object."
        )
    else:
        progenitor_title = "A Core-Collapse Class Transient"
        progenitor_p1 = (
            f"<strong>{name}</strong> is classified in a core-collapse spectroscopic family. Events of this class are generally "
            f"linked to the death of a massive star after successive nuclear burning stages, but "
            f"<strong>no unique progenitor mass, lifetime, or pre-explosion identification is established for this object</strong>. "
            f"The narrative of onion-shell fusion ending in iron-core collapse describes the class model, not a measured biography of {name}."
        )

    # Telescope guidance
    story_guidance_html = lifecycle.get("story_guidance_html", "") if lifecycle else ""

    v_km = vel_info["km_s"]
    v_pct = vel_info["pct_c"]
    p_cnt = photo_info["count"]
    s_cnt = spec_info["count"]
    bnds_str = ", ".join(f"<code>{b}</code>" for b in photo_info["bands"][:6]) if photo_info["bands"] else "optical bands"

    article_html = f"""
    <div class="narrative">
      <!-- Chapter 1: The Cataclysm -->
      <div class="article-chapter" id="chapter-1">
        <div class="article-chapter-num">CHAPTER I</div>
        <h2>{progenitor_title}</h2>
        <p class="article-lead">
          On {discoverdate}, astronomers scanning the heavens flagged a sudden, violent pinpoint of light that had flared into visibility.
          Designated <strong>{name}</strong>,
          {"it is an unclassified astronomical transient whose physical nature is not yet established." if _story_unclass else f"it represents a catastrophic stellar explosion classified as a <strong>Type {claimedtype}</strong> supernova."}
        </p>
        <p>{progenitor_p1}</p>

        <div class="article-callout" style="border-left:4px solid #38bdf8;background:rgba(56,189,248,0.06);padding:1rem 1.25rem;border-radius:6px;margin:1.25rem 0;">
          <div style="font-weight:700;color:#38bdf8;font-size:0.92rem;margin-bottom:0.35rem;">Astrophysical Mechanism Summary</div>
          <div style="font-size:0.88rem;color:#cbd5e1;line-height:1.5;">
            <strong>Type:</strong> {("Unclassified (no spectrum)" if _story_unclass else f"Type {claimedtype}")} &bull; <strong>Progenitor:</strong> {"Unknown" if _story_unclass else ("Carbon-Oxygen White Dwarf (Binary System)" if is_ia else "Massive Red/Stripped Supergiant Star")} &bull; <strong>Velocity:</strong> {"Not measured" if v_km is None else f"~{v_km:,.0f} km/s (~{v_pct:.1f}% c)"}
          </div>
        </div>
      </div>

      <!-- Chapter 2: Deep Time & Lookback -->
      <div class="article-chapter" id="chapter-2">
        <div class="article-chapter-num">CHAPTER II</div>
        <h2>A Message Across Deep Cosmic Time</h2>
        <p>
          {name} has a luminosity distance of approximately <strong>{dist_ly_str}</strong>
          {f" (redshift <code>z = {redshift}</code>)" if redshift != "—" else ""}.
          {"That figure is <em>not</em> the light-travel time: under flat ΛCDM the lookback time is ≈"
           + f"<strong>{cosmo.get('lookback_myr'):.0f} Myr</strong>, when the light set out <strong>{era_context}</strong>."
           if cosmo.get("lookback_myr") is not None and era_context and era_context != "deep cosmic time"
           else (
             f"The cosmological lookback time is ≈<strong>{cosmo.get('lookback_myr'):.0f} Myr</strong>."
             if cosmo.get("lookback_myr") is not None
             else "Lookback time is unavailable without a usable redshift; do not equate luminosity distance with travel time."
           )}
        </p>
        <p>
          Luminosity distance incorporates cosmic expansion and exceeds the light-travel distance. The two quantities must be reported separately.
        </p>
      </div>

      <!-- Chapter 3: Peak Solar Radiance & Energetics -->
      <div class="article-chapter" id="chapter-3">
        <div class="article-chapter-num">CHAPTER III</div>
        <h2>{"Brightness Record" if (solar_lum is None or maxappmag == "—" or _story_unclass) else f"Incandescence of {solar_lum}"}</h2>
        <p>
          {"No calibrated peak magnitude is published for " + name + ", so neither its apparent brightness nor an equivalent solar luminosity can be stated."
            if maxappmag == "—"
            else (
              f"An <strong>observed</strong> magnitude of <strong>{maxappmag}</strong> is on record"
              + (f" around {maxdate}" if maxdate != "—" else "")
              + (f", with absolute magnitude <strong>{maxabsmag}</strong>" if maxabsmag != "—" else "")
              + ". A single detection is not evidence of a peak."
              if (lifecycle and lifecycle.get("magnitude_kind") == "observed_single_epoch")
              else (
                f"At the height of the outburst"
                + (f" around {maxdate}" if maxdate != "—" else "")
                + f", {name} surged to a peak apparent magnitude of <strong>{maxappmag}</strong>"
                + (f" and an intrinsic absolute magnitude of <strong>{maxabsmag}</strong>" if maxabsmag != "—" else "")
                + (
                  f". At that instant, this single dying star radiated with the collective power of approximately <strong>{solar_lum} combined</strong>, outshining whole dwarf galaxies."
                  if solar_lum else "."
                )
              )
            )}
        </p>
        <p>
          {"The total energy release is unknown without a spectroscopic classification."
            if _story_unclass
            else (
              "The total energy released by the cataclysm was on the order of <strong>10⁵¹ to 10⁵³ ergs</strong>. "
              + ("Virtually all of this was deposited into the kinetic shockwave and radioactive nucleosynthesis." if is_ia else "Over 99% of this energy was emitted within the first 10 seconds as a dense burst of trillions of neutrinos, with only 1% driving the visible blast wave.")
            )}
        </p>
      </div>

      <!-- Chapter 4: The Radioactive Engine -->
      <div class="article-chapter" id="chapter-4">
        <div class="article-chapter-num">CHAPTER IV</div>
        <h2>The Radioactive Furnace: Why Supernovae Glow for Months</h2>
        <p>
          {"Without a classification, the power source of " + name + " cannot be identified; radioactive ⁵⁶Ni decay powers many supernovae but is not established for this transient."
            if _story_unclass
            else "After peak, many supernovae are powered by the radioactive chain <strong>⁵⁶Ni → ⁵⁶Co → ⁵⁶Fe</strong>. That is the standard model for Type "
                 + claimedtype + " light curves; an object-specific nickel mass for " + name + " is not published here."}
        </p>
        <p>
          Nickel-56 decays to Cobalt-56 (half-life ≈6.1 days), then to stable Iron-56 (half-life ≈77.2 days), heating the ejecta from within.
          Typical class yields must not be quoted as measured values for this event.
        </p>
      </div>

      <!-- Chapter 5: Nucleosynthesis & Stardust -->
      <div class="article-chapter" id="chapter-5">
        <div class="article-chapter-num">CHAPTER V</div>
        <h2>Cosmic Kiln: Seeding the Elements of Life</h2>
        <p>
          Supernovae enrich galaxies with heavy elements. Events of {name}'s class are associated with
          {"iron-peak and intermediate-mass products (Ni/Fe, Si, S, Ca)" if is_ia else "oxygen-group and intermediate-mass products (O, C, Ne, Mg, Si)"}
          in galactic chemical-evolution models.
          <strong>No measured elemental yields are published for {name}</strong>.
        </p>
        <p>
          As Carl Sagan observed, <em>"We are made of star-stuff"</em> — a statement about nucleosynthesis in general, not a claim that atoms from this specific remnant are identified in the Solar System.
        </p>
      </div>

      <!-- Chapter 6: Galactic Setting & Coordinates -->
      <div class="article-chapter" id="chapter-6">
        <div class="article-chapter-num">CHAPTER VI</div>
        <h2>Galactic Setting in {const_name}</h2>
        <p>
          {f"{name} is associated with cataloged host {host_phrase}"
            if host_name
            else f"<strong>No host galaxy is identified</strong> for {name} in this catalog record"}
          {f", at an offset of <strong>{host_offset_str}</strong> from the reported galactic center" if (host_name and host_offset_str != "—") else ""}.
          In our terrestrial sky, it resides in the constellation <strong>{const_name} ({const_eng})</strong> at Right Ascension <code>{ra_str}</code>
          and Declination <code>{dec_str}</code>.
        </p>
      </div>

      <!-- Chapter 7: The Observational Campaign -->
      <div class="article-chapter" id="chapter-7">
        <div class="article-chapter-num">CHAPTER VII</div>
        <h2>The Scientific Surveillance Campaign</h2>
        <p>
          Following its discovery by {disc_who}, observatories worldwide swung their lenses toward {name}.
          In the Open Supernova Catalog, {name} is documented across <strong>{p_cnt} photometric measurements</strong>
          {f"in passbands such as {bnds_str}" if photo_info["bands"] else ""} and <strong>{s_cnt} spectroscopic epochs</strong>.
          These multi-wavelength observations allow astrophysicists to model the expanding photosphere, measure shock velocities, and probe circumstellar interactions.
        </p>
      </div>

      <!-- Chapter 8: Tonight's Stargazer Guide -->
      <div class="article-chapter" id="chapter-8">
        <div class="article-chapter-num">CHAPTER VIII</div>
        <h2>Stargazer's Field Guide: Can You See It Tonight?</h2>
        {story_guidance_html}
        <p style="font-size:0.92rem;color:var(--text-muted);margin-top:1rem;">
          <strong>Planetary Safety Note:</strong> Even though {name} was a titanic explosion, our planet sits safely outside the lethal 50–100 light-year kill zone.
          At a distance of {dist_ly_str}, the blast poses zero physical hazard to Earth's biosphere.
        </p>
      </div>
    </div>"""
    return article_html


def build_article_jsonld(
    name: str,
    claimedtype: str,
    host: str,
    discoverdate: str,
    dist_ly_str: str,
    maxappmag: str,
    schema_type: str = "Article",
    ra_deg: Optional[float] = None,
    dec_deg: Optional[float] = None,
) -> str:
    """Build rich Schema.org Article / NewsArticle structured data."""
    const_name, const_eng = identify_constellation(ra_deg, dec_deg)
    headline = f"{name}: Complete Astrophysical Dossier & Story of a Cosmic Supernova"
    description = (
        f"Detailed astrophysical dossier for supernova {name} (Type {claimedtype}) in {host if host != '—' else 'deep space'}, "
        f"located {dist_ly_str} away. Covers discovery, peak magnitude {maxappmag}, nucleosynthesis, and telescope visibility."
    )

    clean_headline = headline.replace('"', '\\"')
    clean_desc = description.replace('"', '\\"')
    encoded_name = urllib.parse.quote(name)

    about_items = [
        f"""      {{
        "@type": "AstronomicalObject",
        "name": "{name}",
        "description": "Type {claimedtype} supernova transient"
      }}"""
    ]
    if host != "—":
        about_items.append(f"""      {{
        "@type": "AstronomicalObject",
        "name": "{host}",
        "description": "Host galaxy of supernova {name}"
      }}""")

    about_json = ",\n".join(about_items)

    sections = [
        "Astrophysics & Progenitor Physics",
        "Cosmic Distance & Lookback Time",
        "Explosion Energetics & Radiance",
        "The Radioactive Decay Engine",
        "Cosmic Nucleosynthesis & Elements",
        "Galactic Setting & Coordinates",
        "Astronomical Surveillance Campaign",
        "Backyard Stargazer Guide",
    ]
    sections_json = json.dumps(sections)
    keywords = ["supernova", claimedtype, "astrophysics", "light curve", "open supernova catalog", const_name]
    if host != "—":
        keywords.append(host)
    keywords_json = json.dumps(keywords)

    jsonld = f"""  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "{schema_type}",
    "headline": "{clean_headline}",
    "description": "{clean_desc}",
    "url": "https://sne.space/sne/{encoded_name}/story",
    "datePublished": "{discoverdate if discoverdate != '—' else '2023-01-01'}",
    "articleSection": {sections_json},
    "keywords": {keywords_json},
    "author": {{
      "@type": "Organization",
      "name": "Open Supernova Catalog",
      "url": "https://sne.space"
    }},
    "publisher": {{
      "@type": "Organization",
      "name": "Open Supernova Catalog",
      "url": "https://sne.space"
    }},
    "about": [
{about_json}
    ]
  }}
  </script>"""
    return jsonld
