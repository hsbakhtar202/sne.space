#!/usr/bin/env python3
"""P0 scientific-integrity regressions across event classes.

Validates FAQ / velocity / lookback / host / nucleosynthesis grounding for:
  Type Ia, II, Ib/c, SLSN, TDE, unclassified, no-redshift, no-host.

Also asserts object-specific numerical claims require supporting evidence.

Run: python3 serve/test_scientific_integrity_p0.py
"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "serve") not in sys.path:
    sys.path.insert(0, str(REPO / "serve"))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))


def _meta(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "TEST",
        "discoverdate": [{"value": "2026/09/19"}],
        "ra": [{"value": "01:28:39.388"}],
        "dec": [{"value": "+12:10:40.68"}],
        "photometry": [],
        "spectra": [],
        "alias": [],
        "sources": [],
    }
    base.update(overrides)
    return base


def _faqs(name: str, meta: dict, claimedtype: str, **kwargs: Any) -> str:
    from serve.faq_engine import generate_supernova_faqs
    from serve.event_render import get_transient_lifecycle, get_val

    z = kwargs.get("redshift", get_val(meta, "redshift"))
    host = kwargs.get("host", get_val(meta, "host"))
    lumdist = kwargs.get("lumdist", get_val(meta, "lumdist"))
    lc = get_transient_lifecycle(
        meta, redshift=z if z != "—" else "", claimedtype=claimedtype, event_name=name
    )
    faqs = generate_supernova_faqs(
        name=name,
        meta=meta,
        claimedtype=claimedtype,
        discoverdate=get_val(meta, "discoverdate"),
        maxappmag=get_val(meta, "maxappmag"),
        maxdate=get_val(meta, "maxdate"),
        maxabsmag=get_val(meta, "maxabsmag"),
        lumdist=lumdist,
        redshift=z,
        host=host,
        dist_ly_str=kwargs.get("dist_ly_str", "815.5 Million Light-Years"),
        lifecycle=lc,
    )
    return " ".join(f.get("answer", "") for f in faqs).lower()


def _strip(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html).lower()


# ---------------------------------------------------------------------------
# Cross-class FAQ grounding
# ---------------------------------------------------------------------------

def test_type_ia_does_not_claim_unique_progenitor() -> None:
    meta = _meta(
        claimedtype=[{"value": "Ia"}],
        redshift=[{"value": "0.056"}],
        lumdist=[{"value": "250.04"}],
        spectra=[{"data": [[4000, 1.0]]}],
    )
    blob = _faqs("SN2026acug", meta, "Ia", redshift="0.056", lumdist="250.04")
    check("Ia: competing progenitor models", "competing" in blob or "not established" in blob)
    check("Ia: no unique accretion biography", "gradually accreting" not in blob)
    check("Ia: Ni mass not claimed as measured", "not a measured" in blob or "not published" in blob)
    check("Ia: no ejecta from redshift", "no ejecta velocity is measured" in blob)
    check(
        "Ia: lookback separated from DL",
        "lookback" in blob
        and (
            "must not be equated" in blob
            or "not equal" in blob
            or "not the light-travel" in blob
            or "doppler-equivalent" in blob
        ),
    )


def test_type_ii_no_ia_physics() -> None:
    meta = _meta(claimedtype=[{"value": "II"}], redshift=[{"value": "0.02"}])
    blob = _faqs("SN1999em", meta, "II", redshift="0.02", lumdist="—", dist_ly_str="Millions of Light-Years")
    check(
        "II: does not claim this object is Type Ia",
        "sn1999em is classified as a type ia" not in blob
        and "sn1999em is a type ia" not in blob,
    )
    check("II: no Chandrasekhar accretion biography", "chandrasekhar" not in blob)
    check("II: no half-solar-mass iron claim", "half a solar mass of iron" not in blob)


def test_type_ibc_no_ia_nickel_yield() -> None:
    meta = _meta(claimedtype=[{"value": "Ib/c"}], redshift=[{"value": "0.03"}])
    blob = _faqs("SN2008D", meta, "Ib/c", redshift="0.03", lumdist="—", dist_ly_str="Millions of Light-Years")
    check("Ib/c: no Ia white-dwarf biography", "white dwarf" not in blob or "not established" in blob)
    check("Ib/c: nickel not asserted as measured yield", "not a measured" in blob or "not published" in blob or "class scale" in blob)


def test_slsn_not_generic_ia() -> None:
    meta = _meta(claimedtype=[{"value": "SLSN-I"}], redshift=[{"value": "0.2"}])
    blob = _faqs("PTF09atu", meta, "SLSN-I", redshift="0.2", lumdist="—", dist_ly_str="Millions of Light-Years")
    check("SLSN: not phrased as ordinary Type Ia", "type ia thermonuclear" not in blob)
    check("SLSN: no Chandrasekhar accretion story", "chandrasekhar" not in blob)


def test_tde_no_supernova_radioactive_engine() -> None:
    meta = _meta(claimedtype=[{"value": "TDE"}], redshift=[{"value": "0.02"}])
    blob = _faqs("ASASSN-14li", meta, "TDE", redshift="0.02", lumdist="—", dist_ly_str="Millions of Light-Years")
    # TDE must not inherit SN Ia/II Ni→Co→Fe object-specific power narrative
    check(
        "TDE: no object-specific 0.5-0.7 Msun Ni claim",
        "0.5 to 0.7 solar masses of radioactive nickel" not in blob
        and "half a solar mass of iron-56" not in blob,
    )
    check("TDE: no white-dwarf Chandrasekhar progenitor", "chandrasekhar" not in blob)


def test_unclassified_no_mechanism() -> None:
    meta = _meta(claimedtype=[{"value": "unclassified"}])
    blob = _faqs("AT2026agyd", meta, "unclassified", redshift="—", lumdist="—", host="—", dist_ly_str="Millions of Light-Years")
    check("AT: says not classified", "not been spectroscopically classified" in blob or "has not been spectroscopically classified" in blob)
    check("AT: no core-collapse assertion", "core-collapse supernovae like at2026agyd" not in blob)
    check("AT: no Ia assertion", "is a type ia" not in blob)
    check("AT: host unidentified when blank", "no host galaxy is identified" in blob)
    check("AT: distance unknown", "distance" in blob and ("not been measured" in blob or "not measured" in blob or "has not been measured" in blob))


def test_no_redshift_no_lookback_invention() -> None:
    meta = _meta(claimedtype=[{"value": "Ia"}])
    blob = _faqs("SNNoZ", meta, "Ia", redshift="—", lumdist="—", dist_ly_str="Millions of Light-Years")
    check("no-z: no fabricated lookback era from placeholder", "paleozoic" not in blob and "cretaceous" not in blob)
    check("no-z: no recessional velocity number", "recessional velocity of approximately" not in blob)


def test_blank_host_not_uncataloged_claim() -> None:
    meta = _meta(claimedtype=[{"value": "Ia"}], redshift=[{"value": "0.05"}])
    blob = _faqs("SNNoHost", meta, "Ia", redshift="0.05", host="—", lumdist="—", dist_ly_str="Millions of Light-Years")
    check("blank host: not 'uncataloged host galaxy' biography", "uncataloged host galaxy" not in blob)
    check("blank host: unidentified language", "no host galaxy is identified" in blob)


# ---------------------------------------------------------------------------
# Velocity / cosmology hygiene
# ---------------------------------------------------------------------------

def test_derived_cosmo_velocity_never_ejecta() -> None:
    from serve.faq_engine import analyze_velocity
    from serve.astro_engine import enrich_transient_astrophysics

    meta = _meta(claimedtype=[{"value": "Ia"}], redshift=[{"value": "0.056"}])
    enriched = enrich_transient_astrophysics("SN2026acug", copy.deepcopy(meta), allow_network=False)
    vel = (enriched.get("velocity") or [{}])[0]
    check(
        "enrich kind is redshift_doppler_equivalent",
        str(vel.get("kind")) == "redshift_doppler_equivalent",
        str(vel.get("kind")),
    )
    check("enrich marks derived", bool(vel.get("derived")))
    av = analyze_velocity(enriched, "Ia")
    check("analyze_velocity ignores cosmo kind", av.get("km_s") is None and av.get("is_measured") is False)
    check("class typical available only as context", av.get("class_typical_kms") == 11000.0)


def test_lookback_not_equal_to_luminosity_distance() -> None:
    from serve.faq_engine import analyze_cosmology, get_lookback_geological_era

    cosmo = analyze_cosmology("0.056", "250.04")
    lb = cosmo.get("lookback_myr")
    dl = cosmo.get("ly_millions")
    check("lookback present", lb is not None and lb > 0)
    check("DL Mly present", dl is not None and dl > 0)
    check("lookback < DL Mly at z=0.056", float(lb) < float(dl), f"lb={lb} dl={dl}")
    check("lookback ~750-770 Myr", 740 <= float(lb) <= 780, str(lb))
    era = get_lookback_geological_era(lb)
    check("era uses lookback not DL", "815" not in era)


def test_lifecycle_separates_discovery_and_peak() -> None:
    from serve.event_render import get_transient_lifecycle
    from datetime import datetime, timezone

    meta = _meta(
        claimedtype=[{"value": "Ia"}],
        discoverdate=[{"value": "2026/09/19"}],
        maxdate=[{"value": "2026/10/06"}],
        maxappmag=[{"value": "18.27"}],
        redshift=[{"value": "0.056"}],
        photometry=[
            {"time": "61319.3", "magnitude": "18.27", "band": "r"},
            {"time": "61320.3", "magnitude": "18.86", "band": "i"},
        ],
    )
    lc = get_transient_lifecycle(meta, redshift="0.056", claimedtype="Ia", event_name="SN2026acug")
    now = datetime.now(timezone.utc)
    disc = datetime(2026, 9, 19, tzinfo=timezone.utc)
    peak = datetime(2026, 10, 6, tzinfo=timezone.utc)
    expect_disc = (now - disc).days
    expect_peak = (now - peak).days
    check("days_since_discovery", lc.get("days_since_discovery") == expect_disc, str(lc.get("days_since_discovery")))
    check("days_since_peak", lc.get("days_since_peak") == expect_peak, str(lc.get("days_since_peak")))
    check("days_since uses discovery", lc.get("days_since") == expect_disc, str(lc.get("days_since")))
    notice = _strip(lc.get("cockpit_notice") or "")
    check("notice cites discovery date 09/19", "2026/09/19" in notice)
    check("no false current brightening", "brightening" not in notice)


# ---------------------------------------------------------------------------
# Object-specific numbers require evidence
# ---------------------------------------------------------------------------

def test_no_object_specific_numbers_without_evidence() -> None:
    """FAQ must not publish object-specific numerics absent supporting inputs."""
    meta = _meta(claimedtype=[{"value": "unclassified"}])
    blob = _faqs("ATBare", meta, "unclassified", redshift="—", lumdist="—", host="—", dist_ly_str="Millions of Light-Years")

    # Forbidden: invented distance/time/velocity/mag figures *for this object*.
    # Historical comparisons (e.g. SN 1987A m=2.9) are allowed as context.
    blob_no_hist = re.sub(
        r"compared to historical landmarks.*?(?=faqs?|$)",
        " ",
        blob,
        flags=re.S,
    )
    # Also drop the dedicated historical FAQ answer if present as a long clause.
    blob_no_hist = re.sub(r"sn 1987a.*?crab supernova of 1054.{0,200}", " ", blob_no_hist)
    for bad in [
        r"z\s*=\s*0\.\d",
        r"\d{1,3}(?:\.\d+)?\s*million light-years",
        r"\d{4,},\d{3}\s*km/s",  # formatted recession like 16,319
        r"atbare[^\.]{0,80}m\s*[≈~=]\s*\d{1,2}\.\d",
        r"e\(b[-−]v\)\s*=\s*0\.\d",
    ]:
        hit = re.search(bad, blob_no_hist)
        check(
            f"no unsupported numeric /{bad}/",
            hit is None,
            hit.group(0) if hit else "",
        )


def test_with_redshift_numbers_are_disclosed_as_derived() -> None:
    meta = _meta(
        claimedtype=[{"value": "Ia"}],
        redshift=[{"value": "0.056"}],
        lumdist=[{"value": "250.04"}],
    )
    blob = _faqs("SN2026acug", meta, "Ia", redshift="0.056", lumdist="250.04")
    check("with z: doppler-equivalent disclosed", "doppler-equivalent" in blob)
    check("with z: not called ejecta", "not</strong> the supernova's ejecta" in blob or "not the supernova's ejecta" in blob or "not</strong> supernova ejecta" in blob)


# ---------------------------------------------------------------------------
# Neighbors: nonzero index + ranking sanity for SN2026acug
# ---------------------------------------------------------------------------

def test_neighbor_index_and_acug_ranking() -> None:
    import serve.cone_search as cone_search
    from serve.cone_search import init_cone_index, find_closest_events, _resolve_catalog_paths

    paths = _resolve_catalog_paths()
    check("catalog path(s) resolved", len(paths) >= 1, str(paths))
    n = init_cone_index()
    check("neighbor index nonzero", n > 1000, f"n={n} status={cone_search._INDEX_STATUS}")
    check("index status ok", cone_search._INDEX_STATUS == "ok", cone_search._INDEX_STATUS)

    # SN2026acug coords from TNS/WISeREP-backed fixture
    ra, dec = 22.16411666666667, 12.177966666666666
    res = find_closest_events("SN2026acug", ra, dec, "2026/09/19", "0.056", limit=3)
    check("neighbor query status ok", res.get("_status") == "ok", str(res.get("_status")))
    check("sky neighbors nonempty", len(res.get("sky") or []) >= 1)
    check("cosmic neighbors nonempty", len(res.get("cosmic") or []) >= 1)

    sky = res.get("sky") or []
    if len(sky) >= 2:
        seps = [float(x["separation_arcmin"]) for x in sky]
        check("sky neighbors sorted by separation", seps == sorted(seps), str(seps))
    # Expected historical sky neighbor from audit
    sky_names = [x.get("name") for x in sky]
    check(
        "PS1-14acj among top sky neighbors for acug",
        "PS1-14acj" in sky_names,
        str(sky_names),
    )
    cosmic = res.get("cosmic") or []
    cosmic_z = [abs(float(x["delta_z"])) for x in cosmic if x.get("delta_z") is not None]
    if len(cosmic_z) >= 2:
        check("cosmic neighbors sorted by |Δz|", cosmic_z == sorted(cosmic_z), str(cosmic_z))
    check(
        "same-z historical SN1992bj in cosmic set",
        any(x.get("name") == "SN1992bj" for x in cosmic),
        str([x.get("name") for x in cosmic]),
    )
    top_dz = cosmic[0].get("delta_z") if cosmic else None
    check(
        "cosmic Δz near zero for top match",
        top_dz is not None and abs(float(top_dz)) <= 0.001,
        str(top_dz),
    )

    # Empty-index messaging contract
    from serve.event_render import format_cosmic_neighbors_panel

    html_ok = format_cosmic_neighbors_panel("SN2026acug", res)
    check("ok panel does not say unavailable", "Neighbor search unavailable" not in html_ok)
    html_bad = format_cosmic_neighbors_panel(
        "SN2026acug",
        {"sky": [], "time": [], "cosmic": [], "_status": "unavailable", "_index_size": 0},
    )
    check("empty index says unavailable not absent", "Neighbor search unavailable" in html_bad)
    check("empty index does not claim no neighbors exist", "No sky neighbors cataloged in this field" not in html_bad)


def test_neighbor_index_from_sne_data_dir_gz_only() -> None:
    """Production dockerignores plain catalog.min.json; volume may only have .gz."""
    import importlib
    import os
    import shutil
    import tempfile

    import serve.cone_search as cone_search

    src = REPO / "serve/www/astrocats/astrocats/supernovae/output/catalog.min.json.gz"
    if not src.is_file():
        check("gz fixture present", False, str(src))
        return

    td = Path(tempfile.mkdtemp())
    shutil.copy(src, td / "catalog.min.json.gz")
    old_env = os.environ.get("SNE_DATA_DIR")
    old_baked = cone_search._BAKED_CAT
    try:
        os.environ["SNE_DATA_DIR"] = str(td)
        cone_search._BAKED_CAT = td / "missing" / "catalog.min.json"
        cone_search._INDEX_INITIALIZED = False
        cone_search._SPATIAL_INDEX = []
        cone_search._INDEX_STATUS = "uninitialized"
        n = cone_search.init_cone_index()
        check("gz-only SNE_DATA_DIR loads index", n > 1000, f"n={n}")
        check("gz-only status ok", cone_search._INDEX_STATUS == "ok", cone_search._INDEX_STATUS)
        res = cone_search.find_closest_events(
            "SN2026acug", 22.16411666666667, 12.177966666666666, "2026/09/19", "0.056", limit=3
        )
        check("gz-only neighbor query ok", res.get("_status") == "ok")
        check("gz-only sky nonempty", bool(res.get("sky")))
    finally:
        cone_search._BAKED_CAT = old_baked
        if old_env is None:
            os.environ.pop("SNE_DATA_DIR", None)
        else:
            os.environ["SNE_DATA_DIR"] = old_env
        # Leave index rebuilt from default paths for any later tests in-process.
        cone_search._INDEX_INITIALIZED = False
        cone_search._SPATIAL_INDEX = []
        cone_search._INDEX_STATUS = "uninitialized"
        importlib.reload(cone_search)


def test_catalog_store_merge_policy() -> None:
    """recent stubs must not clobber published-updates or primary photolink."""
    import json
    import tempfile
    from serve.catalog_store import CatalogStore

    td = Path(tempfile.mkdtemp())
    primary = td / "catalog.min.json"
    recent = td / "recent-catalog.min.json"
    published = td / "published-updates.min.json"

    def row(name: str, phot: str, ctype: str = "Ia") -> dict:
        return {
            "name": name,
            "alias": [{"value": name}],
            "claimedtype": [{"value": ctype}],
            "discoverdate": [{"value": "2026/10/28"}],
            "maxappmag": [{"value": "19.0"}],
            "ra": [{"value": "01:00:00"}],
            "dec": [{"value": "+00:00:00"}],
            "photolink": phot,
            "spectralink": "0",
        }

    primary.write_text(json.dumps([row("SN1999xx", "10,0")]), encoding="utf-8")
    recent.write_text(
        json.dumps([row("AT2026agym", "1,0", "unclassified"), row("SN1999xx", "1,0")]),
        encoding="utf-8",
    )
    published.write_text(json.dumps([row("AT2026agym", "59,56", "unclassified")]), encoding="utf-8")

    store = CatalogStore(td / "c.db")
    store.build([primary, recent, published])
    a = store.query(q="AT2026agym", limit=1)["items"][0]
    b = store.query(q="SN1999xx", limit=1)["items"][0]
    check("published phot wins for new AT", a["phot"] == 59, str(a["phot"]))
    check("primary phot preserved vs recent stub", b["phot"] == 10, str(b["phot"]))


def main() -> int:
    print("=== P0 scientific integrity (cross-class) ===")
    tests = [
        test_type_ia_does_not_claim_unique_progenitor,
        test_type_ii_no_ia_physics,
        test_type_ibc_no_ia_nickel_yield,
        test_slsn_not_generic_ia,
        test_tde_no_supernova_radioactive_engine,
        test_unclassified_no_mechanism,
        test_no_redshift_no_lookback_invention,
        test_blank_host_not_uncataloged_claim,
        test_derived_cosmo_velocity_never_ejecta,
        test_lookback_not_equal_to_luminosity_distance,
        test_lifecycle_separates_discovery_and_peak,
        test_no_object_specific_numbers_without_evidence,
        test_with_redshift_numbers_are_disclosed_as_derived,
        test_neighbor_index_and_acug_ranking,
        test_neighbor_index_from_sne_data_dir_gz_only,
        test_catalog_store_merge_policy,
    ]
    for fn in tests:
        print(f"\n-- {fn.__name__} --")
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(fn.__name__ + " raised", False, str(exc))

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n=== {passed}/{passed + failed} passed, {failed} failed ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
