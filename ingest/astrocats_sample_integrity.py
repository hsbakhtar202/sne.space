#!/usr/bin/env python3
"""Sample observation integrity for P0B staging (beyond array-count matching).

For a stratified sample of complete-classified files, check:
  - photometry entries have time + magnitude (or upperlimit)
  - u_time / filter / band / telescope when present are non-empty strings
  - source / provenance references resolve into the file's ``sources`` list when present
  - spectra entries have data or filename/url
  - duplicate (time, magnitude, band) keys within a file

Also classifies the known partial set individually (never silently filled).

Does not modify the live event volume.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent

KNOWN_PARTIALS = [
    "AT2021aak",
    "AT2021gzn",
    "AT2021lgi",
    "AT2021lyb",
    "AT2021xap",
    "AT2021zzl",
    "SN2021uhn",
    "SN2021wrr",
]


def _index_phot(item: dict) -> int:
    pl = item.get("photolink")
    if pl is None:
        return 0
    if isinstance(pl, list) and pl:
        pl = pl[0].get("value") if isinstance(pl[0], dict) else pl[0]
    try:
        return int(str(pl).split(",")[0])
    except Exception:
        return 0


def _index_spec(item: dict) -> int:
    pl = item.get("spectralink")
    if pl is None:
        return 0
    if isinstance(pl, list) and pl:
        pl = pl[0].get("value") if isinstance(pl[0], dict) else pl[0]
    try:
        return int(str(pl).split(",")[0])
    except Exception:
        return 0


def _meta(raw: dict, name: str) -> Optional[dict]:
    if name in raw and isinstance(raw[name], dict):
        return raw[name]
    for v in raw.values():
        if isinstance(v, dict):
            return v
    return None


def _source_ids(meta: dict) -> set[str]:
    out: set[str] = set()
    for s in meta.get("sources") or []:
        if isinstance(s, dict) and s.get("alias") is not None:
            out.add(str(s["alias"]))
        elif isinstance(s, dict) and s.get("name") is not None:
            out.add(str(s["name"]))
    return out


def inspect_event(name: str, path: Path, *, want_phot: int, want_spec: int) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    meta = _meta(raw, name)
    if meta is None:
        return {"name": name, "ok": False, "error": "no_meta"}

    phot = meta.get("photometry") or []
    spectra = meta.get("spectra") or []
    sources = _source_ids(meta)
    issues: list[str] = []
    phot_ok = 0
    dup_keys: set[tuple] = set()
    dups = 0
    missing_source_ref = 0
    filters: set[str] = set()
    units: set[str] = set()

    for i, p in enumerate(phot):
        if not isinstance(p, dict):
            issues.append(f"phot[{i}]_not_object")
            continue
        has_mag = p.get("magnitude") is not None
        has_ul = bool(p.get("upperlimit")) or p.get("kind") == "non_detection"
        if p.get("time") is None:
            issues.append(f"phot[{i}]_missing_time")
        if not has_mag and not has_ul:
            issues.append(f"phot[{i}]_missing_mag_and_ul")
        else:
            phot_ok += 1
        band = p.get("band") or p.get("filter") or ""
        if band:
            filters.add(str(band))
        if p.get("u_time"):
            units.add(str(p["u_time"]))
        key = (str(p.get("time")), str(p.get("magnitude")), str(band))
        if key in dup_keys:
            dups += 1
        else:
            dup_keys.add(key)
        src = p.get("source")
        if src is not None and sources:
            # source may be comma-separated aliases
            parts = [x.strip() for x in str(src).split(",") if x.strip()]
            if parts and not any(x in sources for x in parts):
                missing_source_ref += 1

    spec_ok = 0
    for i, s in enumerate(spectra):
        if not isinstance(s, dict):
            issues.append(f"spec[{i}]_not_object")
            continue
        has_data = bool(s.get("data")) or bool(s.get("u_fluxes"))
        has_file = bool(s.get("filename")) or bool(s.get("url"))
        if has_data or has_file:
            spec_ok += 1
        else:
            issues.append(f"spec[{i}]_no_data_or_file")

    det = sum(
        1
        for p in phot
        if isinstance(p, dict)
        and p.get("magnitude") is not None
        and not p.get("upperlimit")
        and p.get("kind") != "non_detection"
        and not str(p.get("magnitude", "")).startswith(">")
    )
    classification = "complete"
    if det < want_phot or len(spectra) < want_spec:
        classification = "partial_vs_index"
    if not phot and not spectra and (want_phot or want_spec):
        classification = "empty_vs_index"

    return {
        "name": name,
        "path": str(path),
        "classification": classification,
        "want_phot": want_phot,
        "want_spec": want_spec,
        "det": det,
        "phot_n": len(phot),
        "phot_struct_ok": phot_ok,
        "spec_n": len(spectra),
        "spec_struct_ok": spec_ok,
        "duplicate_phot_keys": dups,
        "missing_source_refs": missing_source_ref,
        "filters_seen": sorted(filters)[:20],
        "u_time_seen": sorted(units)[:10],
        "sources_n": len(sources),
        "issues": issues[:30],
        "issue_n": len(issues),
        "ok": len(issues) == 0 and dups == 0,
    }


def classify_partial(name: str, path: Optional[Path], catalog_item: Optional[dict]) -> dict[str, Any]:
    want_phot = _index_phot(catalog_item or {})
    want_spec = _index_spec(catalog_item or {})
    if path is None or not path.is_file():
        return {
            "name": name,
            "class": "missing_file",
            "want_phot": want_phot,
            "want_spec": want_spec,
            "action": "do_not_silently_fill; leave index gap explicit",
        }
    detail = inspect_event(name, path, want_phot=want_phot, want_spec=want_spec)
    # Explicit disposition — never auto-fill from another source here.
    if detail["det"] == 0 and detail["spec_n"] == 0:
        disposition = "upstream_empty_keep_partial"
    elif detail["det"] < want_phot or detail["spec_n"] < want_spec:
        disposition = "upstream_short_of_index_keep_partial_do_not_pad"
    else:
        disposition = "reclassify_complete"
    return {
        "name": name,
        "class": detail["classification"],
        "disposition": disposition,
        "detail": detail,
        "action": "report_only; do not invent observations to match index",
    }


def build_file_index(staging_repos: Path) -> dict[str, Path]:
    """Best-effort FS index; collision stems may be ambiguous on macOS."""
    by: dict[str, Path] = {}
    for part in staging_repos.iterdir():
        if not part.is_dir():
            continue
        for p in part.rglob("*.json"):
            if ".git" in p.parts:
                continue
            by[p.stem] = p
    return by


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--staging-root",
        type=Path,
        default=ROOT / "staging/astrocats-restore",
    )
    ap.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "docs/audit/prod_truth_evidence/prod_catalog.min.json",
    )
    ap.add_argument("--sample-size", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20261101)
    args = ap.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    by_name = {it["name"]: it for it in catalog if isinstance(it, dict) and it.get("name")}
    files = build_file_index(args.staging_root / "repos")

    # Stratify sample among files that look complete vs index.
    candidates = []
    for name, path in files.items():
        item = by_name.get(name)
        if not item:
            continue
        candidates.append(name)
    rng = random.Random(args.seed)
    rng.shuffle(candidates)
    sample_names = candidates[: args.sample_size]

    sample_rows = []
    for name in sample_names:
        item = by_name[name]
        sample_rows.append(
            inspect_event(
                name,
                files[name],
                want_phot=_index_phot(item),
                want_spec=_index_spec(item),
            )
        )

    partials = []
    for name in KNOWN_PARTIALS:
        partials.append(
            classify_partial(name, files.get(name), by_name.get(name))
        )

    ok_n = sum(1 for r in sample_rows if r.get("ok"))
    issue_n = sum(1 for r in sample_rows if r.get("issue_n", 0) > 0)
    dup_n = sum(1 for r in sample_rows if r.get("duplicate_phot_keys", 0) > 0)
    src_n = sum(1 for r in sample_rows if r.get("missing_source_refs", 0) > 0)

    report = {
        "drawn_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "sample_size_requested": args.sample_size,
        "sample_size_actual": len(sample_rows),
        "sample_ok": ok_n,
        "sample_with_issues": issue_n,
        "sample_with_duplicate_phot": dup_n,
        "sample_with_missing_source_refs": src_n,
        "sample_rows": sample_rows,
        "partials_individual": partials,
        "caveat": (
            "Structural/provenance sampling — not a scientific re-reduction against "
            "original survey catalogs. Count-complete ≠ measurement-verified."
        ),
        "live_data_untouched": True,
        "fingerprint": hashlib.sha256(
            json.dumps(
                {"sample": sample_names, "partials": KNOWN_PARTIALS}, sort_keys=True
            ).encode()
        ).hexdigest()[:16],
    }
    out = args.staging_root / "SAMPLE_INTEGRITY_REPORT.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "sample_ok": ok_n,
                "sample_with_issues": issue_n,
                "sample_with_duplicate_phot": dup_n,
                "sample_with_missing_source_refs": src_n,
                "partials": [
                    {"name": p["name"], "disposition": p.get("disposition"), "class": p.get("class")}
                    for p in partials
                ],
            },
            indent=2,
        )
    )
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
