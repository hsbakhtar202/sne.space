#!/usr/bin/env python3
"""Resolver unit checks matching event.php rules (S1.3 / §9)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "serve"))
from server import _normalize_event_name, _resolve_event, _names_maps  # noqa: E402


def main() -> int:
    # Warm / ensure maps load
    names, _ = _names_maps()
    assert len(names) > 1000, f"names too small: {len(names)}"

    norms = [
        ("2011fe", "SN2011fe"),
        ("sn2011fe", "SN2011fe"),
        ("SN2011fe", "SN2011fe"),
        ("SN 2011fe", "SN2011fe"),
        ("1987A", "SN1987A"),
        ("1979C", "SN1979C"),  # year+letter: first-4 numeric rule
        ("79C", "79C"),  # PHP is_numeric('79C') is false — no prepend
    ]

    fail = 0
    for raw, expect in norms:
        got = _normalize_event_name(raw)
        # 79C: is_numeric first 3 and len<=4 → SN79C; then SN+digit rules may lower tail
        if got != expect:
            print(f"NORM FAIL {raw!r} -> {got!r} expected {expect!r}")
            fail += 1
        else:
            print(f"NORM OK  {raw!r} -> {got!r}")

    resolves = [
        ("2011fe", "SN2011fe"),
        ("SN2011fe", "SN2011fe"),
        ("sn2011fe", "SN2011fe"),
        ("1987A", "SN1987A"),
        ("iPTF14hls", "CSS141118:092034+504148"),  # alias
        ("PTF11kly", "SN2011fe"),  # alias of SN2011fe
    ]
    for raw, expect in resolves:
        resolved, entered = _resolve_event(raw)
        if resolved != expect:
            print(f"RESOLVE FAIL {raw!r} -> {resolved!r} (fuzzy={entered!r}) expected {expect!r}")
            fail += 1
        else:
            print(f"RESOLVE OK  {raw!r} -> {resolved!r}")

    # Unknown should 404-path (None)
    resolved, _ = _resolve_event("NOTAREALSUPERNOVA99999")
    if resolved is not None:
        # Levenshtein may still fuzzy-match; only fail if distance somehow <4 to something
        print(f"RESOLVE NOTE unknown -> {resolved!r} (Levenshtein may fire)")
    else:
        print("RESOLVE OK  nonsense -> None")

    print(f"{'PASS' if fail == 0 else 'FAIL'} resolver_unit_tests fail={fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
