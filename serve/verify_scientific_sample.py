#!/usr/bin/env python3
"""Independent verification of rendered claims vs upstream ALeRCE for a stratified sample."""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ingest.alerce import get_alerce_lightcurve  # noqa: E402
from serve.astro_engine import enrich_transient_astrophysics  # noqa: E402
from serve.audit_data_integrity import UNCLASSIFIED_TYPES  # noqa: E402
from serve.data_paths import OUTPUT_DIR  # noqa: E402
from serve.event_render import get_transient_lifecycle, get_val  # noqa: E402
from serve.faq_engine import generate_story_article_html, generate_supernova_faqs  # noqa: E402

UNCLASS_FORBIDDEN = [
    "as a core-collapse supernova",
    "is a type ia supernova",
    "is classified as",
    "places it in the expanding hubble flow",
    "occurred at a distance of",
]
ALWAYS_FORBIDDEN = [
    "m ≈ 18.2",
    "faded below detection limits",
    "incandescence of none",
    "model-predicted</strong> brightness tonight",
    "model-predicted tonight",
]


def plain(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").lower()


def sample_events(n: int = 50):
    root = Path(OUTPUT_DIR)
    buckets = {"2025_sparse": [], "2026_sparse": [], "2026_rich": [], "classic": []}
    for f in root.glob("sne-*/**/*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for name, meta in d.items():
            if not isinstance(meta, dict):
                continue
            disc = get_val(meta, "discoverdate") or ""
            year = int(disc[:4]) if disc[:4].isdigit() else 0
            ph = [
                p for p in (meta.get("photometry") or [])
                if isinstance(p, dict) and not p.get("upperlimit") and p.get("magnitude")
            ]
            item = (f, name, meta, len(ph), year)
            if year == 2025 and len(ph) <= 1:
                buckets["2025_sparse"].append(item)
            elif year == 2026 and len(ph) <= 1:
                buckets["2026_sparse"].append(item)
            elif year == 2026 and len(ph) >= 2:
                buckets["2026_rich"].append(item)
            elif year and year < 2025:
                buckets["classic"].append(item)
    rng = random.Random(42)
    out = []
    for key, q in [("2025_sparse", 15), ("2026_sparse", 10), ("2026_rich", 10), ("classic", 15)]:
        pool = buckets[key][:]
        rng.shuffle(pool)
        out.extend(pool[:q])
    return out[:n]


def main() -> int:
    results = {
        "checked": 0,
        "fabricated_claims": [],
        "m_current_set_without_fit": [],
        "peak_from_single_epoch_claims": [],
        "missing_but_valid": {"no_photometry": 0, "no_spectrum": 0, "no_redshift": 0, "unclassified": 0},
        "upstream_match": {
            "compared": 0, "local_dets_leq_upstream": 0, "local_dets_gt_upstream": 0,
            "no_ztf": 0, "alerce_fail": 0,
        },
        "alerce_compare": [],
        "render_ok": 0,
    }
    for fpath, name, meta, nphot, year in sample_events(50):
        results["checked"] += 1
        meta2 = enrich_transient_astrophysics(name, json.loads(json.dumps(meta)), allow_network=False)
        ctype = (get_val(meta2, "claimedtype") or "unclassified").strip()
        ctype_l = ctype.lower()
        z = get_val(meta2, "redshift") or "—"
        lc = get_transient_lifecycle(meta2, claimedtype=ctype, event_name=name, redshift=z)
        if lc.get("m_current") is not None and not lc.get("fit_meta"):
            results["m_current_set_without_fit"].append(name)
        if nphot == 1 and lc.get("peak_confirmed"):
            results["peak_from_single_epoch_claims"].append(name)

        faqs = generate_supernova_faqs(
            name=name, meta=meta2, claimedtype=ctype,
            discoverdate=get_val(meta2, "discoverdate") or "—",
            maxappmag=get_val(meta2, "maxappmag") or "—",
            maxdate=get_val(meta2, "maxdate") or "—",
            maxabsmag=get_val(meta2, "maxabsmag") or "—",
            lumdist=get_val(meta2, "lumdist") or "—",
            redshift=z, host=get_val(meta2, "host") or "—",
            dist_ly_str="Millions of Light-Years", lifecycle=lc,
        )
        story = generate_story_article_html(
            name=name, meta=meta2, claimedtype=ctype,
            discoverdate=get_val(meta2, "discoverdate") or "—",
            discoverer=get_val(meta2, "discoverer") or "—",
            maxappmag=get_val(meta2, "maxappmag") or "—",
            maxdate=get_val(meta2, "maxdate") or "—",
            maxabsmag=get_val(meta2, "maxabsmag") or "—",
            lumdist=get_val(meta2, "lumdist") or "—",
            redshift=z, host=get_val(meta2, "host") or "—",
            host_offset_str="—", ra_str="—", dec_str="—",
            dist_ly_str="Millions of Light-Years", lifecycle=lc,
        )
        blob = plain(lc.get("cockpit_notice", "")) + " " + plain(lc.get("story_guidance_html", ""))
        blob += " " + " ".join(plain(f.get("answer", "")) for f in faqs) + " " + plain(story)
        for phrase in ALWAYS_FORBIDDEN:
            if phrase in blob:
                results["fabricated_claims"].append({"name": name, "phrase": phrase, "ctype": ctype})
        if ctype_l in UNCLASSIFIED_TYPES:
            for phrase in UNCLASS_FORBIDDEN:
                if phrase in blob:
                    results["fabricated_claims"].append({"name": name, "phrase": phrase, "ctype": ctype})
        results["render_ok"] += 1

        if nphot == 0:
            results["missing_but_valid"]["no_photometry"] += 1
        if not (meta2.get("spectra") or []):
            results["missing_but_valid"]["no_spectrum"] += 1
        if z in ("—", "", None):
            results["missing_but_valid"]["no_redshift"] += 1
        if ctype_l in UNCLASSIFIED_TYPES:
            results["missing_but_valid"]["unclassified"] += 1

        ztf = None
        for a in meta2.get("alias") or []:
            val = a.get("value") if isinstance(a, dict) else str(a)
            if val and str(val).startswith("ZTF") and len(str(val)) >= 12:
                if year and str(val)[3:5] == f"{year % 100:02d}":
                    ztf = str(val)
                    break
                ztf = ztf or str(val)
        if not ztf:
            results["upstream_match"]["no_ztf"] += 1
            continue
        results["upstream_match"]["compared"] += 1
        lc_up = get_alerce_lightcurve(ztf, max_cache_age=86400)
        if not lc_up:
            results["upstream_match"]["alerce_fail"] += 1
            continue
        up_dets = len(lc_up.get("detections") or [])
        local_ztf = sum(
            1 for p in (meta2.get("photometry") or [])
            if isinstance(p, dict) and not p.get("upperlimit")
            and str(p.get("telescope", "")).upper() == "ZTF"
        )
        results["alerce_compare"].append(
            {"name": name, "ztf": ztf, "local_ztf": local_ztf, "upstream": up_dets, "local_total": nphot}
        )
        if local_ztf <= up_dets:
            results["upstream_match"]["local_dets_leq_upstream"] += 1
        else:
            results["upstream_match"]["local_dets_gt_upstream"] += 1

    out = Path("/tmp/independent_verification.json")
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    bad = (
        results["fabricated_claims"]
        or results["m_current_set_without_fit"]
        or results["peak_from_single_epoch_claims"]
    )
    print(json.dumps({k: v for k, v in results.items() if k != "alerce_compare"}, indent=2))
    print("RESULT:", "FAIL" if bad else "PASS", f"(wrote {out})")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
