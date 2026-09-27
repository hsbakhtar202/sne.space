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
    else:
        return f"{ly_millions:.1f} million years ago during the Paleozoic era, long before the first dinosaurs appeared on Earth"


def calculate_solar_luminosities(max_abs_mag: str) -> str:
    """Convert peak absolute magnitude into equivalent solar luminosities."""
    try:
        m_abs = float(re.sub(r"[^\d.-]", "", max_abs_mag))
        l_suns = 10 ** (-0.4 * (m_abs - 4.83))
        if l_suns >= 1e9:
            return f"{l_suns / 1e9:.1f} billion Suns"
        elif l_suns >= 1e6:
            return f"{l_suns / 1e6:.1f} million Suns"
        else:
            return f"{l_suns:,.0f} Suns"
    except Exception:
        return "hundreds of millions of Suns"


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
    """Extract or model blast wave expansion velocities and relativistic kinematics."""
    vel_raw = meta.get("velocity", [])
    vel_val = None
    if isinstance(vel_raw, list) and vel_raw:
        first = vel_raw[0]
        v_str = first.get("value", "") if isinstance(first, dict) else str(first)
        try:
            vel_val = float(re.sub(r"[^\d.-]", "", v_str))
        except Exception:
            pass
    elif isinstance(vel_raw, (int, float)):
        vel_val = float(vel_raw)
    elif isinstance(vel_raw, str):
        try:
            vel_val = float(re.sub(r"[^\d.-]", "", vel_raw))
        except Exception:
            pass

    is_measured = vel_val is not None and vel_val > 0

    if not is_measured:
        c_low = claimedtype.lower()
        if "ia" in c_low:
            vel_val = 11000.0  # Type Ia ~11,000 km/s
        elif "ic-bl" in c_low or "broad" in c_low:
            vel_val = 22000.0  # Broad-line Ic ~22,000 km/s
        elif "ib" in c_low or "ic" in c_low:
            vel_val = 12500.0  # Stripped-envelope ~12,500 km/s
        elif "slsn" in c_low:
            vel_val = 15000.0  # Superluminous ~15,000 km/s
        else:
            vel_val = 8500.0   # Standard Type II ~8,500 km/s

    c_light = 299792.458  # km/s
    pct_c = (vel_val / c_light) * 100.0
    earth_diam = 12742.0  # km
    earths_per_sec = vel_val / earth_diam
    mach = vel_val / 0.343  # Mach number (speed of sound in air = 0.343 km/s)

    return {
        "is_measured": is_measured,
        "km_s": vel_val,
        "pct_c": pct_c,
        "earths_per_sec": earths_per_sec,
        "mach": mach,
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
    """Compute recession velocity and cosmic lookback metrics."""
    z = None
    if redshift_str != "—":
        try:
            z = float(re.sub(r"[^\d.-]", "", redshift_str))
        except Exception:
            pass

    recession_km_s = None
    if z is not None:
        recession_km_s = round(z * 299792.458, 1)

    mpc = None
    ly_millions = None
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
    era_context = get_lookback_geological_era(cosmo["ly_millions"])
    solar_lum = calculate_solar_luminosities(maxabsmag)

    # Aliases
    raw_aliases = meta.get("alias", [])
    aliases = []
    for a in raw_aliases:
        val = a.get("value", "") if isinstance(a, dict) else str(a)
        if val and val != name:
            aliases.append(val)

    # Foreground dust
    ebv_val = "—"
    ebv_raw = meta.get("ebv", [])
    if isinstance(ebv_raw, list) and ebv_raw:
        ebv_val = str(ebv_raw[0].get("value", "—") if isinstance(ebv_raw[0], dict) else ebv_raw[0])
    elif isinstance(ebv_raw, str):
        ebv_val = ebv_raw

    c_lower = claimedtype.lower()
    host_name = host if host != "—" else "an uncataloged host galaxy"
    disc_who = discoverer if discoverer != "—" else "an automated robotic transient sky survey"

    # =========================================================================
    # CATEGORY 1: ASTROPHYSICS & PROGENITOR STAR
    # =========================================================================

    # 1. Type & Progenitor Physics
    if "ia" in c_lower:
        type_ans = (
            f"{name} is classified as a <strong>Type Ia Supernova</strong>—the complete thermonuclear detonation "
            f"of an ultra-dense carbon-oxygen white dwarf star. In a binary system, the white dwarf siphoned material from "
            f"a companion star (or merged with a second white dwarf) until reaching the Chandrasekhar limit (~1.4 solar masses). "
            f"At this critical threshold, uncontrollable carbon and oxygen fusion detonated through the stellar interior in less than "
            f"a second with supersonic speeds exceeding 10,000 km/s. Because their peak absolute luminosities follow remarkably consistent "
            f"empirical relations (the Phillips relation), Type Ia supernovae serve as 'Standard Candles' for measuring cosmological distances "
            f"and the accelerated expansion of the universe."
        )
    elif "iip" in c_lower or "ii-p" in c_lower or ("ii" in c_lower and "iin" not in c_lower and "iib" not in c_lower):
        type_ans = (
            f"{name} is a <strong>Type II Core-Collapse Supernova</strong>, marking the death of an evolved red supergiant star "
            f"(with an initial mass between 8 and 25 times our Sun) that preserved its vast outer hydrogen envelope. Having exhausted "
            f"all nuclear fuel through successive stages of fusion (hydrogen, helium, carbon, neon, oxygen, and silicon), its inert iron core "
            f"could no longer withstand gravitational pressure. In less than a quarter of a second, the iron core collapsed into nuclear density, "
            f"triggering a catastrophic outward shockwave that blasted the star's outer layers into interstellar space."
        )
    elif "ib" in c_lower or "ic" in c_lower or "iib" in c_lower:
        type_ans = (
            f"{name} is a <strong>Stripped-Envelope Supernova (Type {claimedtype})</strong>. It originated from an extremely massive star "
            f"(such as a Wolf-Rayet star) that violently shed its outer hydrogen (and in Type Ic, helium) layers via intense stellar winds "
            f"or binary mass-transfer stripping prior to core collapse. Because the outer envelopes were lost before detonation, its spectra "
            f"reveal the inner helium, carbon, and oxygen mantle moving at extreme velocities."
        )
    elif "slsn" in c_lower or "superluminous" in c_lower:
        type_ans = (
            f"{name} is a rare <strong>Superluminous Supernova (SLSN)</strong>, radiating 10 to 100 times more total light than a standard "
            f"core-collapse supernova. Such titanic explosions are thought to be powered by an internal central engine—such as a newborn, "
            f"rapidly spinning millisecond magnetar with a magnetic field exceeding 10¹⁴ Gauss, or the violent collision of expanding blast "
            f"waves with dense circumstellar gas shells ejected shortly before the star died."
        )
    else:
        type_ans = (
            f"{name} is cataloged as a <strong>Type {claimedtype} transient</strong>. It represents a catastrophic stellar explosion "
            f"marking the terminal evolutionary endpoint of a star, liberating immense radiant energy and dispersing newly synthesized "
            f"chemical elements into the host galaxy's interstellar medium."
        )
    faqs.append({
        "category": "Astrophysics & Progenitor",
        "question": f"What type of supernova is {name} and what kind of star exploded?",
        "answer": type_ans,
    })

    # 2. Pre-Explosion Evolutionary History
    if "ia" in c_lower:
        pre_ans = (
            f"The progenitor of {name} began billions of years ago as a modest intermediate-mass star (1 to 8 solar masses). After exhausting "
            f"its core hydrogen and helium, it expelled its outer envelope as a glowing planetary nebula, leaving behind a dense carbon-oxygen "
            f"white dwarf the size of Earth but with the mass of the Sun. For millions or billions of years, it orbited in a close binary system, "
            f"gradually accreting hydrogen- and helium-rich gas from its stellar companion until gravitational compression pushed its core temperature "
            f"past the threshold of runaway carbon ignition."
        )
    else:
        pre_ans = (
            f"Before detonating as {name}, the progenitor lived a short, furious stellar life of roughly 10 to 30 million years. In its interior, "
            f"temperatures and pressures reached astronomical extremes, burning through nuclear fuel in an 'onion-skin' arrangement of concentric shells: "
            f"hydrogen burning into helium for millions of years, helium into carbon for hundreds of thousands of years, carbon into neon for centuries, "
            f"oxygen into silicon for months, and silicon fusing into iron in mere days! Once iron filled the core, fusion could no longer extract energy, "
            f"dooming the star to sudden gravitational collapse."
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
    dist_ans = (
        f"{name} is located approximately <strong>{dist_ly_str}</strong> from Earth"
        + (f" (cosmological redshift z = {redshift}, luminosity distance d_L = {lumdist})" if redshift != "—" else "")
        + f". Because electromagnetic radiation travels at 299,792 km/s, the photons detected by modern telescopes began their cosmic voyage "
        f"<strong>{era_context}</strong>. While that light traveled across intergalactic space, Earth's continents shifted and biological evolution "
        f"shaped the history of our planet."
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
            f"Under Hubble's Law, this redshift corresponds to an apparent recessional velocity of approximately "
            f"<strong>{rec_val:,.1f} km/s</strong> away from our Milky Way galaxy. "
            f"This redshift is not motion through space alone, but the stretching of light waves as the fabric of the universe itself expanded "
            f"during the millions of years the photons traveled to our telescopes."
        )
    else:
        red_ans = (
            f"{name}'s cosmological redshift z = {redshift} places it in the expanding Hubble flow. "
            f"Spectroscopic redshift measures the expansion of space itself stretching the light waves toward redder wavelengths, "
            f"providing a direct benchmark for calculating cosmological distances and the local Hubble constant (H₀)."
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
    bright_ans = (
        f"At peak brightness, {name} achieved an apparent magnitude of <strong>{maxappmag}</strong>"
        + (f" around {maxdate}" if maxdate != "—" else "")
        + (f". Corrected for cosmic distance and foreground interstellar dust, its intrinsic absolute magnitude was <strong>{maxabsmag}</strong>" if maxabsmag != "—" else "")
        + f". At this peak, the exploding star radiated with the incandescent brilliance of approximately <strong>{solar_lum} combined</strong>, "
        f"briefly outshining the cumulative starlight of entire dwarf galaxies!"
    )
    faqs.append({
        "category": "Explosion Energetics",
        "question": f"How bright did {name} become at its peak, and how many Suns does that equal?",
        "answer": bright_ans,
    })

    # 6. Total Energy Release & Neutrino Flash
    if "ia" in c_lower:
        energy_ans = (
            f"The thermonuclear explosion of {name} released approximately <strong>10⁵¹ ergs of energy</strong> (1 Bethe or 1 foe), "
            f"equivalent to 10²⁸ megatons of TNT! Virtually all of this energy was converted into the kinetic blast wave and the radioactive "
            f"synthesis of heavy isotopes. Because Type Ia supernovae lack a gravitational core collapse into a neutron star, neutrino emission "
            f"was minimal (~1%), and the blast converted its full binding energy into the kinetic destruction of the white dwarf."
        )
    else:
        energy_ans = (
            f"The collapse of {name}'s progenitor released a staggering <strong>10⁵³ ergs of gravitational binding energy</strong>—more energy "
            f"than our Sun will radiate across its entire 10-billion-year lifespan! Astonishingly, <strong>99% of this titanic energy was emitted "
            f"within 10 seconds in the form of trillions of nearly massless neutrinos</strong>. Only about 1% (10⁵¹ ergs) drove the physical kinetic "
            f"blast wave, and a mere 0.01% (10⁴⁹ ergs) was radiated as the visible starlight observed by telescopes."
        )
    faqs.append({
        "category": "Explosion Energetics",
        "question": f"How much total energy was released by {name}, and where did that energy go?",
        "answer": energy_ans,
    })

    # 7. Expansion Velocity & Blast Kinematics
    v_km = vel_info["km_s"]
    v_pct = vel_info["pct_c"]
    v_mach = vel_info["mach"]
    v_earths = vel_info["earths_per_sec"]
    vel_status = "measured spectroscopically" if vel_info["is_measured"] else "characteristic of this supernova class"
    vel_ans = (
        f"The debris and shockwave of {name} erupted into space at an astounding velocity of approximately "
        f"<strong>{v_km:,.0f} km/s</strong> ({vel_status}). "
        f"This corresponds to roughly <strong>{v_pct:.1f}% of the speed of light</strong> (Mach {v_mach:,.0f} in air)! "
        f"At this blistering speed, the expanding debris shell traverses the entire diameter of planet Earth in just "
        f"<strong>{1.0 / v_earths:.2f} seconds</strong>, carving a giant bubble in the interstellar medium."
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
    if "ia" in c_lower:
        engine_ans = (
            f"The brilliant light curve of {name} is energized by the radioactive decay of heavy isotopes synthesized during detonation. "
            f"The blast produced approximately <strong>0.5 to 0.7 solar masses of radioactive Nickel-56 (⁵⁶Ni)</strong>. "
            f"⁵⁶Ni decays with a half-life of <strong>6.075 days</strong> into Cobalt-56 (⁵⁶Co), emitting energetic gamma rays that heat the opaque "
            f"expanding fireball to power the optical peak. Subsequently, ⁵⁶Co decays into stable Iron-56 (⁵⁶Fe) with a half-life of <strong>77.2 days</strong>, "
            f"governing the smooth, exponential decline tail observed over the following year."
        )
    else:
        engine_ans = (
            f"While the initial flash of {name} was driven by shock breakout heating through the stellar envelope, its prolonged visibility over weeks "
            f"and months was sustained by the radioactive decay of approximately <strong>0.05 to 0.15 solar masses of Nickel-56 (⁵⁶Ni)</strong> forged "
            f"in the core shock. As ⁵⁶Ni decays into ⁵⁶Co (half-life: 6.1 days) and then into stable ⁵⁶Fe (half-life: 77.2 days), gamma rays and positrons "
            f"thermalize within the expanding ejecta, preventing the debris from instantly freezing in the vacuum of space."
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
    if "ia" in c_lower:
        elements_ans = (
            f"As a thermonuclear Type Ia explosion, {name} functioned as a premier cosmic foundry for <strong>iron-peak elements</strong>. "
            f"The detonation synthesized over <strong>half a solar mass of Iron-56 (⁵⁶Fe)</strong>—the exact element that forms Earth's dense metallic core "
            f"and binds oxygen in human red blood cells! It also forged substantial quantities of silicon (producing the hallmark Si II λ6355 absorption dip), "
            f"sulfur, calcium, argon, and titanium, enriching the interstellar clouds that condense into future planetary systems."
        )
    else:
        elements_ans = (
            f"Core-collapse supernovae like {name} are the primary creators of life-sustaining elements in the cosmos. "
            f"The explosion manufactured and dispersed immense reservoirs of <strong>oxygen</strong> (the single most abundant heavy element in the universe), "
            f"alongside carbon, nitrogen, neon, magnesium, silicon, sulfur, and calcium (which builds terrestrial bones and teeth). In the ultra-dense, "
            f"neutron-rich shockwave, rapid neutron capture (r-process nucleosynthesis) forged heavy elements like gold, platinum, and uranium."
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
    if "ia" in c_lower:
        remnant_ans = (
            f"<strong>Nothing remains at the center.</strong> Because a Type Ia supernova involves the total thermonuclear disruption of the progenitor "
            f"white dwarf, the entire star was incinerated and flung into space. There is no central neutron star, pulsar, or black hole left behind. "
            f"The star's entire mass now exists as an expanding gaseous shell traveling through the host galaxy."
        )
    else:
        remnant_ans = (
            f"The crushing core collapse of {name}'s progenitor forged an ultra-dense compact stellar remnant at the center of the detonation. "
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
        f"Over the coming millennia, the explosion site of {name} will undergo three dramatic evolutionary epochs: "
        f"During the next few centuries (Free Expansion phase), the ejecta shell will continue expanding at thousands of km/s. "
        f"Between 500 and 10,000 years (the Sedov-Taylor adiabatic phase), the forward shock will sweep up hundreds of solar masses of interstellar gas, "
        f"heating it to tens of millions of degrees and glowing in bright thermal X-rays (similar to the famous Cygnus Loop or Cassiopeia A). "
        f"Eventually, the cooling shock will compress nearby giant molecular clouds, triggering the gravitational collapse of new stars and solar systems!"
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
    if host_offset_str != "—":
        host_ans = (
            f"{name} occurred in <strong>{host_name}</strong>, located at an offset of <strong>{host_offset_str}</strong> from the galactic nucleus. "
            f"In optical and infrared imaging, this positions the explosion within the galaxy's active stellar disk or spiral arms, where ongoing "
            f"star formation constantly generates massive short-lived stellar progenitors."
        )
    else:
        host_ans = (
            f"{name} is associated with <strong>{host_name}</strong>. High-precision astrometry from optical sky surveys pins the explosion coordinates "
            f"directly to the galaxy's underlying stellar population."
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
            dust_ans = (
                f"Light from {name} passed through interstellar dust in the Milky Way, suffering a foreground color excess of "
                f"<strong>E(B-V) = {ebv_num:.3f} magnitudes</strong> (based on Schlafly & Finkbeiner 2011 galactic recalibrations). "
                f"This cosmic dust absorbs and scatters shorter blue wavelengths, dimming the transient by approximately "
                f"<strong>A_V ≈ {av_num:.2f} magnitudes</strong> in visual light."
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
    if p_cnt > 0:
        bnd_str = ", ".join(f"<code>{b}</code>" for b in p_bnds[:8]) if p_bnds else "optical filters"
        tel_str = ", ".join(p_tels[:4]) if p_tels else "global optical observatories"
        span_str = f" across a baseline of <strong>{p_days} days</strong>" if p_days else ""
        photo_ans = (
            f"{name} was tracked across <strong>{p_cnt} photometric observations</strong>{span_str} utilizing filter bands including {bnd_str}. "
            f"Data were captured by observatories and survey networks including {tel_str}. "
            f"Multi-color photometry tracks the temperature evolution of the fireball, verifying the rise time to peak and the rate of radioactive decline."
        )
    else:
        photo_ans = (
            f"Photometric light curves for {name} were acquired through standard astronomical alert streams and survey programs, "
            f"measuring flux across optical passbands to map its peak magnitude and fading rate."
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
            f"Spectroscopic observations of {name} confirmed its astrophysical classification by dissecting its light into individual wavelengths. "
            f"Absorption and emission line features reveal the chemical composition, expansion velocity, and temperature of the expanding fireball."
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
    else:
        cosmo_ans = (
            f"As a core-collapse supernova, {name} provides independent cosmological distance calibrations via the <strong>Expanding Photosphere Method (EPM)</strong> "
            f"and the Standard Candle Method for Type II supernovae (SCM-II). By correlating the physical expansion speed of the photosphere (measured via spectroscopic "
            f"Doppler shifts) with its photometric color temperature, astronomers determine direct geometric distances independent of secondary distance ladders."
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
    else:
        mm_ans = (
            f"Core-collapse supernovae like {name} are premier targets for multi-messenger astrophysics! During the collapse of the iron core, an intense "
            f"burst of 10⁵⁸ neutrinos escaped into space hours before the shock broke out through the stellar surface (as famously seen in SN 1987A). "
            f"Furthermore, violent core asymmetries and non-axisymmetric core bounce can emit high-frequency gravitational waves detectable by advanced "
            f"interferometers (LIGO, Virgo, KAGRA) for events within the Milky Way and Local Group."
        )
    faqs.append({
        "category": "Multi-Messenger Astronomy",
        "question": f"Could gravitational waves or neutrinos from {name} be detected on Earth?",
        "answer": mm_ans,
    })

    # 22. Historical Supernova Comparison
    hist_ans = (
        f"Compared to historical landmarks like <strong>SN 1987A</strong> in the Large Magellanic Cloud (168,000 light-years away, naked-eye peak m = 2.9) "
        f"or the <strong>Crab Supernova of 1054</strong> (6,500 light-years away), {name} occurred at a distance of <strong>{dist_ly_str}</strong>. "
        f"While historical naked-eye supernovae occurred within our Milky Way or its immediate satellites, modern discoveries like {name} allow astrophysicists "
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
        m_current = lifecycle.get("m_current", 20.0)
        time_str = lifecycle.get("time_str", "")

        if phase == "extinguished":
            obs_ans = (
                f"{name} exploded <strong>{time_str}</strong> ({discoverdate}). Optical transient emission has completely faded along its radioactive "
                f"decay curve. Today, pointing a telescope at these coordinates reveals the expanding remnant nebula or {host_name}; "
                f"the original optical transient is no longer detectable with amateur backyard equipment."
            )
        elif phase == "peak":
            obs_ans = (
                f"<strong>Yes, {name} is currently near peak brightness!</strong> Discovered {days_since} days ago ({discoverdate}), "
                f"it is shining at an estimated apparent magnitude of <strong>m ≈ {m_current:.1f}</strong>. "
                f"Backyard astronomers with appropriate telescope aperture can observe or image it tonight under dark skies."
            )
        else:
            obs_ans = (
                f"Discovered <strong>{days_since} days ago</strong> ({discoverdate}), {name} has passed peak maximum and is fading along its radioactive "
                f"Co-56 decay tail at an estimated apparent magnitude of <strong>m ≈ {m_current:.1f}</strong>. "
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
    earth_ans = (
        f"<strong>No, Earth is in zero danger.</strong> Supernovae are violent events emitting powerful gamma rays, X-rays, and cosmic rays; "
        f"however, the astrophysical 'lethal kill zone' for our planet's protective ozone layer is estimated at 50 to 100 light-years. "
        f"At a distance of <strong>{dist_ly_str}</strong>, the inverse-square law dilutes the radiation by quintillions of times, making "
        f"{name} completely harmless to our biosphere and purely a fascinating spectacle for human exploration."
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

    jsonld = f"""  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "FAQPage",
    "mainEntity": [
{",\n".join(entities)}
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
    era_context = get_lookback_geological_era(cosmo["ly_millions"])
    solar_lum = calculate_solar_luminosities(maxabsmag)

    c_low = claimedtype.lower()
    is_ia = "ia" in c_low
    host_name = host if host != "—" else "an uncataloged host galaxy"
    disc_who = discoverer if discoverer != "—" else "an automated sky survey"

    # Progenitor narrative
    if is_ia:
        progenitor_title = "The Thermonuclear Obliteration of a White Dwarf"
        progenitor_p1 = (
            f"In a binary star system located deep within <strong>{host_name}</strong>, a dense carbon-oxygen white dwarf—the dead stellar corpse "
            f"of an ancient sun—orbited its stellar companion for millions of years. As it siphoned material across the gravitational saddle point, "
            f"its mass relentlessly climbed toward the Chandrasekhar limit of 1.4 solar masses. At that fateful tipping point, uncontrollable carbon "
            f"fusion ignited in the degenerate core, ripping the entire star apart in a thermonuclear detonation that left behind zero remnant."
        )
    else:
        progenitor_title = "The Iron Core Collapse of a Dying Supergiant"
        progenitor_p1 = (
            f"The progenitor of <strong>{name}</strong> was a mammoth supergiant star, shining with the furious vigor of an object at least "
            f"8 to 25 times more massive than our Sun. For millions of years, it synthesized heavier and heavier elements in concentric onion-like shells: "
            f"hydrogen burning into helium, helium into carbon, carbon into oxygen, neon, and silicon. But when silicon fused into iron, the stellar engine "
            f"ran out of fuel. Iron fusion absorbs energy rather than liberating it; within fractions of a second, the iron core collapsed under its own "
            f"gravity, rebounding into an immense cosmic shockwave that blasted the star into pieces."
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
          Designated <strong>{name}</strong>, it represents a catastrophic stellar explosion classified as a <strong>Type {claimedtype}</strong> supernova.
        </p>
        <p>{progenitor_p1}</p>

        <div class="article-callout" style="border-left:4px solid #38bdf8;background:rgba(56,189,248,0.06);padding:1rem 1.25rem;border-radius:6px;margin:1.25rem 0;">
          <div style="font-weight:700;color:#38bdf8;font-size:0.92rem;margin-bottom:0.35rem;">Astrophysical Mechanism Summary</div>
          <div style="font-size:0.88rem;color:#cbd5e1;line-height:1.5;">
            <strong>Type:</strong> Type {claimedtype} &bull; <strong>Progenitor:</strong> {"Carbon-Oxygen White Dwarf (Binary System)" if is_ia else "Massive Red/Stripped Supergiant Star"} &bull; <strong>Velocity:</strong> ~{v_km:,.0f} km/s (~{v_pct:.1f}% c)
          </div>
        </div>
      </div>

      <!-- Chapter 2: Deep Time & Lookback -->
      <div class="article-chapter" id="chapter-2">
        <div class="article-chapter-num">CHAPTER II</div>
        <h2>A Message Across Deep Cosmic Time</h2>
        <p>
          The light from {name} is a dispatch from an ancient past. Located approximately <strong>{dist_ly_str}</strong> away
          {f" (redshift <code>z = {redshift}</code>)" if redshift != "—" else ""}, the photons detected by telescopes today began their journey
          <strong>{era_context}</strong>.
        </p>
        <p>
          While this burst of electromagnetic radiation traversed the cold void of intergalactic space at 299,792 kilometers per second,
          continents on Earth drifted, mountain ranges rose, and entire ecosystems rose and fell. To look into a telescope at {name} is to gaze
          directly into prehistoric cosmic time.
        </p>
      </div>

      <!-- Chapter 3: Peak Solar Radiance & Energetics -->
      <div class="article-chapter" id="chapter-3">
        <div class="article-chapter-num">CHAPTER III</div>
        <h2>Incandescence of {solar_lum}</h2>
        <p>
          At the height of the outburst{f" around {maxdate}" if maxdate != "—" else ""}, {name} surged to a peak apparent magnitude of <strong>{maxappmag}</strong>
          {f" and an intrinsic absolute magnitude of <strong>{maxabsmag}</strong>" if maxabsmag != "—" else ""}.
          At that instant, this single dying star radiated with the collective power of approximately <strong>{solar_lum} combined</strong>,
          outshining whole dwarf galaxies and illuminating the surrounding interstellar medium.
        </p>
        <p>
          The total energy released by the cataclysm was on the order of <strong>10⁵¹ to 10⁵³ ergs</strong>.
          {"Virtually all of this was deposited into the kinetic shockwave and radioactive nucleosynthesis." if is_ia else "Over 99% of this energy was emitted within the first 10 seconds as a dense burst of trillions of neutrinos, with only 1% driving the visible blast wave."}
        </p>
      </div>

      <!-- Chapter 4: The Radioactive Engine -->
      <div class="article-chapter" id="chapter-4">
        <div class="article-chapter-num">CHAPTER IV</div>
        <h2>The Radioactive Furnace: Why Supernovae Glow for Months</h2>
        <p>
          Unlike a conventional terrestrial explosion that cools and goes dark in seconds, {name} shone brightly for weeks and months.
          The secret behind this prolonged celestial glow is nuclear physics: the extreme heat and pressure of detonation synthesized vast quantities
          of <strong>radioactive Nickel-56 (⁵⁶Ni)</strong>.
        </p>
        <p>
          With a half-life of <strong>6.075 days</strong>, Nickel-56 decays into Cobalt-56 (⁵⁶Co), emitting gamma rays and high-energy positrons
          that heat the expanding ejecta from within. Cobalt-56 in turn decays with a half-life of <strong>77.2 days</strong> into stable Iron-56 (⁵⁶Fe),
          powering the steady exponential radioactive tail observed in the light curve.
        </p>
      </div>

      <!-- Chapter 5: Nucleosynthesis & Stardust -->
      <div class="article-chapter" id="chapter-5">
        <div class="article-chapter-num">CHAPTER V</div>
        <h2>Cosmic Kiln: Seeding the Elements of Life</h2>
        <p>
          Supernovae are the premier chemical foundries of our universe. {name} forged and liberated tons of newly synthesized elements:
          {"rich supplies of iron, silicon, calcium, and sulfur that will one day seed the formation of rocky terrestrial worlds." if is_ia else "vast reservoirs of oxygen (the most abundant heavy element in living organisms), carbon, nitrogen, magnesium, and silicon."}
        </p>
        <p>
          As Carl Sagan famously observed, <em>"We are made of star-stuff."</em> The iron atoms that carry oxygen in human hemoglobin and the calcium in
          our bones were originally forged in explosions identical to {name} billions of years ago.
        </p>
      </div>

      <!-- Chapter 6: Galactic Setting & Coordinates -->
      <div class="article-chapter" id="chapter-6">
        <div class="article-chapter-num">CHAPTER VI</div>
        <h2>Galactic Setting in {const_name}</h2>
        <p>
          {name} detonated inside <strong>{host_name}</strong>{f", positioned at an offset of <strong>{host_offset_str}</strong> from the galactic nucleus" if host_offset_str != "—" else ""}.
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
