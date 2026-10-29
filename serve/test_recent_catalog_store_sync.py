#!/usr/bin/env python3
"""P0: recent TNS list and /api/transients CatalogStore must not disagree.

Regression for the homepage flash: SSR paints recent-catalog.min.json (AT2026ahaw),
then catalog-table.js replaces the tbody with /api/transients which previously
omitted those same names because pull_recent never upserted stubs into SQLite.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestPublishRecentUpsertsStore(unittest.TestCase):
    def test_publish_catalog_items_upserts_sqlite(self) -> None:
        from ingest.catalog_publish import publish_catalog_items
        from serve.catalog_store import CatalogStore

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            db = td_path / "catalog.db"
            # Seed empty-ish store with one old event
            seed = td_path / "seed.min.json"
            seed.write_text(
                json.dumps(
                    [
                        {
                            "name": "SN2026aeiv",
                            "discoverdate": [{"value": "2026/10/05"}],
                            "claimedtype": [{"value": "Ia"}],
                            "ra": [{"value": "03:16:41.828"}],
                            "dec": [{"value": "+80:48:09.12"}],
                            "photolink": "1,0",
                            "spectralink": "2",
                        }
                    ],
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            store = CatalogStore(db)
            self.assertTrue(store.build([seed], force=True))

            fresh = [
                {
                    "name": "AT2026ahaw",
                    "alias": [{"value": "AT2026ahaw"}],
                    "discoverdate": [{"value": "2026/10/29"}],
                    "claimedtype": [{"value": "unclassified"}],
                    "maxappmag": [{"value": "13.98", "kind": "discovery"}],
                    "ra": [{"value": "00:35:16.317"}],
                    "dec": [{"value": "+34:30:00.50"}],
                    "photolink": "0,0",
                    "spectralink": "0",
                    "host": [{"value": "NGC 123"}],
                }
            ]
            overlay = td_path / "published-updates.min.json"
            result = publish_catalog_items(
                fresh,
                catalog_db=db,
                overlay_file=overlay,
            )
            self.assertGreaterEqual(result.get("upserted", 0), 1)

            store2 = CatalogStore(db)
            store2.load_existing()
            q = store2.query(sort="discoverdate", order="desc", page=1, limit=5)
            names = [i["name"] for i in q["items"]]
            self.assertIn("AT2026ahaw", names)
            self.assertEqual(names[0], "AT2026ahaw")
            ahaw = next(i for i in q["items"] if i["name"] == "AT2026ahaw")
            self.assertEqual(ahaw.get("host"), "NGC 123")

    def test_pull_recent_publish_calls_catalog_upsert(self) -> None:
        from ingest import pull_recent as pr

        written = [
            {
                "name": "AT2026ahaw",
                "date": "2026-10-29",
                "type": "unclassified",
                "discoverer": "ZTF",
                "ra": "00:35:16.317",
                "dec": "+34:30:00.50",
                "discoverymag": "13.98",
                "maxappmag": "",
                "spectra_count": 0,
                "photo_count": 0,
                "host": "NGC 123",
                "sort": "2026-10-29 01:00:00",
            }
        ]
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            calls: list = []

            def _fake_runtime(name: str) -> Path:
                return td_path / name

            def _fake_publish(items, **kwargs):
                calls.append(items)
                return {"upserted": len(items), "items": len(items)}

            with mock.patch.object(pr, "_runtime_write_path", _fake_runtime), mock.patch(
                "ingest.catalog_publish.publish_catalog_items", _fake_publish
            ):
                pr._publish(written)

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0]["name"], "AT2026ahaw")
            self.assertEqual(calls[0][0]["host"][0]["value"], "NGC 123")
            # Runtime recent-catalog must still be written
            cat = json.loads((td_path / "recent-catalog.min.json").read_text(encoding="utf-8"))
            self.assertEqual(cat[0]["name"], "AT2026ahaw")


class TestCatalogEngineMergesRecent(unittest.TestCase):
    def test_query_page1_includes_recent_not_in_store(self) -> None:
        from serve.catalog_engine import CatalogEngine
        from serve.catalog_store import CatalogStore

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            db = td_path / "catalog.db"
            seed = td_path / "seed.min.json"
            seed.write_text(
                json.dumps(
                    [
                        {
                            "name": "SN2026aeiv",
                            "discoverdate": [{"value": "2026/10/05"}],
                            "claimedtype": [{"value": "Ia"}],
                            "ra": [{"value": "03:16:41"}],
                            "dec": [{"value": "+80:48:09"}],
                            "photolink": "1,0",
                            "spectralink": "0",
                        }
                    ],
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            store = CatalogStore(db)
            store.build([seed], force=True)

            recent = td_path / "recent-catalog.min.json"
            recent.write_text(
                json.dumps(
                    [
                        {
                            "name": "AT2026ahaw",
                            "discoverdate": [{"value": "2026/10/29"}],
                            "claimedtype": [{"value": "unclassified"}],
                            "maxappmag": [{"value": "13.98"}],
                            "ra": [{"value": "00:35:16.317"}],
                            "dec": [{"value": "+34:30:00.50"}],
                            "photolink": "0,0",
                            "spectralink": "0",
                        }
                    ],
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )

            engine = CatalogEngine()
            engine.attach_store(store)
            with mock.patch(
                "serve.catalog_engine._runtime_recent_path", return_value=recent
            ):
                res = engine.query(sort="discoverdate", order="desc", page=1, limit=10)
            names = [i["name"] for i in res["items"]]
            self.assertEqual(names[0], "AT2026ahaw")
            self.assertIn("SN2026aeiv", names)


if __name__ == "__main__":
    unittest.main()
