#!/usr/bin/env python3
"""Materialize the 33 case-collision groups onto a case-sensitive Linux volume.

Preserves BOTH exact filenames as distinct event objects. Does not casefold-merge.
Does not write to the live production event volume.

Classification per group:
  - distinct_objects: different blob SHA256 (must keep both)
  - duplicate_objects: identical content, different casing (keep both names; flag)
  - alias_only: reserved for future alias-table work (not auto-inferred here)

Output: docker named volume ``sne-p0b-case-sensitive`` + JSON report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VOLUME = "sne-p0b-case-sensitive"


def git_json_paths(repo: Path) -> list[str]:
    out = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        cwd=str(repo),
        text=True,
    )
    return [line for line in out.splitlines() if line.endswith(".json")]


def load_collision_groups(identity_report: Path) -> dict[str, dict[str, list[str]]]:
    raw = json.loads(identity_report.read_text(encoding="utf-8"))
    out: dict[str, dict[str, list[str]]] = {}
    for repo in raw.get("repos") or []:
        name = repo.get("repo")
        coll = repo.get("case_collisions") or {}
        if name and coll:
            out[str(name)] = {str(k): list(v) for k, v in coll.items()}
    return out


def materialize(staging_root: Path, identity_report: Path) -> dict[str, Any]:
    groups = load_collision_groups(identity_report)
    plan: list[dict[str, Any]] = []
    repos = staging_root / "repos"
    for repo_name, coll in sorted(groups.items()):
        repo = repos / repo_name
        paths = git_json_paths(repo)
        for low, stems in sorted(coll.items()):
            members = []
            for stem in stems:
                matches = [p for p in paths if p.rsplit("/", 1)[-1] == f"{stem}.json"]
                if not matches:
                    members.append({"stem": stem, "error": "missing_in_git"})
                    continue
                rel = matches[0]
                blob = subprocess.check_output(
                    ["git", "show", f"HEAD:{rel}"], cwd=str(repo)
                )
                digest = hashlib.sha256(blob).hexdigest()
                try:
                    obj = json.loads(blob.decode("utf-8"))
                    keys = list(obj.keys()) if isinstance(obj, dict) else []
                except Exception:
                    keys = []
                members.append(
                    {
                        "stem": stem,
                        "git_path": rel,
                        "sha256": digest,
                        "bytes": len(blob),
                        "object_keys": keys[:5],
                        "stem_in_keys": stem in keys,
                    }
                )
            digests = {m["sha256"] for m in members if "sha256" in m}
            if len(digests) > 1:
                kind = "distinct_objects"
            elif len(digests) == 1 and len(members) > 1:
                kind = "duplicate_objects_different_case"
            else:
                kind = "incomplete"
            plan.append(
                {
                    "repo": repo_name,
                    "group": low,
                    "kind": kind,
                    "members": members,
                }
            )

    plan_path = staging_root / "collision-materialize" / "plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    # Ensure docker volume exists (Linux case-sensitive). Also export the 66
    # exact-name files to a host dir so the merge tool's --collision-source can
    # reference them without a docker volume mount on macOS.
    subprocess.run(["docker", "volume", "create", VOLUME], check=False, capture_output=True)
    export_dir = plan_path.parent / "exported"
    export_dir.mkdir(parents=True, exist_ok=True)

    # Extract inside container from mounted git repos + plan.
    script = r"""
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git >/dev/null
python - <<'PY'
import json, pathlib, subprocess, hashlib
plan=json.loads(pathlib.Path('/plan/plan.json').read_text())
root=pathlib.Path('/vol/events')
root.mkdir(parents=True, exist_ok=True)
written=[]
for g in plan:
  repo=pathlib.Path('/repos')/g['repo']
  for m in g['members']:
    if 'git_path' not in m: continue
    blob=subprocess.check_output(['git','-C',str(repo),'show',f"HEAD:{m['git_path']}"])
    # Preserve exact stem; epoch bin by digits in stem (no casefold).
    stem=m['stem']
    digits=''.join(ch for ch in stem if ch.isdigit())
    year=int(digits[:4]) if len(digits)>=4 else 0
    if year and year<1990: epoch='sne-pre-1990'
    elif year and year<2000: epoch='sne-1990-1999'
    elif year and year<2005: epoch='sne-2000-2004'
    elif year and year<2010: epoch='sne-2005-2009'
    elif year and year<2015: epoch='sne-2010-2014'
    elif year and year<2020: epoch='sne-2015-2019'
    elif year and year<2025: epoch='sne-2020-2024'
    else: epoch='sne-unknown'
    dest=root/epoch/f'{stem}.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    written.append({'stem':stem,'path':str(dest.relative_to(root)),'bytes':len(blob),
                    'sha256':hashlib.sha256(blob).hexdigest(),'kind':g['kind'],'group':g['group']})
# Verify case-sensitive listing for each group
verify=[]
for g in plan:
  stems=[m['stem'] for m in g['members'] if 'stem' in m]
  found=[]
  for p in root.rglob('*.json'):
    if p.stem in stems:
      found.append(p.name)
  verify.append({'group':g['group'],'expected':sorted(stems),'found':sorted(found),
                 'ok':sorted(found)==sorted(f'{s}.json' for s in stems)})
# Host export for merge --collision-source: case-escaped names + manifest so a
# case-insensitive host FS keeps both casings distinct. Escape: _u_<hex>_ = uppercase.
exp=pathlib.Path('/export')
exp.mkdir(parents=True, exist_ok=True)
def _esc(stem):
  out=[]
  for ch in stem:
    if ch.isupper():
      out.append('_u_'+format(ord(ch),'x')+'_')
    else:
      out.append(ch)
  return ''.join(out)
pathlib.Path('/plan/written.json').write_text(json.dumps({'written':written,'verify':verify}, indent=2))
manifest=[]
for g in plan:
  for m in g['members']:
    if 'git_path' not in m: continue
    repo=pathlib.Path('/repos')/g['repo']
    blob=subprocess.check_output(['git','-C',str(repo),'show',f"HEAD:{m['git_path']}"])
    dest=exp/(_esc(m['stem'])+'.json')
    dest.write_bytes(blob)
    manifest.append({'stem':m['stem'],'escaped':dest.name,'group':g['group'],
                     'sha256':hashlib.sha256(blob).hexdigest()})
pathlib.Path('/export/manifest.json').write_text(json.dumps(manifest, indent=2))
print(json.dumps({'n_written':len(written),'groups_ok':sum(1 for v in verify if v['ok']),
                  'groups':len(verify),'exported':len(manifest)}))
PY
"""
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{VOLUME}:/vol",
        "-v",
        f"{(staging_root / 'repos').resolve()}:/repos:ro",
            "-v",
            f"{plan_path.parent.resolve()}:/plan",
            "-v",
            f"{export_dir.resolve()}:/export",
            "python:3.12-slim",
        "bash",
        "-lc",
        script,
    ]
    out = subprocess.check_output(cmd, text=True, timeout=600)
    lines = [ln for ln in out.splitlines() if ln.startswith("{")]
    summary = json.loads(lines[-1]) if lines else {"error": "no_summary", "raw": out[-500:]}
    written_meta = {}
    written_path = plan_path.parent / "written.json"
    if written_path.is_file():
        written_meta = json.loads(written_path.read_text(encoding="utf-8"))

    kinds = {}
    for g in plan:
        kinds[g["kind"]] = kinds.get(g["kind"], 0) + 1

    report = {
        "drawn_at_utc": datetime.now(timezone.utc).isoformat(),
        "docker_volume": VOLUME,
        "host_export_dir": str(export_dir),
        "host_export_manifest": str(export_dir / "manifest.json"),
        "groups": len(plan),
        "kind_counts": kinds,
        "materialize_summary": summary,
        "verify": written_meta.get("verify"),
        "policy": [
            "exact filename identity preserved",
            "no casefold merge",
            "distinct_objects keep both files",
            "duplicate_objects_different_case keep both names pending alias review",
            "live production volume untouched",
        ],
        "live_data_untouched": True,
    }
    out_path = staging_root / "COLLISION_MATERIALIZE_REPORT.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "groups", "kind_counts", "materialize_summary", "docker_volume"
    )}, indent=2))
    print("wrote", out_path)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--staging-root",
        type=Path,
        default=ROOT / "staging/astrocats-restore",
    )
    ap.add_argument(
        "--identity-audit",
        type=Path,
        default=None,
    )
    args = ap.parse_args()
    identity = args.identity_audit or (args.staging_root / "IDENTITY_AUDIT_REPORT.json")
    materialize(args.staging_root, identity)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
