#!/usr/bin/env python3
"""Verify cross-process discovery priority: backfill yields for the full hold."""
from __future__ import annotations

import multiprocessing as mp
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _discovery(lock_dir: str, ready: mp.Event, hold_s: float) -> None:
    os.environ["SNE_INGEST_LOCK_DIR"] = lock_dir
    sys.path.insert(0, str(REPO))
    from ingest.provider_quota import recent_ingest_priority

    with recent_ingest_priority():
        ready.set()
        time.sleep(hold_s)


def _backfill(lock_dir: str, ready: mp.Event, result: mp.Value) -> None:
    os.environ["SNE_INGEST_LOCK_DIR"] = lock_dir
    sys.path.insert(0, str(REPO))
    from ingest.provider_quota import (
        acquire,
        backfill_mode,
        discovery_priority_held,
        wait_for_recent_priority,
    )

    ready.wait(timeout=10)
    t0 = time.time()
    assert discovery_priority_held(), "discovery should hold lock"
    with backfill_mode():
        wait_for_recent_priority()
        acquire("alerce", is_backfill=True)
    result.value = time.time() - t0


def main() -> int:
    print("=== cross-process priority lock ===")
    with tempfile.TemporaryDirectory() as td:
        ready = mp.Event()
        waited = mp.Value("d", 0.0)
        hold_s = 7.0
        p1 = mp.Process(target=_discovery, args=(td, ready, hold_s))
        p2 = mp.Process(target=_backfill, args=(td, ready, waited))
        p1.start()
        p2.start()
        p2.join(timeout=25)
        p1.join(timeout=25)
        ok_exit = p1.exitcode == 0 and p2.exitcode == 0
        ok_wait = waited.value >= hold_s - 1.0
        print(f"  [{'PASS' if ok_exit else 'FAIL'}] both processes exited cleanly "
              f"(disc={p1.exitcode} bf={p2.exitcode})")
        print(f"  [{'PASS' if ok_wait else 'FAIL'}] backfill waited ~{hold_s}s "
              f"(actual={waited.value:.2f}s)")
        # Backfill must not hold priority lock itself after finishing
        os.environ["SNE_INGEST_LOCK_DIR"] = td
        from ingest.provider_quota import discovery_priority_held
        free = not discovery_priority_held()
        print(f"  [{'PASS' if free else 'FAIL'}] priority lock free after both exit")
        return 0 if (ok_exit and ok_wait and free) else 1


if __name__ == "__main__":
    raise SystemExit(main())
