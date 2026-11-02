"""P0A staging acceptance: publish → CatalogStore → API merge survives restart/interrupt.

Uses an isolated temp runtime + data dir (never production volumes).
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path


class TestP0AStagingAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.runtime = root / "runtime"
        self.data = root / "data"
        self.epoch = self.data / "sne-2025-2029"
        self.runtime.mkdir(parents=True)
        self.epoch.mkdir(parents=True)
        os.environ["SNE_RUNTIME_DIR"] = str(self.runtime)
        # Point SUPERNOVAE_OUTPUT used by catalog_publish
        import ingest.manager as mgr
        import ingest.catalog_publish as cp

        self._old_out = mgr.SUPERNOVAE_OUTPUT
        mgr.SUPERNOVAE_OUTPUT = self.data
        cp.SUPERNOVAE_OUTPUT = self.data

    def tearDown(self) -> None:
        import ingest.manager as mgr
        import ingest.catalog_publish as cp

        mgr.SUPERNOVAE_OUTPUT = self._old_out
        cp.SUPERNOVAE_OUTPUT = self._old_out
        os.environ.pop("SNE_RUNTIME_DIR", None)
        self._td.cleanup()

    def _write_event(self, name: str, n_det: int, n_lim: int = 0) -> Path:
        # Times near discoverdate MJD (~61338 for 2026-10-25) so outburst-window
        # filters do not discard the points.
        base_mjd = 61338.0
        phot = []
        for i in range(n_lim):
            phot.append(
                {
                    "time": str(base_mjd - 1.0 - i),
                    "magnitude": "20.0",
                    "upperlimit": True,
                    "kind": "non_detection",
                }
            )
        for i in range(n_det):
            phot.append(
                {
                    "time": str(base_mjd + i),
                    "magnitude": str(19.0 - 0.1 * i),
                    "upperlimit": False,
                }
            )
        body = {
            name: {
                "name": name,
                "discoverdate": [{"value": "2026/10/25"}],
                "claimedtype": [{"value": "unclassified"}],
                "ra": [{"value": "01:00:00"}],
                "dec": [{"value": "+00:00:00"}],
                "photometry": phot,
            }
        }
        path = self.epoch / f"{name}.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        return path

    def _build_store(self) -> Path:
        from serve.catalog_store import CatalogStore

        db = self.data / ".index" / "catalog.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        # Seed empty primary so upsert has a file
        primary = self.data / "catalog.min.json"
        primary.write_text("[]", encoding="utf-8")
        store = CatalogStore(db)
        store.build([primary])
        return db

    def test_enriched_store_survives_stale_recent_after_republish(self) -> None:
        from ingest.catalog_publish import publish_event_files
        from ingest.publication import publish_event_paths
        from serve import catalog_engine as ce
        from serve.catalog_store import CatalogStore

        name = "AT2026agub"
        path = self._write_event(name, n_det=1, n_lim=1)
        db = self._build_store()
        # Authoritative publish from event JSON
        result = publish_event_paths([path], catalog_db=db)
        self.assertEqual(result.get("state"), "published")

        store = CatalogStore(db)
        store.load_existing()
        store_hit = store.query(q=name, limit=1)["items"][0]
        self.assertEqual(store_hit["phot"], 1)
        self.assertIn("publish_revision", store_hit)

        # Stale recent-catalog stub (phot=0, no/older revision)
        recent_path = self.runtime / "recent-catalog.min.json"
        recent_path.write_text(
            json.dumps(
                [
                    {
                        "name": name,
                        "alias": [{"value": name}],
                        "claimedtype": [{"value": "unclassified"}],
                        "discoverdate": [{"value": "2026/10/25"}],
                        "photolink": "0,0",
                        "spectralink": "0",
                    }
                ]
            ),
            encoding="utf-8",
        )
        with unittest.mock.patch.object(ce, "_runtime_recent_path", return_value=recent_path):
            merged = ce._merge_recent_into_query_result(
                {"total": 1, "page": 1, "limit": 50, "pages": 1, "items": [store_hit]},
                sort="discoverdate",
                order="desc",
            )
        hit = next(i for i in merged["items"] if i["name"] == name)
        self.assertEqual(hit["phot"], 1)

    def test_downward_correction_with_newer_revision_wins(self) -> None:
        from ingest.catalog_publish import event_to_catalog_item, publish_catalog_items
        from serve import catalog_engine as ce
        from serve.catalog_store import CatalogStore

        db = self._build_store()
        rich = event_to_catalog_item(
            "AT2026fix",
            {
                "discoverdate": [{"value": "2026/10/01"}],
                "photometry": [
                    {"time": "61314.0", "magnitude": "18.0"},
                    {"time": "61315.0", "magnitude": "17.9"},
                ],
            },
        )
        publish_catalog_items([rich], catalog_db=db, write_overlay=True)
        # Correction removes one point — newer revision, lower count
        corrected = event_to_catalog_item(
            "AT2026fix",
            {
                "discoverdate": [{"value": "2026/10/01"}],
                "photometry": [{"time": "61314.0", "magnitude": "18.0"}],
            },
        )
        self.assertGreater(corrected["publish_revision"], rich["publish_revision"])
        publish_catalog_items([corrected], catalog_db=db, write_overlay=True)

        store = CatalogStore(db)
        store.load_existing()
        store_hit = store.query(q="AT2026fix", limit=1)["items"][0]
        self.assertEqual(store_hit["phot"], 1)

        # Even if recent still has the old higher count with older revision
        recent = [
            {
                **{k: store_hit[k] for k in store_hit if k != "publish_revision"},
                "phot": 2,
                "publish_revision": rich["publish_revision"],
            }
        ]
        with unittest.mock.patch.object(ce, "_load_recent_query_items", return_value=recent):
            merged = ce._merge_recent_into_query_result(
                {"total": 1, "page": 1, "limit": 50, "pages": 1, "items": [store_hit]},
            )
        self.assertEqual(merged["items"][0]["phot"], 1)

    def test_interrupted_publish_recovers_pending(self) -> None:
        from ingest.publication import mark_ingested, pending_names, recover_pending

        name = "AT2026crash"
        path = self._write_event(name, n_det=1)
        db = self._build_store()
        mark_ingested(name, path)
        self.assertIn(name, pending_names())
        # Simulate crash before published marker: recover_pending republishes
        os.environ["SNE_PUBLISH_FAIL_SQLITE"] = "1"
        try:
            failed = recover_pending(catalog_db=db)
            self.assertEqual(failed.get("state"), "failed")
        finally:
            os.environ.pop("SNE_PUBLISH_FAIL_SQLITE", None)
        recovered = recover_pending(catalog_db=db)
        self.assertEqual(recovered.get("state"), "published")
        self.assertNotIn(name, pending_names())


if __name__ == "__main__":
    unittest.main()
