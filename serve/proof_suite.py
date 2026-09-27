#!/usr/bin/env python3
"""First-pass sne.space namespace + API proof suite (S1.6 start).

Usage:
  python3 serve/proof_suite.py [--base http://127.0.0.1:8080] [--api http://127.0.0.1:8090]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fetch(url: str, timeout: float = 30.0) -> tuple[int, int, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sne.space-proof/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, len(body), body[:200].decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, 0, str(e)
    except Exception as e:
        return 0, 0, str(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--api", default="http://127.0.0.1:8090")
    ap.add_argument("--crawl-limit", type=int, default=500,
                    help="Max /sne/ URLs sampled from crawl CSV")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    api = args.api.rstrip("/")

    cases: list[tuple[str, str, callable]] = []

    # Core surfaces
    for path in [
        "/",
        "/about/",
        "/download/",
        "/contribute/",
        "/statistics/",
        "/bibliography/",
        "/contribute/find-duplicates/",
        "/contribute/find-conflicts/",
        "/graveyard/",
        "/links/",
        "/astrocats/astrocats/supernovae/output/catalog.min.json",
        "/astrocats/astrocats/supernovae/output/names.min.json",
    ]:
        cases.append((f"GET {path}", f"{base}{path}", lambda s, n, _b: s == 200 and n > 0))

    # Resolver gold set
    for path in [
        "/sne/2011fe/",
        "/sne/SN2011fe/",
        "/sne/sn2011fe/",
        "/event/SN2011fe",
        "/sne/1987A/",
        "/sne/SN2014J/",
        "/sne/SN2011fe.json",
    ]:
        cases.append((f"resolver {path}", f"{base}{path}", lambda s, n, _b: s == 200 and n > 100))

    # API gold set
    for path in [
        "/sne/SN2011fe/redshift",
        "/sne/SN2011fe/claimedtype",
        "/sne/SN2014J",
        "/sne/SN1987A/photometry/magnitude+band?item=0",
    ]:
        cases.append((f"api {path}", f"{api}{path}", lambda s, n, b: s == 200 and n > 2 and "message" not in b[:80].lower()))


    # Priority event HTML shells (resolver + gzipped plot page)
    def _ok200(min_bytes):
        return lambda s, n, _b, m=min_bytes: s == 200 and n > m

    for name, asset in [
        ("SN2011fe", "SN2011fe"),
        ("SN1987A", "SN1987A"),
        ("SN2014J", "SN2014J"),
        ("SN2009ip", "SN2009ip"),
        ("iPTF14hls", "CSS141118:092034+504148"),
        ("SN1979C", "SN1979C"),
    ]:
        cases.append((f"html-shell {name}", f"{base}/sne/{name}/", _ok200(100)))
        cases.append((
            f"html-asset {name}",
            f"{base}/astrocats/astrocats/supernovae/output/html/{asset}.html",
            _ok200(1000),
        ))

    # Sample crawl /sne/ paths
    crawl = ROOT / "sne_space_crawled_pages_unique.csv"
    sne_paths: list[str] = []
    if crawl.is_file():
        with crawl.open() as f:
            for row in csv.DictReader(f):
                url = row.get("url") or ""
                m = re.search(r"https?://sne\.space(/sne/[^?#]+)", url)
                if m:
                    sne_paths.append(urllib.parse.unquote(m.group(1)))
        # Prefer diverse short sample
        seen = set()
        sampled = []
        for p in sne_paths:
            key = p.rstrip("/").split("/")[-1][:2]
            if p in seen:
                continue
            seen.add(p)
            sampled.append(p)
            if len(sampled) >= args.crawl_limit:
                break
        for p in sampled:
            # Resolver should return 200 (found/fuzzy) or 404 (not in corpus)
            cases.append((f"crawl {p}", f"{base}{p if p.endswith('/') else p + '/'}",
                          lambda s, n, _b: s in (200, 404)))

    ok = fail = 0
    failures = []
    for name, url, pred in cases:
        status, nbytes, head = fetch(url)
        passed = False
        try:
            passed = pred(status, nbytes, head)
        except Exception:
            passed = False
        if passed:
            ok += 1
        else:
            fail += 1
            failures.append((name, url, status, nbytes, head[:120]))

    print(f"PASS {ok}  FAIL {fail}  TOTAL {ok + fail}")
    for name, url, status, nbytes, head in failures[:40]:
        print(f"  FAIL {name} -> {status} ({nbytes}b) {url}")
        if head:
            print(f"       {head!r}")
    if fail > 40:
        print(f"  ... {fail - 40} more")

    out = ROOT / "serve" / "proof_results.json"
    out.write_text(json.dumps({
        "pass": ok, "fail": fail, "total": ok + fail,
        "failures": [
            {"name": n, "url": u, "status": s, "bytes": b, "head": h}
            for n, u, s, b, h in failures
        ],
    }, indent=2))
    print(f"wrote {out}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
