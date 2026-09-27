#!/usr/bin/env python3
"""Crawl /sne/ namespace proof: offline resolve + light HTTP sample."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "serve"))
from server import _normalize_event_name, _resolve_event, _names_maps  # noqa: E402


def fetch(url: str, timeout: float = 10.0) -> int:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sne.space-proof/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(32)
            return int(resp.status)
    except urllib.error.HTTPError as e:
        return int(e.code)
    except Exception:
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--http-sample", type=int, default=300)
    args = ap.parse_args()
    base = args.base.rstrip("/")

    _names_maps()
    paths: list[str] = []
    seen = set()
    with (ROOT / "sne_space_crawled_pages_unique.csv").open() as f:
        for row in csv.DictReader(f):
            m = re.search(r"https?://sne\.space(/sne/[^?#]+)", row.get("url") or "")
            if not m:
                continue
            raw = urllib.parse.unquote(m.group(1))
            name = raw[len("/sne/") :].rstrip("/")
            if not name or name in seen:
                continue
            seen.add(name)
            paths.append(name)

    offline = Counter()
    unresolved = []
    for name in paths:
        resolved, _ = _resolve_event(name)
        if resolved:
            offline["resolved"] += 1
        else:
            offline["unresolved"] += 1
            unresolved.append(name)

    print(f"OFFLINE crawl unique /sne/ names: {len(paths)}")
    print(f"  resolved:   {offline['resolved']}")
    print(f"  unresolved: {offline['unresolved']}")

    # HTTP sample: mix of resolved + unresolved
    sample = []
    for n in paths:
        if len(sample) >= args.http_sample:
            break
        sample.append(n)
    http = Counter()
    for n in sample:
        status = fetch(f"{base}/sne/{urllib.parse.quote(n, safe='')}/")
        if status == 200:
            http["200"] += 1
        elif status == 404:
            http["404"] += 1
        else:
            http[f"other:{status}"] += 1
    print(f"HTTP sample {len(sample)}: {dict(http)}")

    out = ROOT / "serve" / "crawl_resolve_results.json"
    out.write_text(json.dumps({
        "offline": {"total": len(paths), **dict(offline)},
        "http_sample": {"n": len(sample), **dict(http)},
        "unresolved_sample": unresolved[:100],
    }, indent=2))
    print(f"wrote {out}")
    hard = sum(v for k, v in http.items() if k.startswith("other:"))
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
