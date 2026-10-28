#!/usr/bin/env python3
"""Corpus-wide scientific & data integrity auditor for sne.space.

Encodes the scientific-integrity invariants required for every event page:

1. No event may display an inferred/model-predicted current magnitude beyond the
   validated rest-frame domain of its physical model (Type Ia / Ib / Ic <= 300d,
   Type II / IIn / SLSN <= 365d, Kilonova <= 30d, Unclassified = 0d).
2. Outside the model's valid range (or without sufficient observations to anchor
   a decay model), the page must display "No reliable current brightness estimate"
   and set m_current = None.
3. Observed, cataloged/estimated, and model-predicted magnitudes must be
   explicitly distinguished alongside their observation/reference timestamps.
4. A single photometry measurement must never be presented as evidence of an
   observed rise, decline, peak, or multi-point light curve.
5. An event must not be labeled "faded below detection limits" or "beyond ground
   telescope limits" without supporting observational evidence or a validated
   in-domain model prediction against a stated threshold.
6. Pre-discovery background alerts (>60d before discovery) must never be used as
   the supernova's peak epoch.
7. Unclassified transients and records missing redshift, photometry, or spectra
   must never be described with fabricated mechanisms, distances, velocities, or
   confirmations.

Usage:
    python3 serve/audit_data_integrity.py                # audit all events
    python3 serve/audit_data_integrity.py --limit 200    # sample
    python3 serve/audit_data_integrity.py --verbose      # show every violation
    python3 serve/audit_data_integrity.py --json out.json

Exit code 0 when clean, 1 when violations exist.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from serve.astro_engine import enrich_transient_astrophysics  # noqa: E402
from serve.data_paths import OUTPUT_DIR  # noqa: E402
from serve.event_render import get_transient_lifecycle, get_val  # noqa: E402
from serve.faq_engine import generate_story_article_html, generate_supernova_faqs  # noqa: E402

# Types that carry no classification: asserting a mechanism for these is fabrication.
UNCLASSIFIED_TYPES = {"", "—", "none", "unknown", "unclassified", "at", "other", "candidate"}

# Phrases that assert a specific physical mechanism as fact.
MECHANISM_PHRASES = (
    "as a core-collapse supernova",
    "core-collapse supernovae like",
    "is a type ia supernova",
    "as a thermonuclear type ia explosion",
    "is classified as",
    "the collapse of ",
    "crushing core collapse of ",
    "iron core collapse of a dying supergiant",
)
DISTANCE_PHRASES = (
    "occurred at a distance of",
    "located approximately millions of light-years",
)
SINGLE_POINT_FORBIDDEN_PHRASES = (
    "at peak maximum",
    "at peak brightness",
    "has passed peak",
    "optical peak has passed",
    "decayed by",
    "dropped the estimated brightness by",
    "fading along its radioactive",
    "rate of radioactive decline",
    "multi-color photometry tracks",
)
UNSUPPORTED_LIMIT_PHRASES = (
    "faded below detection limits",
    "beyond ground telescope limits",
    "undetectable to all ground-based observatories",
)


def _empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, list):
        return len(v) == 0
    if isinstance(v, str):
        return v.strip() in ("", "—", "None")
    return False


def _claimedtype(meta: dict) -> str:
    ct = meta.get("claimedtype")
    if isinstance(ct, list) and ct:
        first = ct[0]
        return str(first.get("value", "") if isinstance(first, dict) else first).strip().lower()
    if isinstance(ct, str):
        return ct.strip().lower()
    return ""


def _usable_photometry(meta: dict) -> list:
    ph = meta.get("photometry") or []
    if not isinstance(ph, list):
        return []
    return [
        p for p in ph
        if isinstance(p, dict)
        and not p.get("upperlimit", False)
        and not str(p.get("magnitude", "")).startswith(">")
        and p.get("magnitude") is not None
    ]


def _has_upper_limits(meta: dict) -> bool:
    ph = meta.get("photometry") or []
    if not isinstance(ph, list):
        return False
    return any(
        isinstance(p, dict)
        and (bool(p.get("upperlimit", False)) or str(p.get("magnitude", "")).startswith(">"))
        for p in ph
    )


def _plain(html: str) -> str:
    """Strip tags and collapse whitespace, so phrase checks see rendered prose."""
    return " ".join(re.sub(r"<[^>]+>", " ", html or "").split()).lower()


def _parse_ymd(date_str: str) -> datetime | None:
    if not date_str or date_str == "—":
        return None
    m = re.match(r"\s*(\d{4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})", str(date_str))
    if not m:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= y <= 9999 and 1 <= mo <= 12 and 1 <= d <= 31:
            return datetime(y, mo, d)
    except Exception:
        return None
    return None


def max_valid_model_rest_days(ctype: str, event_name: str = "") -> float:
    """Return the maximum validated rest-frame day interval for a class decay model.

    Returns 0.0 when no validated class-specific decay model exists (unclassified).
    """
    c = (ctype or "").strip().lower()
    if c in UNCLASSIFIED_TYPES:
        return 0.0
    if "kilonova" in c or "at2017gfo" in (event_name or "").lower():
        return 30.0
    if "ia" in c:
        return 300.0
    if "ib" in c or "ic" in c or "iib" in c:
        return 300.0
    if "ii" in c or "slsn" in c or "magnetar" in c:
        return 365.0
    return 0.0


def audit_event(name: str, raw_meta: dict) -> list[dict]:
    """Return a list of violations for one event. Empty list means clean."""
    v: list[dict] = []

    # Run the same non-network astrophysics enrichment that render_pro_cockpit runs.
    meta = copy.deepcopy(raw_meta)
    try:
        meta = enrich_transient_astrophysics(name, meta, allow_network=False)
    except Exception as e:  # noqa: BLE001
        v.append({"rule": "enrich_raises", "detail": f"{type(e).__name__}: {e}"})
        return v

    ctype = _claimedtype(meta)
    phot = _usable_photometry(meta)
    raw_maxappmag = raw_meta.get("maxappmag")
    has_independent_peak = (
        not _empty(raw_maxappmag)
        and not (
            isinstance(raw_maxappmag, list)
            and raw_maxappmag
            and isinstance(raw_maxappmag[0], dict)
            and raw_maxappmag[0].get("derived")
        )
    )
    has_any_mag = has_independent_peak or len(phot) > 0
    has_redshift = not _empty(meta.get("redshift"))
    has_lumdist = not _empty(meta.get("lumdist"))
    specs = meta.get("spectra") or []
    spec_count = len(specs) if isinstance(specs, list) else 0

    discoverdate = get_val(meta, "discoverdate")
    maxdate = get_val(meta, "maxdate")
    maxappmag = get_val(meta, "maxappmag")
    maxabsmag = get_val(meta, "maxabsmag")
    lumdist = get_val(meta, "lumdist")
    redshift = get_val(meta, "redshift")
    host = get_val(meta, "host")

    # --- 1. Pre-discovery peak artifact check ------------------------------
    disc_dt = _parse_ymd(discoverdate)
    max_dt = _parse_ymd(maxdate)
    if disc_dt and max_dt and (disc_dt - max_dt).days > 60:
        v.append({
            "rule": "pre_discovery_peak_artifact",
            "detail": f"maxdate={maxdate!r} is {(disc_dt - max_dt).days}d before discoverdate={discoverdate!r}",
        })

    # --- 2. Lifecycle evaluation -------------------------------------------
    try:
        lc = get_transient_lifecycle(
            meta,
            host_name=host,
            event_name=name,
            redshift=redshift,
            claimedtype=ctype,
        )
    except Exception as e:  # noqa: BLE001
        v.append({"rule": "lifecycle_raises", "detail": f"{type(e).__name__}: {e}"})
        return v

    ref_dt = _parse_ymd(str(lc.get("ref_date", "—")))
    if disc_dt and ref_dt and (disc_dt - ref_dt).days > 60:
        v.append({
            "rule": "pre_discovery_peak_artifact",
            "detail": f"lifecycle ref_date={lc.get('ref_date')!r} predates discoverdate={discoverdate!r}",
        })

    notice_plain = _plain(lc.get("cockpit_notice", ""))
    story_plain = _plain(lc.get("story_guidance_html", ""))
    tel_plain = _plain(lc.get("tel_table_html", ""))
    prose_parts = [notice_plain, story_plain, tel_plain]

    # --- A. Missing photometry & missing peak: no invented magnitude -------
    if not has_any_mag:
        if lc.get("m_peak") is not None or lc.get("m_current") is not None:
            v.append({
                "rule": "invented_magnitude",
                "detail": f"m_peak={lc.get('m_peak')!r} m_current={lc.get('m_current')!r} "
                          f"with no maxappmag and no photometry",
            })
        if lc.get("phase") != "unmeasured":
            v.append({
                "rule": "unmeasured_phase_missing",
                "detail": f"phase={lc.get('phase')!r} but no magnitude source exists",
            })
        if lc.get("tel_table_html"):
            v.append({
                "rule": "telescope_table_without_magnitude",
                "detail": "telescope recommendation table rendered without a measured magnitude",
            })

    # --- B0. Class-template tonight magnitudes are forbidden -----------------
    if lc.get("m_current") is not None and not lc.get("fit_meta"):
        v.append({
            "rule": "class_template_tonight_magnitude",
            "detail": f"m_current={lc.get('m_current')!r} without event-specific fit_meta",
        })

    # --- B. Unphysical / out-of-domain extrapolation -----------------------
    t_rest = lc.get("t_rest")
    valid_domain_days = max_valid_model_rest_days(ctype, name)
    m_cur = lc.get("m_current")

    if m_cur is not None and (float(m_cur) > 30.0 or float(m_cur) < -30.0):
        v.append({
            "rule": "unphysical_current_magnitude",
            "detail": f"m_current={m_cur} is outside physical observational range [-30, 30]",
        })

    # Can a model-predicted current magnitude be shown?
    has_multi_or_indep_peak = len(phot) >= 2 or has_independent_peak
    in_model_domain = (
        valid_domain_days > 0.0
        and t_rest is not None
        and 0.0 <= float(t_rest) <= valid_domain_days
        and has_multi_or_indep_peak
    )

    if not in_model_domain and has_any_mag:
        # Outside the validated model domain (or unclassified / single-point):
        # no model-predicted m_current is permitted, and the page must state
        # "No reliable current brightness estimate" when the observation is not current.
        if m_cur is not None and lc.get("magnitude_kind") != "observed":
            v.append({
                "rule": "extrapolation_beyond_model_domain",
                "detail": f"m_current={m_cur} computed at t_rest={t_rest}d "
                          f"(valid domain <= {valid_domain_days}d for type={ctype!r}, phot={len(phot)})",
            })
        days_since = lc.get("days_since")
        if days_since is not None and days_since > 0:
            if "no reliable current brightness estimate" not in notice_plain:
                v.append({
                    "rule": "missing_no_reliable_estimate_notice",
                    "detail": f"cockpit_notice lacks 'No reliable current brightness estimate' "
                              f"at t_rest={t_rest}d (valid <= {valid_domain_days}d, phot={len(phot)})",
                })

    # --- C. Single photometry point must never be presented as peak/LC -----
    if len(phot) == 1 and not has_independent_peak:
        if lc.get("phase") in ("active", "fading", "peak"):
            v.append({
                "rule": "single_point_presented_as_lightcurve_or_peak",
                "detail": f"phase={lc.get('phase')!r} with only 1 photometry point",
            })
        if m_cur is not None:
            v.append({
                "rule": "single_point_presented_as_lightcurve_or_peak",
                "detail": f"m_current={m_cur!r} inferred from a single photometry point",
            })
        for part in prose_parts:
            for phrase in SINGLE_POINT_FORBIDDEN_PHRASES:
                if phrase in part:
                    v.append({
                        "rule": "single_point_presented_as_lightcurve_or_peak",
                        "detail": f"prose contains {phrase!r} on a 1-point record",
                    })

    # --- D. Detection-limit claims require evidence or in-domain threshold -
    has_uplim = _has_upper_limits(meta)
    in_domain_faint = bool(in_model_domain and m_cur is not None and float(m_cur) > 25.0)
    if not has_uplim and not in_domain_faint:
        for part in prose_parts:
            for phrase in UNSUPPORTED_LIMIT_PHRASES:
                if phrase in part:
                    v.append({
                        "rule": "unsupported_detection_limit_claim",
                        "detail": f"{phrase!r} without upper limit or in-domain model threshold",
                    })

    # --- E. Explicit provenance & timestamp for magnitudes -----------------
    if has_any_mag and lc.get("days_since") is not None:
        has_kind_label = any(
            kw in notice_plain
            for kw in ("observed", "cataloged", "model-predicted", "event-specific fit", "event-fit", "single-epoch", "no reliable current brightness estimate")
        )
        if not has_kind_label:
            v.append({
                "rule": "missing_magnitude_provenance_or_timestamp",
                "detail": "cockpit_notice does not distinguish observed/cataloged/model-predicted magnitude",
            })

    # --- F. Unclassified mechanism / distance checks in lifecycle prose ----
    if ctype in UNCLASSIFIED_TYPES:
        for part in prose_parts:
            for phrase in MECHANISM_PHRASES:
                if phrase in part:
                    v.append({
                        "rule": "asserts_mechanism_for_unclassified",
                        "detail": f"{phrase!r} on type={ctype!r}",
                    })
            for phrase in DISTANCE_PHRASES:
                if phrase in part:
                    v.append({
                        "rule": "asserts_distance_without_redshift",
                        "detail": f"{phrase!r} with no redshift or lumdist",
                    })

    # --- G. FAQ & Story Article checks -------------------------------------
    dist_ly_str = "Millions of Light-Years"
    if lumdist != "—":
        try:
            mpc = float(re.sub(r"[^0-9.]", "", lumdist))
            dist_ly_str = f"{mpc * 3.26156:.1f} Million Light-Years"
        except Exception:
            pass

    try:
        faqs = generate_supernova_faqs(
            name=name,
            meta=meta,
            claimedtype=(ctype or "—"),
            discoverdate=discoverdate,
            maxappmag=maxappmag,
            maxdate=maxdate,
            maxabsmag=maxabsmag,
            lumdist=lumdist,
            redshift=redshift,
            host=host,
            dist_ly_str=dist_ly_str,
            lifecycle=lc,
        )
    except Exception as e:  # noqa: BLE001
        v.append({"rule": "faq_raises", "detail": f"{type(e).__name__}: {e}"})
        return v

    for f in faqs:
        blob = _plain(f.get("answer", ""))
        cat = f.get("category", "")
        if ctype in UNCLASSIFIED_TYPES:
            for phrase in MECHANISM_PHRASES:
                if phrase in blob:
                    v.append({
                        "rule": "faq_asserts_mechanism_for_unclassified",
                        "detail": f"{phrase!r} in category {cat!r}",
                    })
            for phrase in DISTANCE_PHRASES:
                if phrase in blob:
                    v.append({
                        "rule": "faq_asserts_distance_without_redshift",
                        "detail": f"{phrase!r} in category {cat!r}",
                    })
        if not has_any_mag and re.search(r"m\s*[≈~]\s*\d", blob):
            v.append({
                "rule": "faq_prints_magnitude_without_measurement",
                "detail": f"numeric magnitude in category {cat!r}",
            })
        if len(phot) == 1 and not has_independent_peak:
            for phrase in SINGLE_POINT_FORBIDDEN_PHRASES:
                if phrase in blob:
                    v.append({
                        "rule": "single_point_presented_as_lightcurve_or_peak",
                        "detail": f"FAQ {cat!r} contains {phrase!r} on a 1-point record",
                    })
        if not has_redshift and "places it in the expanding hubble flow" in blob:
            v.append({
                "rule": "faq_redshift_dash_in_hubble_flow",
                "detail": f"FAQ {cat!r} claims z = {redshift!r} is in the Hubble flow",
            })
        if len(phot) == 0 and "photometric light curves for" in blob and "were acquired" in blob:
            v.append({
                "rule": "faq_claims_lightcurve_when_zero_photometry",
                "detail": f"FAQ {cat!r} claims light curves were acquired when phot=0",
            })
        if spec_count == 0 and ctype in UNCLASSIFIED_TYPES and "confirmed its astrophysical classification" in blob:
            v.append({
                "rule": "faq_claims_spectroscopy_confirmed_unclassified",
                "detail": f"FAQ {cat!r} claims spectroscopy confirmed classification when spec=0",
            })
        if not has_uplim and not in_domain_faint:
            for phrase in UNSUPPORTED_LIMIT_PHRASES:
                if phrase in blob:
                    v.append({
                        "rule": "unsupported_detection_limit_claim",
                        "detail": f"FAQ {cat!r} contains {phrase!r} without evidence",
                    })

    # Check Story Article generator too
    try:
        article_html = generate_story_article_html(
            name=name,
            meta=meta,
            claimedtype=(ctype or "—"),
            discoverdate=discoverdate,
            discoverer=get_val(meta, "discoverer"),
            maxappmag=maxappmag,
            maxdate=maxdate,
            maxabsmag=maxabsmag,
            lumdist=lumdist,
            redshift=redshift,
            host=host,
            host_offset_str="—",
            ra_str="—",
            dec_str="—",
            dist_ly_str=dist_ly_str,
            lifecycle=lc,
        )
        art_plain = _plain(article_html)
        if ctype in UNCLASSIFIED_TYPES:
            for phrase in MECHANISM_PHRASES:
                if phrase in art_plain:
                    v.append({
                        "rule": "story_asserts_mechanism_for_unclassified",
                        "detail": f"story article contains {phrase!r} for unclassified transient",
                    })
    except Exception as e:  # noqa: BLE001
        v.append({"rule": "story_raises", "detail": f"{type(e).__name__}: {e}"})

    return v


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit corpus scientific & data integrity")
    ap.add_argument("--limit", type=int, default=0, help="max events to audit (0 = all)")
    ap.add_argument("--verbose", action="store_true", help="print every violation")
    ap.add_argument("--json", default="", help="write full report to this path")
    args = ap.parse_args()

    files = sorted(glob.glob(str(Path(OUTPUT_DIR) / "sne-*" / "*.json")))
    if not files:
        print(f"no event JSON found under {OUTPUT_DIR}", file=sys.stderr)
        return 1

    total = 0
    dirty = 0
    by_rule: dict[str, int] = {}
    details: list[dict] = []
    errors = 0

    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            errors += 1
            continue
        for name, meta in d.items():
            if not isinstance(meta, dict):
                continue
            total += 1
            violations = audit_event(name, meta)
            if violations:
                dirty += 1
                for item in violations:
                    by_rule[item["rule"]] = by_rule.get(item["rule"], 0) + 1
                details.append({"name": name, "violations": violations})
            if args.limit and total >= args.limit:
                break
        if args.limit and total >= args.limit:
            break

    print("=== DATA INTEGRITY AUDIT ===")
    print(f"events audited      : {total}")
    print(f"parse errors        : {errors}")
    print(f"events with issues  : {dirty}")
    print(f"events clean        : {total - dirty}")
    if by_rule:
        print()
        print("violations by rule:")
        for rule, cnt in sorted(by_rule.items(), key=lambda x: -x[1]):
            print(f"  {cnt:5d}  {rule}")
        print()
        if args.verbose:
            for item in details:
                print(f"  {item['name']}:")
                for vi in item["violations"]:
                    print(f"      [{vi['rule']}] {vi['detail']}")
        else:
            print("first 15 offenders:")
            for item in details[:15]:
                rules = ", ".join(sorted({x["rule"] for x in item["violations"]}))
                print(f"  {item['name']:20s} {rules}")
            if len(details) > 15:
                print(f"  ... and {len(details) - 15} more (use --verbose)")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"total": total, "dirty": dirty, "by_rule": by_rule,
                       "details": details}, fh, indent=2)
        print(f"\nreport written to {args.json}")

    print()
    if dirty == 0:
        print("RESULT: CLEAN - no fabricated claims detected")
        return 0
    print(f"RESULT: {dirty} event(s) contain claims not supported by their source data")
    return 1


if __name__ == "__main__":
    sys.exit(main())
