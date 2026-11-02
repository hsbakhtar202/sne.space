#!/usr/bin/env python3
"""Case-sensitive identity audit for the P0B staging corpus.

Uses ``git ls-tree`` (exact blob paths) — never filesystem readdir — so macOS
case-insensitive volumes cannot hide collisions. Optionally re-extracts
collision pairs into a Linux container mount for dual-file proof.

Does not write to the live event volume.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def git_json_paths(repo: Path) -> list[str]:
    out = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        cwd=str(repo),
        text=True,
    )
    return [line for line in out.splitlines() if line.endswith(".json")]


def audit_repo(repo: Path) -> dict[str, Any]:
    paths = git_json_paths(repo)
    by_exact: dict[str, str] = {}
    by_lower: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        base = path.rsplit("/", 1)[-1]
        stem = base[:-5] if base.endswith(".json") else base
        by_exact[stem] = path
        by_lower[stem.lower()].append(stem)

    collisions = {
        low: sorted(set(names))
        for low, names in by_lower.items()
        if len(set(names)) > 1
    }

    # Cross-check: top-level object key vs filename stem (exact, no lowercasing).
    identity_mismatches: list[dict[str, Any]] = []
    sample_checked = 0
    for stem, rel in list(by_exact.items())[:5000]:
        # Skip if this stem is part of a case-collision set — FS may be wrong.
        if stem.lower() in collisions:
            continue
        fp = repo / rel
        if not fp.is_file():
            continue
        try:
            raw = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as exc:
            identity_mismatches.append(
                {"stem": stem, "error": f"json:{exc.__class__.__name__}"}
            )
            continue
        if not isinstance(raw, dict) or not raw:
            identity_mismatches.append({"stem": stem, "error": "empty_or_non_object"})
            continue
        keys = list(raw.keys())
        sample_checked += 1
        if stem not in raw:
            identity_mismatches.append(
                {
                    "stem": stem,
                    "error": "filename_stem_absent_from_object_keys",
                    "keys": keys[:5],
                }
            )

    return {
        "repo": repo.name,
        "git_json_paths": len(paths),
        "exact_stems": len(by_exact),
        "case_collision_groups": len(collisions),
        "case_collisions": collisions,
        "identity_sample_checked": sample_checked,
        "identity_mismatches": identity_mismatches[:50],
        "identity_mismatch_n": len(identity_mismatches),
    }


def docker_extract_collisions(
    repo: Path, collisions: dict[str, list[str]], out_dir: Path
) -> dict[str, Any]:
    """Prove both casings exist as distinct files on a Linux FS.

    Extraction must happen *inside* the container. Writing both casings onto a
    macOS case-insensitive host path first collapses them before Docker mounts.
    """
    if not collisions:
        return {"skipped": True, "reason": "no_collisions"}
    out_dir.mkdir(parents=True, exist_ok=True)

    # Host-side metadata from git (exact paths) — content compare via sha256.
    pairs: list[dict[str, Any]] = []
    collision_plan: list[dict[str, Any]] = []
    paths = git_json_paths(repo)
    for low, names in sorted(collisions.items()):
        group: dict[str, Any] = {"group": low, "members": []}
        for stem in names:
            matches = [p for p in paths if p.rsplit("/", 1)[-1] == f"{stem}.json"]
            if not matches:
                pairs.append({"stem": stem, "error": "path_not_in_git"})
                continue
            rel = matches[0]
            blob = subprocess.check_output(
                ["git", "show", f"HEAD:{rel}"], cwd=str(repo)
            )
            digest = hashlib.sha256(blob).hexdigest()
            try:
                raw = json.loads(blob.decode("utf-8"))
                keys = list(raw.keys()) if isinstance(raw, dict) else []
            except Exception:
                keys = []
            row = {
                "stem": stem,
                "git_path": rel,
                "bytes": len(blob),
                "sha256": digest,
                "object_keys": keys[:5],
                "stem_in_keys": stem in keys,
                "keys_equal_stem_casefold": any(
                    k.casefold() == stem.casefold() for k in keys
                ),
            }
            pairs.append(row)
            group["members"].append({"stem": stem, "git_path": rel, "sha256": digest})
        # Distinct content?
        digests = {m["sha256"] for m in group["members"]}
        group["distinct_blob_sha256"] = len(digests)
        group["same_content_different_case"] = len(digests) == 1 and len(group["members"]) > 1
        collision_plan.append(group)

    plan_path = out_dir / "collision_plan.json"
    plan_path.write_text(json.dumps(collision_plan, indent=2), encoding="utf-8")

    linux_proof: dict[str, Any]
    try:
        # Extract inside Linux so both casings remain distinct. Host APFS would
        # collapse ASASSN-15bd.json vs asassn-15bd.json before the mount.
        py = (
            "import json, pathlib, subprocess\n"
            "plan=json.loads(pathlib.Path('/plan/collision_plan.json').read_text())\n"
            "out=[]\n"
            "root=pathlib.Path('/out')\n"
            "root.mkdir(parents=True, exist_ok=True)\n"
            "for g in plan:\n"
            "  gdir=root/g['group']\n"
            "  gdir.mkdir(parents=True, exist_ok=True)\n"
            "  files=[]\n"
            "  for m in g['members']:\n"
            "    blob=subprocess.check_output(['git','-C','/repo','show',f\"HEAD:{m['git_path']}\"])\n"
            "    dest=gdir/(m['stem']+'.json')\n"
            "    dest.write_bytes(blob)\n"
            "    files.append(dest.name)\n"
            "  listed=sorted(p.name for p in gdir.glob('*.json'))\n"
            "  out.append({'group':g['group'],'written':sorted(files),'listed':listed,'n':len(listed),"
            "'distinct_blob_sha256':g.get('distinct_blob_sha256'),"
            "'same_content_different_case':g.get('same_content_different_case')})\n"
            "print(json.dumps(out))\n"
        )
        # IMPORTANT: /out must be container-local. A bind mount of a macOS path
        # is still case-insensitive and collapses the dual casings we are proving.
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{repo.resolve()}:/repo:ro",
            "-v",
            f"{out_dir.resolve()}:/plan:ro",
            "python:3.12-slim",
            "bash",
            "-lc",
            "export DEBIAN_FRONTEND=noninteractive; "
            "apt-get update -qq && apt-get install -y -qq git >/dev/null "
            "&& python - <<'PY'\n" + py + "PY",
        ]
        raw_out = subprocess.check_output(cmd, text=True, timeout=600)
        lines = [ln for ln in raw_out.splitlines() if ln.startswith("[")]
        linux_proof = {
            "ok": True,
            "groups": json.loads(lines[-1]) if lines else [],
            "note": (
                "extracted via git show into container-local /out "
                "(case-sensitive; not a macOS bind mount)"
            ),
        }
    except Exception as exc:
        linux_proof = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}

    return {
        "pairs": pairs,
        "collision_plan_summary": {
            "groups": len(collision_plan),
            "same_content_different_case": sum(
                1 for g in collision_plan if g.get("same_content_different_case")
            ),
            "distinct_content_pairs": sum(
                1
                for g in collision_plan
                if int(g.get("distinct_blob_sha256") or 0) > 1
            ),
        },
        "linux_proof": linux_proof,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--staging-root",
        type=Path,
        default=ROOT / "staging/astrocats-restore",
    )
    ap.add_argument("--docker-proof", action="store_true")
    args = ap.parse_args()
    repos = args.staging_root / "repos"
    reports = []
    all_collisions: dict[str, dict[str, list[str]]] = {}
    for repo in sorted(repos.iterdir()) if repos.is_dir() else []:
        if not (repo / ".git").is_dir():
            continue
        print(f"audit {repo.name}…", flush=True)
        r = audit_repo(repo)
        reports.append(r)
        if r["case_collisions"]:
            all_collisions[repo.name] = r["case_collisions"]

    docker_results = {}
    if args.docker_proof and all_collisions:
        proof_root = args.staging_root / "identity-audit-linux"
        for repo_name, coll in all_collisions.items():
            docker_results[repo_name] = docker_extract_collisions(
                repos / repo_name, coll, proof_root / repo_name
            )

    summary = {
        "drawn_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "git ls-tree exact paths; no case normalization for identity",
        "repos": reports,
        "total_case_collision_groups": sum(
            r["case_collision_groups"] for r in reports
        ),
        "total_identity_mismatches": sum(r["identity_mismatch_n"] for r in reports),
        "docker_proof": docker_results or None,
        "live_data_untouched": True,
        "warnings": [
            "macOS APFS default is case-insensitive; filesystem file counts understate "
            "distinct git paths when case-collision groups exist.",
            "Do not treat casefold-equal stems as the same astronomical object.",
        ],
    }
    out = args.staging_root / "IDENTITY_AUDIT_REPORT.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "total_case_collision_groups": summary["total_case_collision_groups"],
                "total_identity_mismatches": summary["total_identity_mismatches"],
                "docker_proof_repos": list(docker_results),
            },
            indent=2,
        )
    )
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
