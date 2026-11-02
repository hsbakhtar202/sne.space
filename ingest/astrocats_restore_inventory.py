#!/usr/bin/env python3
"""P0B read-only inventory: pin AstroCats GitHub partitions vs production index.

Does NOT download or sync event bodies. Writes a restore manifest for staging.

Usage:
  python3 -m ingest.astrocats_restore_inventory \\
    --catalog docs/audit/prod_truth_evidence/prod_catalog.min.json \\
    --out docs/audit/P0B_RESTORE_MANIFEST.json
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PARTITIONS = [
    "sne-pre-1990",
    "sne-1990-1999",
    "sne-2000-2004",
    "sne-2005-2009",
    "sne-2010-2014",
    "sne-2015-2019",
    "sne-2020-2024",
]

ORG = "astrocatalogs"
UA = {"User-Agent": "sne-space-p0b-inventory/1.0", "Accept": "application/vnd.github+json"}


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def pin_partition(name: str) -> dict[str, Any]:
    meta = _get_json(f"https://api.github.com/repos/{ORG}/{name}")
    branch = meta.get("default_branch") or "master"
    ref = _get_json(f"https://api.github.com/repos/{ORG}/{name}/git/ref/heads/{branch}")
    sha = (ref.get("object") or {}).get("sha")
    tree = _get_json(
        f"https://api.github.com/repos/{ORG}/{name}/git/trees/{sha}?recursive=1"
    )
    files = []
    for ent in tree.get("tree") or []:
        if ent.get("type") != "blob":
            continue
        path = str(ent.get("path") or "")
        if path.endswith(".json") and "/" not in path.strip("/"):
            # top-level event JSON (AstroCats layout)
            files.append({"name": path[:-5], "path": path, "sha": ent.get("sha"), "size": ent.get("size")})
        elif path.endswith(".json"):
            # nested
            base = path.rsplit("/", 1)[-1]
            if base.endswith(".json"):
                files.append(
                    {
                        "name": base[:-5],
                        "path": path,
                        "sha": ent.get("sha"),
                        "size": ent.get("size"),
                    }
                )
    # de-dupe by name (prefer larger)
    by: dict[str, dict] = {}
    for f in files:
        prev = by.get(f["name"])
        if prev is None or int(f.get("size") or 0) >= int(prev.get("size") or 0):
            by[f["name"]] = f
    return {
        "repo": f"{ORG}/{name}",
        "html_url": meta.get("html_url"),
        "default_branch": branch,
        "commit_sha": sha,
        "pushed_at": meta.get("pushed_at"),
        "event_json_count": len(by),
        "truncated": tree.get("truncated"),
        "names": sorted(by.keys()),
        "files_by_name": by,
    }


def catalog_names(path: Path) -> set[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"catalog must be a JSON array: {path}")
    out = set()
    for it in raw:
        if isinstance(it, dict) and it.get("name"):
            out.add(str(it["name"]))
    return out


def local_event_names(root: Path) -> dict[str, str]:
    """Map event name -> relative path under local output."""
    found: dict[str, str] = {}
    if not root.is_dir():
        return found
    for p in root.glob("sne-*/*.json"):
        found[p.stem] = str(p.relative_to(root))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--local-output", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sleep", type=float, default=0.4, help="delay between GitHub API calls")
    args = ap.parse_args()

    idx = catalog_names(args.catalog)
    local_root = args.local_output
    if local_root is None:
        local_root = (
            Path(__file__).resolve().parent.parent
            / "serve/www/astrocats/astrocats/supernovae/output"
        )
    local = local_event_names(local_root)

    partitions = []
    upstream_names: set[str] = set()
    for part in PARTITIONS:
        print(f"pinning {part}…", flush=True)
        info = pin_partition(part)
        partitions.append({k: v for k, v in info.items() if k != "files_by_name"})
        upstream_names.update(info["names"])
        # keep file map separately to avoid huge duplicate in summary
        partitions[-1]["sample_names"] = info["names"][:20]
        time.sleep(args.sleep)

    recoverable = sorted(idx & upstream_names)
    index_only = sorted(idx - upstream_names)
    upstream_only = sorted(upstream_names - idx)
    local_present = sorted(idx & set(local))
    local_missing_vs_index = sorted(idx - set(local))

    # Conflicts: present locally AND upstream (need provenance merge in staging)
    conflict_candidates = sorted(set(local) & upstream_names & idx)

    manifest = {
        "drawn_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "GitHub git tree listing of official AstroCats partitions; compare to prod catalog.min.json + local output",
        "sources": {
            "B_upstream": f"https://github.com/{ORG} partitions {PARTITIONS}",
            "A_local": str(local_root),
            "C_vultr": "not accessible this run",
        },
        "index_n": len(idx),
        "upstream_event_json_n": len(upstream_names),
        "local_event_json_n": len(local),
        "partitions": partitions,
        "coverage": {
            "recoverable_from_upstream_vs_index": len(recoverable),
            "recoverable_pct_of_index": round(100.0 * len(recoverable) / max(1, len(idx)), 2),
            "index_not_in_upstream": len(index_only),
            "upstream_not_in_index": len(upstream_only),
            "local_present_vs_index": len(local_present),
            "local_missing_vs_index": len(local_missing_vs_index),
            "conflict_candidates_local_and_upstream": len(conflict_candidates),
        },
        "examples": {
            "index_not_in_upstream": index_only[:40],
            "recoverable": recoverable[:40],
            "conflict_candidates": conflict_candidates[:40],
        },
        "warnings": [
            "Upstream partitions last pushed ~2022; not a complete live catalog.",
            "Do not production-sync until staging dry-run + provenance merge policy is applied.",
            "cp -n alone is insufficient; conflicting files need observation-level merge.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    md = args.out.with_suffix(".md")
    cov = manifest["coverage"]
    md.write_text(
        "\n".join(
            [
                "# P0B Restore Manifest (inventory only)",
                "",
                f"Drawn: `{manifest['drawn_at_utc']}`",
                "",
                "| Metric | Value |",
                "| --- | ---: |",
                f"| Production index names | {manifest['index_n']} |",
                f"| Upstream event JSON names (union) | {manifest['upstream_event_json_n']} |",
                f"| Local laptop event JSON | {manifest['local_event_json_n']} |",
                f"| Recoverable from upstream ∩ index | {cov['recoverable_from_upstream_vs_index']} ({cov['recoverable_pct_of_index']}%) |",
                f"| Index not in upstream | {cov['index_not_in_upstream']} |",
                f"| Conflict candidates (local∩upstream∩index) | {cov['conflict_candidates_local_and_upstream']} |",
                "",
                "## Pinned partitions",
                "",
                *[
                    f"- `{p['repo']}` @ `{p['commit_sha'][:12]}` — {p['event_json_count']} JSON "
                    f"(pushed {p['pushed_at']})"
                    for p in partitions
                ],
                "",
                "## Next steps (staging only)",
                "",
                "1. Sparse-checkout / download only names in `index_not_on_volume` ∩ upstream.",
                "2. Provenance-aware merge for conflict candidates; never blind overwrite enriched files.",
                "3. Verify restored arrays vs advertised photolink/spectralink.",
                "4. Report remaining gaps before any production sync.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(manifest["coverage"], indent=2))
    print("wrote", args.out)
    print("wrote", md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
