#!/usr/bin/env python3
"""Non-destructive, provenance-aware P0B merge (staging only).

Dry-run by default against a *clone* of a production-like event tree.
Never targets the live production volume unless ``--i-understand-live`` is set
(and even then refuses paths that look like the deployed sne.space output).

Policy:
  - Missing locally, present upstream → copy into staging target (add-only)
  - Present both, identical observation fingerprint → skip
  - Present both, differing → conflict; write both sides under
    ``_merge_conflicts/<name>/`` and do **not** overwrite the local file
  - Partial upstream vs richer local → keep local; record in report
  - Case-collision stems → never casefold-merge. If a Linux materialize
    volume/source provides both exact filenames, copy both as distinct
    objects; otherwise hold for case-sensitive target (not discard).

Produces before/after reconciliation JSON.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent

LIVE_MARKERS = (
    ROOT / "serve/www/astrocats/astrocats/supernovae/output",
)


def _fingerprint(meta: dict) -> str:
    phot = meta.get("photometry") or []
    spec = meta.get("spectra") or []
    payload = {
        "phot": [
            {
                "t": p.get("time"),
                "m": p.get("magnitude"),
                "b": p.get("band") or p.get("filter"),
                "ul": p.get("upperlimit"),
                "s": p.get("source"),
            }
            for p in phot
            if isinstance(p, dict)
        ],
        "spec_n": len(spec) if isinstance(spec, list) else 0,
        "sources_n": len(meta.get("sources") or []),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def _load_meta(path: Path, name: str) -> Optional[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    if name in raw and isinstance(raw[name], dict):
        return raw[name]
    for v in raw.values():
        if isinstance(v, dict):
            return v
    return None


def _epoch_dir(name: str) -> str:
    """Best-effort year bin matching AstroCats layout."""
    # AT2021x / SN1999x → year from digits after prefix
    digits = "".join(ch for ch in name if ch.isdigit())
    if len(digits) >= 4:
        year = int(digits[:4])
    else:
        return "sne-unknown"
    if year < 1990:
        return "sne-pre-1990"
    if year < 2000:
        return "sne-1990-1999"
    if year < 2005:
        return "sne-2000-2004"
    if year < 2010:
        return "sne-2005-2009"
    if year < 2015:
        return "sne-2010-2014"
    if year < 2020:
        return "sne-2015-2019"
    if year < 2025:
        return "sne-2020-2024"
    return "sne-2025-2029"


def index_tree(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*.json"):
        if "_merge_conflicts" in p.parts or p.name.startswith("."):
            continue
        out[p.stem] = p
    return out


def index_upstream(repos: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for part in repos.iterdir() if repos.is_dir() else []:
        if not part.is_dir() or not (part / ".git").is_dir():
            continue
        for p in part.rglob("*.json"):
            if ".git" in p.parts:
                continue
            # Prefer larger file on collision within same exact stem
            prev = out.get(p.stem)
            if prev is None or p.stat().st_size >= prev.stat().st_size:
                out[p.stem] = p
    return out


def merge(
    *,
    upstream: dict[str, Path],
    target_root: Path,
    conflict_root: Path,
    apply: bool,
    case_collision_stems: set[str],
    case_collision_files: Optional[dict[str, Path]] = None,
) -> dict[str, Any]:
    before = index_tree(target_root)
    actions = {
        "add": [],
        "skip_identical": [],
        "conflict": [],
        "keep_local_richer": [],
        "case_collision_held": [],
        "case_collision_materialized": [],
        "upstream_only_partial_note": [],
    }
    collision_files = case_collision_files or {}

    def _materialize_exact(name: str, exact: Path) -> None:
        dest = target_root / _epoch_dir(name) / f"{name}.json"
        actions["case_collision_materialized"].append(
            {"name": name, "dest": str(dest), "bytes": exact.stat().st_size}
        )
        if not apply:
            return
        if dest.exists():
            lmeta = _load_meta(dest, name)
            umeta = _load_meta(exact, name)
            if lmeta and umeta and _fingerprint(lmeta) != _fingerprint(umeta):
                actions["conflict"].append(
                    {"name": name, "reason": "collision_materialize_vs_local"}
                )
                cdir = conflict_root / name
                cdir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, cdir / "local.json")
                shutil.copy2(exact, cdir / "upstream.json")
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(exact, dest)

    processed_collisions: set[str] = set()
    for name, up in sorted(upstream.items()):
        if name.lower() in case_collision_stems or name in case_collision_stems:
            exact = collision_files.get(name)
            if exact is not None and exact.is_file():
                _materialize_exact(name, exact)
                processed_collisions.add(name)
                continue
            actions["case_collision_held"].append(
                {
                    "name": name,
                    "reason": "await_case_sensitive_dual_preserve",
                    "note": "not discarded; needs Linux exact-name materialize",
                }
            )
            processed_collisions.add(name)
            continue
        local = before.get(name)
        umeta = _load_meta(up, name)
        if umeta is None:
            continue
        ufp = _fingerprint(umeta)
        if local is None:
            dest = target_root / _epoch_dir(name) / f"{name}.json"
            actions["add"].append({"name": name, "dest": str(dest), "bytes": up.stat().st_size})
            if apply:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(up, dest)
            continue
        lmeta = _load_meta(local, name)
        if lmeta is None:
            actions["conflict"].append({"name": name, "reason": "local_unreadable"})
            continue
        lfp = _fingerprint(lmeta)
        if lfp == ufp:
            actions["skip_identical"].append(name)
            continue
        # Observation-level: if local has more photometry points, keep local
        l_n = len(lmeta.get("photometry") or [])
        u_n = len(umeta.get("photometry") or [])
        if l_n > u_n:
            actions["keep_local_richer"].append(
                {"name": name, "local_phot": l_n, "upstream_phot": u_n}
            )
            continue
        # True conflict — stage both, do not overwrite
        actions["conflict"].append(
            {
                "name": name,
                "reason": "fingerprint_mismatch",
                "local_phot": l_n,
                "upstream_phot": u_n,
                "local_fp": lfp[:12],
                "upstream_fp": ufp[:12],
            }
        )
        if apply:
            cdir = conflict_root / name
            cdir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local, cdir / "local.json")
            shutil.copy2(up, cdir / "upstream.json")

    # Second casing often absent from macOS upstream index — materialize explicitly.
    for name, exact in sorted(collision_files.items()):
        if name in processed_collisions:
            continue
        if exact.is_file():
            _materialize_exact(name, exact)
            processed_collisions.add(name)

    after = index_tree(target_root) if apply else dict(before)
    if not apply:
        # Project after for dry-run
        after = dict(before)
        for row in actions["add"]:
            after[row["name"]] = Path(row["dest"])
        for row in actions["case_collision_materialized"]:
            after[row["name"]] = Path(row["dest"])

    return {
        "before_count": len(before),
        "after_count": len(after),
        "added": len(actions["add"]),
        "skipped_identical": len(actions["skip_identical"]),
        "conflicts": len(actions["conflict"]),
        "keep_local_richer": len(actions["keep_local_richer"]),
        "case_collision_held": len(actions["case_collision_held"]),
        "case_collision_materialized": len(actions["case_collision_materialized"]),
        "actions": actions,
        "apply": apply,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--staging-root",
        type=Path,
        default=ROOT / "staging/astrocats-restore",
    )
    ap.add_argument(
        "--target",
        type=Path,
        required=True,
        help="Staging clone of event tree (not production)",
    )
    ap.add_argument(
        "--identity-audit",
        type=Path,
        default=None,
        help="IDENTITY_AUDIT_REPORT.json for case-collision refusals",
    )
    ap.add_argument("--apply", action="store_true", help="Perform copies (still staging-only)")
    ap.add_argument(
        "--collision-source",
        type=Path,
        default=None,
        help="Directory of exact-name collision JSON files (from Linux materialize export)",
    )
    ap.add_argument(
        "--i-understand-live",
        action="store_true",
        help="Required only if target resolves to a live marker path (still refused)",
    )
    args = ap.parse_args()

    target = args.target.resolve()
    for marker in LIVE_MARKERS:
        if target == marker.resolve() or marker.resolve() in target.parents:
            raise SystemExit(
                f"Refusing target under live marker {marker}. "
                "Clone the volume to a staging path first."
            )
        if str(target).startswith(str(marker.resolve())) and not args.i_understand_live:
            raise SystemExit("Refusing live-like target path")

    case_stems: set[str] = set()
    audit_path = args.identity_audit or (args.staging_root / "IDENTITY_AUDIT_REPORT.json")
    if audit_path.is_file():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        for repo in audit.get("repos") or []:
            for names in (repo.get("case_collisions") or {}).values():
                for n in names:
                    case_stems.add(n)
                    case_stems.add(n.lower())

    upstream = index_upstream(args.staging_root / "repos")
    collision_files: dict[str, Path] = {}
    if args.collision_source and args.collision_source.is_dir():
        manifest = args.collision_source / "manifest.json"
        if manifest.is_file():
            # Case-escaped host export from astrocats_collision_materialize.
            for row in json.loads(manifest.read_text(encoding="utf-8")):
                esc = args.collision_source / str(row.get("escaped") or "")
                stem = str(row.get("stem") or "")
                if stem and esc.is_file():
                    collision_files[stem] = esc
        else:
            for p in args.collision_source.rglob("*.json"):
                collision_files[p.stem] = p
    conflict_root = args.staging_root / "merge-conflicts"
    before_names = sorted(index_tree(target))
    result = merge(
        upstream=upstream,
        target_root=target,
        conflict_root=conflict_root,
        apply=args.apply,
        case_collision_stems=case_stems,
        case_collision_files=collision_files,
    )
    after_names = sorted(index_tree(target)) if args.apply else sorted(
        set(before_names) | {a["name"] for a in result["actions"]["add"]}
    )

    report = {
        "drawn_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": str(target),
        "apply": args.apply,
        "live_data_untouched": True,
        "before": {"event_files": len(before_names)},
        "after": {"event_files": len(after_names)},
        "reconciliation": result,
        "policy": [
            "add missing only",
            "never overwrite local on fingerprint mismatch",
            "stage conflicts under merge-conflicts/",
            "hold case-collision stems until exact dual materialize (no casefold)",
            "do not pad partial upstream arrays",
        ],
    }
    out = args.staging_root / (
        "MERGE_DRY_RUN_REPORT.json" if not args.apply else "MERGE_APPLY_REPORT.json"
    )
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "apply": args.apply,
                "before": report["before"],
                "after": report["after"],
                "added": result["added"],
                "conflicts": result["conflicts"],
                "keep_local_richer": result["keep_local_richer"],
                "case_collision_held": result["case_collision_held"],
                "case_collision_materialized": result["case_collision_materialized"],
            },
            indent=2,
        )
    )
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
