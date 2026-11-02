#!/usr/bin/env python3
"""P0B staging sync: download pinned AstroCats partitions into a SEPARATE staging tree.

Never writes under the live ``SNE_DATA_DIR`` / production event volume.

Steps:
  1. Clone/fetch pinned commit SHAs into ``staging/astrocats-restore/repos/``
  2. Validate JSON + photometry/spectra arrays vs production index photolink
  3. Classify each index∩upstream name: complete | partial | invalid | missing
  4. Dry-run conflict report for local∩upstream names (no promote)

Resumable: existing repos at the correct SHA are skipped.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], *, cwd: Optional[Path] = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def ensure_repo(staging_repos: Path, repo: str, branch: str, sha: str) -> dict[str, Any]:
    """Clone or update one partition to the pinned SHA. Returns timing/size stats."""
    name = repo.split("/")[-1]
    dest = staging_repos / name
    url = f"https://github.com/{repo}.git"
    t0 = time.time()
    action = "skip"
    if dest.is_dir() and (dest / ".git").is_dir():
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(dest), text=True
        ).strip()
        if head.startswith(sha[:12]) or head == sha:
            action = "already_pinned"
        else:
            action = "fetch_checkout"
            _run(["git", "fetch", "--depth", "1", "origin", sha], cwd=dest)
            _run(["git", "checkout", "--force", sha], cwd=dest)
    else:
        action = "clone"
        dest.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                branch,
                url,
                str(dest),
            ]
        )
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(dest), text=True
        ).strip()
        if head != sha and not head.startswith(sha[:12]):
            # Shallow clone of branch tip may differ from inventory-time SHA;
            # pin exactly when possible.
            try:
                _run(["git", "fetch", "--depth", "1", "origin", sha], cwd=dest)
                _run(["git", "checkout", "--force", sha], cwd=dest)
            except subprocess.CalledProcessError:
                # Fall back to branch tip; record mismatch for the report.
                pass
    elapsed = time.time() - t0
    # Count JSON files
    json_files = list(dest.rglob("*.json"))
    # Exclude .git
    json_files = [p for p in json_files if ".git" not in p.parts]
    bytes_total = sum(p.stat().st_size for p in json_files)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(dest), text=True
    ).strip()
    return {
        "repo": repo,
        "path": str(dest),
        "action": action,
        "elapsed_s": round(elapsed, 2),
        "head": head,
        "wanted_sha": sha,
        "sha_match": head == sha or head.startswith(sha[:12]),
        "json_files": len(json_files),
        "json_bytes": bytes_total,
    }


def _phot_counts(meta: dict) -> tuple[int, int, int]:
    ph = meta.get("photometry") or []
    det = lim = 0
    for p in ph:
        if not isinstance(p, dict):
            continue
        if p.get("upperlimit") or p.get("kind") == "non_detection" or str(
            p.get("magnitude", "")
        ).startswith(">"):
            lim += 1
        elif p.get("magnitude") is not None:
            det += 1
    spec = len(meta.get("spectra") or []) if isinstance(meta.get("spectra"), list) else 0
    return det, lim, spec


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


def build_name_index(staging_repos: Path) -> dict[str, Path]:
    by: dict[str, Path] = {}
    for part in staging_repos.iterdir():
        if not part.is_dir():
            continue
        for p in part.rglob("*.json"):
            if ".git" in p.parts:
                continue
            name = p.stem
            prev = by.get(name)
            if prev is None or p.stat().st_size >= prev.stat().st_size:
                by[name] = p
    return by


def classify(
    catalog: list[dict],
    upstream_files: dict[str, Path],
    local_files: dict[str, Path],
    *,
    sample_limit: int = 0,
) -> dict[str, Any]:
    """Classify index∩upstream into complete/partial/invalid/missing."""
    complete = partial = invalid = missing = 0
    examples = {"complete": [], "partial": [], "invalid": [], "missing": []}
    checked = 0
    for item in catalog:
        name = item.get("name")
        if not name or name not in upstream_files:
            continue
        checked += 1
        if sample_limit and checked > sample_limit:
            # Still count remaining as unchecked for projection
            break
        path = upstream_files[name]
        want_phot = _index_phot(item)
        want_spec = _index_spec(item)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not raw:
                invalid += 1
                if len(examples["invalid"]) < 10:
                    examples["invalid"].append(name)
                continue
            meta = raw.get(name) or raw[next(iter(raw))]
            if not isinstance(meta, dict):
                invalid += 1
                continue
            det, lim, spec = _phot_counts(meta)
            # Complete: JSON valid and arrays meet-or-exceed advertised counts
            # (index can under-count; failing to meet is partial).
            if det >= want_phot and spec >= want_spec:
                complete += 1
                if len(examples["complete"]) < 10:
                    examples["complete"].append(
                        {"name": name, "det": det, "want_phot": want_phot, "spec": spec}
                    )
            elif det > 0 or spec > 0 or lim > 0:
                partial += 1
                if len(examples["partial"]) < 10:
                    examples["partial"].append(
                        {
                            "name": name,
                            "det": det,
                            "want_phot": want_phot,
                            "spec": spec,
                            "want_spec": want_spec,
                        }
                    )
            else:
                # Valid JSON but empty arrays while index claims data → partial/empty
                if want_phot > 0 or want_spec > 0:
                    partial += 1
                    if len(examples["partial"]) < 10:
                        examples["partial"].append(
                            {"name": name, "det": 0, "want_phot": want_phot, "empty": True}
                        )
                else:
                    complete += 1
        except Exception:
            invalid += 1
            if len(examples["invalid"]) < 10:
                examples["invalid"].append(name)

    # Names in index∩upstream not yet classified because sample truncated:
    recoverable_ids = sum(1 for it in catalog if it.get("name") in upstream_files)
    classified = complete + partial + invalid
    return {
        "recoverable_ids": recoverable_ids,
        "classified": classified,
        "complete": complete,
        "partial": partial,
        "invalid": invalid,
        "missing_file": max(0, recoverable_ids - len(upstream_files)),
        "examples": examples,
        "sample_limit": sample_limit or None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "docs/audit/P0B_RESTORE_MANIFEST.json",
    )
    ap.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "docs/audit/prod_truth_evidence/prod_catalog.min.json",
    )
    ap.add_argument(
        "--staging-root",
        type=Path,
        default=ROOT / "staging/astrocats-restore",
        help="Separate staging directory (never the live event volume)",
    )
    ap.add_argument(
        "--partitions",
        nargs="*",
        default=None,
        help="Optional subset of partition repo names (e.g. sne-2020-2024)",
    )
    ap.add_argument(
        "--validate-sample",
        type=int,
        default=5000,
        help="Max index∩upstream events to fully parse (0 = all present files)",
    )
    ap.add_argument("--skip-clone", action="store_true")
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    staging_repos = args.staging_root / "repos"
    staging_repos.mkdir(parents=True, exist_ok=True)

    # Safety: refuse if staging root looks like the live output tree
    live_marker = ROOT / "serve/www/astrocats/astrocats/supernovae/output"
    if args.staging_root.resolve() == live_marker.resolve():
        raise SystemExit("Refusing to use live output as staging root")

    clone_stats = []
    t_clone0 = time.time()
    if not args.skip_clone:
        for part in manifest.get("partitions") or []:
            repo = part["repo"]
            short = repo.split("/")[-1]
            if args.partitions and short not in args.partitions and repo not in args.partitions:
                continue
            print(f"sync {repo} @ {part['commit_sha'][:12]}…", flush=True)
            st = ensure_repo(
                staging_repos,
                repo,
                part.get("default_branch") or "master",
                part["commit_sha"],
            )
            clone_stats.append(st)
            print(
                f"  {st['action']} files={st['json_files']} "
                f"bytes={st['json_bytes']} elapsed={st['elapsed_s']}s "
                f"sha_match={st['sha_match']}",
                flush=True,
            )
    clone_elapsed = time.time() - t_clone0

    upstream_files = build_name_index(staging_repos)
    local_root = ROOT / "serve/www/astrocats/astrocats/supernovae/output"
    local_files = {
        p.stem: p for p in local_root.glob("sne-*/*.json")
    } if local_root.is_dir() else {}

    t_val0 = time.time()
    classes = classify(
        catalog,
        upstream_files,
        local_files,
        sample_limit=args.validate_sample,
    )
    val_elapsed = time.time() - t_val0

    conflicts = sorted(set(local_files) & set(upstream_files))
    conflict_report = []
    for name in conflicts[:50]:
        lp, up = local_files[name], upstream_files[name]
        try:
            lraw = json.loads(lp.read_text(encoding="utf-8"))
            lmeta = lraw.get(name) or lraw[next(iter(lraw))]
            ld, ll, ls = _phot_counts(lmeta)
        except Exception:
            ld = ll = ls = -1
        try:
            uraw = json.loads(up.read_text(encoding="utf-8"))
            umeta = uraw.get(name) or uraw[next(iter(uraw))]
            ud, ul, us = _phot_counts(umeta)
        except Exception:
            ud = ul = us = -1
        conflict_report.append(
            {
                "name": name,
                "local": {"det": ld, "lim": ll, "spec": ls, "bytes": lp.stat().st_size},
                "upstream": {"det": ud, "lim": ul, "spec": us, "bytes": up.stat().st_size},
                "action": "observation_level_merge_required",
            }
        )

    total_bytes = sum(s.get("json_bytes", 0) for s in clone_stats) or sum(
        p.stat().st_size for p in upstream_files.values()
    )
    files_n = len(upstream_files)
    # Project full restore from measured clone rate if we only did a subset
    measured_files = sum(s.get("json_files", 0) for s in clone_stats)
    measured_bytes = sum(s.get("json_bytes", 0) for s in clone_stats)
    measured_s = sum(s.get("elapsed_s", 0) for s in clone_stats) or clone_elapsed
    target_ids = int(manifest.get("coverage", {}).get("recoverable_from_upstream_vs_index") or 0)

    report = {
        "drawn_at_utc": datetime.now(timezone.utc).isoformat(),
        "staging_root": str(args.staging_root.resolve()),
        "live_data_untouched": True,
        "clone_stats": clone_stats,
        "clone_elapsed_s": round(clone_elapsed, 2),
        "upstream_files_on_disk": files_n,
        "upstream_json_bytes": total_bytes,
        "validation": classes,
        "validation_elapsed_s": round(val_elapsed, 2),
        "conflicts": {
            "n": len(conflicts),
            "sample": conflict_report,
            "note": "Do not promote with cp -n alone; merge observation arrays in staging.",
        },
        "projections": {
            "target_recoverable_ids": target_ids,
            "measured_files_cloned": measured_files,
            "measured_bytes": measured_bytes,
            "measured_clone_seconds": round(measured_s, 2),
            "bytes_per_file": round(measured_bytes / measured_files, 1) if measured_files else None,
            "seconds_per_file": round(measured_s / measured_files, 4) if measured_files else None,
            "projected_full_clone_seconds": (
                round(measured_s * (target_ids / measured_files), 1) if measured_files else None
            ),
            "projected_full_clone_gib": (
                round((measured_bytes * (target_ids / measured_files)) / (1024**3), 2)
                if measured_files
                else None
            ),
            "caveat": (
                "Projections scale by identifier count; actual git pack sizes and "
                "validation cost differ. complete/partial rates are from the validated sample only."
            ),
        },
        "warnings": [
            "Identifier match ≠ observation recovery. See validation.complete vs partial.",
            "SHA may differ from inventory pin if GitHub no longer serves that shallow object.",
            "No files were promoted into the live event volume.",
        ],
    }
    out = args.staging_root / "STAGING_SYNC_REPORT.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "upstream_files_on_disk", "upstream_json_bytes", "validation", "projections", "conflicts"
    ) if k in report}, indent=2)[:4000])
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
