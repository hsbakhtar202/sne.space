#!/usr/bin/env python3
"""Catalog consistency after event-file sync/publication — the deployment blocker."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ingest.association_policy import stamp_candidate  # noqa: E402
from ingest.backfill_photometry import (  # noqa: E402
    usable_outburst_detections,
    verified_outburst_detections,
)
from ingest.catalog_publish import (  # noqa: E402
    apply_overlay_to_catalog_list,
    event_to_catalog_item,
    merge_overlay,
    publish_event_files,
)
from serve.catalog_store import CatalogStore, _row_from_catalog_item  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))


# Discovery 2025/03/15 ≈ MJD 60749; keep test points inside the outburst window.
_DISC_MJD = 60750.0


def _pt(mjd_offset, mag, candid=None, candidate=False):
    mjd = _DISC_MJD + float(mjd_offset)
    p = {
        "time": f"{mjd:.5f}",
        "magnitude": f"{mag:.4f}",
        "band": "g",
        "telescope": "ZTF",
        "kind": "detection",
        "provider": "ALeRCE",
    }
    if candid is not None:
        p["candid"] = str(candid)
    if candidate:
        p = stamp_candidate(p, ["year_mismatched_ztf_oid"], oid="ZTF19x")
    return p


def _write_event(folder: Path, name: str, photometry: list) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    env = {
        name: {
            "name": name,
            "discoverdate": [{"value": "2025/03/15"}],
            "claimedtype": [{"value": "SN Ia"}],
            "ra": [{"value": "10:00:00"}],
            "dec": [{"value": "+10:00:00"}],
            "photometry": photometry,
            "alias": [{"value": name}, {"value": "ZTF25test"}],
        }
    }
    path = folder / f"{name}.json"
    path.write_text(json.dumps(env, indent=2), encoding="utf-8")
    return path


def _build_mini_store(db_path: Path, items: list[dict]) -> CatalogStore:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Seed via a tiny JSON array source then build
    src = db_path.parent / "seed.min.json"
    src.write_text(json.dumps(items, separators=(",", ":")), encoding="utf-8")
    store = CatalogStore(db_path)
    store.build([src], force=True)
    return store


def test_publish_updates_store_and_overlay() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # Stale catalog says 1 phot point
        stale = {
            "name": "SN2025pub",
            "alias": [{"value": "SN2025pub"}],
            "discoverdate": [{"value": "2025/03/15"}],
            "claimedtype": [{"value": "SN Ia"}],
            "photolink": "1,0",
            "spectralink": "0",
            "ra": [{"value": "10:00:00"}],
            "dec": [{"value": "+10:00:00"}],
        }
        db = td / "catalog.db"
        store = _build_mini_store(db, [stale])
        before = store.get_meta("SN2025pub")
        check("stale store photolink is 1", str(before.get("photolink")).startswith("1"), str(before.get("photolink")))

        # Event file now has 5 raw detections (1 of them quarantined)
        events = td / "sne-2025-2029"
        path = _write_event(
            events,
            "SN2025pub",
            [
                _pt(0.0, 18.0, "1"),
                _pt(1.0, 17.5, "2"),
                _pt(2.0, 17.0, "3"),
                _pt(3.0, 16.5, "4"),
                _pt(4.0, 16.0, "5", candidate=True),
            ],
        )
        # Point overlay at temp runtime
        import os
        os.environ["SNE_RUNTIME_DIR"] = str(td / "runtime")
        (td / "runtime").mkdir()

        result = publish_event_files([path], catalog_db=db)
        check("publish upserted 1", result.get("upserted") == 1, str(result))
        check("quarantine preserved in publish", result.get("quarantine_preserved") == 1, "")

        store2 = CatalogStore(db)
        check("load_existing after upsert", store2.load_existing(), "")
        meta = store2.get_meta("SN2025pub")
        check("store meta present", meta is not None, "")
        assert meta is not None
        check(
            "store photolink reflects raw outburst dets",
            str(meta.get("photolink")).startswith("5"),
            str(meta.get("photolink")),
        )
        check(
            "verified_phot not auto-promoted",
            int(meta.get("verified_phot") or 0) == 4,
            str(meta.get("verified_phot")),
        )
        check("quarantined flag set", meta.get("quarantined") is True, "")

        # Overlay merge replaces base listing
        overlay = json.loads((td / "runtime" / "published-updates.min.json").read_text())
        merged = apply_overlay_to_catalog_list([stale], overlay)
        check("listing photolink updated", str(merged[0].get("photolink")).startswith("5"), str(merged[0].get("photolink")))
        check("single listing row (no duplicate)", len(merged) == 1, str(len(merged)))


def test_idempotent_republish() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        os_environ_runtime = td / "runtime"
        os_environ_runtime.mkdir()
        import os
        os.environ["SNE_RUNTIME_DIR"] = str(os_environ_runtime)
        item = {
            "name": "SN2025idem",
            "alias": [{"value": "SN2025idem"}],
            "discoverdate": [{"value": "2025/01/01"}],
            "claimedtype": [{"value": "SN II"}],
            "photolink": "1,0",
            "spectralink": "0",
        }
        db = td / "catalog.db"
        _build_mini_store(db, [item])
        path = _write_event(
            td / "sne-2025-2029",
            "SN2025idem",
            [_pt(0, 18.0, "a"), _pt(1, 17.0, "b"), _pt(2, 16.0, "c")],
        )
        r1 = publish_event_files([path], catalog_db=db)
        r2 = publish_event_files([path], catalog_db=db)
        overlay = json.loads((os_environ_runtime / "published-updates.min.json").read_text())
        check("republish upserted again", r1["upserted"] == 1 and r2["upserted"] == 1, "")
        check("overlay still one entry", len(overlay) == 1, str(len(overlay)))
        store = CatalogStore(db)
        store.load_existing()
        check("store count unchanged", store.count() == 1, str(store.count()))
        check(
            "photolink stable at 3",
            str(store.get_meta("SN2025idem").get("photolink")).startswith("3"),
            "",
        )


def test_event_page_search_catalog_agree() -> None:
    """Same accepted counts from event file, catalog item, and store row."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        import os
        os.environ["SNE_RUNTIME_DIR"] = str(td / "runtime")
        (td / "runtime").mkdir()
        name = "SN2025agree"
        path = _write_event(
            td / "sne-2025-2029",
            name,
            [
                _pt(0, 18.0, "1"),
                _pt(1, 17.0, "2"),
                _pt(2, 16.0, "3", candidate=True),
            ],
        )
        raw = json.loads(path.read_text())[name]
        raw_n = len(usable_outburst_detections(raw))
        ver_n = len(verified_outburst_detections(raw))
        item = event_to_catalog_item(name, raw)
        check("item raw_phot == event raw", item["raw_phot"] == raw_n == 3, f"{item['raw_phot']},{raw_n}")
        check("item verified_phot == event verified", item["verified_phot"] == ver_n == 2, f"{item['verified_phot']},{ver_n}")
        check("quarantine not released", item["quarantined"] is True and ver_n < raw_n, "")

        seed = [{**item, "photolink": "1,0", "verified_phot": 1, "raw_phot": 1}]
        db = td / "catalog.db"
        _build_mini_store(db, seed)
        publish_event_files([path], catalog_db=db)
        store = CatalogStore(db)
        store.load_existing()
        meta = store.get_meta(name)
        check(
            "search/store raw matches event",
            int(str(meta.get("photolink")).split(",")[0]) == raw_n,
            str(meta.get("photolink")),
        )
        check(
            "search/store verified matches event",
            int(meta.get("verified_phot")) == ver_n,
            str(meta.get("verified_phot")),
        )


def test_overlay_merge_helper() -> None:
    a = [{"name": "A", "photolink": "1,0"}, {"name": "B", "photolink": "2,0"}]
    b = [{"name": "B", "photolink": "9,0"}, {"name": "C", "photolink": "3,0"}]
    merged = apply_overlay_to_catalog_list(a, b)
    by = {x["name"]: x["photolink"] for x in merged}
    check("B replaced", by["B"] == "9,0", str(by))
    check("C prepended", by["C"] == "3,0" and merged[0]["name"] == "C", str(merged[0]))
    check("A preserved", by["A"] == "1,0", "")
    m2 = merge_overlay(b, [{"name": "B", "photolink": "11,0"}])
    check("merge_overlay idempotent size", len(m2) == 2, str(len(m2)))


def main() -> int:
    print("=== catalog publish consistency ===")
    test_overlay_merge_helper()
    test_publish_updates_store_and_overlay()
    test_idempotent_republish()
    test_event_page_search_catalog_agree()
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"=== {len(RESULTS) - failed}/{len(RESULTS)} passed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
