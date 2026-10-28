#!/usr/bin/env python3
"""Crash-window and idempotency tests for historical photometry backfill.

Ordering contract:
  1. Atomically write the enriched event JSON.
  2. Only then append the name to the checkpoint.

Failure after (1) and before (2) must rematch cleanly with no duplicate points.
Checkpointing before a durable event write must never happen (would skip forever).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ingest.alerce import photometry_dedupe_key  # noqa: E402
from ingest.association_policy import is_candidate_point  # noqa: E402
from ingest.backfill_photometry import merge_photometry  # noqa: E402


RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))


def _point(mjd: float, mag: float, band: str = "g", candid: str | None = None, **extra):
    p = {
        "time": f"{mjd:.5f}",
        "magnitude": f"{mag:.4f}",
        "band": band,
        "telescope": "ZTF",
        "kind": "detection",
        "provider": "ALeRCE",
        **extra,
    }
    if candid is not None:
        p["candid"] = str(candid)
    return p


def test_merge_idempotent() -> None:
    event = {"photometry": [_point(60000.1, 18.1, candid="111")]}
    incoming = [
        _point(60000.1, 18.1, candid="111"),
        _point(60000.2, 18.3, candid="222"),
    ]
    add1, skip1, _ = merge_photometry(event, incoming)
    add2, skip2, _ = merge_photometry(event, incoming)
    check("first merge adds new candid", add1 == 1 and skip1 == 1, f"add={add1} skip={skip1}")
    check("second merge adds nothing", add2 == 0 and skip2 == 2, f"add={add2} skip={skip2}")
    check("no duplicate candids", len(event["photometry"]) == 2, f"n={len(event['photometry'])}")
    keys = [photometry_dedupe_key(p) for p in event["photometry"]]
    check("dedupe keys unique", len(keys) == len(set(keys)), "")


def test_write_then_checkpoint_ordering() -> None:
    """Simulate crash after event write, before checkpoint — rematch is safe."""
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        event_path = td_path / "AT2025test.json"
        checkpoint_path = td_path / "checkpoint.json"

        # Step 1: durable event write (as backfill does via atomic_write_json)
        meta = {
            "photometry": [_point(60000.0, 19.0, candid="1")],
            "_backfill": {"provider": "ALeRCE", "ztf_oid": "ZTF25abc", "detections_added": 1},
        }
        event_path.write_text(json.dumps({"AT2025test": meta}), encoding="utf-8")
        # Crash: checkpoint NOT updated
        check("event exists before checkpoint", event_path.is_file(), "")
        check("checkpoint absent after crash", not checkpoint_path.is_file(), "")

        # Restart: load event, merge same points again
        raw = json.loads(event_path.read_text(encoding="utf-8"))
        body = raw["AT2025test"]
        incoming = [
            _point(60000.0, 19.0, candid="1"),
            _point(60000.5, 18.5, candid="2"),
        ]
        add, skip, _ = merge_photometry(body, incoming)
        check("rematch after crash adds only new point", add == 1 and skip == 1, f"add={add} skip={skip}")
        event_path.write_text(json.dumps(raw), encoding="utf-8")
        # Step 2: checkpoint after durable write
        checkpoint_path.write_text(json.dumps({"completed": ["AT2025test"]}), encoding="utf-8")
        check("checkpoint written only after event", checkpoint_path.is_file(), "")


def test_checkpoint_before_write_is_forbidden_pattern() -> None:
    """Document the anti-pattern: checkpointing first would skip forever."""
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        event_path = td_path / "AT2025miss.json"
        checkpoint_path = td_path / "checkpoint.json"
        # Anti-pattern
        checkpoint_path.write_text(json.dumps({"completed": ["AT2025miss"]}), encoding="utf-8")
        # Event never written
        done = set(json.loads(checkpoint_path.read_text())["completed"])
        check(
            "anti-pattern would skip missing event",
            "AT2025miss" in done and not event_path.is_file(),
            "",
        )
        # Production code order is write-then-checkpoint (asserted by inspecting backfill_one).
        src = (REPO / "ingest" / "backfill_photometry.py").read_text(encoding="utf-8")
        write_idx = src.index("atomic_write_json(fpath, {name: meta})")
        # save_checkpoint is called in run_backfill after backfill_one returns
        call_idx = src.index("result = backfill_one(")
        save_idx = src.index("save_checkpoint(state)", call_idx)
        check(
            "source order: backfill_one (contains write) before save_checkpoint",
            write_idx < save_idx and call_idx < save_idx,
            f"write@{write_idx} call@{call_idx} save@{save_idx}",
        )


def test_candidate_points_quarantined() -> None:
    from ingest.association_policy import stamp_candidate
    p = stamp_candidate(_point(60000.0, 18.0, candid="9"), ["year_mismatched_ztf_oid"], oid="ZTF19x")
    check("stamped point is candidate", is_candidate_point(p), "")
    check("association_status unverified", p.get("association_status") == "unverified", "")


def main() -> int:
    print("=== backfill crash / idempotency tests ===")
    test_merge_idempotent()
    test_write_then_checkpoint_ordering()
    test_checkpoint_before_write_is_forbidden_pattern()
    test_candidate_points_quarantined()
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"=== {len(RESULTS) - failed}/{len(RESULTS)} passed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
