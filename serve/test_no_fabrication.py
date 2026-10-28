#!/usr/bin/env python3
"""Regression tests for fabricated values on sparse-metadata transients.

Every assertion here corresponds to a bug found on AT2026AGPL, where the page
reported "currently in active outburst at m ~= 18.2" for a transient whose only
real measurement was 17.80 and whose production record had no photometry at all.
The renderer filled the gap with 18.0 and then derived a whole narrative from it.

The principle these tests enforce: a page may not state a number or a physical
classification that is not present in the event's own data. Absent data must
render as "unknown", not as a plausible default.

Run: python3 serve/test_no_fabrication.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f": {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Fixtures: event records with deliberately missing metadata
# ---------------------------------------------------------------------------

def _event(**overrides):
    """Minimal event record shaped like the catalog JSON."""
    base = {
        "name": "AT2026agpl",
        "discoverdate": [{"value": "2026/10/23", "source": "1"}],
        "ra": [{"value": "10:52:52.460", "source": "1"}],
        "dec": [{"value": "-47:25:06.70", "source": "1"}],
        "claimedtype": [{"value": "unclassified", "source": "1"}],
        "discoverer": [{"value": "MASTER", "source": "1"}],
    }
    base.update(overrides)
    return base


def _empty_mag_event():
    """No maxappmag, no photometry: the exact AT2026AGPL production record."""
    return _event(
        maxappmag=[],
        photometry=[],
        photolink="1,0",
        spectralink="0",
    )


def _one_point_event():
    """One MASTER detection: real magnitude, but no light curve."""
    return _event(
        photometry=[
            {
                "time": "61336.12907",
                "magnitude": "17.80",
                "band": "Other-",
                "telescope": "MASTER",
                "source": "2",
            }
        ]
    )


def _two_point_event():
    """Two detections in time order: enough for a trend claim."""
    return _event(
        photometry=[
            {"time": "61336.12907", "magnitude": "17.80", "band": "r", "telescope": "MASTER"},
            {"time": "61339.20000", "magnitude": "18.40", "band": "r", "telescope": "MASTER"},
        ]
    )


def _typed_ia_event():
    return _event(claimedtype=[{"value": "Ia", "source": "1"}], maxappmag=[{"value": "15.2"}])


# ---------------------------------------------------------------------------
# 1. No invented peak magnitude
# ---------------------------------------------------------------------------

def test_no_invented_magnitude() -> None:
    from serve.event_render import get_transient_lifecycle

    lc = get_transient_lifecycle(_empty_mag_event(), claimedtype="unclassified")
    check(
        "empty record: m_peak is None (not 18.0)",
        lc.get("m_peak") is None,
        f"got {lc.get('m_peak')!r}",
    )
    check(
        "empty record: m_current is None (not 18.16)",
        lc.get("m_current") is None,
        f"got {lc.get('m_current')!r}",
    )
    check(
        "empty record: phase is 'unmeasured'",
        lc.get("phase") == "unmeasured",
        f"got {lc.get('phase')!r}",
    )
    notice = lc.get("cockpit_notice", "")
    check(
        "empty record: notice says brightness not measured",
        "not measured" in notice.lower(),
        "",
    )
    check(
        "empty record: no telescope table emitted",
        lc.get("tel_table_html") == "",
        "",
    )


def test_measured_magnitude_is_preserved() -> None:
    from serve.event_render import get_transient_lifecycle

    lc = get_transient_lifecycle(_one_point_event(), claimedtype="unclassified")
    check(
        "one real point: m_peak equals the measured 17.80",
        lc.get("m_peak") == 17.80,
        f"got {lc.get('m_peak')!r}",
    )
    check(
        "one real point: phase is not 'active' (no light curve)",
        lc.get("phase") != "active",
        f"got {lc.get('phase')!r}",
    )
    check(
        "one real point: measured flag is True",
        lc.get("measured") is True,
        "",
    )


def test_active_requires_two_points() -> None:
    from serve.event_render import get_transient_lifecycle

    one = get_transient_lifecycle(_one_point_event(), claimedtype="unclassified")
    two = get_transient_lifecycle(_two_point_event(), claimedtype="unclassified")
    check(
        "1 detection cannot claim 'Active Outburst'",
        one.get("phase") != "active",
        f"phase={one.get('phase')!r}",
    )
    check(
        "2 detections may claim 'Active Outburst'",
        two.get("phase") == "active",
        f"phase={two.get('phase')!r}",
    )
    # The second point is fainter, so the prose must say fading, not brightening.
    story = two.get("story_guidance_html", "")
    check(
        "trend direction follows the data (17.80 -> 18.40 is fading)",
        "fading" in story.lower(),
        "",
    )


# ---------------------------------------------------------------------------
# 2. No invented classification
# ---------------------------------------------------------------------------

def test_no_invented_classification() -> None:
    from serve.faq_engine import generate_supernova_faqs

    faqs = generate_supernova_faqs(
        name="AT2026agpl",
        meta=_empty_mag_event(),
        ra_deg=163.21858,
        dec_deg=-47.41853,
        claimedtype="unclassified",
        discoverdate="2026/10/23",
        discoverer="MASTER",
        maxappmag="—",
        maxdate="—",
        maxabsmag="—",
        lumdist="—",
        redshift="—",
        host="—",
        dist_ly_str="Millions of Light-Years",
        lifecycle=None,
    )
    blob = " ".join(f.get("answer", "") for f in faqs).lower()

    # The disclaimers legitimately *mention* these mechanisms while explaining why
    # they do not apply. What matters is that none is asserted as fact about this
    # object. Assert-on-fact phrasing looks like "X is a Type Ia supernova" or
    # "As a core-collapse supernova, X ..." or "occurred at a distance of".
    for bad in (
        "is a type ia supernova",
        "as a core-collapse supernova",
        "core-collapse supernovae like at2026agpl are",
        "occurred at a distance of",
        "is classified as",
    ):
        check(
            f"unclassified: does not assert {bad!r}",
            bad not in blob,
            "",
        )
    check(
        "unclassified: does not assert a measured distance",
        "millions of light-years</strong>" not in blob,
        "",
    )
    check(
        "unclassified: explicitly says not classified",
        "not been spectroscopically classified" in blob or "unclassified" in blob,
        "",
    )
    check(
        "unclassified: does not claim a Hubble-constant contribution",
        "distance ladder" not in blob or "cannot" in blob,
        "",
    )


def test_typed_event_still_gets_physics() -> None:
    """The fix must not silence legitimate classified events."""
    from serve.faq_engine import generate_supernova_faqs

    faqs = generate_supernova_faqs(
        name="SN2011fe",
        meta=_typed_ia_event(),
        ra_deg=210.77,
        dec_deg=54.27,
        claimedtype="Ia",
        discoverdate="2011/08/24",
        discoverer="PTF",
        maxappmag="9.9",
        maxdate="2011/09/10",
        maxabsmag="-19.1",
        lumdist="6.4",
        redshift="0.000804",
        host="M101",
        dist_ly_str="21",
        lifecycle=None,
    )
    blob = " ".join(f.get("answer", "") for f in faqs).lower()
    check(
        "Type Ia event: still describes thermonuclear mechanism",
        "thermonuclear" in blob,
        "",
    )
    check(
        "Type Ia event: still describes the Phillips relation",
        "phillips" in blob,
        "",
    )
    check(
        "Type Ia event: does not emit the 'unclassified' disclaimer",
        "not been spectroscopically classified" not in blob,
        "",
    )


# ---------------------------------------------------------------------------
# 3. No invented numbers in the solar-luminosity helper
# ---------------------------------------------------------------------------

def test_solar_luminosity_returns_none_when_unknown() -> None:
    from serve.faq_engine import calculate_solar_luminosities

    check(
        "unknown absolute magnitude -> None (not 'hundreds of millions')",
        calculate_solar_luminosities("—") is None,
        f"got {calculate_solar_luminosities('—')!r}",
    )
    check(
        "known absolute magnitude still computes",
        calculate_solar_luminosities("-19.1") is not None,
        f"got {calculate_solar_luminosities('-19.1')!r}",
    )


# ---------------------------------------------------------------------------
# 4. Altitude helper must exist and be sane
# ---------------------------------------------------------------------------

def test_altitude_helper() -> None:
    from serve.astro_engine import compute_target_altitude

    check(
        "altitude helper returns None without coordinates",
        compute_target_altitude(None, None) is None,
        "",
    )
    alt = compute_target_altitude(163.21858, -47.41853)
    check(
        "altitude helper returns a bounded number",
        alt is not None and -90.0 <= alt <= 90.0,
        f"got {alt!r}",
    )


# ---------------------------------------------------------------------------
# 5. Live-page assertions (only when a base URL is provided)
# ---------------------------------------------------------------------------

def test_live_page(base: str) -> None:
    """Fetch a real page and assert no fabricated claims are present."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"{base}/sne/AT2026agpl/", timeout=60) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        check("live page reachable", False, f"{type(e).__name__}: {e}")
        return

    check("live page reachable", True, f"{len(html)} bytes")
    low = html.lower()
    # These strings were all present on the fabricated page.
    for phrase in ("m ≈ 18.2", "amateur cmos rig", "as a core-collapse supernova"):
        check(f"live page does not contain {phrase!r}", phrase not in low, "")
    check(
        "live page does not claim 'active outburst' without a light curve",
        "active outburst" not in low,
        "",
    )



# ---------------------------------------------------------------------------
# 6. Model-domain / single-epoch / provenance regressions
# ---------------------------------------------------------------------------

def test_single_epoch_no_current_or_peak_claims() -> None:
    from serve.event_render import get_transient_lifecycle
    from serve.faq_engine import generate_supernova_faqs

    lc = get_transient_lifecycle(_one_point_event(), claimedtype="unclassified", event_name="AT2026agpl")
    check(
        "single-epoch: m_current is None",
        lc.get("m_current") is None,
        f"got {lc.get('m_current')!r}",
    )
    check(
        "single-epoch: peak_confirmed is False",
        lc.get("peak_confirmed") is False,
        "",
    )
    check(
        "single-epoch: magnitude_kind is observed_single_epoch",
        lc.get("magnitude_kind") == "observed_single_epoch",
        f"got {lc.get('magnitude_kind')!r}",
    )
    notice = (lc.get("cockpit_notice") or "").lower()
    check(
        "single-epoch: notice says no reliable current brightness estimate",
        "no reliable current brightness estimate" in notice,
        "",
    )
    for bad in ("at peak brightness", "decayed by", "faded below detection limits", "active outburst"):
        check(
            f"single-epoch: prose does not contain {bad!r}",
            bad not in notice and bad not in (lc.get("story_guidance_html") or "").lower(),
            "",
        )
    faqs = generate_supernova_faqs(
        name="AT2026agpl",
        meta=_one_point_event(),
        claimedtype="unclassified",
        discoverdate="2026/10/23",
        discoverer="MASTER",
        maxappmag="17.80",
        maxdate="2026/10/23",
        maxabsmag="—",
        lumdist="—",
        redshift="—",
        host="—",
        dist_ly_str="Millions of Light-Years",
        lifecycle=lc,
    )
    blob = " ".join(f.get("answer", "") for f in faqs).lower()
    check(
        "single-epoch FAQ: does not say at peak brightness",
        "at peak brightness" not in blob,
        "",
    )
    check(
        "single-epoch FAQ: does not invent energy collapse narrative",
        "the collapse of at2026agpl" not in blob,
        "",
    )
    check(
        "single-epoch FAQ: velocity unknown without spectrum",
        "no ejecta velocity is measured" in blob or "not measured" in blob,
        "",
    )


def test_typed_ia_class_template_does_not_predict_tonight() -> None:
    """Class templates must not invent an object-specific tonight magnitude."""
    from datetime import datetime, timezone, timedelta
    from serve.event_render import get_transient_lifecycle

    now = datetime.now(timezone.utc)
    disc = (now - timedelta(days=40)).strftime("%Y/%m/%d")
    mjd0 = 40587.0 + (now - timedelta(days=40)).timestamp() / 86400.0
    meta = {
        "name": "SN2026test",
        "discoverdate": [{"value": disc}],
        "maxdate": [{"value": disc}],
        "maxappmag": [{"value": "15.0"}],
        "claimedtype": [{"value": "Ia"}],
        "redshift": [{"value": "0.01"}],
        "photometry": [
            {"time": str(mjd0), "magnitude": "15.0", "band": "r"},
            {"time": str(mjd0 + 10), "magnitude": "15.5", "band": "r"},
            {"time": str(mjd0 + 20), "magnitude": "16.0", "band": "r"},
        ],
    }
    lc = get_transient_lifecycle(meta, claimedtype="Ia", event_name="SN2026test", redshift="0.01")
    check(
        "typed Ia multi-epoch without event fit: m_current is None",
        lc.get("m_current") is None,
        f"got {lc.get('m_current')!r} kind={lc.get('magnitude_kind')!r}",
    )
    check(
        "typed Ia without event fit: notice says no reliable current brightness estimate",
        "no reliable current brightness estimate" in (lc.get("cockpit_notice") or "").lower(),
        "",
    )
    check(
        "typed Ia without event fit: does not claim model-predicted tonight",
        "model-predicted" not in (lc.get("cockpit_notice") or "").lower(),
        "",
    )


def test_event_specific_fit_may_predict() -> None:
    """Only an explicit fitted prediction with uncertainty may set m_current."""
    from datetime import datetime, timezone, timedelta
    from serve.event_render import get_transient_lifecycle

    now = datetime.now(timezone.utc)
    disc = (now - timedelta(days=20)).strftime("%Y/%m/%d")
    mjd0 = 40587.0 + (now - timedelta(days=20)).timestamp() / 86400.0
    now_mjd = 40587.0 + now.timestamp() / 86400.0
    meta = {
        "discoverdate": [{"value": disc}],
        "maxappmag": [{"value": "15.0"}],
        "claimedtype": [{"value": "Ia"}],
        "photometry": [
            {"time": str(mjd0), "magnitude": "15.0", "band": "r"},
            {"time": str(mjd0 + 5), "magnitude": "15.4", "band": "r"},
        ],
        "brightness_prediction": [{
            "value": 16.2,
            "e_magnitude": 0.15,
            "model": "MOSFiT-Ia-fit",
            "reference_epoch_mjd": mjd0,
            "valid_until_mjd": now_mjd + 10,
            "band": "r",
        }],
    }
    lc = get_transient_lifecycle(meta, claimedtype="Ia", event_name="SN2026fit")
    check(
        "event fit: m_current equals fitted value",
        lc.get("m_current") == 16.2,
        f"got {lc.get('m_current')!r}",
    )
    check(
        "event fit: magnitude_kind is event_fit_predicted",
        lc.get("magnitude_kind") == "event_fit_predicted",
        f"got {lc.get('magnitude_kind')!r}",
    )


def test_ancient_event_no_extrapolation() -> None:
    """An old classified event past the model domain must not invent m_current."""
    from serve.event_render import get_transient_lifecycle

    meta = {
        "discoverdate": [{"value": "2011/08/24"}],
        "maxdate": [{"value": "2011/09/10"}],
        "maxappmag": [{"value": "9.9"}],
        "claimedtype": [{"value": "Ia"}],
        "redshift": [{"value": "0.000804"}],
        "photometry": [
            {"time": "55800.0", "magnitude": "9.9", "band": "r"},
            {"time": "55820.0", "magnitude": "12.0", "band": "r"},
        ],
    }
    lc = get_transient_lifecycle(meta, claimedtype="Ia", event_name="SN2011fe", redshift="0.000804")
    check(
        "ancient Ia: m_current is None (past 300d domain)",
        lc.get("m_current") is None,
        f"got {lc.get('m_current')!r} t_rest={lc.get('t_rest')!r}",
    )
    check(
        "ancient Ia: notice states no reliable current brightness estimate",
        "no reliable current brightness estimate" in (lc.get("cockpit_notice") or "").lower(),
        "",
    )


def test_pull_recent_needs_enrich_logic() -> None:
    """Sparse on-disk stubs must be flagged for re-enrichment."""
    # Inline the same rules as pull_recent._needs_enrich without network I/O.
    def usable(body):
        n = 0
        for p in body.get("photometry") or []:
            if not isinstance(p, dict):
                continue
            if p.get("upperlimit") or str(p.get("magnitude", "")).startswith(">"):
                continue
            if p.get("magnitude") is None:
                continue
            n += 1
        return n

    def needs(body):
        if usable(body) <= 1:
            return True
        if len(body.get("spectra") or []) == 0:
            return True
        return False

    stub = {"photometry": [{"magnitude": "17.8", "time": "1"}], "spectra": []}
    rich = {
        "photometry": [
            {"magnitude": "17.8", "time": "1"},
            {"magnitude": "18.1", "time": "2"},
            {"magnitude": "18.5", "time": "3"},
        ],
        "spectra": [{"data": [[4000, 1.0]]}],
    }
    check("1-point stub needs enrich", needs(stub) is True, "")
    check("empty photo needs enrich", needs({"photometry": [], "spectra": []}) is True, "")
    check("rich multi-epoch with spectra does not need enrich", needs(rich) is False, "")
    check("multi-epoch without spectra still needs enrich", needs({**rich, "spectra": []}) is True, "")



def main() -> int:
    base = ""
    for arg in sys.argv[1:]:
        if arg.startswith("--base="):
            base = arg.split("=", 1)[1]

    print("=== fabrication regression tests ===")
    test_no_invented_magnitude()
    test_measured_magnitude_is_preserved()
    test_active_requires_two_points()
    test_no_invented_classification()
    test_typed_event_still_gets_physics()
    test_solar_luminosity_returns_none_when_unknown()
    test_altitude_helper()
    test_single_epoch_no_current_or_peak_claims()
    test_typed_ia_class_template_does_not_predict_tonight()
    test_event_specific_fit_may_predict()
    test_ancient_event_no_extrapolation()
    test_pull_recent_needs_enrich_logic()
    if base:
        test_live_page(base)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print()
    print(f"=== {passed}/{len(RESULTS)} passed, {failed} failed ===")
    for name, ok, _ in RESULTS:
        if not ok:
            print(f"  FAILED: {name}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
