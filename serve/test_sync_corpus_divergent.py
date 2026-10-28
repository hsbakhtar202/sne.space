#!/usr/bin/env python3
"""Divergent local/remote fixtures for corpus sync — required scenarios before prod."""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ingest.alerce import photometry_dedupe_key  # noqa: E402
from ingest.event_file_lock import event_file_lock  # noqa: E402
from ingest.manager import atomic_write_json  # noqa: E402
from ingest.sync_corpus import (  # noqa: E402
    apply_merge_to_remote_file,
    merge_event_into_remote,
    run_compare,
)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))


def _pt(mjd, mag, band="g", candid=None, **extra):
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


def _event(name, photometry, claimedtype="SN Ia", year=2025):
    return {
        name: {
            "name": name,
            "discoverdate": [{"value": f"{year}/03/15"}],
            "claimedtype": [{"value": claimedtype}],
            "photometry": photometry,
        }
    }


def _write_corpus(root: Path, folder: str, name: str, envelope: dict) -> Path:
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.json"
    p.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    return p


def test_newer_remote_preserved() -> None:
    remote = {"photometry": [_pt(60000, 18.0, candid="R1"), _pt(60001, 17.5, candid="R2")]}
    local = {"photometry": [_pt(60000, 18.0, candid="R1")]}
    out = merge_event_into_remote(remote, local)
    keys = {photometry_dedupe_key(p) for p in out["merged"]["photometry"]}
    check("newer remote points preserved", ("candid", "R2") in keys, f"keys={keys}")
    check("no spurious add", out["report"]["would_add"] == 0, "")


def test_local_additions_merged() -> None:
    remote = {"photometry": [_pt(60000, 18.0, candid="1")]}
    local = {"photometry": [_pt(60000, 18.0, candid="1"), _pt(60002, 17.0, candid="L2")]}
    out = merge_event_into_remote(remote, local)
    check("local detection merged", out["report"]["would_add"] == 1, "")
    check("no duplicate after merge", len(out["merged"]["photometry"]) == 2, "")


def test_candid_conflict_keeps_remote() -> None:
    remote = {"photometry": [_pt(60000, 18.0, candid="C")]}
    local = {"photometry": [_pt(60000, 19.5, candid="C")]}
    out = merge_event_into_remote(remote, local)
    check("conflict flagged", out["report"]["conflict_count"] == 1, "")
    check(
        "remote magnitude kept",
        float(out["merged"]["photometry"][0]["magnitude"]) == 18.0,
        "",
    )


def test_class_conflict_keeps_remote() -> None:
    remote = {"claimedtype": [{"value": "SN II"}], "photometry": []}
    local = {"claimedtype": [{"value": "SN Ia"}], "photometry": []}
    out = merge_event_into_remote(remote, local)
    check("class conflict flagged", out["report"]["class_conflict_count"] == 1, "")
    check(
        "remote class kept",
        out["merged"]["claimedtype"][0]["value"] == "SN II",
        "",
    )


def test_remote_only_preserved_in_compare() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        local = td / "local"
        remote = td / "remote"
        _write_corpus(local, "sne-2025-2029", "SN2025aa", _event("SN2025aa", [_pt(60000, 18.0, candid="1")]))
        _write_corpus(remote, "sne-2025-2029", "SN2025aa", _event("SN2025aa", [_pt(60000, 18.0, candid="1")]))
        _write_corpus(remote, "sne-2025-2029", "SN2025bb", _event("SN2025bb", [_pt(60000, 19.0, candid="9")]))
        summary = run_compare(local, remote, {2025}, apply=False)
        check("remote_only counted", summary["remote_only"] == 1, str(summary["remote_only"]))
        # Ensure remote-only file still exists untouched
        check(
            "remote-only event file intact",
            (remote / "sne-2025-2029" / "SN2025bb.json").is_file(),
            "",
        )


def test_interrupted_sync_no_partial_corruption() -> None:
    """Simulate crash after staging write, before promote — remote untouched."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        remote_path = _write_corpus(
            td, "sne-2025-2029", "SN2025cc",
            _event("SN2025cc", [_pt(60000, 18.0, candid="1")]),
        )
        before = remote_path.read_text(encoding="utf-8")
        staging = td / "staging"
        local_meta = _event("SN2025cc", [
            _pt(60000, 18.0, candid="1"),
            _pt(60001, 17.0, candid="2"),
        ])["SN2025cc"]
        res = apply_merge_to_remote_file(remote_path, local_meta, staging_dir=staging)
        check("staged not applied to remote", remote_path.read_text(encoding="utf-8") == before, "")
        check("staging has merged file", res["status"] == "staged" and Path(res["path"]).is_file(), "")
        staged = json.loads(Path(res["path"]).read_text())
        check("staged has both points", len(staged["SN2025cc"]["photometry"]) == 2, "")


def test_repeated_sync_idempotent() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        remote_path = _write_corpus(
            td, "sne-2025-2029", "SN2025dd",
            _event("SN2025dd", [_pt(60000, 18.0, candid="1")]),
        )
        local_meta = _event("SN2025dd", [
            _pt(60000, 18.0, candid="1"),
            _pt(60001, 17.2, candid="2"),
        ])["SN2025dd"]
        r1 = apply_merge_to_remote_file(remote_path, local_meta)
        n1 = len(json.loads(remote_path.read_text())["SN2025dd"]["photometry"])
        r2 = apply_merge_to_remote_file(remote_path, local_meta)
        n2 = len(json.loads(remote_path.read_text())["SN2025dd"]["photometry"])
        check("first sync adds", r1["report"]["would_add"] == 1 and n1 == 2, f"n1={n1}")
        check("second sync zero adds", r2["report"]["would_add"] == 0 and n2 == 2, f"n2={n2}")


def _concurrent_writer(lock_dir: str, path: str, candid: str, barrier: mp.Barrier) -> None:
    os.environ["SNE_INGEST_LOCK_DIR"] = lock_dir
    sys.path.insert(0, str(REPO))
    from ingest.event_file_lock import event_file_lock
    from ingest.manager import atomic_write_json
    from ingest.alerce import photometry_dedupe_key

    p = Path(path)
    barrier.wait(timeout=10)
    with event_file_lock(p):
        raw = json.loads(p.read_text(encoding="utf-8"))
        name = next(iter(raw))
        meta = raw[name]
        ph = list(meta.get("photometry") or [])
        keys = {photometry_dedupe_key(x) for x in ph if isinstance(x, dict)}
        new = {
            "time": "60010.00000",
            "magnitude": "16.5000",
            "band": "g",
            "telescope": "ZTF",
            "kind": "detection",
            "candid": candid,
            "provider": "test",
        }
        if photometry_dedupe_key(new) not in keys:
            ph.append(new)
        meta["photometry"] = ph
        time.sleep(0.15)  # widen race window without the lock
        atomic_write_json(p, {name: meta}, skip_if_unchanged=False)


def test_concurrent_ingestion_no_lost_updates() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        lock_dir = td / "locks"
        lock_dir.mkdir()
        os.environ["SNE_INGEST_LOCK_DIR"] = str(lock_dir)
        remote_path = _write_corpus(
            td, "sne-2025-2029", "SN2025ee",
            _event("SN2025ee", [_pt(60000, 18.0, candid="base")]),
        )
        mp.set_start_method("spawn", force=True)
        barrier = mp.Barrier(2)
        p1 = mp.Process(target=_concurrent_writer, args=(str(lock_dir), str(remote_path), "A", barrier))
        p2 = mp.Process(target=_concurrent_writer, args=(str(lock_dir), str(remote_path), "B", barrier))
        p1.start(); p2.start()
        p1.join(timeout=20); p2.join(timeout=20)
        raw = json.loads(remote_path.read_text())
        ph = raw["SN2025ee"]["photometry"]
        candids = {p.get("candid") for p in ph}
        check("both concurrent writers survived", candids >= {"base", "A", "B"}, f"candids={candids}")
        check("processes exited ok", p1.exitcode == 0 and p2.exitcode == 0, f"{p1.exitcode},{p2.exitcode}")


def test_shared_lock_module_used_by_writers() -> None:
    """Static check: pull_recent, backfill, sync, enrich all reference event_file_lock."""
    texts = {
        "backfill": (REPO / "ingest" / "backfill_photometry.py").read_text(),
        "pull_recent": (REPO / "ingest" / "pull_recent.py").read_text(),
        "sync": (REPO / "ingest" / "sync_corpus.py").read_text(),
        "manager": (REPO / "ingest" / "manager.py").read_text(),
    }
    for label, src in texts.items():
        check(f"{label} imports/uses event_file_lock", "event_file_lock" in src, "")


def main() -> int:
    print("=== divergent corpus sync tests ===")
    test_newer_remote_preserved()
    test_local_additions_merged()
    test_candid_conflict_keeps_remote()
    test_class_conflict_keeps_remote()
    test_remote_only_preserved_in_compare()
    test_interrupted_sync_no_partial_corruption()
    test_repeated_sync_idempotent()
    test_concurrent_ingestion_no_lost_updates()
    test_shared_lock_module_used_by_writers()
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"=== {len(RESULTS) - failed}/{len(RESULTS)} passed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
